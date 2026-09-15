export const DEFAULT_FLOW_ID = 'qo-open-close-snapshot';
export const DEFAULT_ENV = 'qa';
export const DEFAULT_CYCLES = 5;
export const DEFAULT_GC_PASSES = 3;
export const ALLOWED_ENVS = ['local', 'qa', 'test', 'smoke'] as const;
export const PO_LIST_PATH = '/#/vpro/production-orders/folder/all';
export const AI_INTAKE_PATH = '/#/vpro/ai-intake';
export const SPOT_ROW_SELECTOR =
    'tr.p-datatable-selectable-row, tr[app-vppo-spot-row], .p-datatable-tbody tr';
export const DETAILS_SELECTOR =
    'app-production-order-details, #qo-form-panel, .spot-detail, .po-detail';
export const SEARCH_PANEL_SELECTOR =
    '.p-sidebar, .p-drawer, p-drawer, [data-pc-name="drawer"], .filter-overlay, dialog';
export const SIDEBAR_SELECTOR = 'app-quickorders, .p-sidebar, .p-drawer, #quickorders-sidebar';
export const RITUAL_FIRST_GHOST = 'Demo Prod Dir';
export const RITUAL_SECOND_GHOST = 'Suzan Goritz';
export const RITUAL_FIRST_GHOST_FALLBACKS = ['Demo Production Director', 'DemoProdDirector'];

export const FLOW_IDS = [
    'qo-open-close-snapshot',
    'po-open-spot',
    'po-search-panel',
    'ai-intake-open-close',
    'sidebar-open-close',
] as const;

export type MemoryFlowId = (typeof FLOW_IDS)[number];
export type MemoryEnv = (typeof ALLOWED_ENVS)[number];

export const FLOW_LABELS: Record<MemoryFlowId, string> = {
    'qo-open-close-snapshot': 'Production Orders — Quick Order open/close snapshots',
    'po-open-spot': 'Production Orders — open and close spot',
    'po-search-panel': 'Production Orders — open and close search panel',
    'ai-intake-open-close': 'AI Intake — open and leave',
    'sidebar-open-close': 'Production Orders — open and close sidebar',
};

export const FLOW_PREVIEW_STEPS: Record<MemoryFlowId, string[]> = {
    'qo-open-close-snapshot': [
        'Start screen recording',
        'Ghost in as Demo Prod Dir',
        'Open a 1-spot Quick Order',
        'Close the order without making changes',
        'Clear the console',
        'Force garbage collection',
        'Take a snapshot',
        'Open a 5-spot or larger Quick Order',
        'Close without changes, clear console, GC, snapshot',
        'Ghost in as Suzan Goritz (wide-orbit clients)',
        'Repeat the 1-spot and 5-spot snapshot steps',
    ],
    'po-open-spot': [
        'Open Production Orders',
        'Open the first spot',
        'Return to the list',
        'Force GC and take a snapshot',
        'Repeat for the cycle count',
    ],
    'po-search-panel': [
        'Open Production Orders',
        'Open the search panel',
        'Close the search panel',
        'Force GC and take a snapshot',
        'Repeat for the cycle count',
    ],
    'ai-intake-open-close': [
        'Open AI Intake',
        'Leave back to Production Orders',
        'Force GC and take a snapshot',
        'Repeat for the cycle count',
    ],
    'sidebar-open-close': [
        'Open Production Orders',
        'Open the Quick Order sidebar',
        'Close without saving',
        'Force GC and take a snapshot',
        'Repeat for the cycle count',
    ],
};
