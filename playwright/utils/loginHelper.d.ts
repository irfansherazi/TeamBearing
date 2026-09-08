import { Page } from '@playwright/test';

export function login(page: Page, username: string, password?: string, baseURL?: string): Promise<void>;
export function logout(page: Page): Promise<void>;
export function assumeUser(page: Page, identifier?: string, password?: string, baseURL?: string): Promise<void>;
export function loginWithStoredSession(page: Page, storageStatePath: string): Promise<void>;
