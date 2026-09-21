/**
 * vReview — Review Rules Page
 * ===========================
 * Module: frontend/src/pages/ReviewRulesPage.tsx
 *
 * Lists every AI Review checklist code (CQ-01, F-01, …) with a plain
 * explanation of what is checked on a PR.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { authenticatedFetch } from "../api_client";
import { AddReviewRulePanel } from "../components/AddReviewRulePanel";
import {
  countReviewRules,
  filterReviewRuleSections,
  reviewRuleSectionId,
  type ReviewRulesApp,
  type ReviewRulesPayload,
  type ReviewRuleSection,
} from "../lib/reviewRules";
import { API_BASE_URL } from "../types";

/**
 * Browse the AI Review checklist codes for vsuitePlatform or vcapi.
 *
 * @returns The Review rules page
 */
export function ReviewRulesPage() {
  const [app, setApp] = useState<ReviewRulesApp>("platform");
  const [query, setQuery] = useState("");
  const [payload, setPayload] = useState<ReviewRulesPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const destroyedRef = useRef(false);
  const requestIdRef = useRef(0);

  /**
   * Load checklist codes for the selected app. No-ops after unmount
   * or if a newer request has started.
   *
   * @param nextApp - platform or vcapi
   * @returns void
   */
  const loadRules = useCallback((nextApp: ReviewRulesApp) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setLoadError(null);
    setPayload(null);
    authenticatedFetch(`${API_BASE_URL}/ai-review/rules?app=${nextApp}`)
      .then((response) => {
        if (destroyedRef.current || requestIdRef.current !== requestId) {
          return null;
        }
        if (!response.ok) {
          throw new Error("Could not load review rules");
        }
        return response.json() as Promise<ReviewRulesPayload>;
      })
      .then((data) => {
        if (destroyedRef.current || requestIdRef.current !== requestId || data === null) {
          return;
        }
        setPayload(data);
      })
      .catch(() => {
        if (destroyedRef.current || requestIdRef.current !== requestId) {
          return;
        }
        setPayload(null);
        setLoadError("Could not load review rules. Try again.");
      });
  }, []);

  useEffect(() => {
    destroyedRef.current = false;
    return () => {
      destroyedRef.current = true;
    };
  }, []);

  useEffect(() => {
    loadRules(app);
  }, [app, loadRules]);

  const sections: ReviewRuleSection[] = payload?.sections ?? [];
  const visibleSections = filterReviewRuleSections(sections, query);
  const visibleCount = countReviewRules(visibleSections);
  const totalCount = countReviewRules(sections);

  return (
    <div className="review-rules-page">
      <div className="panel select-card review-rules-card">
        <div className="panel-header">
          <h2>Review rules</h2>
          <span className="panel-badge">AI REVIEW</span>
        </div>

        <p className="review-rules-intro">
          These are the codes AI Review scores on every PR. Each code is a
          check — CQ-01 is conventions, CQ-02 is leftover commented code, and
          so on. Open a code to read the exact rule.
        </p>

        <div className="review-rules-toolbar">
          <div className="form-group">
            <label htmlFor="review-rules-app">App</label>
            <select
              id="review-rules-app"
              className="form-input"
              value={app}
              onChange={(event) => {
                const nextApp =
                  event.target.value === "vcapi" ? "vcapi" : "platform";
                setApp(nextApp);
                setQuery("");
              }}
            >
              <option value="platform">vsuitePlatform</option>
              <option value="vcapi">vcapi</option>
            </select>
          </div>
          <div className="form-group">
            <label htmlFor="review-rules-search">Search</label>
            <input
              id="review-rules-search"
              type="search"
              className="form-input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="CQ-01, translation, timers…"
              autoComplete="off"
            />
          </div>
        </div>

        <AddReviewRulePanel
          key={app}
          app={app}
          sections={sections}
          onSaved={() => loadRules(app)}
        />

        {loadError ? (
          <p className="ai-review-error" id="review-rules-error">
            {loadError}
          </p>
        ) : null}

        {!loadError && payload === null ? (
          <p className="review-rules-empty" id="review-rules-loading">
            Loading review rules…
          </p>
        ) : null}

        {payload && visibleCount === 0 ? (
          <p className="review-rules-empty" id="review-rules-empty">
            No rules match that search.
          </p>
        ) : null}

        {payload && visibleCount > 0 ? (
          <p className="review-rules-count" id="review-rules-count">
            {query.trim()
              ? `${visibleCount} of ${totalCount} rules`
              : `${totalCount} rules`}
          </p>
        ) : null}

        {visibleSections.map((section) => (
          <section
            key={section.name}
            className="review-rules-section"
            aria-labelledby={`review-rules-section-${reviewRuleSectionId(section.name)}`}
          >
            <h3
              className="review-rules-section-title"
              id={`review-rules-section-${reviewRuleSectionId(section.name)}`}
            >
              {section.name}
            </h3>
            <ul className="review-rules-list" role="list">
              {section.rules.map((rule) => (
                <li key={rule.id}>
                  <details
                    className="review-rule-card"
                    id={`review-rule-${rule.id}`}
                  >
                    <summary
                      className="review-rule-summary"
                      id={`review-rule-summary-${rule.id}`}
                    >
                      <span className="review-rule-id">{rule.id}</span>
                      <span className="review-rule-plain">{rule.plain}</span>
                    </summary>
                    <p className="review-rule-official">{rule.rule}</p>
                  </details>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
