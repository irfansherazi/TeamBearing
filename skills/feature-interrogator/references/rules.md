# vQA Coding Rules and Standards Reference

Use this reference during feature design and interrogation to verify absolute rule-compliance and prevent over-engineering.

## 1. Complexity & Code Footprint Constraints
- **Keep it Simple**: Minimize the lines of code (LoC). Every line added is a potential point of failure.
- **Explicit over Implicit**: Avoid complex inheritance, reflection, or prototype-based cloning. Prioritize explicit composition and delegation.
- **Ecosystem Tools First**: Leverage existing utility functions, model abstractions, and database libraries. Do not duplicate helper code.

## 2. 12-Factor App Principles
- **Config in Environment**: Store configuration in environment variables, not in code.
- **No Hardcoded Values**: Database URLs, API keys, credentials, endpoints, paths, timeouts, and feature flags must be configurable.
- **Dev/Prod Parity**: Ensure configuration patterns are identical between local, CI, and production environments.

## 3. Observability Standards
- **OpenTelemetry First**: Use the OpenTelemetry SDK (via common logger abstractions) for all logging, metrics, and traces.
- **Distributed Tracing Always**: Every request must carry a traceable transaction ID (W3C Trace Context).
- **Structured Logging**: Log outputs must be structured JSON containing `traceId`, `spanId`, `service`, and `level`.
- **Configuration Over Code**: Logging configuration must be controlled via environment variables (e.g., `LOG_LEVEL`, `LOG_FORMAT`, `LOG_OUTPUT`).

## 4. Blocking Violations (Hard Rejection Criteria)
- **Standard Console Prints**: Using `console.log` or `console.error` (in JavaScript/TypeScript) or standard `print` (in Python) in production code. Use the standard logger abstraction.
- **Missing Trace Propagation**: Failing to propagate trace context in downstream or upstream HTTP/gRPC requests.
- **Sensitive Data Exposure**: Logging credentials, tokens, passwords, or PII.
- **Hardcoded Configs**: Hardcoding log levels, environments, endpoints, or keys.

## 5. Testing Requirements
- **Mandatory Verification**: Every feature, bug fix, or behavioral change must be accompanied by relevant unit or integration tests (pytest for Python, Vitest for React).
- **No Test Suppression**: Do not suppress or ignore test failures or type-check warnings unless explicitly requested by the user.
