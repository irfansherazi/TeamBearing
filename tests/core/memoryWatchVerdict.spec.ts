/**
 * tests/core/memoryWatchVerdict.spec.ts
 * Unit tests for Memory Watch heap pass/fail rules.
 */

import { describe, it, expect } from 'vitest';
import {
    evaluateHeapSeries,
    isStrictlyIncreasing,
    toHeapSamples,
} from '../../playwright/memory/lib/verdict';

const increaseCases = [
    {
        description: 'detects a climb on every cycle',
        setup: () => [40, 45, 50, 55],
        expectations: (result: boolean) => {
            expect(result).toBe(true);
        },
    },
    {
        description: 'is false when a later sample drops',
        setup: () => [40, 48, 47, 49],
        expectations: (result: boolean) => {
            expect(result).toBe(false);
        },
    },
];

describe('isStrictlyIncreasing', () => {
    increaseCases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            expectations(isStrictlyIncreasing(setup()));
        });
    });
});

const verdictCases = [
    {
        description: 'passes when growth is under 15 MB and not unbounded',
        setup: () => [42, 48, 49, 48],
        expectations: (result: ReturnType<typeof evaluateHeapSeries>) => {
            expect(result.pass).toBe(true);
            expect(result.overCap).toBe(false);
        },
    },
    {
        description: 'fails when growth exceeds 15 MB',
        setup: () => [40, 50, 58, 70],
        expectations: (result: ReturnType<typeof evaluateHeapSeries>) => {
            expect(result.pass).toBe(false);
            expect(result.overCap).toBe(true);
        },
    },
];

describe('evaluateHeapSeries', () => {
    verdictCases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            expectations(evaluateHeapSeries(setup()));
        });
    });
});

describe('toHeapSamples', () => {
    it('marks baseline watching and last cycle pass or fail', () => {
        const samples = toHeapSamples([42, 48, 47], 3);
        expect(samples[0].status).toBe('watching');
        expect(samples[samples.length - 1].status).toBe('pass');
        expect(samples[1].deltaMb).toBeCloseTo(6);
    });
});
