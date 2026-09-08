/**
 * core/types/TenantAuth.ts
 * =============================
 * Strong typing interfaces for Multi-Tenant Isolation boundaries.
 */

export interface TenantConfig {
  tenantId: string;
  credentials?: Record<string, any>;
  browserPreferences?: {
    headless?: boolean;
    viewport?: { width: number; height: number };
    [key: string]: any;
  };
  timingOverrides?: Record<string, number>;
  [key: string]: any;
}

export interface SelectorMappings {
  [key: string]: string;
}

export interface TenantAuth {
  tenantId: string;
  configPath: string;
  selectorsPath: string;
  helpersDir: string;
}
