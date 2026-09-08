import type { Reporter, FullConfig, Suite, TestCase, TestResult, FullResult, TestStep } from '@playwright/test/reporter';
import fs from 'fs';
import path from 'path';

const htmlReporterPath = path.join(path.dirname(require.resolve('@playwright/test')),
  'node_modules', 'playwright', 'lib', 'reporters', 'html.js');
const HtmlReporter = require(htmlReporterPath).default;

function collectSteps(steps: TestStep[] = [], store: string[]) {
  for (const step of steps) {
    store.push(step.title);
    collectSteps(step.steps, store);
  }
}

export default class StepsSummaryReporter implements Reporter {
  private html: any;
  private tests: { title: string; status: string; steps: string[] }[] = [];
  private folder = '';

  constructor(options: any = {}) {
    this.html = new HtmlReporter(options);
  }

  onConfigure(config: FullConfig) {
    this.html.onConfigure?.(config);
  }

  onBegin(config: FullConfig, suite: Suite) {
    this.html.onConfigure?.(config);
    this.html.onBegin?.(suite);
  }

  onTestBegin(test: TestCase, result: TestResult) {
    this.html.onTestBegin?.(test, result);
  }

  onTestEnd(test: TestCase, result: TestResult) {
    this.html.onTestEnd?.(test, result);
    const stepTitles: string[] = [];
    collectSteps(result.steps, stepTitles);
    this.tests.push({ title: test.title, status: result.status, steps: stepTitles });
  }

  async onEnd(result: FullResult) {
    await this.html.onEnd?.(result);
    this.folder = (this.html as any)._reportFolder || 'playwright-report';
    const summaryHtml = this.renderHtml();
    fs.writeFileSync(path.join(this.folder, 'steps-summary.html'), summaryHtml, 'utf-8');

    const indexPath = path.join(this.folder, 'index.html');
    if (fs.existsSync(indexPath)) {
      const original = fs.readFileSync(indexPath, 'utf-8');
      const link = '<div style="padding:10px"><a href="steps-summary.html">View Step Summary</a></div>';
      fs.writeFileSync(indexPath, original.replace('</body>', `${link}</body>`));
    }
  }

  private renderHtml(): string {
    const content = this.tests.map(t => {
      const steps = t.steps.map(s => `<li>${s}</li>`).join('');
      return `<h3>${t.title} <span style="font-weight:normal">(${t.status})</span></h3><ol>${steps}</ol>`;
    }).join('');
    return `<html><head><title>Test Steps Summary</title></head><body>${content}</body></html>`;
  }
}

