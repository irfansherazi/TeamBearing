/**
 * Best-effort phase classification for a Memory Watch test failure that
 * happened before normal per-sample/verdict reporting — most commonly a
 * login/session fixture failure, which runs before the test body starts
 * and so can't be tagged by the body itself.
 */

export interface MemoryWatchFailureSummary {
    phase: string;
    reason: string;
}

/**
 * Phase detectors, checked in order. First match wins. Ordered from the
 * most specific failure signal (where the code actually threw) to the
 * weakest, so a background warning never outranks the real failure site.
 */
const PHASE_PATTERNS: { phase: string; pattern: RegExp }[] = [
    { phase: 'Login / session', pattern: /at login \(|loginHelper\.mjs|Session expired or not logged in|Falling back to manual login/i },
    { phase: 'Ghost login', pattern: /ghost picker|ghostLogin|Could not ghost as/i },
    { phase: 'Quick Order flow steps', pattern: /Quick Order details did not open|No 1-spot Quick Order|No 5-spot or larger Quick Order|openMatchingQuickOrder/i },
    { phase: 'Flow steps', pattern: /FLOW error|runFlowCycle/i },
    { phase: 'Heap capture', pattern: /HeapProfiler|captureMetrics/i },
    { phase: 'Page load / connection', pattern: /exceeded while setting up "page"|net::ERR_CONNECTION|ERR_CONNECTION_REFUSED/i },
];

/**
 * Classify an uncaught test failure into a short phase label + one-line reason.
 *
 * @param errorText - Combined message + stack from Playwright's testInfo.error
 * @returns Phase + reason
 */
export function classifyMemoryWatchFailure(errorText: string): MemoryWatchFailureSummary {
    const text = errorText || '';

    let phase = 'Unknown';
    for (const { phase: candidate, pattern } of PHASE_PATTERNS) {
        if (pattern.test(text)) {
            phase = candidate;
            break;
        }
    }

    const firstLine =
        text
            .split(/\r?\n/)
            .map((line) => line.trim())
            .find((line) => line.length > 0) || 'Unknown error';
    const reason = firstLine.length > 200 ? `${firstLine.slice(0, 197)}...` : firstLine;

    return { phase, reason };
}
