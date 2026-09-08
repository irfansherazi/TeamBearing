/**
 * Pass/fail rules for a Memory Watch heap series.
 */

export interface HeapSample {
    cycle: number;
    label: string;
    usedMb: number;
    deltaMb: number;
    gcRuns: number;
    status: 'watching' | 'pass' | 'fail';
}

export interface MemoryVerdict {
    pass: boolean;
    growthMb: number;
    overCap: boolean;
    strictlyIncreasing: boolean;
    reason: string;
}

export const DEFAULT_MAX_HEAP_GROWTH_MB = 15;

/**
 * True when every consecutive sample is higher than the previous one.
 *
 * @param usedMb - Heap samples in order (baseline first)
 * @returns Whether the series climbs every cycle
 */
export function isStrictlyIncreasing(usedMb: number[]): boolean {
    if (usedMb.length < 3) {
        return false;
    }
    for (let i = 1; i < usedMb.length; i++) {
        if (usedMb[i] <= usedMb[i - 1]) {
            return false;
        }
    }
    return true;
}

/**
 * Grade heap growth against the agreed MB cap and unbounded-trend rule.
 *
 * @param usedMb - Heap samples in MB, index 0 = baseline
 * @param maxGrowthMb - Allowed growth from baseline
 * @returns Verdict
 */
export function evaluateHeapSeries(
    usedMb: number[],
    maxGrowthMb: number = DEFAULT_MAX_HEAP_GROWTH_MB
): MemoryVerdict {
    if (usedMb.length === 0) {
        return {
            pass: false,
            growthMb: 0,
            overCap: false,
            strictlyIncreasing: false,
            reason: 'No heap samples were captured',
        };
    }
    const baseline = usedMb[0];
    const last = usedMb[usedMb.length - 1];
    const growthMb = last - baseline;
    const strictlyIncreasing = isStrictlyIncreasing(usedMb);
    const overCap = growthMb > maxGrowthMb;
    const pass = !overCap && !strictlyIncreasing;
    let reason = `Heap ${growthMb >= 0 ? '+' : ''}${growthMb.toFixed(2)} MB vs ${maxGrowthMb} MB limit`;
    if (overCap) {
        reason = `Heap grew ${growthMb.toFixed(2)} MB (limit ${maxGrowthMb} MB)`;
    } else if (strictlyIncreasing) {
        reason = 'Heap increased on every cycle (unbounded trend)';
    }
    return { pass, growthMb, overCap, strictlyIncreasing, reason };
}

/**
 * Build per-cycle sample rows from raw used-heap MB values.
 *
 * @param usedMb - Heap samples in MB, index 0 = baseline
 * @param gcRuns - GC passes used before each sample
 * @param maxGrowthMb - Allowed growth from baseline
 * @returns Sample rows for the report table
 */
export function toHeapSamples(
    usedMb: number[],
    gcRuns: number,
    maxGrowthMb: number = DEFAULT_MAX_HEAP_GROWTH_MB
): HeapSample[] {
    const verdict = evaluateHeapSeries(usedMb, maxGrowthMb);
    return usedMb.map((value, index) => {
        const deltaMb = value - usedMb[0];
        let status: HeapSample['status'] = 'watching';
        if (index === 0) {
            status = 'watching';
        } else if (index === usedMb.length - 1) {
            status = verdict.pass ? 'pass' : 'fail';
        }
        return {
            cycle: index,
            label: index === 0 ? 'baseline' : `cycle-${index}`,
            usedMb: value,
            deltaMb,
            gcRuns,
            status,
        };
    });
}
