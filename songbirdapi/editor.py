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


async def apply_edits(source_path: str, dest_path: str, params: dict) -> None:
    """Run ffmpeg with trim/volume/fade params. Raises RuntimeError on failure."""
    trim_start: float = params.get("trim_start") or 0.0
    trim_end: float | None = params.get("trim_end")
    volume: float = params.get("volume") or 1.0
    fade_in: float = params.get("fade_in") or 0.0
    fade_out: float = params.get("fade_out") or 0.0

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

    if filters:
        cmd += ["-af", ",".join(filters)]

    cmd += ["-c:a", "libmp3lame", "-q:a", "2", dest_path]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode(errors="replace")[-500:])
