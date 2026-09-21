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
import { AppPage } from "../components/AppPage";
import {
  countReviewRules,
  filterReviewRuleSections,
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
  const [category, setCategory] = useState("all");
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
  const categorySections =
    category === "all"
      ? sections
      : sections.filter((section) => section.name === category);
  const visibleSections = filterReviewRuleSections(categorySections, query);
  const visibleRules = visibleSections.flatMap((section) =>
    section.rules.map((rule) => ({ ...rule, section: section.name }))
  );
  const visibleCount = visibleRules.length;
  const totalCount = countReviewRules(sections);
  const filtersActive = query.trim().length > 0 || category !== "all";

  /**
   * Reset search and category without changing the selected app.
   *
   * @returns void
   */
  const handleClearFilters = () => {
    setQuery("");
    setCategory("all");
  };

  return (
    <AppPage
      title="Review rules"
      subtitle="Define, organize, and maintain the standards used by AI Review."
    >
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

      <div className="app-card review-rules-browse" id="review-rules-browse">
        <div className="app-filters" id="review-rules-filters">
          <span className="app-filters-label">Filters</span>
          <div className="app-filters-fields">
            <div className="form-group app-filters-search">
              <label htmlFor="review-rules-search">Search</label>
              <input
                id="review-rules-search"
                type="search"
                className="form-input"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search rules..."
                autoComplete="off"
              />
            </div>
            <div className="form-group">
              <label htmlFor="review-rules-category">Category</label>
              <select
                id="review-rules-category"
                className="form-input form-select"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
              >
                <option value="all">All</option>
                {sections.map((section) => (
                  <option key={section.name} value={section.name}>
                    {section.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="review-rules-app">App</label>
              <select
                id="review-rules-app"
                className="form-input form-select"
                value={app}
                onChange={(event) => {
                  const nextApp =
                    event.target.value === "vcapi" ? "vcapi" : "platform";
                  setApp(nextApp);
                  setQuery("");
                  setCategory("all");
                }}
              >
                <option value="platform">vsuitePlatform</option>
                <option value="vcapi">vcapi</option>
              </select>
            </div>
            <button
              id="review-rules-clear-filters"
              type="button"
              className="app-filters-clear"
              onClick={handleClearFilters}
              disabled={!filtersActive}
            >
              Clear filters
            </button>
          </div>
        </div>

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
            {filtersActive
              ? `${visibleCount} of ${totalCount} rules`
              : `${totalCount} rules`}
          </p>
        ) : null}

        {visibleRules.length > 0 ? (
          <ul className="app-row-list" role="list" id="review-rules-list">
            {visibleRules.map((rule) => (
              <li key={rule.id}>
                <details className="app-row" id={`review-rule-${rule.id}`}>
                  <summary
                    className="app-row-summary"
                    id={`review-rule-summary-${rule.id}`}
                  >
                    <span className="app-row-id">{rule.id}</span>
                    <span className="app-row-copy">
                      <span className="app-row-title">{rule.plain}</span>
                      <span className="app-row-desc">{rule.rule}</span>
                    </span>
                    <span className="app-row-status">Active</span>
                    <span className="app-row-chevron" aria-hidden="true">
                      ›
                    </span>
                  </summary>
                  <p className="app-row-official">{rule.rule}</p>
                </details>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </AppPage>
  );
}
