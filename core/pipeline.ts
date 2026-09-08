import * as fs from 'fs';
import * as path from 'path';
import { exec } from 'child_process';

export interface PipelineDependencies {
  execShell: (command: string, env: Record<string, string>) => Promise<{ stdout: string; stderr: string; code: number }>;
  readJsonFile: <T>(filePath: string) => T;
  writeTextFile: (filePath: string, content: string) => void;
  readTextFile: (filePath: string) => string;
  llmGenerate: (prompt: string) => Promise<string>;
  exists: (filePath: string) => boolean;
  readdir: (dirPath: string) => string[];
}

export class CompileFailedException extends Error {
  constructor(message: string) { super(message); this.name = 'CompileFailedException'; }
}

export class ExecutionFailedException extends Error {
  constructor(message: string) { super(message); this.name = 'ExecutionFailedException'; }
}

export class LinearPipeline {
  private tenantId: string;
  private deps: PipelineDependencies;
  private retryCounts = { compile: 0, execute: 0 };
  private traceId: string;
  private spanId: string;

  constructor(tenantId: string, deps?: Partial<PipelineDependencies>) {
    this.tenantId = tenantId;
    const defaultDeps: PipelineDependencies = {
      execShell: (cmd, env) => new Promise(r => exec(cmd, { env: { ...process.env, ...env } }, (err, stdout, stderr) => r({ stdout, stderr, code: err ? (err.code || 1) : 0 }))),
      readJsonFile: f => JSON.parse(fs.readFileSync(f, 'utf-8')),
      writeTextFile: (f, c) => { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, c, 'utf-8'); },
      readTextFile: f => fs.readFileSync(f, 'utf-8'),
      llmGenerate: async p => `// Generated spec placeholder for ${p.substring(0, 50)}`,
      exists: f => fs.existsSync(f),
      readdir: d => fs.readdirSync(d)
    };
    this.deps = { ...defaultDeps, ...deps };
    this.traceId = this.generateHex(32);
    this.spanId = this.generateHex(16);
  }

  private generateHex(len: number): string {
    const chars = '0123456789abcdef';
    let res = '';
    for (let i = 0; i < len; i++) res += chars[Math.floor(Math.random() * chars.length)];
    return res;
  }

  private logEvent(lvl: 'INFO' | 'WARN' | 'ERROR', nod: 'Generate' | 'Validate' | 'Execute' | 'Analyze', msg: string, extra?: any): void {
    console.log(JSON.stringify({ timestamp: new Date().toISOString(), level: lvl, node: nod, message: msg, tenant_id: this.tenantId, trace_id: this.traceId, span_id: this.spanId, ...extra }));
  }

  public async run(bddStep: string): Promise<string> {
    const cfgP = `tenants/${this.tenantId}/vqa.config.json`, selP = `tenants/${this.tenantId}/selectors.json`;
    if (!this.deps.exists(cfgP) || !this.deps.exists(selP)) throw new Error(`Tenant files not found for tenant: ${this.tenantId}`);
    const config = this.deps.readJsonFile<any>(cfgP), selectors = this.deps.readJsonFile<Record<string, any>>(selP);

    this.logEvent('INFO', 'Generate', `Retrieving RAG selectors for BDD step: "${bddStep}"`);
    const topSelectors = this.retrieveSelectors(bddStep, selectors);

    let helperContext = '';
    const helpersDir = config.helpers_dir || `tenants/${this.tenantId}/helpers`;
    if (this.deps.exists(helpersDir)) {
      const files = this.deps.readdir(helpersDir).filter(f => f.endsWith('.ts'));
      if (files.length < 10) {
        this.logEvent('INFO', 'Generate', `Helper corpus size ${files.length} is < 10. Triggering full helper inject fallback.`);
        helperContext = files.map(file => `// File: ${file}\n${this.deps.readTextFile(path.join(helpersDir, file))}`).join('\n\n');
      }
    }

    let specCode = await this.deps.llmGenerate(`Generate Playwright test for: "${bddStep}".\nSelectors:\n${JSON.stringify(topSelectors, null, 2)}\nHelpers:\n${helperContext}`);
    const specPath = path.join(config.pipeline?.output_dir || 'playwright/tests/generated', `${this.tenantId}_spec.spec.ts`);
    this.deps.writeTextFile(specPath, specCode);

    let validated = false;
    while (!validated) {
      this.logEvent('INFO', 'Validate', `Compiling generated spec: ${specPath}`);
      const tscConfig = config.pipeline?.tsc_config || 'tsconfig.json';
      const compileRes = await this.deps.execShell(`npx tsc --noEmit --project ${tscConfig} ${specPath}`, {});
      if (compileRes.code !== 0) {
        if (this.retryCounts.compile === 0) {
          this.retryCounts.compile = 1;
          this.logEvent('WARN', 'Validate', 'Compilation failed. Triggering exactly ONE auto-fix retry.', { error_output: compileRes.stderr || compileRes.stdout });
          specCode = await this.deps.llmGenerate(`Fix TS compiler errors.\nCode:\n${specCode}\nErrors:\n${compileRes.stderr || compileRes.stdout}`);
          this.deps.writeTextFile(specPath, specCode);
        } else {
          this.logEvent('ERROR', 'Validate', 'COMPILE_FAILED', { error_details: compileRes.stderr || compileRes.stdout });
          throw new CompileFailedException(`TypeScript compilation failed twice. Final error: ${compileRes.stderr || compileRes.stdout}`);
        }
      } else validated = true;
    }

    this.logEvent('INFO', 'Validate', 'Running runtime selector schema validation.');
    try { this.validateSpecSelectors(specCode, new Set(Object.keys(selectors))); }
    catch (err: any) { this.logEvent('ERROR', 'Validate', 'Selector schema validation failed', { error: err.message }); throw err; }

    let executedSuccessfully = false;
    while (!executedSuccessfully) {
      this.logEvent('INFO', 'Execute', `Executing generated spec: ${specPath}`);
      const executionRes = await this.deps.execShell(`npx playwright test ${specPath}`, { VQA_TRACE_ID: this.traceId, VQA_SPAN_ID: this.spanId, VQA_TENANT_ID: this.tenantId });

      (executionRes.stdout + '\n' + executionRes.stderr).split('\n').forEach(line => {
        if (line.includes('VQA_SELECTOR_FALLBACK')) {
          try {
            const parsed = JSON.parse(line.trim());
            if (parsed.message === 'VQA_SELECTOR_FALLBACK') this.logEvent('WARN', 'Execute', 'VQA_SELECTOR_FALLBACK', { technical_debt_metrics: parsed.technical_debt_metrics });
          } catch {}
        }
      });

      if (executionRes.code !== 0) {
        const outputText = executionRes.stdout + '\n' + executionRes.stderr;
        const collisionMatch = /strict mode violation: locator\(['"](.*?)['"]\)/i.exec(outputText) || /locator\(['"](.*?)['"]\).*?resolved to \d+ elements/i.exec(outputText);
        if (collisionMatch) {
          const selectorKey = collisionMatch[1];
          if (this.retryCounts.execute === 0) {
            this.retryCounts.execute = 1;
            this.logEvent('WARN', 'Execute', `Strict mode collision detected on locator "${selectorKey}". Retrying with correction.`, { error: outputText });
            specCode = await this.deps.llmGenerate(`Strict mode violation: locator('${selectorKey}') matched multiple elements. Scope it using parent container.\nBDD: ${bddStep}\nSpec:\n${specCode}`);
            this.deps.writeTextFile(specPath, specCode);
            const tscConfig = config.pipeline?.tsc_config || 'tsconfig.json';
            const reCompile = await this.deps.execShell(`npx tsc --noEmit --project ${tscConfig} ${specPath}`, {});
            if (reCompile.code !== 0) {
              this.logEvent('ERROR', 'Validate', 'COMPILE_FAILED on corrected spec after strict mode retry');
              throw new CompileFailedException(`TypeScript compilation failed on corrected spec. Final error: ${reCompile.stderr || reCompile.stdout}`);
            }
          } else {
            this.logEvent('ERROR', 'Execute', 'EXECUTE_FAILED due to persistent strict mode collision');
            await this.runAnalyze(bddStep, specCode, outputText, selectors);
            throw new ExecutionFailedException(`Persistent strict-mode collision on locator "${selectorKey}". Escalating to human code reviewer.`);
          }
        } else {
          this.logEvent('ERROR', 'Execute', 'EXECUTE_FAILED due to non-collision runtime error');
          await this.runAnalyze(bddStep, specCode, outputText, selectors);
          throw new ExecutionFailedException(`Execution failed with runtime error. Escalating to human code reviewer. Error: ${outputText}`);
        }
      } else executedSuccessfully = true;
    }

    this.logEvent('INFO', 'Execute', 'Execution completed successfully.');
    return 'SUCCESS';
  }

  private retrieveSelectors(bddStep: string, selectors: Record<string, any>, limit = 5): Record<string, any> {
    const bddTokens = bddStep.toLowerCase().match(/\w+/g) || [];
    if (bddTokens.length === 0) {
      const result: Record<string, any> = {};
      Object.entries(selectors).slice(0, limit).forEach(([k, v]) => { result[k] = v; });
      return result;
    }
    const scored = Object.entries(selectors).map(([key, value]: [string, any]) => {
      if (key === '_readme') return { key, score: -1 };
      if (!value) return { key, score: 0 };
      const desc = (value.description || '').toLowerCase(), sel = (value.selector || '').toLowerCase();
      const text = `${desc} ${sel} ${key.toLowerCase()}`, targetTokens = text.match(/\w+/g) || [];
      let score = 0;
      bddTokens.forEach(t => { if (targetTokens.includes(t)) score += 1; });
      return { key, value, score };
    }).filter(x => x.score >= 0);
    scored.sort((a, b) => b.score - a.score);
    const result: Record<string, any> = {};
    scored.slice(0, limit).forEach(item => { if (item.value) result[item.key] = item.value; });
    return result;
  }

  private validateSpecSelectors(content: string, validKeys: Set<string>): void {
    const regex = /vqa=([a-zA-Z0-9_\-]+)/g;
    let m;
    while ((m = regex.exec(content)) !== null) {
      if (!validKeys.has(m[1])) throw new Error(`Invalid selector key found in spec: "${m[1]}". Not registered in tenant's selectors.json.`);
    }
  }

  private async runAnalyze(bddStep: string, specCode: string, logs: string, selectors: Record<string, any>): Promise<void> {
    this.logEvent('INFO', 'Analyze', 'Translating test execution failure back to scenario BDD steps.');
    const analysis = await this.deps.llmGenerate(`Analyze failure.\nBDD: ${bddStep}\nSpec:\n${specCode}\nLogs:\n${logs}\nSelectors:\n${JSON.stringify(selectors, null, 2)}`);
    this.logEvent('ERROR', 'Analyze', 'Failure translation complete', { analysis });
  }
}
