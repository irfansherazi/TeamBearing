/**
 * vReview — Add Review Rule Panel
 * Form to propose a new checklist rule, then save the rewritten wording.
 */

import { useEffect, useState, type FormEvent } from "react";
import { authenticatedFetch } from "../api_client";
import {
  OTHER_REVIEW_SECTION,
  reviewRuleSectionDiffers,
  reviewRuleWordingLegend,
  type ReviewRuleProposeResponse,
  type ReviewRulesApp,
  type ReviewRuleSection,
} from "../lib/reviewRules";
import { API_BASE_URL } from "../types";

const IDEA_MAX = 500;

interface AddReviewRulePanelProps {
  app: ReviewRulesApp;
  sections: ReviewRuleSection[];
  onSaved: () => void;
}

/**
 * Label for a checklist section, with the code prefix when known.
 *
 * @param section - Checklist section
 * @returns Dropdown label
 */
function sectionOptionLabel(section: ReviewRuleSection): string {
  const prefix = section.rules[0]?.id.split("-")[0];
  return prefix ? `${section.name} (${prefix})` : section.name;
}

/**
 * Propose and save a new AI Review rule for the selected app.
 *
 * @param props - App, section list, and reload callback
 * @returns The add-rule panel
 */
export function AddReviewRulePanel({
  app,
  sections,
  onSaved,
}: AddReviewRulePanelProps) {
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState(sections[0]?.name ?? OTHER_REVIEW_SECTION);
  const [otherSection, setOtherSection] = useState("");
  const [idea, setIdea] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<ReviewRuleProposeResponse | null>(null);
  const [useSuggestedSection, setUseSuggestedSection] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);

  const firstSection = sections[0]?.name ?? OTHER_REVIEW_SECTION;

  useEffect(() => {
    if (sections.length === 0) {
      return;
    }
    setSection((current) => {
      const names = sections.map((item) => item.name);
      if (names.includes(current)) {
        return current;
      }
      return names[0];
    });
  }, [sections]);

  /**
   * Reset the form after a save or when starting over.
   *
   * @returns void
   */
  const resetForm = () => {
    setIdea("");
    setOtherSection("");
    setSection(firstSection);
    setProposal(null);
    setUseSuggestedSection(false);
    setError(null);
  };

  /**
   * Ask the backend to accept, reject, or mark overlap for the idea.
   *
   * @param event - Form submit
   * @returns void
   */
  const handlePropose = (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setProposal(null);
    setSavedId(null);
    authenticatedFetch(`${API_BASE_URL}/ai-review/rules/propose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        app,
        section,
        other_section: otherSection,
        idea,
      }),
    })
      .then((response) =>
        response.json().then((data: ReviewRuleProposeResponse & { detail?: string }) => ({
          ok: response.ok,
          data,
        }))
      )
      .then(({ ok, data }) => {
        if (!ok) {
          const detail = data.detail;
          setError(typeof detail === "string" ? detail : "Could not check this idea.");
          return;
        }
        setProposal(data);
        setUseSuggestedSection(false);
      })
      .catch(() => {
        setError("Could not check this idea right now. Try again.");
      })
      .then(() => {
        setBusy(false);
      });
  };

  /**
   * Save the rewritten rule.
   *
   * @returns void
   */
  const handleSave = () => {
    if (!proposal?.proposal_id) {
      return;
    }
    setBusy(true);
    setError(null);
    authenticatedFetch(`${API_BASE_URL}/ai-review/rules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        proposal_id: proposal.proposal_id,
        choice: 0,
        use_suggested_section: useSuggestedSection,
      }),
    })
      .then((response) =>
        response.json().then((data: { id?: string; detail?: string }) => ({
          ok: response.ok,
          data,
        }))
      )
      .then(({ ok, data }) => {
        if (!ok) {
          const detail = data.detail;
          setError(typeof detail === "string" ? detail : "Could not save this rule.");
          return;
        }
        setSavedId(data.id ?? proposal.assigned_id);
        resetForm();
        setOpen(false);
        onSaved();
      })
      .catch(() => {
        setError("Could not save this rule. Try again.");
      })
      .then(() => {
        setBusy(false);
      });
  };

  /**
   * Clear the form and close the accordion.
   *
   * @returns void
   */
  const handleCancel = () => {
    resetForm();
    setSavedId(null);
    setOpen(false);
  };

  /**
   * Open or close the add-rule accordion.
   *
   * @returns void
   */
  const handleToggle = () => {
    if (open) {
      handleCancel();
      return;
    }
    setOpen(true);
    setSavedId(null);
    setError(null);
    setProposal(null);
  };

  const assignedId = useSuggestedSection
    ? proposal?.suggested_id ?? proposal?.assigned_id ?? ""
    : proposal?.assigned_id ?? "";
  const wordingToSave = proposal?.suggestions?.[0]?.wording ?? "";

  return (
    <div className={`app-card review-rules-add${open ? " is-open" : ""}`} id="review-rules-add">
      <button
        id="review-rules-add-toggle"
        type="button"
        className="review-rules-add-toggle"
        aria-expanded={open}
        onClick={handleToggle}
      >
        <span className="review-rules-add-toggle-copy">
          <h2 className="app-card-title">Add rule</h2>
          <span className="app-card-subtitle">
            Create a new review rule to extend the standards enforced by AI Review.
          </span>
        </span>
        <span className="app-row-chevron" aria-hidden="true">
          ›
        </span>
      </button>

      {savedId ? (
        <p className="review-rules-saved" id="review-rules-saved">
          Saved {savedId}.
        </p>
      ) : null}

      {open ? (
        <form className="review-rules-add-form" onSubmit={handlePropose}>
        <div className="form-group">
          <label htmlFor="review-rules-new-section">Section</label>
          <select
            id="review-rules-new-section"
            className="form-input form-select"
            value={section}
            onChange={(event) => setSection(event.target.value)}
            disabled={busy}
          >
            {sections.map((item) => (
              <option key={item.name} value={item.name}>
                {sectionOptionLabel(item)}
              </option>
            ))}
            <option value={OTHER_REVIEW_SECTION}>Other</option>
          </select>
        </div>
        {section === OTHER_REVIEW_SECTION ? (
          <div className="form-group">
            <label htmlFor="review-rules-other-section">New section name</label>
            <input
              id="review-rules-other-section"
              className="form-input"
              value={otherSection}
              onChange={(event) => setOtherSection(event.target.value)}
              disabled={busy}
              autoComplete="off"
            />
          </div>
        ) : null}
        <div className="form-group">
          <label htmlFor="review-rules-new-idea">Rule description</label>
          <textarea
            id="review-rules-new-idea"
            className="form-input review-rules-idea"
            value={idea}
            onChange={(event) => setIdea(event.target.value.slice(0, IDEA_MAX))}
            disabled={busy}
            rows={4}
            maxLength={IDEA_MAX}
            placeholder="Enter the rule description and expectations. Be specific about what should be checked and why it matters."
          />
          <span className="app-char-count" id="review-rules-idea-count">
            {idea.length}/{IDEA_MAX}
          </span>
        </div>
        {error ? (
          <p className="ai-review-error" id="review-rules-add-error">
            {error}
          </p>
        ) : null}
        {proposal && proposal.verdict === "reject" ? (
          <p className="ai-review-error" id="review-rules-add-reject">
            {proposal.reason}
          </p>
        ) : null}
        {proposal && proposal.verdict === "overlap" ? (
          <p className="review-rules-overlap" id="review-rules-add-overlap">
            Already covered
            {proposal.overlap_ids.length > 0
              ? ` by ${proposal.overlap_ids.join(", ")}`
              : ""}
            . {proposal.reason}
          </p>
        ) : null}
        {proposal && proposal.verdict === "accept" && wordingToSave ? (
          <>
            {reviewRuleSectionDiffers(
              proposal.section,
              proposal.suggested_section
            ) ? (
              <p className="review-rules-section-hint" id="review-rules-section-hint">
                This looks like a {proposal.suggested_section} check, not{" "}
                {proposal.section}.
                <button
                  id="review-rules-use-suggested-section"
                  type="button"
                  className="btn-secondary review-rules-section-hint-btn"
                  onClick={() => setUseSuggestedSection((current) => !current)}
                  disabled={busy}
                >
                  {useSuggestedSection
                    ? `Keep ${proposal.section}`
                    : `Save under ${proposal.suggested_section} instead`}
                </button>
              </p>
            ) : null}
            <div className="review-rules-suggestions" id="review-rules-suggestions">
              <p className="review-rules-suggestion-label" id="review-rules-suggestion-label">
                {reviewRuleWordingLegend(assignedId)}
              </p>
              <p className="review-rules-suggestion-box" id="review-rules-suggestion-box">
                {wordingToSave}
              </p>
            </div>
          </>
        ) : null}
        <div className="review-rules-add-actions">
          {proposal && proposal.verdict === "accept" && wordingToSave ? (
            <button
              id="review-rules-save-btn"
              type="button"
              className="btn-primary"
              onClick={handleSave}
              disabled={busy}
            >
              {busy ? "Saving…" : "Save this rule"}
            </button>
          ) : (
            <button
              id="review-rules-propose-btn"
              type="submit"
              className="btn-primary"
              disabled={busy || idea.trim().length === 0}
            >
              <svg
                className="btn-primary-icon"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                aria-hidden="true"
              >
                <path d="M12 3l7 3v6c0 5-3 8-7 9-4-1-7-4-7-9V6l7-3z" />
              </svg>
              {busy ? "Checking…" : "Check idea"}
            </button>
          )}
          <button
            id="review-rules-cancel-btn"
            type="button"
            className="btn-ghost"
            onClick={handleCancel}
            disabled={busy}
          >
            Cancel
          </button>
        </div>
      </form>
      ) : null}
    </div>
  );
}
