/**
 * stdout lines the vReview dashboard parses during a Memory Watch run.
 */

import type { HeapSample, MemoryVerdict } from './verdict';

export const SAMPLE_PREFIX = 'MEMORY_WATCH_SAMPLE ';
export const VERDICT_PREFIX = 'MEMORY_WATCH_VERDICT ';
export const REPORT_PREFIX = 'MEMORY_WATCH_REPORT ';

/**
 * Print one markdown results row the AI Review parser also accepts.
 *
 * @param item - Row id (C0, HEAP, FLOW)
 * @param status - PASS, FAIL, SKIP
 * @param evidence - Note text
 * @returns Markdown table line
 */
export function formatChecklistRow(item: string, status: string, evidence: string): string {
    return `| ${item} | ${status} | ${evidence} |`;
}

/**
 * Print heap sample JSON for the dashboard table.
 *
 * @param sample - One cycle sample
 * @returns Prefixed JSON line
 */
export function formatSampleLine(sample: HeapSample): string {
    return `${SAMPLE_PREFIX}${JSON.stringify(sample)}`;
}

/**
 * Print the final verdict JSON.
 *
 * @param verdict - Pass/fail summary
 * @returns Prefixed JSON line
 */
export function formatVerdictLine(verdict: MemoryVerdict): string {
    return `${VERDICT_PREFIX}${JSON.stringify(verdict)}`;
}

/**
 * Print report artifact paths.
 *
 * @param payload - Report directory and file names
 * @returns Prefixed JSON line
 */
export function formatReportLine(payload: {
    dir: string;
    html: string;
    json: string;
    video: string;
}): string {
    return `${REPORT_PREFIX}${JSON.stringify(payload)}`;
}

/**
 * Build the markdown heap table plus HEAP / TREND / FLOW checklist rows.
 *
 * @param samples - Per-cycle samples
 * @param verdict - Final grade
 * @param flowOk - Whether Playwright steps completed
 * @returns Lines to write to stdout
 */
export function formatResultLines(
    samples: HeapSample[],
    verdict: MemoryVerdict,
    flowOk: boolean
): string[] {
    const lines = [
        '| Item | Status | Evidence |',
        '| --- | --- | --- |',
    ];
    for (const sample of samples) {
        const item = `C${sample.cycle}`;
        const status = sample.cycle === 0 ? 'SKIP' : sample.status === 'fail' ? 'FAIL' : 'PASS';
        const evidence = `${sample.usedMb.toFixed(2)} MB (${sample.deltaMb >= 0 ? '+' : ''}${sample.deltaMb.toFixed(2)} MB)`;
        lines.push(formatChecklistRow(item, status, evidence));
    }
    lines.push(
        formatChecklistRow(
            'HEAP',
            verdict.overCap ? 'FAIL' : 'PASS',
            verdict.reason
        )
    );
    lines.push(
        formatChecklistRow(
            'TREND',
            verdict.strictlyIncreasing ? 'FAIL' : 'PASS',
            verdict.strictlyIncreasing ? 'Heap rose every cycle' : 'No unbounded per-cycle climb'
        )
    );
    lines.push(formatChecklistRow('FLOW', flowOk ? 'PASS' : 'FAIL', flowOk ? 'Flow steps completed' : 'Flow steps failed'));
    return lines;
}
