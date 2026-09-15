/**
 * tests/core/poSpotCount.spec.ts
 * Unit tests for Production Orders compact-card spot-count labels.
 */

import { describe, it, expect } from 'vitest';
import {
    isLargeOrder,
    isOneSpotOrder,
    parsePoTotalSpots,
} from '../../playwright/memory/poSpotCount';

const parseCases = [
    {
        description: 'reads total spots from 1/1',
        setup: () => '1/1',
        expectations: (result: number | null) => {
            expect(result).toBe(1);
        },
    },
    {
        description: 'reads total spots from 2/5',
        setup: () => '2/5',
        expectations: (result: number | null) => {
            expect(result).toBe(5);
        },
    },
    {
        description: 'returns null when the label is not a PO count',
        setup: () => 'Inbox',
        expectations: (result: number | null) => {
            expect(result).toBeNull();
        },
    },
];

describe('parsePoTotalSpots', () => {
    parseCases.forEach(({ description, setup, expectations }) => {
        it(description, () => {
            expectations(parsePoTotalSpots(setup()));
        });
    });
});

describe('isOneSpotOrder', () => {
    it('is true for 1/1', () => {
        expect(isOneSpotOrder('1/1')).toBe(true);
        expect(isOneSpotOrder('1/5')).toBe(false);
    });
});

describe('isLargeOrder', () => {
    it('is true when total spots is 5 or more', () => {
        expect(isLargeOrder('1/5')).toBe(true);
        expect(isLargeOrder('1/4')).toBe(false);
    });
});
