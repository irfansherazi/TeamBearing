import asyncio
import logging
import shutil

from langchain_core.messages import HumanMessage

from backend.llm import get_llm

logger = logging.getLogger(__name__)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class VisionAnalyzer:
    """
    Vision Analysis Service for Jira Attachments.

    Uses Claude 3.5 Sonnet via Bedrock to extract visual grounding context
    from image attachments, helping the AC Parser produce more accurate
    test plans.
    """

    def __init__(self):
        # Vision tasks require a heavy model for accurate UI reasoning
        self.llm = get_llm("vision_analyzer", heavy=True)

    async def analyze_image(self, image_bytes: bytes, mime_type: str, ac_text: str, run_id: str = "") -> str:
        """
        Analyze a single attachment (image or PDF) and return a text summary.

        Args:
            image_bytes: Raw binary content.
            mime_type: Mime type (e.g. 'image/png', 'application/pdf').
            ac_text: The raw Acceptance Criteria text for context.
            run_id: Optional run identifier for metrics recording.

        Returns:
            A string containing visual facts, or an empty string if analysis fails.
        """
        # Map mime types to Bedrock supported formats
        supported_images = {
            "image/png": "png",
            "image/jpeg": "jpeg",
            "image/jpg": "jpeg",
            "image/webp": "webp",
            "image/gif": "gif",
        }

        # Bedrock Converse API supports PDF as a document
        is_pdf = mime_type == "application/pdf"
        img_format = supported_images.get(mime_type)

        if not img_format and not is_pdf:
            logger.warning(f"[VisionAnalyzer] Unsupported mime type: {mime_type}")
            return ""

        logger.info(f"[VisionAnalyzer] Sending {len(image_bytes)} bytes for analysis (type: {mime_type})")

        # Construct Bedrock Converse content blocks
        if is_pdf:
            content_block = {
                "document": {
                    "format": "pdf",
                    "name": "Jira_Attachment",
                    "source": {"bytes": image_bytes},
                }
            }
        else:
            content_block = {
                "image": {
                    "format": img_format,
                    "source": {"bytes": image_bytes},
                }
            }

        user_content = [
            content_block,
            {
                "text": (
                    "You are a Senior QA Automation Engineer. Your goal is to extract visual grounding "
                    "data from this Jira attachment to help write a test plan.\n\n"
                    "Focus on:\n"
                    "1. Exact text of buttons, links, and dropdowns.\n"
                    "2. Layout relationship (e.g., 'The Save button is inside the Header component').\n"
                    "3. Field names in forms.\n\n"
                    f"Acceptance Criteria for context:\n{ac_text}\n\n"
                    "Analyze the attachment and provide concise bullet points of visual facts that "
                    "specifically help clarify the terms or workflows mentioned in the AC."
                ),
            },
        ]

        try:
            import time
            t0 = time.monotonic()
            message = HumanMessage(content=user_content)
            response = await self.llm.ainvoke([message])
            latency_ms = int((time.monotonic() - t0) * 1000)

            summary = str(response.content).strip()

            # ── Record metrics ──────────────────────────────────────
            if run_id:
                try:
                    from backend.config import settings
                    from backend.engine.metrics import get_run_metrics
                    run_metrics = get_run_metrics(run_id)
                    usage = response.response_metadata.get("usage", {})
                    run_metrics.record_llm_call(
                        purpose="vision_analyzer",
                        model_id=settings.bedrock_model_id_heavy,
                        input_tokens=usage.get("input_tokens", 0),
                        output_tokens=usage.get("output_tokens", 0),
                        latency_ms=latency_ms,
                    )
                except Exception as e:
                    logger.warning("[%s] Failed to record VisionAnalyzer metrics: %s", run_id, e)

            if not summary:
                logger.warning("[VisionAnalyzer] Received empty response from LLM")
                return ""

            return summary

        except Exception as e:
            logger.error(f"[VisionAnalyzer] Vision analysis failed: {e}")
            return ""

    async def _extract_mp4_frames(self, video_bytes: bytes, max_frames: int = 3) -> list[bytes]:
        """
        Extract up to max_frames PNG frames from MP4 bytes using ffmpeg via stdin pipe.

        Returns an empty list if ffmpeg is unavailable or extraction fails.
        Frames are evenly sampled at 1 fps, scaled to 640px wide for vision model efficiency.
        """
        if not shutil.which("ffmpeg"):
            logger.warning("[VisionAnalyzer] ffmpeg not available — skipping MP4")
            return []

        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-i", "pipe:0",
                "-vf", "fps=1,scale=640:-2",
                "-frames:v", str(max_frames),
                "-f", "image2pipe",
                "-vcodec", "png",
                "-loglevel", "error",
                "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(input=video_bytes), timeout=30.0)
        except FileNotFoundError:
            logger.warning("[VisionAnalyzer] ffmpeg not available — skipping MP4")
            return []
        except Exception as e:
            logger.warning("[VisionAnalyzer] ffmpeg frame extraction failed: %s", e)
            return []

        if proc.returncode != 0 or not stdout:
            if stderr:
                logger.warning("[VisionAnalyzer] ffmpeg stderr: %s", stderr.decode(errors="replace")[:200])
            return []

        # Split concatenated PNG stream on the PNG magic bytes
        parts = stdout.split(PNG_MAGIC)
        frames = [PNG_MAGIC + part for part in parts if part]
        logger.info("[VisionAnalyzer] Extracted %d frame(s) from MP4", len(frames))
        return frames[:max_frames]

    async def analyze_video(self, video_bytes: bytes, ac_text: str, run_id: str = "") -> str:
        """
        Extract key frames from an MP4 and run vision analysis on each frame.

        Frames are extracted via ffmpeg (stdin pipe, no disk writes) and each PNG
        frame is analyzed independently using the vision model. Results are combined
        into a single context string.

        Returns an empty string if ffmpeg is unavailable or no frames can be extracted.
        """
        frames = await self._extract_mp4_frames(video_bytes)
        if not frames:
            return ""

        logger.info("[VisionAnalyzer] Analyzing %d frame(s) from MP4 video (run_id=%s)", len(frames), run_id)

        tasks = [self.analyze_image(frame, "image/png", ac_text, run_id) for frame in frames]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        summaries = [r for r in results if isinstance(r, str) and r]
        if not summaries:
            return ""

        return "\n\n".join(f"[Video Frame {i + 1}] {s}" for i, s in enumerate(summaries))
