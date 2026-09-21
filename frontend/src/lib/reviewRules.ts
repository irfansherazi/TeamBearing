/**
 * Types and helpers for the Review rules page.
 */

export type ReviewRulesApp = "platform" | "vcapi";

export interface ReviewRule {
  id: string;
  plain: string;
  rule: string;
}

export interface ReviewRuleSection {
  name: string;
  rules: ReviewRule[];
}

export const OTHER_REVIEW_SECTION = "__other__";

export interface ReviewRuleSuggestion {
  id: string;
  wording: string;
  plain: string;
}

export interface ReviewRuleProposeResponse {
  verdict: "reject" | "overlap" | "accept";
  reason: string;
  overlap_ids: string[];
  proposal_id: string | null;
  assigned_id: string | null;
  section: string;
  suggested_section: string;
  suggested_id: string | null;
  suggestions: ReviewRuleSuggestion[];
}

export interface ReviewRulesPayload {
  app: ReviewRulesApp;
  label: string;
  source: string;
  sections: ReviewRuleSection[];
}

/**
 * True when AI picked a different checklist section than the user.
 *
 * @param picked - Section the user chose
 * @param suggested - Section the gate recommended
 * @returns Whether to show the section hint
 */
export function reviewRuleSectionDiffers(
  picked: string,
  suggested: string
): boolean {
  const left = picked.trim().toLowerCase();
  const right = suggested.trim().toLowerCase();
  return Boolean(right) && left !== right;
}

/**
 * Heading above the rewritten rule.
 *
 * @param assignedId - Code that would be saved
 * @returns Legend text
 */
export function reviewRuleWordingLegend(assignedId: string): string {
  return `Suggested wording for ${assignedId}.`;
}

/**
 * True when the search looks like a checklist code (F-, CQ-01, LD-7).
 *
 * @param needle - Trimmed lowercase search text
 * @returns Whether to match against rule ids only
 */
export function isReviewRuleCodeQuery(needle: string): boolean {
  return /^[a-z]{1,4}-\d*$/.test(needle);
}

/**
 * Keep sections whose id, wording, or heading matches the search box.
 * Code-style queries (F-, CQ-22) match the id prefix only, so leftover
 * letters inside other rules (self-explanatory, of-id) are ignored.
 *
 * @param sections - Grouped checklist rules
 * @param query - Raw search text
 * @returns Sections that still have at least one matching rule
 */
export function filterReviewRuleSections(
  sections: ReviewRuleSection[],
  query: string
): ReviewRuleSection[] {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return sections;
  }
  const codeQuery = isReviewRuleCodeQuery(needle);
  return sections
    .map((section) => {
      if (codeQuery) {
        return {
          ...section,
          rules: section.rules.filter((rule) =>
            rule.id.toLowerCase().startsWith(needle)
          ),
        };
      }
      const sectionHit = section.name.toLowerCase().includes(needle);
      const rules = sectionHit
        ? section.rules
        : section.rules.filter((rule) => {
            const haystack = `${rule.id} ${rule.plain} ${rule.rule}`.toLowerCase();
            return haystack.includes(needle);
          });
      return { ...section, rules };
    })
    .filter((section) => section.rules.length > 0);
}

/**
 * Count rules across every section.
 *
 * @param sections - Grouped checklist rules
 * @returns Total rule count
 */
export function countReviewRules(sections: ReviewRuleSection[]): number {
  return sections.reduce((total, section) => total + section.rules.length, 0);
}

/**
 * Build a stable HTML id from a section heading.
 *
 * @param name - Checklist section heading
 * @returns Hyphenated id fragment
 */
export function reviewRuleSectionId(name: string): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return slug || "section";
}
