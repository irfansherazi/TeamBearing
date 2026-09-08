/**
 * Shared CDP heap sampler for Memory Watch and VC2-8821 / VC2-8983.
 */

import type { CDPSession } from '@playwright/test';

export interface CycleMetrics {
    label: string;
    usedHeapSize: number;
    totalHeapSize: number;
    domNodes: number;
    listeners: number;
}

export interface CaptureOptions {
    gcPasses?: number;
}

interface HeapUsageResult {
    usedSize?: number;
    totalSize?: number;
}

interface DomCounterResult {
    nodes?: number;
    jsEventListeners?: number;
}

/**
 * Send a CDP method whose Playwright typings may omit the command name.
 *
 * @param client - Open CDP session
 * @param method - CDP method name
 * @returns Parsed result object
 */
async function sendUntypedCdp<T>(client: CDPSession, method: string): Promise<T> {
    const send = client.send.bind(client) as (name: string) => Promise<unknown>;
    return send(method) as Promise<T>;
}

/**
 * Format a byte count as B / KB / MB.
 *
 * @param bytes - Raw byte count
 * @returns Human-readable size
 */
export function formatBytes(bytes: number): string {
    if (bytes < 1024) {
        return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

/**
 * Convert bytes to megabytes.
 *
 * @param bytes - Raw byte count
 * @returns Size in MB
 */
export function bytesToMb(bytes: number): number {
    return bytes / (1024 * 1024);
}

/**
 * Enable the HeapProfiler domain.
 *
 * @param client - Open CDP session
 * @returns void
 */
export async function enableHeapProfiler(client: CDPSession): Promise<void> {
    await client.send('HeapProfiler.enable');
}

/**
 * Disable the HeapProfiler domain.
 *
 * @param client - Open CDP session
 * @returns void
 */
export async function disableHeapProfiler(client: CDPSession): Promise<void> {
    await client.send('HeapProfiler.disable');
}

/**
 * Force garbage collection with multiple V8 passes.
 *
 * @param client - Open CDP session
 * @param passes - Number of HeapProfiler.collectGarbage calls
 * @returns void
 */
export async function forceGC(client: CDPSession, passes = 3): Promise<void> {
    for (let i = 0; i < passes; i++) {
        await client.send('HeapProfiler.collectGarbage');
        await new Promise((resolve) => setTimeout(resolve, 300));
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
}

/**
 * Read live JS heap usage via CDP.
 *
 * @param client - Open CDP session
 * @returns usedSize and totalSize in bytes
 */
export async function getHeapUsage(
    client: CDPSession
): Promise<{ usedSize: number; totalSize: number }> {
    const result = await sendUntypedCdp<HeapUsageResult>(client, 'Runtime.getHeapUsage');
    return {
        usedSize: Number(result.usedSize ?? 0),
        totalSize: Number(result.totalSize ?? 0),
    };
}

/**
 * Read DOM node and listener counts. Returns zeros when the domain is missing.
 *
 * @param client - Open CDP session
 * @returns Node and listener counts
 */
export async function getDOMCounters(
    client: CDPSession
): Promise<{ nodes: number; listeners: number }> {
    try {
        const result = await sendUntypedCdp<DomCounterResult>(client, 'Memory.getDOMCounters');
        return {
            nodes: Number(result.nodes ?? 0),
            listeners: Number(result.jsEventListeners ?? 0),
        };
    } catch {
        return { nodes: 0, listeners: 0 };
    }
}

/**
 * GC, then capture heap and DOM metrics for one sample point.
 *
 * @param client - Open CDP session
 * @param label - Sample label (baseline, cycle-1, ...)
 * @param options - Optional GC pass count
 * @returns Cycle metrics
 */
export async function captureMetrics(
    client: CDPSession,
    label: string,
    options: CaptureOptions = {}
): Promise<CycleMetrics> {
    const gcPasses = options.gcPasses ?? 3;
    await forceGC(client, gcPasses);
    const heap = await getHeapUsage(client);
    const dom = await getDOMCounters(client);
    const metrics: CycleMetrics = {
        label,
        usedHeapSize: heap.usedSize,
        totalHeapSize: heap.totalSize,
        domNodes: dom.nodes,
        listeners: dom.listeners,
    };
    process.stdout.write(
        `\n[${label}] Heap Used: ${formatBytes(metrics.usedHeapSize)} | DOM: ${metrics.domNodes} | Listeners: ${metrics.listeners}\n`
    );
    return metrics;
}
