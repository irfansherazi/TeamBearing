---
name: "Learned: Vision Analysis"
globs: ["backend/engine/vision_analyzer.py", "backend/engine/ac_parser.py"]
topics: ["vision", "multimodal", "ui-reasoning", "video", "ffmpeg"]
priority: low
evidence_count: 2
last_updated: 2026-07-14
auto_generated: true
derived_from: []
last_validated: 2026-07-22
---


# Vision Analysis

- Use heavy models (Claude 3.5 Sonnet+) for UI vision tasks; light models often miss small text or spatial relationships critical for QA.
- Map mime types carefully to provider-supported formats (e.g., Bedrock uses 'jpeg' for both .jpg and .jpeg).
- Prioritize image selection (recency, size, relevance) to minimize token cost and latency while maximizing signal.
- When extracting frames from MP4 via `asyncio.create_subprocess_exec` with ffmpeg (`image2pipe -vcodec png`), split the raw stdout bytes on `b'\x89PNG'` magic bytes but re-prepend the magic bytes to each fragment — the split boundary consumes the first two bytes, so reconstruct as `b'\x89PNG' + chunk` or each frame's PNG header is missing and the bytes are corrupt.

## Evidence

| Learning | Source | Date |
|----------|--------|------|
| Vision Grounding | [reflection-TASK-047.md](../reflection/reflection-TASK-047.md) | 2026-05-21 |
| ffmpeg PNG magic byte reconstruction | [reflection-TASK-122.md](../reflection/reflection-TASK-122.md) | 2026-07-14 |
