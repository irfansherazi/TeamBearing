/**
 * Memory Watch — Playwright entry (Chromium + CDP).
 *
 * Run via: npm run memory:test -- --flow=po-open-spot --env=qa --cycles=5
 */

import fs from 'fs';
import path from 'path';
import { expect } from '@playwright/test';
import { test } from '../../utils/setup';
import {
    DEFAULT_CYCLES,
    DEFAULT_FLOW_ID,
    DEFAULT_GC_PASSES,
    FLOW_IDS,
    type MemoryFlowId,
} from '../../memory/constants';
import { flowLabel, isMemoryFlowId, runFlowCycle } from '../../memory/flows';
import {
    bytesToMb,
    captureMetrics,
    disableHeapProfiler,
    enableHeapProfiler,
} from '../../memory/lib/memorySampler';
import {
    formatReportLine,
    formatResultLines,
    formatSampleLine,
    formatVerdictLine,
} from '../../memory/lib/logFormat';
import { writeMemoryReport } from '../../memory/lib/reportGenerator';
import {
    DEFAULT_MAX_HEAP_GROWTH_MB,
    evaluateHeapSeries,
    toHeapSamples,
} from '../../memory/lib/verdict';

function resolveFlowId(): MemoryFlowId {
    const raw = (process.env.MEMORY_FLOW || DEFAULT_FLOW_ID).trim();
    if (!isMemoryFlowId(raw)) {
        throw new Error(`MEMORY_FLOW must be one of: ${FLOW_IDS.join(', ')}`);
    }
    return raw;
}

function resolveCycles(): number {
    const parsed = Number.parseInt(process.env.MEMORY_CYCLES || String(DEFAULT_CYCLES), 10);
    if (!Number.isFinite(parsed) || parsed < 1 || parsed > 20) {
        throw new Error('MEMORY_CYCLES must be an integer from 1 to 20');
    }
    return parsed;
}

function resolveMaxGrowthMb(): number {
    const parsed = Number.parseFloat(
        process.env.MEMORY_MAX_GROWTH_MB || String(DEFAULT_MAX_HEAP_GROWTH_MB)
    );
    if (!Number.isFinite(parsed) || parsed < 1) {
        throw new Error('MEMORY_MAX_GROWTH_MB must be a positive number');
    }
    return parsed;
}

test.describe('Memory Watch', () => {
    test.skip(({ browserName }) => browserName !== 'chromium', 'CDP requires Chromium');
    test.use({
        user: 'DemoProdDirector',
        video: { mode: 'on', size: { width: 1440, height: 900 } },
    });

    test('heap samples across open/close cycles', async ({ page }) => {
        test.skip(
            !process.env.MEMORY_FLOW && process.env.MEMORY_WATCH !== '1',
            'Run via npm run memory:test'
        );
        const flowId = resolveFlowId();
        const cycles = resolveCycles();
        const maxGrowthMb = resolveMaxGrowthMb();
        const env = process.env.TEST_ENV || 'qa';
        test.setTimeout(Math.max(180_000, cycles * 90_000));

        await page.goto('/', { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(4000);

        const client = await page.context().newCDPSession(page);
        await enableHeapProfiler(client);

        const usedMb: number[] = [];
        let flowOk = true;
        let flowError = '';

        try {
            const baseline = await captureMetrics(client, 'baseline', {
                gcPasses: DEFAULT_GC_PASSES,
            });
            usedMb.push(bytesToMb(baseline.usedHeapSize));

            for (let cycle = 1; cycle <= cycles; cycle++) {
                try {
                    await runFlowCycle(page, flowId);
                } catch (err: unknown) {
                    flowOk = false;
                    flowError = err instanceof Error ? err.message : String(err);
                    process.stdout.write(`FLOW error on cycle ${cycle}: ${flowError}\n`);
                    break;
                }
                const sample = await captureMetrics(client, `cycle-${cycle}`, {
                    gcPasses: DEFAULT_GC_PASSES,
                });
                usedMb.push(bytesToMb(sample.usedHeapSize));
            }
        } finally {
            await disableHeapProfiler(client);
            await client.detach().catch(() => undefined);
        }

        const samples = toHeapSamples(usedMb, DEFAULT_GC_PASSES, maxGrowthMb);
        const verdict = evaluateHeapSeries(usedMb, maxGrowthMb);
        const stamp = new Date().toISOString().replace(/[:.]/g, '-');
        const reportDir = path.resolve(process.cwd(), 'playwright', 'memory-reports', `${stamp}-${flowId}`);

        for (const sample of samples) {
            process.stdout.write(`${formatSampleLine(sample)}\n`);
        }
        process.stdout.write(`${formatVerdictLine(verdict)}\n`);

        const lines = formatResultLines(samples, verdict, flowOk);
        for (const line of lines) {
            process.stdout.write(`${line}\n`);
        }

        const videoName = 'recording.webm';
        writeMemoryReport({
            reportDir,
            flowId,
            flowName: flowLabel(flowId),
            env,
            cycles,
            samples,
            verdict,
            flowOk,
            videoFileName: videoName,
        });

        const video = page.video();
        await page.close();
        if (video) {
            const videoPath = await video.path();
            fs.mkdirSync(reportDir, { recursive: true });
            const dest = path.join(reportDir, videoName);
            if (fs.existsSync(videoPath)) {
                fs.copyFileSync(videoPath, dest);
            }
        }

        process.stdout.write(
            `${formatReportLine({
                dir: reportDir,
                html: 'report.html',
                json: 'report.json',
                video: fs.existsSync(path.join(reportDir, videoName)) ? videoName : '',
            })}\n`
        );

        expect.soft(flowOk, flowError || 'Flow steps failed').toBe(true);
        expect.soft(verdict.overCap, verdict.reason).toBe(false);
        expect.soft(verdict.strictlyIncreasing, 'Heap increased on every cycle').toBe(false);
    });
});
