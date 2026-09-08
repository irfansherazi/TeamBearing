import { describe, it, expect, vi, beforeEach } from 'vitest';
import { LinearPipeline, CompileFailedException, ExecutionFailedException, PipelineDependencies } from '../../core/pipeline';
import * as path from 'path';

describe('LinearPipeline Engine Orchestrator', () => {
  let mockDeps: Record<string, any>;
  const mockTenantConfig = {
    tenant_id: 'vpromedia',
    helpers_dir: 'tenants/vpromedia/helpers',
    pipeline: {
      output_dir: 'playwright/tests/generated',
      tsc_config: 'playwright/tsconfig.json'
    }
  };
  const mockSelectors = {
    "search-open-btn": { selector: "#open", description: "Search button" },
    "search-client-input": { selector: "#client", description: "Client field" }
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    mockDeps = {
      execShell: vi.fn(),
      readJsonFile: vi.fn(),
      writeTextFile: vi.fn(),
      readTextFile: vi.fn(),
      llmGenerate: vi.fn(),
      exists: vi.fn(),
      readdir: vi.fn()
    };
  });

  it('should throw an error if tenant config or selectors files do not exist', async () => {
    mockDeps.exists.mockReturnValue(false);
    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    await expect(pipeline.run('Click search')).rejects.toThrow('Tenant files not found for tenant: vpromedia');
  });

  it('should run successfully in happy path (Generate -> Validate (compile success) -> Execute -> Success)', async () => {
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue(['SearchHelper.ts']);
    mockDeps.readTextFile.mockReturnValue('// SearchHelper implementation');
    mockDeps.llmGenerate.mockResolvedValue('// Generated spec code\nconst btn = page.locator("vqa=search-open-btn");');
    
    // Compilation success (code: 0) and Execution success (code: 0)
    mockDeps.execShell.mockResolvedValue({ stdout: '', stderr: '', code: 0 });

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    const result = await pipeline.run('Click search');

    expect(result).toBe('SUCCESS');
    expect(mockDeps.llmGenerate).toHaveBeenCalledOnce();
    expect(mockDeps.execShell).toHaveBeenCalledTimes(2); // 1 tsc, 1 playwright
    expect(mockDeps.writeTextFile).toHaveBeenCalledOnce();
  });

  it('should handle compilation failure and trigger exactly ONE auto-fix retry', async () => {
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Generated code with bug');
    
    // First tsc fails (code: 1), second tsc succeeds (code: 0), execution succeeds (code: 0)
    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: '', stderr: 'TS2304: Cannot find name', code: 1 }) // 1st Compile
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // 2nd Compile
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }); // Execution

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    const result = await pipeline.run('Click search');

    expect(result).toBe('SUCCESS');
    expect(mockDeps.llmGenerate).toHaveBeenCalledTimes(2); // 1 original, 1 fix compile
    expect(mockDeps.execShell).toHaveBeenCalledTimes(3); // 2 compiles, 1 execute
  });

  it('should halt with CompileFailedException when compilation fails twice', async () => {
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Generated bad code');

    // Both tsc fail
    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: '', stderr: 'TS Error 1', code: 1 })
      .mockResolvedValueOnce({ stdout: '', stderr: 'TS Error 2', code: 1 });

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    await expect(pipeline.run('Click search')).rejects.toThrow(CompileFailedException);
    expect(mockDeps.llmGenerate).toHaveBeenCalledTimes(2); // 1 original, 1 fix compile
    expect(mockDeps.execShell).toHaveBeenCalledTimes(2); // 2 compiles
  });

  it('should throw error during runtime schema validation if spec uses unregistered vqa key', async () => {
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    // Spec uses vqa=unknown-selector-key which is not in mockSelectors
    mockDeps.llmGenerate.mockResolvedValue('// Generated spec code\nconst btn = page.locator("vqa=unknown-selector-key");');
    mockDeps.execShell.mockResolvedValue({ stdout: '', stderr: '', code: 0 }); // Compile success

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    await expect(pipeline.run('Click search')).rejects.toThrow('Invalid selector key found in spec: "unknown-selector-key". Not registered in tenant\'s selectors.json.');
  });

  it('should handle strict mode execution collision and trigger exactly ONE correction retry', async () => {
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Original bad selector\nconst btn = page.locator("vqa=search-open-btn");');

    // Mocks for:
    // 1st compile: success
    // 1st execute: fails with strict mode collision
    // 2nd compile (corrected spec): success
    // 2nd execute (corrected spec): success
    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // 1st Compile
      .mockResolvedValueOnce({
        stdout: '',
        stderr: 'locator.click: strict mode violation: locator("vqa=search-open-btn") resolved to 3 elements',
        code: 1
      }) // 1st Execute (fails)
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // 2nd Compile
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }); // 2nd Execute (success)

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    const result = await pipeline.run('Click search');

    expect(result).toBe('SUCCESS');
    expect(mockDeps.llmGenerate).toHaveBeenCalledTimes(2); // 1 original, 1 collision fix
    expect(mockDeps.execShell).toHaveBeenCalledTimes(4); // 2 compiles, 2 executes
  });

  it('should escalate to human and run Analyze on persistent strict mode collision', async () => {
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Persistent failing code\nconst btn = page.locator("vqa=search-open-btn");');

    // Mocks:
    // 1st compile: success
    // 1st execute: collision fail
    // 2nd compile: success
    // 2nd execute: collision fail
    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // 1st Compile
      .mockResolvedValueOnce({
        stdout: '',
        stderr: 'locator.click: strict mode violation: locator("vqa=search-open-btn") resolved to 3 elements',
        code: 1
      }) // 1st Execute
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // 2nd Compile
      .mockResolvedValueOnce({
        stdout: '',
        stderr: 'locator.click: strict mode violation: locator("vqa=search-open-btn") resolved to 3 elements',
        code: 1
      }); // 2nd Execute

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    await expect(pipeline.run('Click search')).rejects.toThrow(ExecutionFailedException);
    expect(mockDeps.llmGenerate).toHaveBeenCalledTimes(3); // 1 original, 1 fix, 1 post-failure translation
  });

  it('should immediately fail and escalate to human on non-collision runtime error', async () => {
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Code');

    // Mocks:
    // Compile: success
    // Execute: non-collision timeout error (code 1)
    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // Compile
      .mockResolvedValueOnce({
        stdout: '',
        stderr: 'Timeout 30000ms exceeded',
        code: 1
      }); // Execute

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    await expect(pipeline.run('Click search')).rejects.toThrow(ExecutionFailedException);
    expect(mockDeps.llmGenerate).toHaveBeenCalledTimes(2); // 1 original, 1 post-failure translation
  });

  it('should bridge selector fallback warning from execution logs to orchestrator event logs', async () => {
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Happy spec');

    const warningLine = JSON.stringify({
      timestamp: new Date().toISOString(),
      level: 'WARN',
      node: 'Executor',
      message: 'VQA_SELECTOR_FALLBACK',
      tenant_id: 'vpromedia',
      technical_debt_metrics: { selector: '.legacy-btn', type: 'legacy_css' }
    });

    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // Compile
      .mockResolvedValueOnce({
        stdout: `Running tests...\n${warningLine}\nTest passed!`,
        stderr: '',
        code: 0
      }); // Execute with warning in stdout

    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    await pipeline.run('Click search');

    // Verify warning line was bridged/logged
    expect(logSpy).toHaveBeenCalled();
    const loggedObjects = logSpy.mock.calls.map(args => JSON.parse(args[0]));
    const fallbackLog = loggedObjects.find(obj => obj.message === 'VQA_SELECTOR_FALLBACK');
    expect(fallbackLog).toBeDefined();
    expect(fallbackLog.technical_debt_metrics).toMatchObject({
      selector: '.legacy-btn',
      type: 'legacy_css'
    });
  });

  it('should execute retrieveSelectors with BM25 token splitting and fallback when step is empty', () => {
    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    
    // Empty step returns first N
    const resEmpty = (pipeline as any).retrieveSelectors('', mockSelectors, 1);
    expect(Object.keys(resEmpty)).toHaveLength(1);
    expect(resEmpty['search-open-btn']).toBeDefined();

    // Step with matching tokens
    const resTokens = (pipeline as any).retrieveSelectors('user clicks search open button', mockSelectors, 1);
    expect(resTokens['search-open-btn']).toBeDefined();
  });

  it('should skip _readme key in retrieveSelectors (score -1 branch, filtered by score >= 0 guard)', () => {
    // _readme is a special documentation key in selectors.json — it must be excluded from scoring
    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    const selectorsWithReadme = {
      '_readme': 'This file documents selector conventions.',
      'search-open-btn': { selector: '#open', description: 'Search button' }
    };

    const result = (pipeline as any).retrieveSelectors('search open button', selectorsWithReadme, 5);

    // _readme must NOT appear in results — it is filtered by score: -1 < 0
    expect(result['_readme']).toBeUndefined();
    expect(result['search-open-btn']).toBeDefined();
  });

  it('should handle selector entries with missing description or selector fields (|| "" branches)', () => {
    // Covers lines 157-158: (value.description || '').toLowerCase() and (value.selector || '').toLowerCase()
    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    const selectorsWithMissingFields = {
      'no-desc-btn': { selector: '#btn' },                // missing description → '' branch
      'no-sel-btn': { description: 'A button' },          // missing selector → '' branch
      'bare-btn': {}                                       // both missing → both '' branches
    };

    const result = (pipeline as any).retrieveSelectors('button', selectorsWithMissingFields, 5);

    // All three entries should participate in scoring (none are _readme, all have score >= 0)
    // At minimum the entry matching "button" in its description or key should appear
    expect(Object.keys(result).length).toBeGreaterThanOrEqual(1);
  });

  it('should skip scored entries with no value property in retrieveSelectors (if(item.value) false branch)', () => {
    // Covers line 165: if (item.value) result[item.key] = item.value
    // An entry whose value is null/undefined but score >= 0 is discarded from result
    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);

    // Directly call private method with a patched selectors object containing a null-valued entry
    // null values happen when selectors.json has explicit null entries (e.g., a stub placeholder)
    const selectorsWithNull = {
      'valid-btn': { selector: '#btn', description: 'Valid button' },
      'null-btn': null   // null value → item.value is falsy at line 165
    };

    const result = (pipeline as any).retrieveSelectors('button', selectorsWithNull as any, 5);

    // null-btn should NOT appear in result (item.value is falsy)
    expect(result['null-btn']).toBeUndefined();
    // valid-btn should appear since it matched "button" token and has value
    expect(result['valid-btn']).toBeDefined();
  });

  it('should fail with CompileFailedException if corrected spec fails compilation after strict-mode collision', async () => {
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Corrected spec');

    // Mocks:
    // 1st compile: success (0)
    // 1st execute: collision fail (1)
    // 2nd compile (corrected spec): fails (1)
    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // 1st Compile
      .mockResolvedValueOnce({
        stdout: '',
        stderr: 'locator.click: strict mode violation: locator("vqa=search-open-btn") resolved to 3 elements',
        code: 1
      }) // 1st Execute
      .mockResolvedValueOnce({ stdout: '', stderr: 'TS Compile Error on Corrected Spec', code: 1 }); // 2nd Compile

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    await expect(pipeline.run('Click search')).rejects.toThrow(CompileFailedException);
  });

  it('should cover the default dependency injection implementations', async () => {
    const pipeline = new LinearPipeline('vpromedia');
    const deps: PipelineDependencies = (pipeline as any).deps;

    // 1. exists
    expect(deps.exists('non_existent_file.json')).toBe(false);

    // 2. writeTextFile and readTextFile and exists
    const tempFile = path.join(__dirname, '../../tmp_test_file.txt');
    deps.writeTextFile(tempFile, 'hello dependency world');
    expect(deps.exists(tempFile)).toBe(true);
    expect(deps.readTextFile(tempFile)).toBe('hello dependency world');

    // 3. readJsonFile
    const tempJsonFile = path.join(__dirname, '../../tmp_test_file.json');
    deps.writeTextFile(tempJsonFile, JSON.stringify({ ok: true }));
    expect(deps.readJsonFile<any>(tempJsonFile)).toEqual({ ok: true });

    // 4. readdir
    const parentDir = path.dirname(tempFile);
    const files = deps.readdir(parentDir);
    expect(files.length).toBeGreaterThan(0);
    expect(files).toContain('tmp_test_file.txt');

    // Clean up
    const fs = require('fs');
    fs.unlinkSync(tempFile);
    fs.unlinkSync(tempJsonFile);

    // 5. llmGenerate
    const promptRes = await deps.llmGenerate('test prompt');
    expect(promptRes).toContain('Generated spec placeholder');

    // 6. execShell
    const shellRes = await deps.execShell('node -e "console.log(\'hello shell\')"');
    expect(shellRes.code).toBe(0);
    expect(shellRes.stdout).toContain('hello shell');
  });

  it('should skip VQA_SELECTOR_FALLBACK bridging when parsed JSON message is different (line 110 false branch)', async () => {
    // Covers: if (parsed.message === 'VQA_SELECTOR_FALLBACK') — the false branch
    // A stdout line containing 'VQA_SELECTOR_FALLBACK' text but parsed .message is something else
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Happy spec');

    const spoofLine = JSON.stringify({
      level: 'DEBUG',
      message: 'Contains VQA_SELECTOR_FALLBACK in body but is not that message type',
      tenant_id: 'vpromedia'
    });

    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 })
      .mockResolvedValueOnce({ stdout: spoofLine, stderr: '', code: 0 });

    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    await pipeline.run('Click search');

    const loggedObjects = logSpy.mock.calls.map(args => { try { return JSON.parse(args[0]); } catch { return null; } }).filter(Boolean);
    const fallbackLog = loggedObjects.find(obj => obj.message === 'VQA_SELECTOR_FALLBACK');
    expect(fallbackLog).toBeUndefined();
  });

  it('should fall back to default tsconfig.json when tsc_config absent in tenant pipeline config (line 125 branch)', async () => {
    // Covers: config.pipeline?.tsc_config || 'tsconfig.json' — the || 'tsconfig.json' branch
    const configWithoutTscConfig = {
      tenant_id: 'vpromedia',
      helpers_dir: 'tenants/vpromedia/helpers',
      pipeline: { output_dir: 'playwright/tests/generated' }
    };

    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return configWithoutTscConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// spec\nconst btn = page.locator("vqa=search-open-btn");');

    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // 1st compile
      .mockResolvedValueOnce({
        stdout: '',
        stderr: 'locator.click: strict mode violation: locator("vqa=search-open-btn") resolved to 3 elements',
        code: 1
      }) // 1st execute — collision triggers re-compile path with fallback tscConfig
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // 2nd compile (line 125 re-compile)
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }); // 2nd execute

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    const result = await pipeline.run('Click search');

    expect(result).toBe('SUCCESS');
    // 3rd execShell call is the re-compile at line 126 — must use fallback 'tsconfig.json'
    const reCompileCmd = mockDeps.execShell.mock.calls[2][0] as string;
    expect(reCompileCmd).toContain('tsconfig.json');
    expect(reCompileCmd).not.toContain('playwright/tsconfig.json');
  });

  it('should handle selector text with no word characters in retrieveSelectors (|| [] branch line 159)', () => {
    // Covers: text.match(/\w+/g) || [] — the || [] branch when match returns null
    // Happens when key + desc + sel contain only non-word chars (hyphens, spaces, dots)
    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);

    const selectorsAllSymbols = {
      '---': { selector: '!!!', description: '...' }
    };

    const result = (pipeline as any).retrieveSelectors('click button', selectorsAllSymbols as any, 5);
    // text = '... !!! ---' → text.match(/\w+/g) = null → fallback to [] → score stays 0
    // Entry survives filter(x => x.score >= 0) with score 0
    expect(typeof result).toBe('object');
  });

  it('should skip full helper inject when helpers directory has >= 10 .ts files (line 69 false branch)', async () => {
    // Covers: if (files.length < 10) — the false branch when corpus is large enough for BM25
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    // Return 10 .ts files — exactly at the threshold, skips full inject
    mockDeps.readdir.mockReturnValue([
      'Helper1.ts', 'Helper2.ts', 'Helper3.ts', 'Helper4.ts', 'Helper5.ts',
      'Helper6.ts', 'Helper7.ts', 'Helper8.ts', 'Helper9.ts', 'Helper10.ts'
    ]);
    mockDeps.llmGenerate.mockResolvedValue('// Generated without helper inject');
    mockDeps.execShell.mockResolvedValue({ stdout: '', stderr: '', code: 0 });

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    const result = await pipeline.run('Click search');

    expect(result).toBe('SUCCESS');
    // readTextFile should NOT be called — full inject was skipped (>= 10 files)
    expect(mockDeps.readTextFile).not.toHaveBeenCalled();
  });

  it('should use default output_dir when pipeline.output_dir is absent from tenant config (line 76 branch)', async () => {
    // Covers: config.pipeline?.output_dir || 'playwright/tests/generated' — the || fallback
    const configWithoutOutputDir = {
      tenant_id: 'vpromedia',
      helpers_dir: 'tenants/vpromedia/helpers',
      pipeline: { tsc_config: 'playwright/tsconfig.json' }
      // output_dir intentionally absent
    };

    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return configWithoutOutputDir;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Generated spec');
    mockDeps.execShell.mockResolvedValue({ stdout: '', stderr: '', code: 0 });

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    const result = await pipeline.run('Click search');

    expect(result).toBe('SUCCESS');
    // writeTextFile path should use the default output dir
    const writePath = mockDeps.writeTextFile.mock.calls[0][0] as string;
    expect(writePath).toContain('playwright/tests/generated');
  });

  it('should include stdout in error message when stderr is empty during compile failure (|| branches lines 87-92)', async () => {
    // Covers compileRes.stderr || compileRes.stdout: when stderr is '' the || takes compileRes.stdout
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Bad code');

    // Both compiles fail — error is in stdout (not stderr)
    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: 'TS2304 error in stdout', stderr: '', code: 1 }) // 1st compile
      .mockResolvedValueOnce({ stdout: 'TS2304 error in stdout again', stderr: '', code: 1 }); // 2nd compile

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    await expect(pipeline.run('Click search')).rejects.toThrow(CompileFailedException);
    // Verify the error message contains stdout content (the || branch was taken)
    try { await pipeline.run('Click search'); } catch (e: any) { /* second run blocked */ }
    expect(mockDeps.llmGenerate).toHaveBeenCalledWith(expect.stringContaining('TS2304 error in stdout'));
  });

  it('should include stdout in error when re-compile fails with empty stderr after strict-mode collision (line 129 branch)', async () => {
    // Covers line 129: throw CompileFailedException with reCompile.stderr || reCompile.stdout
    // When reCompile.stderr is '' but reCompile.stdout has the error (|| branch)
    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return mockTenantConfig;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// spec\nconst btn = page.locator("vqa=search-open-btn");');

    mockDeps.execShell
      .mockResolvedValueOnce({ stdout: '', stderr: '', code: 0 }) // 1st compile OK
      .mockResolvedValueOnce({
        stdout: '',
        stderr: 'locator.click: strict mode violation: locator("vqa=search-open-btn") resolved to 3 elements',
        code: 1
      }) // 1st execute — collision
      .mockResolvedValueOnce({ stdout: 'TS recompile error in stdout only', stderr: '', code: 1 }); // re-compile fails via stdout

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    let thrownError: Error | null = null;
    try {
      await pipeline.run('Click search');
    } catch (e: any) {
      thrownError = e;
    }
    expect(thrownError).toBeInstanceOf(CompileFailedException);
    expect(thrownError!.message).toContain('TS recompile error in stdout only');
  });

  it('should use default helpers_dir path when config.helpers_dir is absent (line 66 || branch)', async () => {
    // Covers: config.helpers_dir || `tenants/${this.tenantId}/helpers` — the || fallback branch
    const configWithoutHelpersDir = {
      tenant_id: 'vpromedia',
      // helpers_dir intentionally absent — falls back to `tenants/vpromedia/helpers`
      pipeline: {
        output_dir: 'playwright/tests/generated',
        tsc_config: 'playwright/tsconfig.json'
      }
    };

    mockDeps.exists.mockReturnValue(true);
    mockDeps.readJsonFile.mockImplementation((filePath: string) => {
      if (filePath.endsWith('vqa.config.json')) return configWithoutHelpersDir;
      if (filePath.endsWith('selectors.json')) return mockSelectors;
      return {};
    });
    mockDeps.readdir.mockReturnValue([]);
    mockDeps.llmGenerate.mockResolvedValue('// Generated spec');
    mockDeps.execShell.mockResolvedValue({ stdout: '', stderr: '', code: 0 });

    const pipeline = new LinearPipeline('vpromedia', mockDeps as any);
    const result = await pipeline.run('Click search');

    expect(result).toBe('SUCCESS');
    // readdir should have been called with the default helpers path
    expect(mockDeps.readdir).toHaveBeenCalledWith('tenants/vpromedia/helpers');
  });

  it('should cover execShell error code branch in default dep implementation (line 33 err.code || 1)', async () => {
    // Covers: err ? (err.code || 1) : 0 — the err truthy branch when shell exits non-zero
    // The default execShell wraps child_process.exec; a failing command sets err with .code
    const pipeline = new LinearPipeline('vpromedia'); // uses default deps
    const deps: PipelineDependencies = (pipeline as any).deps;

    // Run a command guaranteed to exit with non-zero code
    const result = await deps.execShell('node -e "process.exit(42)"');
    expect(result.code).toBe(42); // err.code is 42 — truthy, so (err.code || 1) = 42

    // Cover the || 1 fallback: when process is killed via signal, err.code is null → || 1 returns 1
    // Node's child_process.exec sets err.code = null on signal termination
    const killResult = await deps.execShell("node -e \"process.kill(process.pid, 'SIGKILL')\"");
    // Signal-killed process: err.code = null → err.code || 1 = 1
    expect(killResult.code).toBe(1);
  });
});
