import { useEffect, useRef, useState } from "react";

export interface ClarificationWizardModalProps {
  detectedPaths: string[];
  ambiguities: string[];
  onConfirm: (selectedPaths: string[], resolutions: Record<string, string>) => void;
  onSkip: () => void;
}

export function ClarificationWizardModal({
  detectedPaths,
  ambiguities,
  onConfirm,
  onSkip,
}: ClarificationWizardModalProps) {
  const [checkedPaths, setCheckedPaths] = useState<Set<string>>(
    () => new Set(detectedPaths)
  );
  const [resolutions, setResolutions] = useState<Record<string, string>>(
    () => Object.fromEntries(ambiguities.map((a) => [a, ""]))
  );

  const containerRef = useRef<HTMLDivElement>(null);

  // Focus trap: keep Tab/Shift+Tab within the modal
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const focusable = el.querySelectorAll<HTMLElement>(
      'button, input, textarea, [tabindex]:not([tabindex="-1"])'
    );
    if (focusable.length > 0) focusable[0].focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onSkip();
        return;
      }
      if (e.key !== "Tab") return;
      const list = Array.from(
        el.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
        )
      );
      if (list.length === 0) return;
      const first = list[0];
      const last = list[list.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    el.addEventListener("keydown", handleKeyDown);
    return () => el.removeEventListener("keydown", handleKeyDown);
  }, [onSkip]);

  const includedCount = checkedPaths.size;
  const totalCount = detectedPaths.length;
  const allUnchecked = includedCount === 0;

  const togglePath = (path: string) => {
    setCheckedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  const handleConfirm = () => {
    if (allUnchecked) return;
    onConfirm(Array.from(checkedPaths), resolutions);
  };

  return (
    <div className="wizard-overlay">
      <div
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="wizard-title"
        className="wizard-modal"
      >
        {/* Header */}
        <div className="wizard-header">
          <span id="wizard-title" className="wizard-title">
            Review Navigation Paths
          </span>
          {totalCount > 0 && (
            <span className="wizard-path-badge">
              {includedCount} of {totalCount} path{totalCount !== 1 ? "s" : ""}
            </span>
          )}
        </div>

        {/* Body */}
        <div className="wizard-body">
          {detectedPaths.length > 0 && (
            <>
              <p className="wizard-body-label">
                Select the paths to include in this test run:
              </p>
              <ul className="wizard-path-list">
                {detectedPaths.map((path) => {
                  const checked = checkedPaths.has(path);
                  return (
                    <li
                      key={path}
                      className={`wizard-path-row${!checked ? " wizard-path-row--excluded" : ""}`}
                    >
                      <label className="wizard-path-label">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => togglePath(path)}
                          className="wizard-path-checkbox"
                        />
                        <span className="wizard-path-text">{path}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
              {allUnchecked && (
                <span role="alert" className="wizard-validation-msg">
                  Select at least one path to continue.
                </span>
              )}
            </>
          )}

          {ambiguities.length > 0 && (
            <div className="wizard-ambiguity-section">
              <hr className="wizard-divider" />
              <p className="wizard-body-label">Clarify Ambiguous Terms</p>
              {ambiguities.map((term) => (
                <div key={term} className="wizard-ambiguity-row">
                  <label className="wizard-ambiguity-term">{term}</label>
                  <input
                    type="text"
                    className="wizard-ambiguity-input"
                    placeholder="Optional clarification…"
                    maxLength={300}
                    value={resolutions[term] ?? ""}
                    onChange={(e) =>
                      setResolutions((prev) => ({
                        ...prev,
                        [term]: e.target.value,
                      }))
                    }
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="wizard-footer">
          {/* "Skip" means: use unmodified steps from the initial preview; no re-fetch */}
          <button type="button" className="btn-secondary" onClick={onSkip}>
            Skip — use all paths
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={allUnchecked}
            onClick={handleConfirm}
          >
            Confirm Selection
          </button>
        </div>
      </div>
    </div>
  );
}
