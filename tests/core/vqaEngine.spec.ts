// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { vqaEngine, _isStandardSelector } from '../../core/selectors/vqaEngine';

describe('vqaEngine Selector Resolver', () => {
  beforeEach(() => {
    // Clear the document body before each test
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  describe('_isStandardSelector detection', () => {
    it('should correctly identify standard/legacy selectors', () => {
      expect(_isStandardSelector('#my-id')).toBe(true);
      expect(_isStandardSelector('.my-class')).toBe(true);
      expect(_isStandardSelector('[attr="val"]')).toBe(true);
      expect(_isStandardSelector('div > span')).toBe(true);
      expect(_isStandardSelector('button')).toBe(true);
      expect(_isStandardSelector('input')).toBe(true);
      expect(_isStandardSelector('text=Click Me')).toBe(true);
      expect(_isStandardSelector('button:hover')).toBe(true);
    });

    it('should correctly identify non-standard (vQA key) selectors', () => {
      expect(_isStandardSelector('submit_btn')).toBe(false);
      expect(_isStandardSelector('search-client-input')).toBe(false);
      expect(_isStandardSelector('')).toBe(false);
    });
  });

  describe('query priority resolution', () => {
    it('should resolve data-vqa-id with top priority', () => {
      document.body.innerHTML = `
        <button id="el1" aria-label="test-btn" data-vqa-id="test-btn"></button>
        <button id="el2" aria-label="test-btn"></button>
        <input id="el3" placeholder="test-btn" />
      `;

      const result = vqaEngine.query(document, 'test-btn');
      expect(result).not.toBeNull();
      expect(result!.id).toBe('el1');
    });

    it('should resolve aria-label with second priority', () => {
      document.body.innerHTML = `
        <button id="el2" aria-label="test-btn"></button>
        <input id="el3" placeholder="test-btn" />
      `;

      const result = vqaEngine.query(document, 'test-btn');
      expect(result).not.toBeNull();
      expect(result!.id).toBe('el2');
    });

    it('should resolve input[placeholder] with third priority', () => {
      document.body.innerHTML = `
        <input id="el3" placeholder="test-btn" />
      `;

      const result = vqaEngine.query(document, 'test-btn');
      expect(result).not.toBeNull();
      expect(result!.id).toBe('el3');
    });

    it('should return null if no priority matches exist', () => {
      document.body.innerHTML = `
        <div id="el4">test-btn</div>
      `;

      const result = vqaEngine.query(document, 'test-btn');
      expect(result).toBeNull();
    });
  });

  describe('Active overlay/dialog scoping', () => {
    it('should restrict search root to active PrimeNG overlay when visible', () => {
      document.body.innerHTML = `
        <div class="outside">
          <button id="out-btn" data-vqa-id="test-btn"></button>
        </div>
        <div class="p-dialog">
          <button id="in-btn" data-vqa-id="test-btn"></button>
        </div>
      `;

      // Searching from root
      const result = vqaEngine.query(document, 'test-btn');
      expect(result).not.toBeNull();
      expect(result!.id).toBe('in-btn');
    });

    it('should restrict search root to active role="dialog" overlay when visible', () => {
      document.body.innerHTML = `
        <div class="outside">
          <button id="out-btn" data-vqa-id="test-btn"></button>
        </div>
        <div role="dialog">
          <button id="in-btn" data-vqa-id="test-btn"></button>
        </div>
      `;

      const result = vqaEngine.query(document, 'test-btn');
      expect(result).not.toBeNull();
      expect(result!.id).toBe('in-btn');
    });

    it('should fallback to document if overlays are present but have hidden/dismissed class indicators', () => {
      document.body.innerHTML = `
        <div class="outside">
          <button id="out-btn" data-vqa-id="test-btn"></button>
        </div>
        <div class="p-dialog p-dialog-hidden">
          <button id="in-btn" data-vqa-id="test-btn"></button>
        </div>
      `;

      const result = vqaEngine.query(document, 'test-btn');
      expect(result).not.toBeNull();
      expect(result!.id).toBe('out-btn');
    });
  });

  describe('Legacy selector fallback logging', () => {
    it('should log single-line JSON format warning on fallback standard queries', () => {
      document.body.innerHTML = `<button id="btn" class="legacy-btn"></button>`;
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const result = vqaEngine.query(document, '.legacy-btn');
      expect(result).not.toBeNull();
      expect(result!.id).toBe('btn');

      expect(warnSpy).toHaveBeenCalledOnce();
      const warningJson = JSON.parse(warnSpy.mock.calls[0][0]);
      expect(warningJson).toMatchObject({
        level: 'WARN',
        node: 'Executor',
        message: 'VQA_SELECTOR_FALLBACK',
        tenant_id: 'global',
        technical_debt_metrics: {
          selector: '.legacy-btn',
          type: 'legacy_css'
        }
      });
      expect(warningJson.timestamp).toBeDefined();
    });
  });

  describe('queryAll matching', () => {
    it('should return multiple matching elements ordered by priority', () => {
      document.body.innerHTML = `
        <button id="el1" data-vqa-id="test-btn"></button>
        <button id="el2" data-vqa-id="test-btn"></button>
        <button id="el3" aria-label="test-btn"></button>
      `;

      const results = vqaEngine.queryAll(document, 'test-btn');
      expect(results).toHaveLength(2);
      expect(results[0].id).toBe('el1');
      expect(results[1].id).toBe('el2');
    });

    it('should fall back to aria-label matches in queryAll if no data-vqa-id matches exist', () => {
      document.body.innerHTML = `
        <button id="el3" aria-label="test-btn"></button>
        <button id="el4" aria-label="test-btn"></button>
        <input id="el5" placeholder="test-btn" />
      `;

      const results = vqaEngine.queryAll(document, 'test-btn');
      expect(results).toHaveLength(2);
      expect(results[0].id).toBe('el3');
      expect(results[1].id).toBe('el4');
    });

    it('should fall back to placeholder matches in queryAll if no data-vqa-id or aria-label matches exist', () => {
      document.body.innerHTML = `
        <input id="el5" placeholder="test-btn" />
      `;

      const results = vqaEngine.queryAll(document, 'test-btn');
      expect(results).toHaveLength(1);
      expect(results[0].id).toBe('el5');
    });

    it('should support legacy fallbacks in queryAll', () => {
      document.body.innerHTML = `
        <div class="test-item" id="el1"></div>
        <div class="test-item" id="el2"></div>
      `;
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const results = vqaEngine.queryAll(document, '.test-item');
      expect(results).toHaveLength(2);
      expect(results[0].id).toBe('el1');
      expect(results[1].id).toBe('el2');
      expect(warnSpy).toHaveBeenCalledOnce();
    });

    it('should fallback to document queries if the root does not have querySelector/querySelectorAll', () => {
      document.body.innerHTML = `
        <div class="test-item" id="el1"></div>
      `;
      vi.spyOn(console, 'warn').mockImplementation(() => {});

      const qResult = vqaEngine.query({} as any, '.test-item');
      expect(qResult).not.toBeNull();
      expect(qResult!.id).toBe('el1');

      const qAllResults = vqaEngine.queryAll({} as any, '.test-item');
      expect(qAllResults).toHaveLength(1);
      expect(qAllResults[0].id).toBe('el1');
    });
  });
});
