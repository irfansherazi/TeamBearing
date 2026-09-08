/**
 * Serializes ClarificationWizardModal selections into a pre_parse_guidance string
 * that the backend ac_parser_node understands (TASK-122 / FEAT-113).
 *
 * Format:
 *   "Exclude path: <path>" — one line per excluded navigation path
 *   "Clarification — "<term>": <resolution>" — one line per non-empty ambiguity resolution
 */
export function buildGuidance(
  allPaths: string[],
  selectedPaths: string[],
  resolutions: Record<string, string>
): string {
  const parts: string[] = [];
  const excluded = allPaths.filter((p) => !selectedPaths.includes(p));
  for (const p of excluded) {
    parts.push(`Exclude path: ${p}`);
  }
  for (const [term, resolution] of Object.entries(resolutions)) {
    if (resolution.trim()) {
      parts.push(`Clarification — "${term}": ${resolution.trim()}`);
    }
  }
  return parts.join("\n");
}
