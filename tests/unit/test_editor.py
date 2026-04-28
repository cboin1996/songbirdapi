"""Unit tests for editor filter-string construction. No ffmpeg required."""
import pytest

from songbirdapi.editor import (
    _orig_to_buf_offset,
    _build_volume_and_fades_filter,
    _apply_with_cuts,
    _apply_simple,
)


# ---------------------------------------------------------------------------
# _orig_to_buf_offset
# ---------------------------------------------------------------------------


def test_orig_to_buf_offset_single_seg_start():
    segs = [(0.0, 60.0)]
    assert _orig_to_buf_offset(0.0, segs) == 0.0


def test_orig_to_buf_offset_single_seg_mid():
    segs = [(0.0, 60.0)]
    assert _orig_to_buf_offset(30.0, segs) == 30.0


def test_orig_to_buf_offset_two_segs_before_gap():
    # cut 10-20: segs = (0,10), (20,60)
    segs = [(0.0, 10.0), (20.0, 60.0)]
    # t=5 is in first seg: buf offset = 5
    assert _orig_to_buf_offset(5.0, segs) == 5.0


def test_orig_to_buf_offset_two_segs_after_gap():
    segs = [(0.0, 10.0), (20.0, 60.0)]
    # t=25 in second seg: 10 (len of seg0) + (25-20) = 15
    assert _orig_to_buf_offset(25.0, segs) == 15.0


def test_orig_to_buf_offset_at_gap_boundary():
    segs = [(0.0, 10.0), (20.0, 60.0)]
    # t=15 is in the cut (between segs): orig_to_buf returns off at seg1 start = 10
    assert _orig_to_buf_offset(15.0, segs) == 10.0


def test_orig_to_buf_offset_trimmed_start():
    # trim_start=10: segs = [(10, 60)]
    segs = [(10.0, 60.0)]
    # t=10 -> buf 0, t=30 -> buf 20
    assert _orig_to_buf_offset(10.0, segs) == 0.0
    assert _orig_to_buf_offset(30.0, segs) == 20.0


# ---------------------------------------------------------------------------
# _build_volume_and_fades_filter
# ---------------------------------------------------------------------------


def test_build_no_filter_when_unity_volume_no_fades():
    result = _build_volume_and_fades_filter(1.0, [], [(0.0, 60.0)])
    assert result is None


def test_build_volume_only():
    result = _build_volume_and_fades_filter(0.5, [], [(0.0, 60.0)])
    assert result is not None
    assert "volume=" in result
    assert "0.500000" in result


def test_build_fade_out_standalone():
    # fade-out from t=55 to t=60
    fades = [{"start": 55.0, "end": 60.0, "type": "out"}]
    segs = [(0.0, 60.0)]
    result = _build_volume_and_fades_filter(1.0, fades, segs)
    assert result is not None
    # buf offset: bs=55, be=60, dur=5
    assert "55.000000" in result
    assert "60.000000" in result
    assert "eval=frame" in result


def test_build_fade_in_standalone():
    fades = [{"start": 0.0, "end": 3.0, "type": "in"}]
    segs = [(0.0, 60.0)]
    result = _build_volume_and_fades_filter(1.0, fades, segs)
    assert result is not None
    assert "3.000000" in result


def test_build_fade_out_with_cut_segs():
    # 60s song, cut 10-20, segs=(0,10),(20,60)
    # global fade-out at orig t=55-60 -> buf offset 45-50
    segs = [(0.0, 10.0), (20.0, 60.0)]
    fades = [{"start": 55.0, "end": 60.0, "type": "out"}]
    result = _build_volume_and_fades_filter(1.0, fades, segs)
    assert result is not None
    bs = _orig_to_buf_offset(55.0, segs)  # 10 + (55-20) = 45
    be = _orig_to_buf_offset(60.0, segs)  # 10 + (60-20) = 50
    assert abs(bs - 45.0) < 1e-9
    assert abs(be - 50.0) < 1e-9
    assert f"{bs:.6f}" in result
    assert f"{be:.6f}" in result


def test_build_skips_zero_duration_fade():
    fades = [{"start": 10.0, "end": 10.0, "type": "out"}]
    result = _build_volume_and_fades_filter(1.0, fades, [(0.0, 60.0)])
    assert result is None


# ---------------------------------------------------------------------------
# _apply_with_cuts filter_complex string (no ffmpeg — patch _run_ffmpeg)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cut_with_fade_out_filter_string(monkeypatch):
    """60s song, cut 10-20 with fade_out=2 on the cut, verifies afade st uses original PTS."""
    captured = {}

    async def fake_run(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr("songbirdapi.editor._run_ffmpeg", fake_run)
    monkeypatch.setattr(
        "songbirdapi.editor._get_duration", lambda path: _async_return(60.0)
    )

    cuts = [{"start": 10.0, "end": 20.0, "fade_out": 2.0, "fade_in": 0.0}]
    await _apply_with_cuts(
        "src.mp3", "dst.mp3",
        trim_start=0.0, trim_end=None,
        volume=1.0, fades=[],
        speed=1.0, normalize=False,
        cuts=cuts,
    )

    fc = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    # Segment 0: (0,10), fade_out=2 => afade=t=out:st=0+(10-2)=8.0000:d=2
    assert "afade=t=out:st=8.0000:d=2" in fc
    # No fade_in on segment 0 (pending_fade_in starts 0)
    assert "afade=t=in" not in fc


@pytest.mark.asyncio
async def test_cut_with_fade_in_filter_string(monkeypatch):
    """60s song, cut 10-20 with fade_in=3 on the cut (applies to segment after the cut)."""
    captured = {}

    async def fake_run(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr("songbirdapi.editor._run_ffmpeg", fake_run)
    monkeypatch.setattr(
        "songbirdapi.editor._get_duration", lambda path: _async_return(60.0)
    )

    cuts = [{"start": 10.0, "end": 20.0, "fade_out": 0.0, "fade_in": 3.0}]
    await _apply_with_cuts(
        "src.mp3", "dst.mp3",
        trim_start=0.0, trim_end=None,
        volume=1.0, fades=[],
        speed=1.0, normalize=False,
        cuts=cuts,
    )

    fc = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    # Segment 1: (20,60), fade_in=3 => afade=t=in:st=20.0000:d=3
    assert "afade=t=in:st=20.0000:d=3" in fc


@pytest.mark.asyncio
async def test_cut_with_both_fades_filter_string(monkeypatch):
    """60s song, cut 10-20, fade_out=2 on seg before cut and fade_in=3 on seg after."""
    captured = {}

    async def fake_run(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr("songbirdapi.editor._run_ffmpeg", fake_run)
    monkeypatch.setattr(
        "songbirdapi.editor._get_duration", lambda path: _async_return(60.0)
    )

    cuts = [{"start": 10.0, "end": 20.0, "fade_out": 2.0, "fade_in": 3.0}]
    await _apply_with_cuts(
        "src.mp3", "dst.mp3",
        trim_start=0.0, trim_end=None,
        volume=1.0, fades=[],
        speed=1.0, normalize=False,
        cuts=cuts,
    )

    fc = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    # seg0 (0,10): fade_out=2, st = 0 + (10-2) = 8
    assert "afade=t=out:st=8.0000:d=2" in fc
    # seg1 (20,60): fade_in=3, st = 20
    assert "afade=t=in:st=20.0000:d=3" in fc


@pytest.mark.asyncio
async def test_single_segment_cut_at_start(monkeypatch):
    """Cut removes the beginning (0-10); single segment (10,60) => _apply_simple called."""
    simple_calls = []

    original_apply_simple = _apply_simple

    async def fake_simple(src, dst, trim_s, trim_e, vol, fades, speed, norm):
        simple_calls.append({
            "trim_start": trim_s,
            "trim_end": trim_e,
            "fades": fades,
        })

    monkeypatch.setattr("songbirdapi.editor._apply_simple", fake_simple)
    monkeypatch.setattr(
        "songbirdapi.editor._get_duration", lambda path: _async_return(60.0)
    )

    cuts = [{"start": 0.0, "end": 10.0, "fade_out": 0.0, "fade_in": 2.0}]
    await _apply_with_cuts(
        "src.mp3", "dst.mp3",
        trim_start=0.0, trim_end=None,
        volume=1.0, fades=[],
        speed=1.0, normalize=False,
        cuts=cuts,
    )

    assert len(simple_calls) == 1
    call = simple_calls[0]
    assert call["trim_start"] == 10.0
    assert call["trim_end"] == 60.0
    # fade_in=2 should be merged as fade at start of remaining segment
    fi_fades = [f for f in call["fades"] if f["type"] == "in"]
    assert len(fi_fades) == 1
    assert fi_fades[0]["start"] == 10.0
    assert fi_fades[0]["end"] == 12.0


@pytest.mark.asyncio
async def test_single_segment_cut_at_end(monkeypatch):
    """Cut removes the end (50-60); single segment (0,50) => _apply_simple called."""
    simple_calls = []

    async def fake_simple(src, dst, trim_s, trim_e, vol, fades, speed, norm):
        simple_calls.append({
            "trim_start": trim_s,
            "trim_end": trim_e,
            "fades": fades,
        })

    monkeypatch.setattr("songbirdapi.editor._apply_simple", fake_simple)
    monkeypatch.setattr(
        "songbirdapi.editor._get_duration", lambda path: _async_return(60.0)
    )

    cuts = [{"start": 50.0, "end": 60.0, "fade_out": 3.0, "fade_in": 0.0}]
    await _apply_with_cuts(
        "src.mp3", "dst.mp3",
        trim_start=0.0, trim_end=None,
        volume=1.0, fades=[],
        speed=1.0, normalize=False,
        cuts=cuts,
    )

    assert len(simple_calls) == 1
    call = simple_calls[0]
    assert call["trim_start"] == 0.0
    assert call["trim_end"] == 50.0
    # fade_out=3 should be merged as fade at end of remaining segment
    fo_fades = [f for f in call["fades"] if f["type"] == "out"]
    assert len(fo_fades) == 1
    assert fo_fades[0]["start"] == 47.0
    assert fo_fades[0]["end"] == 50.0


@pytest.mark.asyncio
async def test_standalone_fade_no_cuts(monkeypatch):
    """Standalone fade-out applied to song with no cuts goes through _apply_simple."""
    captured = {}

    async def fake_run(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr("songbirdapi.editor._run_ffmpeg", fake_run)

    from songbirdapi.editor import apply_edits
    params = {
        "fades": [{"start": 55.0, "end": 60.0, "type": "out"}],
        "volume": 1.0,
        "speed": 1.0,
        "normalize": False,
        "cuts": [],
    }
    await apply_edits("src.mp3", "dst.mp3", params)

    cmd = captured["cmd"]
    af_idx = cmd.index("-af")
    af_val = cmd[af_idx + 1]
    assert "volume=" in af_val
    assert "55.000000" in af_val
    assert "60.000000" in af_val


@pytest.mark.asyncio
async def test_standalone_fade_with_cuts(monkeypatch):
    """Global fade-out at original t=55-60 on a song with cut 10-20 => buf offset 45-50."""
    captured = {}

    async def fake_run(cmd):
        captured["cmd"] = cmd

    monkeypatch.setattr("songbirdapi.editor._run_ffmpeg", fake_run)
    monkeypatch.setattr(
        "songbirdapi.editor._get_duration", lambda path: _async_return(60.0)
    )

    from songbirdapi.editor import apply_edits
    params = {
        "fades": [{"start": 55.0, "end": 60.0, "type": "out"}],
        "volume": 1.0,
        "speed": 1.0,
        "normalize": False,
        "cuts": [{"start": 10.0, "end": 20.0, "fade_out": 0.0, "fade_in": 0.0}],
    }
    await apply_edits("src.mp3", "dst.mp3", params)

    fc = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    # segs=(0,10),(20,60): buf offset for 55 = 10+(55-20)=45, for 60 = 10+(60-20)=50
    assert "45.000000" in fc
    assert "50.000000" in fc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_return(val):
    return val
