# conftest.py — project-level pytest configuration
#
# Pre-import numpy/sklearn/scipy before any test file is collected.
# test_blueprint_validation.py inserts backend/ into sys.path[0] at
# module level, which can cause sklearn's first import (triggered later
# by test_matcher.py tests) to fail on Python 3.13 due to a changed
# import resolution path. Importing here ensures these packages are
# fully cached in sys.modules before any test file modifies sys.path.
try:
    import numpy  # noqa: F401
    from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: F401
except ImportError:
    pass  # Optional dependency — KB retrieval tests will skip if absent
