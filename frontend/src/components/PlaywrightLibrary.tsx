import { useEffect, useState } from "react";
import { authenticatedFetch } from "../api_client";
import { API_BASE_URL } from "../types";
import { getTestDisplayName } from "../lib/testFormatting";
import { useProductContext } from "../context/ProductContext";

interface PlaywrightTest {
  id: string;
  name: string;
  path: string;
  type: string;
}

interface PlaywrightLibraryProps {
  onSelect: (testId: string) => void;
  selectedTestId: string | null;
  disabled?: boolean;
}

export function PlaywrightLibrary({ onSelect, selectedTestId, disabled }: PlaywrightLibraryProps) {
  const { activeSlug: productSlug } = useProductContext();
  const [tests, setTests] = useState<PlaywrightTest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    authenticatedFetch(`${API_BASE_URL}/playwright/tests?product=${encodeURIComponent(productSlug)}`)
      .then(async (r) => {
        if (!r.ok) {
          const errorData = await r.json().catch(() => ({ detail: "Unknown error" }));
          throw new Error(errorData.detail || `Server error: ${r.status}`);
        }
        return r.json();
      })
      .then((data: any[]) => {
        const runnable = data.filter((t) =>
          t.file?.endsWith('.test.ts') &&
          (t.steps_count ?? 0) > 0
        );
        const mapped = runnable.map((t) => ({
          id: t.id,
          name: getTestDisplayName({ id: t.id, file: t.file, display_name: t.display_name }),
          path: t.file || "",
          type: t.type || "static",
        }));
        setTests(mapped);
        setLoading(false);
      })
      .catch((err) => {
        console.error("Failed to load Playwright library:", err);
        setError(err instanceof Error ? err.message : "Could not load Playwright tests");
        setLoading(false);
      });
  }, [productSlug]);

  if (loading) return (
    <div className="playwright-library-loading">
      <span className="spinner"></span>
      Loading Playwright library...
    </div>
  );

  if (error) return (
    <div className="playwright-library-error">
      <span className="error-icon">⚠️</span>
      {error}
    </div>
  );

  return (
    <div className="playwright-library">
      <div className="test-grid">
        {tests.map((test) => (
          <div
            key={test.id}
            className={`test-card ${selectedTestId === test.id ? "selected" : ""} ${disabled ? "disabled" : ""}`}
            onClick={() => !disabled && onSelect(test.id)}
            role="button"
            tabIndex={disabled ? -1 : 0}
          >
            <div className="test-card-icon">🎭</div>
            <div className="test-card-info">
              <div className="test-name">{test.name}</div>
              <div className="test-id">{test.id}</div>
            </div>
            {selectedTestId === test.id && <div className="selected-check">✅</div>}
          </div>
        ))}
        {tests.length === 0 && (
          <div className="empty-library">
            <p>No tests found in <code>backend/playwright_tests/</code></p>
            <span className="hint">Make sure your .spec.ts files are in the correct directory.</span>
          </div>
        )}
      </div>
    </div>
  );
}
