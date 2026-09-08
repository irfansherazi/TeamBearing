---
derived_from: []
evidence_count: 1
last_validated: 2026-07-22
---
# Learned Rules: python-compatibility

_Auto-extracted from task reflections. Reinforced rules are promoted; unreinforced rules expire after 90 days._

---

## Rules

- **early-import-precache** (`backend/main.py`, `conftest.py`): In Python 3.13+ environments where `pydantic` or other modules partially initialize `numpy`, pre-import `numpy` and `sklearn.feature_extraction.text.TfidfVectorizer` at the very top of the application entrypoint (before any other vQA imports). This resolves the `ImportError: cannot import name randbits` bug caused by corrupted import resolution chains. Apply this to both application entrypoints (`main.py`) and test entrypoints (`conftest.py`).
  - _Source_: reflection-TASK-075 (2026-05-29)
  - _Reinforced_: 1x (re-applied fix from `conftest.py` to `main.py`)
