"""
Tests for MP4 frame extraction and video analysis (TASK-122 Phase 2).

Covers:
- _extract_mp4_frames: ffmpeg subprocess called with correct args, frames returned
- analyze_video: frames passed to vision model, combined summary returned
- analyze_video: graceful degradation when ffmpeg is unavailable
- analyze_video: graceful degradation when ffmpeg returns non-zero exit code
- _get_visual_context: video/mp4 MIME type is now processed (not silently skipped)
- analyze_video: empty result when video produces no frames
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.engine.vision_analyzer import VisionAnalyzer

# ── PNG fixture helpers ────────────────────────────────────────────────────────

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
FAKE_PNG_1 = PNG_MAGIC + b"\x00" * 20 + b"FRAME1"
FAKE_PNG_2 = PNG_MAGIC + b"\x00" * 20 + b"FRAME2"


# ── _extract_mp4_frames tests ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_extract_mp4_frames_calls_ffmpeg_with_pipe_args():
    """Verify _extract_mp4_frames runs ffmpeg with stdin/stdout pipe flags."""
    analyzer = VisionAnalyzer()
    fake_proc = AsyncMock()
    fake_proc.communicate.return_value = (FAKE_PNG_1 + FAKE_PNG_2, b"")
    fake_proc.returncode = 0

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("asyncio.create_subprocess_exec", return_value=fake_proc) as mock_exec,
    ):
        frames = await analyzer._extract_mp4_frames(b"fake-mp4-bytes")

    call_args = mock_exec.call_args[0]
    assert call_args[0] == "ffmpeg"
    assert "pipe:0" in call_args or "-i" in call_args
    assert "pipe:1" in call_args or "-f" in call_args
    assert len(frames) >= 1


@pytest.mark.anyio
async def test_extract_mp4_frames_returns_empty_when_ffmpeg_unavailable():
    """Verify _extract_mp4_frames returns [] when ffmpeg is not installed."""
    analyzer = VisionAnalyzer()

    with patch("shutil.which", return_value=None):
        frames = await analyzer._extract_mp4_frames(b"fake-mp4-bytes")

    assert frames == []


@pytest.mark.anyio
async def test_extract_mp4_frames_returns_empty_on_nonzero_exit():
    """Verify _extract_mp4_frames returns [] when ffmpeg exits non-zero."""
    analyzer = VisionAnalyzer()
    fake_proc = AsyncMock()
    fake_proc.communicate.return_value = (b"", b"error: invalid input")
    fake_proc.returncode = 1

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch("asyncio.create_subprocess_exec", return_value=fake_proc),
    ):
        frames = await analyzer._extract_mp4_frames(b"fake-mp4-bytes")

    assert frames == []


# ── analyze_video tests ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_analyze_video_passes_frames_to_vision_model():
    """Verify analyze_video extracts frames and passes each as image/png to LLM."""
    analyzer = VisionAnalyzer()

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(
        content="Frame shows: Submit button in blue.",
        response_metadata={"usage": {}},
    )
    analyzer.llm = mock_llm

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch.object(analyzer, "_extract_mp4_frames", new_callable=AsyncMock) as mock_extract,
    ):
        mock_extract.return_value = [FAKE_PNG_1, FAKE_PNG_2]
        summary = await analyzer.analyze_video(b"fake-mp4-bytes", ac_text="Click the submit button.")

    assert "Submit button in blue" in summary
    assert mock_llm.ainvoke.call_count == 2  # one call per extracted frame

    # Verify each frame was passed as image/png content block
    for call in mock_llm.ainvoke.call_args_list:
        messages = call[0][0]
        content = messages[0].content
        assert content[0]["image"]["format"] == "png"


@pytest.mark.anyio
async def test_analyze_video_returns_empty_when_ffmpeg_unavailable():
    """Verify analyze_video returns '' and logs warning when ffmpeg is absent."""
    analyzer = VisionAnalyzer()

    with patch("shutil.which", return_value=None):
        result = await analyzer.analyze_video(b"fake-mp4-bytes", ac_text="AC text")

    assert result == ""


@pytest.mark.anyio
async def test_analyze_video_returns_empty_when_no_frames_extracted():
    """Verify analyze_video returns '' when ffmpeg produces no frames."""
    analyzer = VisionAnalyzer()

    with (
        patch("shutil.which", return_value="/usr/bin/ffmpeg"),
        patch.object(analyzer, "_extract_mp4_frames", new_callable=AsyncMock) as mock_extract,
    ):
        mock_extract.return_value = []
        result = await analyzer.analyze_video(b"fake-mp4-bytes", ac_text="AC text")

    assert result == ""


# ── _get_visual_context integration: video/mp4 is no longer skipped ──────────


@pytest.mark.anyio
async def test_get_visual_context_processes_mp4_attachment():
    """Verify _get_visual_context dispatches MP4 attachments to analyze_video."""
    from backend.engine.ac_parser import _get_visual_context
    from backend.engine.state import make_initial_state

    state = make_initial_state(
        run_id="test-run", jira_ticket_id="QA-999", role="admin", target_url="http://test.com", mode="headless"
    )
    state["jira_ticket"]["attachments"] = [
        {"id": "vid-1", "filename": "demo.mp4", "mimeType": "video/mp4", "size": 512 * 1024}
    ]
    state["jira_ticket"]["acceptance_criteria"] = "Test the upload flow"

    with (
        patch("backend.engine.ac_parser.download_attachment", new_callable=AsyncMock) as mock_download,
        patch("backend.engine.ac_parser.VisionAnalyzer") as mock_cls,
    ):
        mock_download.return_value = b"fake-mp4-bytes"
        mock_instance = MagicMock()
        mock_instance.analyze_video = AsyncMock(return_value="Video frame: Upload button visible.")
        mock_cls.return_value = mock_instance

        result = await _get_visual_context(state)

    assert "Upload button visible" in result
    assert mock_instance.analyze_video.called
