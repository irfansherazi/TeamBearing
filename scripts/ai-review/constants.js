const DEFAULT_CONFIG = 'ai-code-review.config.json';
const DEFAULT_INSTRUCTIONS = 'pr-review-checklist.md';
const DEFAULT_BASE_BRANCH = 'Develop';
const VALID_MODES = ['branch', 'files'];
const DEFAULT_BRANCH_NAME_RULES = [
    { suffix: '-master', baseBranch: 'master' },
    { suffix: '-rc', baseBranch: 'Release-Candidate' }
];

const DEFAULT_AUTOMATED_CHECKS = {
    'CQ-05': 'noConsoleOrDebugger',
    'CQ-06': 'lint',
    'CQ-07': 'specConventions',
    // Guardrails for common PR sendbacks (diff-based, fast, no AI required)
    'CQ-01': 'conventionGuardrails',
    'CQ-02': 'deadCodeAndBannerComments',
    'CQ-03': 'unsafeSpreadBeforeSort',
    'CQ-04': 'templateBindingsAndSqlModelSet',
    'CQ-09': 'htmlBindingConventions',
    'CQ-10': 'misleadingOptionalChaining',
    'CQ-11': 'noDoRequest',
    'CQ-12': 'booleanNullishOr',
    'CQ-14': 'noNavigatingErrorSeverity',
    'CQ-16': 'noHardCodedThanksgiving',
    'CQ-19': 'noUntypedBrowserHandlers',
    'CQ-20': 'apiDtoMapHygiene',
    'CQ-23': 'noAsyncAwait',
    'CQ-24': 'noHasOwnProperty',
    'CQ-25': 'noEslintDisable',
    'CQ-29': 'elseBraceSameLine',
    'T-05': 'specAsyncSetupAndSeedUsers',
    'F-04': 'historyInfoEscaping',
};

// IDs whose written checklist text is broader than what the automated regex
// actually covers (e.g. CQ-01 = "naming, formatting, structure" but the check
// only catches 4 narrow patterns). These stay in the AI-required table so a
// reviewer still judges the full rule — the automated result is passed along
// as a hint, not a replacement verdict. Narrow/mechanical checks (CQ-05, CQ-06,
// CQ-11, CQ-16, etc.) are NOT listed here because their regex already covers
// the full intent of the rule.
const DEFAULT_ADVISORY_AUTOMATED_IDS = ['CQ-01', 'CQ-02', 'CQ-03', 'CQ-04', 'CQ-09', 'CQ-10'];

// Docs pr-review-checklist.md names as "strict source of truth". Embedded in
// full into the review bundle so no reviewer (human or AI, any chat tool) has
// to remember to go open them separately — see D-01/CQ-01 JSDoc miss incident.
const DEFAULT_SOURCE_OF_TRUTH_DOCS = [
    'PROMPT_coding_conventions.md',
    'Code-Conventions-Pilot.md',
    'PROMPT_unit_test.md'
];

module.exports = {
    DEFAULT_CONFIG,
    DEFAULT_INSTRUCTIONS,
    DEFAULT_BASE_BRANCH,
    VALID_MODES,
    DEFAULT_BRANCH_NAME_RULES,
    DEFAULT_AUTOMATED_CHECKS,
    DEFAULT_ADVISORY_AUTOMATED_IDS,
    DEFAULT_SOURCE_OF_TRUTH_DOCS
};
