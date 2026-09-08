/**
 * Memory Watch HTML/JSON report pack.
 */

import fs from 'fs';
import path from 'path';
import type { HeapSample, MemoryVerdict } from './verdict';

export interface MemoryReportInput {
    reportDir: string;
    flowId: string;
    flowName: string;
    env: string;
    cycles: number;
    samples: HeapSample[];
    verdict: MemoryVerdict;
    flowOk: boolean;
    videoFileName: string;
}

/**
 * Write report.json and report.html for one Memory Watch run.
 *
 * @param input - Samples, verdict, and output directory
 * @returns Absolute paths to json and html
 */
export function writeMemoryReport(input: MemoryReportInput): { jsonPath: string; htmlPath: string } {
    fs.mkdirSync(input.reportDir, { recursive: true });
    const jsonPath = path.join(input.reportDir, 'report.json');
    const htmlPath = path.join(input.reportDir, 'report.html');
    const payload = {
        flowId: input.flowId,
        flowName: input.flowName,
        env: input.env,
        cycles: input.cycles,
        samples: input.samples,
        verdict: input.verdict,
        flowOk: input.flowOk,
        video: input.videoFileName,
        overallPass: input.verdict.pass && input.flowOk,
    };
    fs.writeFileSync(jsonPath, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
    fs.writeFileSync(htmlPath, buildHtml(payload), 'utf8');
    return { jsonPath, htmlPath };
}

interface ReportPayload {
    flowId: string;
    flowName: string;
    env: string;
    cycles: number;
    samples: HeapSample[];
    verdict: MemoryVerdict;
    flowOk: boolean;
    video: string;
    overallPass: boolean;
}

/**
 * Build a standalone HTML table for PR evidence.
 *
 * @param payload - Report JSON body
 * @returns HTML document
 */
function buildHtml(payload: ReportPayload): string {
    const rows = payload.samples
        .map((sample) => {
            const delta = `${sample.deltaMb >= 0 ? '+' : ''}${sample.deltaMb.toFixed(2)}`;
            return `<tr><td>${sample.cycle === 0 ? '0 (baseline)' : String(sample.cycle)}</td><td>${sample.usedMb.toFixed(2)}</td><td>${delta}</td><td>${sample.gcRuns}</td><td>${sample.status}</td></tr>`;
        })
        .join('');
    const verdict = payload.overallPass ? 'PASS' : 'FAIL';
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Memory Watch — ${payload.flowName}</title>
  <style>
    body { font-family: sans-serif; margin: 2rem; color: #1a1a1a; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid #ccc; padding: 0.5rem 0.75rem; text-align: left; }
    th { background: #f4f4f4; }
    .verdict { font-size: 1.25rem; font-weight: 700; }
    .pass { color: #0a7a32; }
    .fail { color: #b42318; }
  </style>
</head>
<body>
  <h1>${payload.flowName}</h1>
  <p>Env: ${payload.env} · Cycles: ${payload.cycles} · Flow: ${payload.flowId}</p>
  <p class="verdict ${payload.overallPass ? 'pass' : 'fail'}">${verdict}</p>
  <p>${payload.verdict.reason}</p>
  <table>
    <thead>
      <tr><th>Cycle</th><th>Used heap (MB)</th><th>Δ from baseline</th><th>GC runs</th><th>Status</th></tr>
    </thead>
    <tbody>${rows}</tbody>
  </table>
  ${payload.video ? `<p>Video: ${payload.video}</p>` : ''}
</body>
</html>
`;
}
