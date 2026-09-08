/**
 * Prompt shown after a successful Computer-Use run — lets the tester name
 * and persist the run's browser interactions as a Playwright .spec.ts file.
 *
 * Only rendered when the parent has verified the run's terminal state was
 * `completed` (successful). The dialog does NOT check terminal state
 * itself; the backend also enforces the gate (409 on non-done runs), but
 * this is defense-in-depth — the UI should never even show this dialog
 * for a failed/stuck run.
 */

import { useMemo, useState } from "react";
import { useExecution, type SaveRunAsTestResponse } from "../hooks/useExecution";

interface SaveAsTestDialogProps {
  runId: string;
  ticketId: string;
  ticketSummary: string;
  product: string;
  onClose: () => void;
}

/**
 * Preview-side slug preview must match the backend's slugify() exactly so
 * the filename users see matches the one written to disk. Rules:
 *   - lowercase
 *   - non-alphanumeric sequences collapse to single '-'
 *   - leading/trailing '-' stripped
 *   - capped at 50 chars
 *   - empty → "unnamed"
 */
function slugifyPreview(text: string): string {
  const cleaned = (text || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50);
  return cleaned || "unnamed";
}

export function SaveAsTestDialog({
  runId,
  ticketId,
  ticketSummary,
  product,
  onClose,
}: SaveAsTestDialogProps) {
  const { saveRunAsTest, error } = useExecution();

  const defaultName = ticketSummary
    ? `${ticketId}: ${ticketSummary}`
    : ticketId;

  const [name, setName] = useState<string>(defaultName);
  const [productOverride, setProductOverride] = useState<string>(product || "");
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [result, setResult] = useState<SaveRunAsTestResponse | null>(null);

  const slugPreview = useMemo(() => slugifyPreview(name), [name]);
  const productSlug = useMemo(
    () => slugifyPreview(productOverride) || "misc",
    [productOverride],
  );
  const filenamePreview = `playwright/tests/${productSlug}/${slugPreview}-cu.test.ts`;

  const canSave = !!name.trim() && !isSaving && !result;

  const handleSave = async () => {
    if (!canSave) return;
    setIsSaving(true);
    try {
      const res = await saveRunAsTest(runId, {
        name: name.trim(),
        product: productOverride.trim() || undefined,
      });
      if (res) {
        setResult(res);
      }
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="record-demo-overlay" role="dialog" aria-modal="true">
      <div
        className="record-demo-modal"
        style={{ maxWidth: 620, maxHeight: "90vh" }}
      >
        <div style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <h2 style={{ margin: 0, fontSize: 20 }}>Save as Playwright test</h2>
              <p style={{ margin: "6px 0 0 0", color: "var(--text-secondary)", fontSize: 13 }}>
                Run <code>{runId}</code> completed successfully. Save it as a reusable Playwright spec?
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              disabled={isSaving}
              aria-label="Close"
              style={{
                background: "transparent",
                border: "none",
                color: "var(--text-secondary)",
                fontSize: 20,
                cursor: isSaving ? "not-allowed" : "pointer",
                padding: 4,
                lineHeight: 1,
              }}
            >
              ×
            </button>
          </div>

          {result ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <div
                style={{
                  padding: 14,
                  borderRadius: 8,
                  background: "var(--bg-tertiary)",
                  border: "1px solid var(--accent)",
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: 6 }}>✓ Saved</div>
                <code style={{ fontSize: 12, wordBreak: "break-all" }}>{result.file_path}</code>
                <div style={{ marginTop: 10, fontSize: 12, color: "var(--text-secondary)" }}>
                  {result.tool_call_count} Playwright calls emitted
                  {result.click_at_count > 0 && (
                    <>
                      {" · "}
                      {result.click_at_count} pixel-clicks translated to selectors via LLM
                    </>
                  )}
                </div>
                {result.pr_url && (
                  <div style={{ marginTop: 10, fontSize: 12 }}>
                    <strong>Pull request:</strong>{" "}
                    <a href={result.pr_url} target="_blank" rel="noreferrer" style={{ wordBreak: "break-all" }}>
                      {result.pr_url}
                    </a>
                    {result.branch && (
                      <div style={{ color: "var(--text-secondary)", marginTop: 4 }}>
                        Branch: <code>{result.branch}</code>
                        {result.commit_hash && <> · Commit: <code>{result.commit_hash}</code></>}
                      </div>
                    )}
                  </div>
                )}
                {result.pr_error && (
                  <div style={{ marginTop: 10, fontSize: 12, color: "var(--danger, #e05555)" }}>
                    <strong>PR creation failed:</strong> {result.pr_error}
                    <div style={{ marginTop: 4, color: "var(--text-secondary)" }}>
                      The file is saved to disk — commit it manually.
                    </div>
                  </div>
                )}
                <div style={{ marginTop: 10, fontSize: 12, color: "var(--success, #22c55e)" }}>
                  Saved as <strong>.test.ts</strong> and synced with index! The test is now registered and available in the Playwright Library.
                </div>
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={onClose}
                >
                  Done
                </button>
              </div>
            </div>
          ) : (
            <>
              <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>Test name</span>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={isSaving}
                  maxLength={200}
                  autoFocus
                  style={{
                    padding: "8px 12px",
                    borderRadius: 6,
                    border: "1px solid var(--border)",
                    background: "var(--bg-tertiary)",
                    color: "var(--text-primary)",
                    fontSize: 14,
                  }}
                />
              </label>

              <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span style={{ fontSize: 13, fontWeight: 500 }}>Product folder</span>
                <input
                  type="text"
                  value={productOverride}
                  onChange={(e) => setProductOverride(e.target.value)}
                  disabled={isSaving}
                  maxLength={50}
                  placeholder="vpromotions"
                  style={{
                    padding: "8px 12px",
                    borderRadius: 6,
                    border: "1px solid var(--border)",
                    background: "var(--bg-tertiary)",
                    color: "var(--text-primary)",
                    fontSize: 14,
                  }}
                />
              </label>

              <div
                style={{
                  padding: 10,
                  borderRadius: 6,
                  background: "var(--bg-tertiary)",
                  fontSize: 12,
                  color: "var(--text-secondary)",
                }}
              >
                <div>Will save to:</div>
                <code style={{ display: "block", marginTop: 4, wordBreak: "break-all", color: "var(--text-primary)" }}>
                  {filenamePreview}
                </code>
              </div>

              {error && (
                <div
                  style={{
                    padding: 10,
                    borderRadius: 6,
                    background: "rgba(220, 60, 60, 0.15)",
                    border: "1px solid rgba(220, 60, 60, 0.4)",
                    color: "var(--danger, #e05555)",
                    fontSize: 12,
                  }}
                >
                  {error}
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isSaving}
                  className="btn btn-secondary"
                >
                  Skip
                </button>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={!canSave}
                  className="btn btn-primary"
                >
                  {isSaving ? "Saving…" : "Save as test"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
