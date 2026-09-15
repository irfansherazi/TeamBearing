/**
 * Parse Production Orders compact-card labels like "1/1" or "3/5".
 * The number after the slash is total spots on that Quick Order.
 */

const PO_COUNT_RE = /\/(\d+)\s*$/;

/**
 * Read total spots from a `_poNumber/_poCount` label.
 *
 * @param label - Visible text such as 1/1 or 2/5
 * @returns Total spots, or null when the label is not a PO count
 */
export function parsePoTotalSpots(label: string): number | null {
    const match = String(label || '').trim().match(PO_COUNT_RE);
    if (!match) {
        return null;
    }
    const total = Number(match[1]);
    return Number.isFinite(total) ? total : null;
}

/**
 * True when the order has exactly one spot.
 *
 * @param label - Visible PO count text
 * @returns Whether total spots is 1
 */
export function isOneSpotOrder(label: string): boolean {
    return parsePoTotalSpots(label) === 1;
}

/**
 * True when the order has at least `minSpots` spots.
 *
 * @param label - Visible PO count text
 * @param minSpots - Minimum total spots (default 5)
 * @returns Whether the order is large enough
 */
export function isLargeOrder(label: string, minSpots = 5): boolean {
    const total = parsePoTotalSpots(label);
    return total !== null && total >= minSpots;
}
