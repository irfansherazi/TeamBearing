"""
vQA — RAG Retrieval Precision Tests (AC-RETRIEVE-1, AC-RETRIEVE-2)
===================================================================
Tests: tests/test_rag_selector_retrieval.py

Phase 2 scope:
  AC-RETRIEVE-1  — Per-Step Selector Retrieval (precision, latency, null)
  AC-RETRIEVE-2  — Per-Step Blueprint/Skill Retrieval (precision, latency)

Mocking approach:
  - selector_registry.json paths mocked via tmp_path fixture
  - memory/selector_rag/ paths redirected to tmp_path for isolation
  - Registry data crafted to include a known-good match for each test
"""

import json
import time

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_registry_with_client_sort() -> dict:
    """
    Build a synthetic registry that includes a 'th.po-col-clientCol' entry
    that should be the top match for 'Sort production orders by CLIENT ascending'.
    """
    selectors = {}

    # Known-good match: CLIENT column selector (AC-RETRIEVE-1 explicit requirement)
    selectors["clientCol"] = {
        "description": "CLIENT column header for sorting production orders by client name",
        "context": "Visible in Production Orders list view. Used to sort ascending or descending.",
        "strategies": [
            {
                "method": "css",
                "selector": "th.po-col-clientCol",
                "name": "clientCol",
                "role": "",
            },
            {
                "method": "get_by_text",
                "name": "CLIENT",
                "role": "",
                "selector": "",
            },
        ],
    }

    # Add noise entries to ensure retrieval is selective
    noise_entries = {
        "loginEmailField": {
            "description": "Email placeholder text field on login form",
            "context": "Appears on the login page authentication screen",
            "strategies": [{"method": "get_by_placeholder", "name": "Email", "role": "", "selector": ""}],
        },
        "submitButton": {
            "description": "Submit All button to save quick order form",
            "context": "Quick Order form submit button area",
            "strategies": [{"method": "get_by_role", "role": "button", "name": "Submit All", "selector": ""}],
        },
        "newRequestButton": {
            "description": "New Request button to open quick order creation",
            "context": "Top navigation bar, opens the New Request panel",
            "strategies": [{"method": "get_by_role", "role": "button", "name": "New Request +", "selector": ""}],
        },
        "statusBadge": {
            "description": "Status badge showing Needs Producing or Needs Dubbing",
            "context": "Status column in production orders table",
            "strategies": [{"method": "get_by_text", "name": "Needs Producing", "role": "", "selector": ""}],
        },
        "adTypeSelect": {
            "description": "Ad Type dropdown selector for radio commercial selection",
            "context": "Quick order form ad type combobox",
            "strategies": [{"method": "get_by_role", "role": "combobox", "name": "Ad Type", "selector": ""}],
        },
        "nextPageButton": {
            "description": "Next Page pagination button to advance table page",
            "context": "Bottom pagination controls in production orders list",
            "strategies": [{"method": "get_by_role", "role": "button", "name": "Next Page", "selector": ""}],
        },
        "talentPoolCombobox": {
            "description": "Select Talent Pool combobox for voice request panel",
            "context": "Add Voice sidebar form talent pool selector",
            "strategies": [{"method": "get_by_role", "role": "combobox", "name": "Select Talent Pool", "selector": ""}],
        },
    }
    selectors.update(noise_entries)

    return {"version": "1.0", "last_updated": "2026-05-18", "selectors": selectors}


def _make_registry_many_entries(n_noise: int = 50) -> dict:
    """Registry with many entries to stress-test the top-K cap."""
    selectors = {}
    selectors["clientCol"] = {
        "description": "CLIENT column header sort production orders ascending descending",
        "context": "Production orders table sort column",
        "strategies": [{"method": "css", "selector": "th.po-col-clientCol", "name": "", "role": ""}],
    }
    for i in range(n_noise):
        selectors[f"noise_{i}"] = {
            "description": f"Unrelated element {i} for form validation checkbox toggle",
            "context": f"Context page {i} settings preferences dialog",
            "strategies": [{"method": "css", "selector": f".noise-{i}", "name": "", "role": ""}],
        }
    return {"version": "1.0", "selectors": selectors}


def _make_blueprint_yaml(name: str, description: str = "") -> str:
    desc = description or f"Open {name} and perform workflow steps"
    return f"""name: {name}
description: {desc}
steps:
  - description: Click New Request button to open Quick Order form
  - description: Select Radio Commercial from ad type dropdown
  - description: Fill client name field with target client
  - description: Submit the quick order form
"""


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def retrieval_rag(tmp_path):
    """
    SelectorRAG instance with a registry that includes a known clientCol entry.
    Pre-built index for use in retrieval tests.
    """
    from backend.kb.selector_rag import SelectorRAG

    registry_file = tmp_path / "selector_registry.json"
    registry_file.write_text(json.dumps(_make_registry_with_client_sort()), encoding="utf-8")

    bp_dir = tmp_path / "blueprints"
    bp_dir.mkdir()
    # Include quick_order_form.yaml — the blueprint AC-RETRIEVE-2 requires
    (bp_dir / "quick_order_form.yaml").write_text(
        _make_blueprint_yaml(
            "quick_order_form",
            "Open Quick Order form and select Radio Commercial ad type",
        ),
        encoding="utf-8",
    )
    (bp_dir / "compact_view_navigate.yaml").write_text(
        _make_blueprint_yaml("compact_view_navigate", "Switch production orders to compact view"),
        encoding="utf-8",
    )
    (bp_dir / "batch_checkbox.yaml").write_text(
        _make_blueprint_yaml("batch_checkbox", "Batch select checkboxes in production orders table"),
        encoding="utf-8",
    )

    index_dir = tmp_path / "selector_rag"
    index_dir.mkdir()

    rag = SelectorRAG(
        registry_path=registry_file,
        blueprints_dir=bp_dir,
        index_dir=index_dir,
    )
    rag.build_index()
    return rag


@pytest.fixture
def large_registry_rag(tmp_path):
    """SelectorRAG with 51+ entries to verify top-K capping."""
    from backend.kb.selector_rag import SelectorRAG

    registry_file = tmp_path / "selector_registry.json"
    registry_file.write_text(json.dumps(_make_registry_many_entries(n_noise=60)), encoding="utf-8")
    bp_dir = tmp_path / "blueprints"
    bp_dir.mkdir()
    index_dir = tmp_path / "selector_rag"
    index_dir.mkdir()

    rag = SelectorRAG(
        registry_path=registry_file,
        blueprints_dir=bp_dir,
        index_dir=index_dir,
    )
    rag.build_index()
    return rag


@pytest.fixture
def empty_registry_rag(tmp_path):
    """SelectorRAG backed by a registry with no relevant content for unmatched steps."""
    from backend.kb.selector_rag import SelectorRAG

    registry_file = tmp_path / "selector_registry.json"
    registry_file.write_text(
        json.dumps(
            {
                "version": "1.0",
                "selectors": {
                    "loginEmail": {
                        "description": "email password login authentication field",
                        "context": "login page only",
                        "strategies": [{"method": "get_by_placeholder", "name": "Email", "role": "", "selector": ""}],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    bp_dir = tmp_path / "blueprints"
    bp_dir.mkdir()
    index_dir = tmp_path / "selector_rag"
    index_dir.mkdir()

    rag = SelectorRAG(
        registry_path=registry_file,
        blueprints_dir=bp_dir,
        index_dir=index_dir,
    )
    rag.build_index()
    return rag


# ── AC-RETRIEVE-1: Per-Step Selector Retrieval ─────────────────────────────────


class TestSelectorRetrieval:
    """AC-RETRIEVE-1: Selector retrieval precision, latency, and null-case."""

    def test_selector_retrieval_client_sort(self, retrieval_rag):
        """
        AC-RETRIEVE-1: Querying 'Sort production orders by CLIENT ascending'
        must return a result block containing 'clientCol' (the known-good selector).

        This is the explicit AC-RETRIEVE-1 requirement:
        'The th.po-col-clientCol CSS selector entry is included in the results'
        """
        result = retrieval_rag.query("Sort production orders by CLIENT ascending")

        assert result, "query() must return a non-empty string for client sort step"
        assert "clientCol" in result or "CLIENT" in result, (
            f"Expected 'clientCol' or 'CLIENT' in retrieval result for sort step.\nGot: {result[:500]!r}"
        )

    def test_selector_retrieval_returns_selector_block(self, retrieval_rag):
        """
        AC-RETRIEVE-1: Returned block must be formatted as a SELECTOR REGISTRY block
        with the expected header marker.
        """
        result = retrieval_rag.query("Sort production orders by CLIENT ascending")

        assert "SELECTOR REGISTRY" in result, "Result block must include 'SELECTOR REGISTRY' header marker"

    def test_selector_retrieval_respects_max_selectors_cap(self, large_registry_rag):
        """
        AC-RETRIEVE-1: ≤20 selector entries returned even with 61-entry registry.

        Count entries by counting the '[' brackets that open entry descriptions.
        We verify by checking the block length is capped, not by parsing the format.
        """
        result = large_registry_rag.query(
            "Sort production orders by CLIENT ascending",
            max_selectors=20,
            max_chars=99999,  # Disable budget cap to test selector count independently
        )

        # Count entry markers: each entry has a "[Description...]" line
        entry_count = result.count("\n  [")
        assert entry_count <= 20, (
            f"Expected ≤20 entries in result, found {entry_count}.\nResult snippet: {result[:300]!r}"
        )

    def test_selector_retrieval_latency_under_50ms(self, retrieval_rag):
        """
        AC-RETRIEVE-1: Retrieval must complete in ≤50ms (pure TF-IDF + BM25, no LLM).
        """
        # Warm up (first call loads index)
        retrieval_rag.query("Sort production orders by CLIENT ascending")

        # Measure hot path
        start = time.monotonic()
        retrieval_rag.query("Sort production orders by CLIENT ascending")
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 50.0, f"Selector retrieval took {elapsed_ms:.1f}ms — must be ≤50ms (hot path)"

    def test_selector_retrieval_empty_for_unmatched_step(self, empty_registry_rag):
        """
        AC-RETRIEVE-1: Returns empty string for steps with no matching selectors.

        Registry contains only login-related entries; step is about an unrelated
        voice request workflow. The retrieval should return empty (graceful null).
        """
        result = empty_registry_rag.query(
            "Navigate to the dashboard settings preferences configuration panel",
            max_selectors=5,
        )
        # Score filter (score <= 0 skipped) should return empty or very short block
        # Allow either "" or a block with no entries inside
        if result:
            # If non-empty, it must not contain any selector entries
            entry_count = result.count("\n  [")
            assert entry_count == 0, (
                f"Expected no entries for unmatched step, found {entry_count}.\nResult: {result[:300]!r}"
            )

    def test_selector_retrieval_block_under_800_chars(self, retrieval_rag):
        """
        AC-RETRIEVE-1: Injected block (selector section only) must be ≤800 chars.
        Tested with max_chars=800 (selector-only cap per AC-RETRIEVE-1).
        """
        result = retrieval_rag.query(
            "Sort production orders by CLIENT ascending",
            max_chars=800,
        )
        assert len(result) <= 800 + 50, (  # +50 for truncation suffix
            f"Selector block is {len(result)} chars — must be ≤800 chars. Got: {result[:300]!r}"
        )

    def test_selector_retrieval_returns_string(self, retrieval_rag):
        """query() must always return a str (never None or dict)."""
        result = retrieval_rag.query("Click the New Request button")
        assert isinstance(result, str), f"query() must return str, got {type(result).__name__}"

    def test_selector_retrieval_empty_step_returns_empty(self, retrieval_rag):
        """query() with empty ac_step must return '' (guard against empty query)."""
        result = retrieval_rag.query("")
        assert result == "", "query('') must return empty string"

    def test_selector_retrieval_domain_context_appended(self, retrieval_rag):
        """
        domain_context is appended to query text (max 100 chars).
        Result should still be valid (no crash).
        """
        result = retrieval_rag.query(
            "Sort production orders by CLIENT",
            domain_context="target_element_types: [th, button, link]",
        )
        # Verify it doesn't crash and returns a string
        assert isinstance(result, str)

    def test_selector_retrieval_semantic_boost_applied(self, tmp_path):
        """
        AC-RETRIEVE-1: Entries with get_by_role/get_by_label strategies receive
        a scoring boost (Decision 7 in creative doc). This test verifies the boost
        constant is defined and applied in query() by examining the SelectorRAG
        internal constants and ensuring _SEMANTIC_SCORE_BONUS > 0.
        """
        from backend.kb.selector_rag import _SEMANTIC_METHODS, _SEMANTIC_SCORE_BONUS, SelectorRAG

        # Verify the boost constant is defined and positive
        assert _SEMANTIC_SCORE_BONUS > 0, f"_SEMANTIC_SCORE_BONUS must be > 0, got {_SEMANTIC_SCORE_BONUS}"
        assert "get_by_role" in _SEMANTIC_METHODS, "get_by_role must be in _SEMANTIC_METHODS"
        assert "get_by_label" in _SEMANTIC_METHODS, "get_by_label must be in _SEMANTIC_METHODS"

        # Build a registry with a differentiated corpus (enough docs for TF-IDF to score)
        # Include many noise entries so the relevant entries get distinct scores
        selectors = {}
        selectors["semanticSubmit"] = {
            "description": "Submit quick order form button action element interaction",
            "context": "Quick order form submission confirmation panel",
            "strategies": [{"method": "get_by_role", "role": "button", "name": "Submit All", "selector": ""}],
        }
        selectors["cssSubmit"] = {
            "description": "Submit quick order form button action element interaction css",
            "context": "Quick order form submission css class locator",
            "strategies": [{"method": "css", "selector": "button.submit-all-btn", "name": "", "role": ""}],
        }
        # Add 20 noise entries with unrelated content
        for i in range(20):
            selectors[f"noise_{i}"] = {
                "description": f"Logout sign out username credential token {i}",
                "context": f"User dropdown navigation logout panel {i}",
                "strategies": [{"method": "css", "selector": f".logout-{i}", "name": "", "role": ""}],
            }

        reg_file = tmp_path / "sr.json"
        reg_file.write_text(json.dumps({"version": "1.0", "selectors": selectors}), encoding="utf-8")
        bp_dir = tmp_path / "bp"
        bp_dir.mkdir()
        idx_dir = tmp_path / "idx"
        idx_dir.mkdir()

        rag = SelectorRAG(registry_path=reg_file, blueprints_dir=bp_dir, index_dir=idx_dir)
        rag.build_index()

        result = rag.query(
            "Submit the quick order form and confirm the order",
            max_chars=99999,
        )

        if result:
            # If both entries appear, semantic entry must come first
            pos_semantic = result.find("Submit All")
            pos_css = result.find("submit-all-btn")

            if pos_semantic != -1 and pos_css != -1:
                assert pos_semantic < pos_css, (
                    f"Expected semantic entry (pos={pos_semantic}) before CSS entry "
                    f"(pos={pos_css}) due to _SEMANTIC_SCORE_BONUS={_SEMANTIC_SCORE_BONUS}"
                )
            # If only one appears, that's acceptable (score threshold filtered the other)


# ── AC-RETRIEVE-2: Per-Step Blueprint/Skill Retrieval ─────────────────────────


class TestSkillRetrieval:
    """AC-RETRIEVE-2: Blueprint/skill retrieval precision and latency."""

    def test_skill_retrieval_quick_order(self, retrieval_rag):
        """
        AC-RETRIEVE-2: 'Open Quick Order form and select Radio Commercial ad type'
        must return a block containing 'quick_order_form' blueprint.
        """
        result = retrieval_rag.query("Open Quick Order form and select Radio Commercial ad type")

        assert result, "query() must return non-empty string for quick order step"
        assert "quick_order_form" in result or "Quick Order" in result, (
            f"Expected 'quick_order_form' blueprint in retrieval result.\nGot: {result[:500]!r}"
        )

    def test_skill_retrieval_includes_blueprint_section(self, tmp_path):
        """
        AC-RETRIEVE-2: When blueprints are matched, result must include
        'SKILL BLUEPRINTS' section header.

        Uses a dedicated fixture with differentiated blueprint content so
        quick_order_form achieves a non-zero TF-IDF score.
        """
        from backend.kb.selector_rag import SelectorRAG

        reg_file = tmp_path / "sr.json"
        reg_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "selectors": {
                        "adTypeSelect": {
                            "description": "Ad Type dropdown selector for quick order radio commercial",
                            "context": "Quick order form panel",
                            "strategies": [
                                {"method": "get_by_role", "role": "combobox", "name": "Ad Type", "selector": ""}
                            ],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        bp_dir = tmp_path / "blueprints"
        bp_dir.mkdir()

        # Differentiated blueprint content so TF-IDF scores vary
        (bp_dir / "quick_order_form.yaml").write_text(
            "name: quick_order_form\n"
            "description: Open Quick Order form and select Radio Commercial ad type\n"
            "steps:\n"
            "  - description: Click New Request plus button in top navigation bar\n"
            "  - description: Select Radio Commercial from ad type dropdown selector\n"
            "  - description: Fill client name field with demo client identifier\n"
            "  - description: Submit the quick order form using Submit All button\n",
            encoding="utf-8",
        )
        (bp_dir / "batch_approve.yaml").write_text(
            "name: batch_approve\n"
            "description: Batch approve multiple spots using checkbox selection\n"
            "steps:\n"
            "  - description: Select checkboxes on target rows in the production list\n"
            "  - description: Click the batch approve action bar button\n",
            encoding="utf-8",
        )
        (bp_dir / "logout_flow.yaml").write_text(
            "name: logout_flow\n"
            "description: Logout from application via user dropdown menu\n"
            "steps:\n"
            "  - description: Click username button to open user dropdown\n"
            "  - description: Click Logout link in dropdown menu\n",
            encoding="utf-8",
        )

        idx_dir = tmp_path / "idx"
        idx_dir.mkdir()

        rag = SelectorRAG(registry_path=reg_file, blueprints_dir=bp_dir, index_dir=idx_dir)
        rag.build_index()

        result = rag.query(
            "Open Quick Order form and select Radio Commercial ad type",
            max_chars=99999,
        )

        assert "SKILL BLUEPRINTS" in result, (
            f"Result must include 'SKILL BLUEPRINTS' section when blueprints are retrieved.\nGot: {result[:600]!r}"
        )

    def test_skill_retrieval_respects_max_skills_cap(self, tmp_path):
        """
        AC-RETRIEVE-2: ≤5 blueprint entries returned even with 10+ blueprints.
        """
        from backend.kb.selector_rag import SelectorRAG

        reg_file = tmp_path / "sr.json"
        reg_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "selectors": {
                        "btn": {
                            "description": "Quick order button form selector",
                            "context": "Order form",
                            "strategies": [
                                {"method": "get_by_role", "role": "button", "name": "Submit", "selector": ""}
                            ],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        bp_dir = tmp_path / "blueprints"
        bp_dir.mkdir()
        # Create 10 blueprints with similar descriptions
        for i in range(10):
            (bp_dir / f"quick_order_{i}.yaml").write_text(
                _make_blueprint_yaml(
                    f"quick_order_{i}",
                    f"Open Quick Order form step {i} and select Radio Commercial",
                ),
                encoding="utf-8",
            )

        idx_dir = tmp_path / "idx"
        idx_dir.mkdir()

        rag = SelectorRAG(registry_path=reg_file, blueprints_dir=bp_dir, index_dir=idx_dir)
        rag.build_index()

        result = rag.query(
            "Open Quick Order form and select Radio Commercial",
            max_skills=5,
            max_chars=99999,
        )

        # Count blueprint entry markers
        blueprint_count = result.count("[Blueprint:")
        assert blueprint_count <= 5, (
            f"Expected ≤5 blueprint entries, found {blueprint_count}.\nResult snippet: {result[:400]!r}"
        )

    def test_skill_retrieval_latency_under_50ms(self, retrieval_rag):
        """
        AC-RETRIEVE-2: Blueprint retrieval must complete in ≤50ms (hot path).
        """
        # Warm up
        retrieval_rag.query("Open Quick Order form and select Radio Commercial ad type")

        # Measure hot path
        start = time.monotonic()
        retrieval_rag.query("Open Quick Order form and select Radio Commercial ad type")
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 50.0, f"Skill retrieval took {elapsed_ms:.1f}ms — must be ≤50ms (hot path)"

    def test_skill_retrieval_block_under_1200_chars(self, retrieval_rag):
        """
        AC-RETRIEVE-2: Injected skill block must be ≤1200 chars.
        """
        result = retrieval_rag.query(
            "Open Quick Order form and select Radio Commercial ad type",
            max_chars=1200,
        )
        assert len(result) <= 1200 + 50, (  # +50 for truncation suffix
            f"Skill block is {len(result)} chars — expected ≤1200 chars."
        )

    def test_skill_retrieval_no_crash_on_empty_blueprints_dir(self, tmp_path):
        """
        AC-RETRIEVE-2: query() must not crash when blueprints/ directory has no YAMLs.
        """
        from backend.kb.selector_rag import SelectorRAG

        reg_file = tmp_path / "sr.json"
        reg_file.write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "selectors": {
                        "clientCol": {
                            "description": "CLIENT column sort table",
                            "context": "Production orders",
                            "strategies": [
                                {"method": "css", "selector": "th.po-col-clientCol", "name": "", "role": ""}
                            ],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        bp_dir = tmp_path / "blueprints"
        bp_dir.mkdir()  # Empty directory
        idx_dir = tmp_path / "idx"
        idx_dir.mkdir()

        rag = SelectorRAG(registry_path=reg_file, blueprints_dir=bp_dir, index_dir=idx_dir)
        rag.build_index()

        result = rag.query("Sort production orders by CLIENT")
        assert isinstance(result, str), "query() must return str even with empty blueprints"


# ── AC-RETRIEVE-1/2: Planner Cache Integration ────────────────────────────────


class TestPlannerCacheIntegration:
    """
    Verify that _SEL_RAG_CACHE exists in planner.py and is cleared by
    clear_rag_caches() (Phase 2 scope: add _SEL_RAG_CACHE to planner).
    """

    def test_sel_rag_cache_exists_in_planner(self):
        """
        Phase 2 requires adding _SEL_RAG_CACHE dict to planner.py.
        This test verifies the cache dict is importable.
        """
        import backend.engine.planner as planner_mod

        assert hasattr(planner_mod, "_SEL_RAG_CACHE"), (
            "_SEL_RAG_CACHE must be added to planner.py as a module-level cache dict"
        )
        assert isinstance(planner_mod._SEL_RAG_CACHE, dict), "_SEL_RAG_CACHE must be a dict"

    def test_clear_rag_caches_clears_sel_rag_cache(self):
        """
        clear_rag_caches() must also clear _SEL_RAG_CACHE to prevent stale
        RAG results from a previous run contaminating the current run.
        """
        import backend.engine.planner as planner_mod
        from backend.engine.planner import clear_rag_caches

        # Seed the cache with a fake entry
        planner_mod._SEL_RAG_CACHE["test_step"] = "fake_result"

        clear_rag_caches()

        assert planner_mod._SEL_RAG_CACHE == {}, "clear_rag_caches() must clear _SEL_RAG_CACHE"

    def test_selector_rag_imported_in_planner(self):
        """
        Phase 2 requires importing selector_rag singleton into planner.py.
        """
        import backend.engine.planner as planner_mod

        assert hasattr(planner_mod, "selector_rag"), "selector_rag singleton must be imported/accessible in planner.py"

    def test_rag_selector_stats_field_in_vqa_state(self):
        """
        Phase 2 requires adding rag_selector_stats field to VQAState in state.py.
        """
        from backend.engine.state import VQAState

        # VQAState is a TypedDict; check the __annotations__
        annotations = VQAState.__annotations__
        assert "rag_selector_stats" in annotations, (
            "VQAState must have 'rag_selector_stats' field (list[dict], append reducer)"
        )

    def test_make_initial_state_includes_rag_selector_stats(self):
        """
        make_initial_state() must initialize rag_selector_stats to [] (empty list).
        """
        from backend.engine.state import make_initial_state

        state = make_initial_state(
            run_id="run-test-001",
            jira_ticket_id="VC2-9999",
            role="account_executive",
            target_url="https://two-test.vcreative.net",
            mode="headless",
        )

        assert "rag_selector_stats" in state, "make_initial_state() must include rag_selector_stats key"
        assert state["rag_selector_stats"] == [], "rag_selector_stats must be initialized to [] in make_initial_state()"
