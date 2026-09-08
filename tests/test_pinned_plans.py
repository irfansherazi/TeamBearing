"""
tests/test_pinned_plans.py
==========================

Unit tests for the pinned TestPlan store (``backend/engine/pinned_plans``).

Covers:
  - Round-trip: save → load returns byte-identical TestPlan + file on disk
    (AC-VERIFY-1)
  - Missing plan_id raises PinnedPlanNotFound (AC-ERROR-1 store side)
  - Expired plan raises PinnedPlanExpired + file deleted from disk
    (AC-VERIFY-2 / AC-ERROR-2 store side)
  - prune_expired() removes expired files + returns count, keeps fresh files
    (AC-VERIFY-6)
  - Config integration: pinned_plan_ttl_days setting present, default=14
"""

import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers: env-var-isolated store directory (same pattern as ac_parse_cache)
# ---------------------------------------------------------------------------

PINNED_PLANS_DIR_ENV = "PINNED_PLANS_DIR"


def _set_store_dir(tmp_path: Path) -> None:
    """Point the module at an isolated temp directory for this test."""
    os.environ[PINNED_PLANS_DIR_ENV] = str(tmp_path)


def _clear_store_dir() -> None:
    os.environ.pop(PINNED_PLANS_DIR_ENV, None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_store(tmp_path):
    """Isolate each test in its own tmp directory — no cross-test pollution."""
    _set_store_dir(tmp_path)
    yield tmp_path
    _clear_store_dir()


SAMPLE_TEST_PLAN = {
    "steps": [
        {
            "step_number": 1,
            "description": "Login as Account Executive",
            "action": "navigate",
            "target": "https://qa.vcreative.net",
        },
        {
            "step_number": 2,
            "description": "Verify dashboard loads",
            "action": "assert_visible",
            "target": "Dashboard",
        },
    ],
    "roles": ["account_executive"],
    "acceptance_criteria": "Given I am logged in as AE\nWhen I open the dashboard\nThen I see the dashboard",
}

SAMPLE_AC = "Given I am logged in as AE\nWhen I open the dashboard\nThen I see the dashboard"


# ---------------------------------------------------------------------------
# AC-VERIFY-1: Round-trip save → load
# ---------------------------------------------------------------------------


class TestSaveLoadRoundTrip:
    """save() + load() returns byte-identical TestPlan; file exists on disk."""

    def test_save_returns_opaque_plan_id(self, isolated_store):
        from backend.engine.pinned_plans import save

        plan_id = save(SAMPLE_TEST_PLAN, SAMPLE_AC)

        assert isinstance(plan_id, str), "plan_id must be a str"
        assert len(plan_id) > 0, "plan_id must be non-empty"

    def test_load_returns_identical_test_plan(self, isolated_store):
        from backend.engine.pinned_plans import load, save

        plan_id = save(SAMPLE_TEST_PLAN, SAMPLE_AC)
        loaded = load(plan_id)

        assert loaded == SAMPLE_TEST_PLAN, (
            "Loaded TestPlan must be byte-identical to saved TestPlan"
        )

    def test_file_exists_on_disk_after_save(self, isolated_store):
        from backend.engine.pinned_plans import save

        plan_id = save(SAMPLE_TEST_PLAN, SAMPLE_AC)

        expected_path = isolated_store / f"{plan_id}.json"
        assert expected_path.exists(), (
            f"Expected pinned plan file at {expected_path} — not found"
        )

    def test_file_contains_required_fields(self, isolated_store):
        from backend.engine.pinned_plans import save

        plan_id = save(SAMPLE_TEST_PLAN, SAMPLE_AC)

        file_path = isolated_store / f"{plan_id}.json"
        with file_path.open("r", encoding="utf-8") as fh:
            on_disk = json.load(fh)

        assert "plan_id" in on_disk, "on-disk JSON must include plan_id"
        assert "created_at" in on_disk, "on-disk JSON must include created_at"
        assert "test_plan" in on_disk, "on-disk JSON must include test_plan"
        assert "acceptance_criteria" in on_disk, (
            "on-disk JSON must include acceptance_criteria"
        )
        assert on_disk["plan_id"] == plan_id
        assert on_disk["acceptance_criteria"] == SAMPLE_AC

    def test_save_is_idempotent_on_same_inputs(self, isolated_store):
        """Saving the same test_plan + AC twice must produce two different plan_ids (UUID-based)."""
        from backend.engine.pinned_plans import save

        plan_id_1 = save(SAMPLE_TEST_PLAN, SAMPLE_AC)
        plan_id_2 = save(SAMPLE_TEST_PLAN, SAMPLE_AC)

        # Each save produces a unique opaque ID (UUID4 — not content-keyed)
        assert plan_id_1 != plan_id_2, (
            "save() must generate a unique plan_id per call (UUID-based)"
        )


# ---------------------------------------------------------------------------
# AC-ERROR-1 (store side): load() raises PinnedPlanNotFound for unknown id
# ---------------------------------------------------------------------------


class TestMissingPlan:
    """load() with an unknown plan_id raises PinnedPlanNotFound."""

    def test_load_unknown_id_raises_not_found(self, isolated_store):
        from backend.engine.pinned_plans import PinnedPlanNotFound, load

        with pytest.raises(PinnedPlanNotFound) as exc_info:
            load("nonexistent-plan-id-xyz")

        assert "nonexistent-plan-id-xyz" in str(exc_info.value), (
            "PinnedPlanNotFound message must include the missing plan_id"
        )

    def test_not_found_is_distinct_from_expired(self, isolated_store):
        from backend.engine.pinned_plans import PinnedPlanExpired, PinnedPlanNotFound

        assert PinnedPlanNotFound is not PinnedPlanExpired, (
            "PinnedPlanNotFound and PinnedPlanExpired must be distinct exception types"
        )
        assert not issubclass(PinnedPlanNotFound, PinnedPlanExpired)
        assert not issubclass(PinnedPlanExpired, PinnedPlanNotFound)


# ---------------------------------------------------------------------------
# AC-VERIFY-2 / AC-ERROR-2 (store side): TTL expiry — lazy prune on load
# ---------------------------------------------------------------------------


class TestTTLExpiry:
    """load() raises PinnedPlanExpired for an expired plan; file deleted from disk."""

    def test_load_expired_raises_expired(self, isolated_store, monkeypatch):
        """A plan whose created_at is older than TTL raises PinnedPlanExpired."""
        import backend.engine.pinned_plans as pp_module
        from backend.engine.pinned_plans import PinnedPlanExpired, save

        plan_id = save(SAMPLE_TEST_PLAN, SAMPLE_AC)

        # Backdate the created_at to simulate expiry (TTL=0 for simplicity)
        file_path = isolated_store / f"{plan_id}.json"
        with file_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["created_at"] = 0.0  # epoch 0 — always expired
        with file_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)

        # Load with TTL of 1 day — a created_at of epoch 0 is decades old
        monkeypatch.setattr(pp_module, "_get_ttl_days", lambda: 1)

        with pytest.raises(PinnedPlanExpired) as exc_info:
            from backend.engine.pinned_plans import load
            load(plan_id)

        assert plan_id in str(exc_info.value), (
            "PinnedPlanExpired message must include the plan_id"
        )

    def test_expired_file_deleted_from_disk(self, isolated_store, monkeypatch):
        """After PinnedPlanExpired, the expired file must be removed (lazy prune)."""
        import backend.engine.pinned_plans as pp_module
        from backend.engine.pinned_plans import PinnedPlanExpired, save

        plan_id = save(SAMPLE_TEST_PLAN, SAMPLE_AC)
        file_path = isolated_store / f"{plan_id}.json"

        # Backdate
        with file_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["created_at"] = 0.0
        with file_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)

        monkeypatch.setattr(pp_module, "_get_ttl_days", lambda: 1)

        with pytest.raises(PinnedPlanExpired):
            from backend.engine.pinned_plans import load
            load(plan_id)

        assert not file_path.exists(), (
            "Expired plan file must be deleted from disk after PinnedPlanExpired is raised"
        )

    def test_non_expired_plan_loads_successfully(self, isolated_store):
        """A fresh plan (just saved) must load successfully — not treated as expired."""
        from backend.engine.pinned_plans import load, save

        plan_id = save(SAMPLE_TEST_PLAN, SAMPLE_AC)
        loaded = load(plan_id)

        assert loaded == SAMPLE_TEST_PLAN


# ---------------------------------------------------------------------------
# AC-VERIFY-6: prune_expired() batch prune at startup
# ---------------------------------------------------------------------------


class TestPruneExpired:
    """prune_expired() removes expired files, keeps fresh files, returns count."""

    def test_prune_removes_expired_files(self, isolated_store, monkeypatch):
        import backend.engine.pinned_plans as pp_module
        from backend.engine.pinned_plans import prune_expired, save

        # Save two plans
        plan_id_old = save(SAMPLE_TEST_PLAN, SAMPLE_AC)
        plan_id_fresh = save(SAMPLE_TEST_PLAN, "Different AC text for fresh plan")

        # Backdate first plan
        file_old = isolated_store / f"{plan_id_old}.json"
        with file_old.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["created_at"] = 0.0
        with file_old.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)

        monkeypatch.setattr(pp_module, "_get_ttl_days", lambda: 1)

        pruned_count = prune_expired()

        assert pruned_count == 1, f"Expected 1 pruned file, got {pruned_count}"
        assert not file_old.exists(), "Expired file must be deleted by prune_expired()"
        assert (isolated_store / f"{plan_id_fresh}.json").exists(), (
            "Fresh file must NOT be deleted by prune_expired()"
        )

    def test_prune_returns_zero_when_no_expired(self, isolated_store):
        from backend.engine.pinned_plans import prune_expired, save

        save(SAMPLE_TEST_PLAN, SAMPLE_AC)  # fresh plan

        pruned_count = prune_expired()

        assert pruned_count == 0, (
            "prune_expired() must return 0 when no plans have expired"
        )

    def test_prune_returns_zero_on_empty_store(self, isolated_store):
        from backend.engine.pinned_plans import prune_expired

        pruned_count = prune_expired()

        assert pruned_count == 0, (
            "prune_expired() must return 0 on an empty store directory"
        )


# ---------------------------------------------------------------------------
# Config integration: pinned_plan_ttl_days setting
# ---------------------------------------------------------------------------


class TestConfigSetting:
    """Settings.pinned_plan_ttl_days is present with default=14."""

    def test_pinned_plan_ttl_days_exists_with_default(self):
        from backend.config import settings

        assert hasattr(settings, "pinned_plan_ttl_days"), (
            "Settings must have a pinned_plan_ttl_days field"
        )
        assert settings.pinned_plan_ttl_days == 14, (
            f"pinned_plan_ttl_days default must be 14, got {settings.pinned_plan_ttl_days}"
        )

    def test_pinned_plan_ttl_days_is_int(self):
        from backend.config import settings

        assert isinstance(settings.pinned_plan_ttl_days, int), (
            "pinned_plan_ttl_days must be an int"
        )

    def test_pinned_plan_ttl_days_overridable_via_env(self, monkeypatch):
        """The TTL must be overridable via PINNED_PLAN_TTL_DAYS env var."""
        monkeypatch.setenv("PINNED_PLAN_TTL_DAYS", "7")

        # Re-instantiate settings to pick up the env var
        from backend.config import Settings
        s = Settings()
        assert s.pinned_plan_ttl_days == 7, (
            "pinned_plan_ttl_days must be overridable via PINNED_PLAN_TTL_DAYS env var"
        )
