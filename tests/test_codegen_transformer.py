"""
tests/test_codegen_transformer.py
==================================
Unit tests for backend/engine/codegen_transformer.py (TASK-121).

Tests cover:
- _strip_fences: typescript fence, ts fence, no fence, trailing-only fence
- transform_recorded_test: mocked Bedrock success path, Bedrock raises → returns raw
- _analyze_transformations: code with helpers → correct counts, no helpers → all zeros/false
"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.engine.codegen_transformer import (
    _strip_fences,
    _analyze_transformations,
    transform_recorded_test,
)


# ---------------------------------------------------------------------------
# _strip_fences
# ---------------------------------------------------------------------------


class TestStripFences:
    def test_typescript_fence(self):
        raw = "```typescript\nconst x = 1;\n```"
        assert _strip_fences(raw) == "const x = 1;"

    def test_ts_fence(self):
        raw = "```ts\nconst x = 1;\n```"
        assert _strip_fences(raw) == "const x = 1;"

    def test_no_fence(self):
        raw = "const x = 1;"
        assert _strip_fences(raw) == "const x = 1;"

    def test_trailing_only_fence(self):
        # Model omitted opening fence but included trailing
        raw = "const x = 1;\n```"
        assert _strip_fences(raw) == "const x = 1;"


# ---------------------------------------------------------------------------
# transform_recorded_test
# ---------------------------------------------------------------------------


class TestTransformRecordedTest:
    @pytest.mark.asyncio
    async def test_success_path_returns_bedrock_output(self):
        raw = "const x = 1;"
        transformed = "// transformed\nconst x = 1;"
        with patch(
            "backend.engine.codegen_transformer._call_bedrock",
            new_callable=AsyncMock,
            return_value=transformed,
        ):
            result = await transform_recorded_test(raw, "QA-999")
        assert result == transformed

    @pytest.mark.asyncio
    async def test_bedrock_failure_returns_raw_code(self):
        raw = "const x = 1;"
        with patch(
            "backend.engine.codegen_transformer._call_bedrock",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Bedrock unavailable"),
        ):
            result = await transform_recorded_test(raw, "QA-999")
        assert result == raw


# ---------------------------------------------------------------------------
# _analyze_transformations
# ---------------------------------------------------------------------------


_CODE_WITH_HELPERS = """
import { test, expect, BASE_URL } from '../utils/setup';
import { goToFolder } from '../utils/NavHelper';
import { resolveCaptcha } from '../utils/CaptchaHelper';
import { calculateDueDate, calculateStartDate } from '../utils/QO_helpers';

test.use({ user: 'DemoProdDirector' });

test('order flow', async ({ page }) => {
    await goToFolder(page, 'All');
    // ⚠️ FRAGILE: Row ID is tied to a specific record.
    // ⚠️ FRAGILE: Positional selector depends on row order.
    await resolveCaptcha(page);
    await page.fill('[name=due]', calculateDueDate());
    await page.fill('[name=start]', calculateStartDate());
});
"""

_CODE_WITHOUT_HELPERS = """
import { test, expect } from '@playwright/test';

test('plain test', async ({ page }) => {
    await page.goto('https://qa.vcreative.net');
    await page.fill('[name=email]', 'user@example.com');
});
"""


class TestAnalyzeTransformations:
    def test_code_with_helpers_returns_correct_counts(self):
        result = _analyze_transformations(_CODE_WITH_HELPERS)
        assert result["auth_applied"] is True
        assert result["date_helpers"] == 2
        assert result["nav_helpers"] == 1
        assert result["fragile_warnings"] == 2
        assert result["captcha_helpers"] == 1

    def test_code_without_helpers_returns_all_zeros(self):
        result = _analyze_transformations(_CODE_WITHOUT_HELPERS)
        assert result["auth_applied"] is False
        assert result["date_helpers"] == 0
        assert result["nav_helpers"] == 0
        assert result["fragile_warnings"] == 0
        assert result["captcha_helpers"] == 0
