import type { Page, BrowserContext } from '@playwright/test';

export type TestContext = {
  page: Page;
  context: BrowserContext;
  user: string;
};
