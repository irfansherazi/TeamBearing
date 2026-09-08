---
legacy_id: feat-056-execution-foundation-hardening
---
# feat-056-execution-foundation-hardening: FEAT-056: Execution Foundation Hardening

## Status
- **ID**: feat-056-execution-foundation-hardening
- **Task**: FEAT-056: Execution Foundation Hardening
- **Phase**: REFLECT
- **Status**: REFLECTION_COMPLETE
- **Complexity**: Level 2
- **Feature**: [FEAT-056: Execution Foundation Hardening (Infrastructure Fixes)](../roadmap.md#feat-056-execution-foundation-hardening-infrastructure-fixes)

## Objectives
- Resolve the `numpy/scipy` randbits ImportError caused by Python 3.13 incompatibility in the production runtime.
- Standardize the loading and validation of 4 critical credentials (`role_default_password`, `role_email_sales_manager`, `shared_test_password`, `admin_test_password`) to prevent pre-flight execution failures.
- Update infrastructure scripts (`setup_ssm.sh`, `validate_env.py`) to enforce these hardening measures.

## Implementation Roadmap

### Phase 1: Python 3.13 Runtime Fix
- [ ] Add early pre-cache imports of `numpy` and `sklearn.feature_extraction.text` to `backend/main.py` to resolve the Python 3.13 import ordering bug.
- [ ] Verify fix by running `python3 -m backend.main` (or a dedicated test script) and ensuring KB retrieval works without `ImportError`.

### Phase 2: Credential Standardization & Validation
- [ ] Update `scripts/setup_ssm.sh` to include prompts for `shared_test_password` and `admin_test_password`.
- [ ] Implement `check_role_credentials()` in `scripts/validate_env.py` to verify all 4 critical credentials are resolved (via SSM or env fallback).
- [ ] Update `backend/secrets.py` to ensure consistent logging and fallback behavior for these 4 keys.

### Phase 3: Final Verification
- [ ] Run `python3 scripts/validate_env.py` and ensure it correctly identifies missing credentials.
- [ ] Populate credentials (locally or in SSM) and verify a full "pre-flight" pass.
- [ ] Verify `benchmark_report.json` no longer shows `step_results: []` for tickets that previously failed due to missing credentials.

## Testing Strategy
- **Reproduction**: Create a minimal script that imports `backend.kb.loader` and triggers the `ImportError` in a Python 3.13 environment.
- **Unit Tests**:
    - Add a test case to `tests/test_secrets_resolution.py` (if it exists) to verify the 4 new critical keys are part of the resolution chain.
- **Integration Tests**:
    - Run `scripts/validate_env.py` to confirm it catches the missing credentials.
- **Manual Verification**:
    - Verify `backend.log` no longer shows `[MISSING]` warnings for these 4 keys after they are configured.
    - Confirm the agent successfully reaches the `planner_node` for roles that previously failed (e.g., Sales Manager).
