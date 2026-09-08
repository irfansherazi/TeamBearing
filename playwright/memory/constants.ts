export const DEFAULT_FLOW_ID = 'po-open-spot';
export const DEFAULT_ENV = 'qa';
export const DEFAULT_CYCLES = 5;
export const DEFAULT_GC_PASSES = 3;
export const ALLOWED_ENVS = ['qa', 'test', 'smoke'] as const;
export const PO_LIST_PATH = '/#/vpro/production-orders/folder/all';
export const AI_INTAKE_PATH = '/#/vpro/ai-intake';
export const SPOT_ROW_SELECTOR =
    'tr.p-datatable-selectable-row, tr[app-vppo-spot-row], .p-datatable-tbody tr';
export const DETAILS_SELECTOR =
    'app-production-order-details, #qo-form-panel, .spot-detail, .po-detail';
export const SEARCH_PANEL_SELECTOR =
    '.p-sidebar, .p-drawer, p-drawer, [data-pc-name="drawer"], .filter-overlay, dialog';
export const SIDEBAR_SELECTOR = 'app-quickorders, .p-sidebar, .p-drawer, #quickorders-sidebar';

export const FLOW_IDS = [
    'po-open-spot',
    'po-search-panel',
    'ai-intake-open-close',
    'sidebar-open-close',
] as const;

export type MemoryFlowId = (typeof FLOW_IDS)[number];
export type MemoryEnv = (typeof ALLOWED_ENVS)[number];

export const FLOW_LABELS: Record<MemoryFlowId, string> = {
    'po-open-spot': 'Production Orders — open and close spot',
    'po-search-panel': 'Production Orders — open and close search panel',
    'ai-intake-open-close': 'AI Intake — open and leave',
    'sidebar-open-close': 'Production Orders — open and close sidebar',
};
