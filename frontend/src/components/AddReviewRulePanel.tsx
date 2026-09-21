/**
 * vReview — Add Review Rule Panel
 * Form to propose a new checklist rule, then save the rewritten wording.
 */

import { useState, type FormEvent } from "react";
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

interface AddReviewRulePanelProps {
  app: ReviewRulesApp;
  sections: ReviewRuleSection[];
  onSaved: () => void;
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
   * Close the form and return to the Add a new rule button.
   *
   * @returns void
   */
  const handleCancel = () => {
    resetForm();
    setSavedId(null);
    setOpen(false);
  };

  const assignedId = useSuggestedSection
    ? proposal?.suggested_id ?? proposal?.assigned_id ?? ""
    : proposal?.assigned_id ?? "";
  const wordingToSave = proposal?.suggestions?.[0]?.wording ?? "";

  return (
    <div className="review-rules-add">
      {!open ? (
        <button
          id="review-rules-add-toggle"
          type="button"
          className="btn-secondary"
          onClick={() => {
            setOpen(true);
            setError(null);
            setProposal(null);
            setSavedId(null);
          }}
        >
          Add a new rule
        </button>
      ) : null}

      {savedId ? (
        <p className="review-rules-saved" id="review-rules-saved">
          Saved {savedId}.
        </p>
      ) : null}

      {open ? (
        <form className="review-rules-add-form" onSubmit={handlePropose}>
          <p className="review-rules-add-help">
            Describe the check in your own words. We assign the code. AI
            will say no, point at an existing rule, suggest a better section
            if the one you picked does not fit, or offer cleaner wording
            to save.
          </p>
          <div className="form-group">
            <label htmlFor="review-rules-new-section">Section</label>
            <select
              id="review-rules-new-section"
              className="form-input"
              value={section}
              onChange={(event) => setSection(event.target.value)}
              disabled={busy}
            >
              {sections.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
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
            <label htmlFor="review-rules-new-idea">What should this rule check?</label>
            <textarea
              id="review-rules-new-idea"
              className="form-input review-rules-idea"
              value={idea}
              onChange={(event) => setIdea(event.target.value)}
              disabled={busy}
              rows={4}
              placeholder="Example: API list rows must drop invalid ids before the UI uses them."
            />
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
                {busy ? "Checking…" : "Check idea"}
              </button>
            )}
            <button
              id="review-rules-cancel-btn"
              type="button"
              className="btn-secondary"
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
