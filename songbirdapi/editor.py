import asyncio
import json


async def _get_duration(path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        data = json.loads(stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                return float(stream.get("duration", 0))
    except Exception:
        pass
    return 0.0


def _build_speed_filters(speed: float) -> list[str]:
    """atempo only accepts [0.5, 2.0]; chain filters for values outside that range."""
    if abs(speed - 1.0) < 0.001:
        return []
    filters: list[str] = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining *= 2.0
    if abs(remaining - 1.0) > 0.001:
        filters.append(f"atempo={remaining:.4f}")
    return filters


async def apply_edits(source_path: str, dest_path: str, params: dict) -> None:
    """Run ffmpeg with trim/volume/fade/cut/speed/normalize params. Raises RuntimeError on failure."""
    trim_start: float = params.get("trim_start") or 0.0
    trim_end: float | None = params.get("trim_end")
    volume: float = params.get("volume") or 1.0
    fade_in: float = params.get("fade_in") or 0.0
    fade_out: float = params.get("fade_out") or 0.0
    speed: float = params.get("speed") or 1.0
    normalize: bool = params.get("normalize") or False
    cuts: list[dict] = [c for c in (params.get("cuts") or []) if float(c.get("end", 0)) > float(c.get("start", 0))]

    if cuts:
        await _apply_with_cuts(source_path, dest_path, trim_start, trim_end, volume, fade_in, fade_out, speed, normalize, cuts)
    else:
        await _apply_simple(source_path, dest_path, trim_start, trim_end, volume, fade_in, fade_out, speed, normalize)


async def _apply_simple(
    source_path: str, dest_path: str,
    trim_start: float, trim_end: float | None,
    volume: float, fade_in: float, fade_out: float,
    speed: float, normalize: bool,
) -> None:
    cmd = ["ffmpeg", "-y"]
    if trim_start > 0:
        cmd += ["-ss", str(trim_start)]
    cmd += ["-i", source_path]
    if trim_end is not None:
        cmd += ["-to", str(trim_end - trim_start)]

    filters: list[str] = []
    if volume != 1.0:
        filters.append(f"volume={volume}")
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        if trim_end is not None:
            trimmed_dur = trim_end - trim_start
        else:
            source_dur = await _get_duration(source_path)
            trimmed_dur = source_dur - trim_start
        out_start = max(0.0, trimmed_dur - fade_out)
        filters.append(f"afade=t=out:st={out_start}:d={fade_out}")
    filters.extend(_build_speed_filters(speed))
    if normalize:
        filters.append("dynaudnorm")

    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd += ["-c:a", "libmp3lame", "-q:a", "0", dest_path]
    await _run_ffmpeg(cmd)


async def _apply_with_cuts(
    source_path: str, dest_path: str,
    trim_start: float, trim_end: float | None,
    volume: float, fade_in: float, fade_out: float,
    speed: float, normalize: bool,
    cuts: list[dict],
) -> None:
    source_dur = trim_end if trim_end is not None else await _get_duration(source_path)

    cuts_sorted = sorted(cuts, key=lambda c: float(c["start"]))

    # Build kept segments, tracking per-segment crossfade values
    segments: list[tuple[float, float]] = []
    seg_fades: list[tuple[float, float]] = []  # (fade_in, fade_out) per segment
    pos = trim_start
    pending_fade_in = 0.0
    for cut in cuts_sorted:
        cs = max(pos, float(cut["start"]))
        ce = min(source_dur, float(cut["end"]))
        if ce <= cs:
            continue
        if cs > pos:
            segments.append((pos, cs))
            seg_fades.append((pending_fade_in, float(cut.get("fade_out") or 0)))
        pending_fade_in = float(cut.get("fade_in") or 0)
        pos = ce
    if pos < source_dur:
        segments.append((pos, source_dur))
        seg_fades.append((pending_fade_in, 0.0))

    if not segments:
        raise RuntimeError("cuts remove the entire audio segment")

    if len(segments) == 1:
        s, e = segments[0]
        fi, fo = seg_fades[0]
        await _apply_simple(source_path, dest_path, s, e, volume, fi or fade_in, fo or fade_out, speed, normalize)
        return

    # filter_complex: per-segment atrim + optional per-cut afades, then concat, then global volume/fades/speed/normalize
    parts: list[str] = []
    for i, ((s, e), (fi, fo)) in enumerate(zip(segments, seg_fades)):
        seg_dur = e - s
        per_seg: list[str] = []
        if fi > 0:
            per_seg.append(f"afade=t=in:st=0:d={fi}")
        if fo > 0:
            per_seg.append(f"afade=t=out:st={max(0.0, seg_dur - fo):.4f}:d={fo}")
        fades_str = "," + ",".join(per_seg) if per_seg else ""
        parts.append(f"[0:a]atrim=start={s}:end={e}{fades_str},asetpts=PTS-STARTPTS[s{i}]")

    n = len(segments)
    concat = "".join(f"[s{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[cat]"

    total_dur = sum(e - s for s, e in segments)
    af: list[str] = []
    if volume != 1.0:
        af.append(f"volume={volume}")
    if fade_in > 0:
        af.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        out_start = max(0.0, total_dur - fade_out)
        af.append(f"afade=t=out:st={out_start}:d={fade_out}")
    af.extend(_build_speed_filters(speed))
    if normalize:
        af.append("dynaudnorm")

    if af:
        chain = "[cat]" + ",".join(af) + "[out]"
        fc = ";".join(parts) + ";" + concat + ";" + chain
        map_arg = "[out]"
    else:
        fc = ";".join(parts) + ";" + concat
        map_arg = "[cat]"

    cmd = ["ffmpeg", "-y", "-i", source_path, "-filter_complex", fc, "-map", map_arg, "-c:a", "libmp3lame", "-q:a", "0", dest_path]
    await _run_ffmpeg(cmd)


async def _run_ffmpeg(cmd: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace")[-500:])
