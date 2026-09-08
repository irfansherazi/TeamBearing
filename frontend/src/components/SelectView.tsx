/**
 * vQA — SelectView Component
 * ===========================
 * Module: frontend/src/components/SelectView.tsx
 *
 * SELECT mode: The user picks a Jira ticket and configures the test run.
 * Centered card design (max-width: 560px).
 *
 * Featured in Phase 4 of the TASK-065 UI/UX Overhaul.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { CredentialCheckResponse, /* ExecuteRequest, */ ExecutionMode, RoleKey, PlaywrightTest } from "../types";
import { ALL_ROLES, API_BASE_URL, ROLE_DISPLAY_NAMES } from "../types";
import { authenticatedFetch } from "../api_client";
import { CredentialPrompt } from "./CredentialPrompt";
import { useProductContext } from "../context/ProductContext";

interface JiraTicketSummary {
  id: string;
  summary: string;
  status: string;
  priority: string;
  issue_type: string;
}

interface SelectViewProps {
  onTicketSelected: (ticket: JiraTicketSummary, config: { role: RoleKey, targetUrl: string, expectLoginFailure: boolean, useCustomCreds: boolean, customEmail?: string, customPassword?: string, preParseGuidance: string }) => void;
  onStaticTestSelected: (ticket: JiraTicketSummary, test: PlaywrightTest, config: { role: RoleKey, targetUrl: string, expectLoginFailure: boolean, useCustomCreds: boolean, customEmail?: string, customPassword?: string, preParseGuidance: string }) => void;
  isLoading: boolean;
  onCheckCredentials: (ticketId: string) => Promise<CredentialCheckResponse | null>;
}

const STATUS_COLORS: Record<string, string> = {
  "In Progress": "#0052cc",
  "To Do": "#6b778c",
  "Done": "#36b37e",
  "In Review": "#ff8b00",
  "Blocked": "#de350b",
  "Testing": "#6554c0",
};

/*
const PRIORITY_ICONS: Record<string, string> = {
  "Highest": "🔴",
  "High": "🟠",
  "Medium": "🟡",
  "Low": "🔵",
  "Lowest": "⚪",
};
*/

const getTestDisplayName = (test: PlaywrightTest): string => {
  if (test.display_name) return test.display_name;
  const filename = test.file.split("/").pop() || "";
  const baseName = filename.replace(/\.(test|spec)?\.(ts|js)$/, "").replace(/\.(test|spec|ts|js)$/, "");
  return baseName
    .replace(/[-_]/g, " ")
    .split(" ")
    .map((word) => {
      if (word.toLowerCase() === "qa") return "QA";
      return word.charAt(0).toUpperCase() + word.slice(1);
    })
    .join(" ");
};

export function SelectView({ onTicketSelected, onStaticTestSelected, onCheckCredentials }: SelectViewProps) {
  // Product context — drives ticket board filtering and role dropdown scoping
  const {
    activeSlug: productSlug,
    activeProduct,
    cancelTicketFetch,
  } = useProductContext();

  // Ticket selector state
  const [tickets, setTickets] = useState<JiraTicketSummary[]>([]);
  const [ticketsLoading, setTicketsLoading] = useState(true);
  const [ticketsError, setTicketsError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [selectedTicket, setSelectedTicket] = useState<JiraTicketSummary | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // AbortController ref for in-flight /tickets requests (AC-ASYNC-1)
  const ticketFetchAbortRef = useRef<AbortController | null>(null);

  // Playwright static match state
  const [playwrightMatch, setPlaywrightMatch] = useState<{ matched: boolean; tests: PlaywrightTest[] } | null>(null);
  const [selectedTestId, setSelectedTestId] = useState<string>("");

  // Form state — persisted in localStorage so selections survive navigation
  const [role, setRole] = useState<RoleKey>(() => {
    return (localStorage.getItem('vqa_role') as RoleKey) || "account_executive";
  });
  const [mode, setMode] = useState<ExecutionMode>("interactive");
  const [targetUrl, setTargetUrl] = useState<string>(() => {
    return localStorage.getItem('vqa_targetUrl') || "";
  });
  const [expectLoginFailure, setExpectLoginFailure] = useState(false);
  const [preParseGuidance, setPreParseGuidance] = useState("");
  const [useCustomCreds, setUseCustomCreds] = useState(false);
  const [customEmail, setCustomEmail] = useState("");
  const [customPassword, setCustomPassword] = useState("");

  // Credential state
  const [credCheck, setCredCheck] = useState<CredentialCheckResponse | null>(null);
  const [credCheckLoading, setCredCheckLoading] = useState(false);
  const [missingFieldValue, setMissingFieldValue] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load tickets when the active product changes (AC-HAPPY-1, AC-ASYNC-1)
  useEffect(() => {
    // Cancel any in-flight fetch from a previous product (AC-ASYNC-1)
    if (ticketFetchAbortRef.current) {
      ticketFetchAbortRef.current.abort();
    }
    const abortController = new AbortController();
    ticketFetchAbortRef.current = abortController;

    // Register the cancel function with ProductContext so ProductSelector can
    // trigger cancellation on product switch via cancelTicketFetch()
    cancelTicketFetch();

    setTicketsLoading(true);
    setTicketsError(null);
    setSelectedTicket(null);
    setSearchQuery("");

    const url = `${API_BASE_URL}/tickets?product=${encodeURIComponent(productSlug)}`;
    authenticatedFetch(url)
      .then(async (r) => {
        if (abortController.signal.aborted) return;
        if (!r.ok) {
          const errorData = await r.json().catch(() => ({ detail: "Unknown error" }));
          throw new Error(errorData.detail || `Server error: ${r.status}`);
        }
        return r.json();
      })
      .then((data: JiraTicketSummary[]) => {
        if (abortController.signal.aborted) return;
        setTickets(data ?? []);
        setTicketsLoading(false);
      })
      .catch((err) => {
        if (abortController.signal.aborted) return;
        setTicketsError(err instanceof Error ? err.message : "Could not load board tickets");
        setTicketsLoading(false);
      });

    return () => {
      abortController.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productSlug]);

  // Sync targetUrl to active product's default environment (Phase 4: AC-HAPPY-3)
  useEffect(() => {
    if (!activeProduct) return;
    const stored = localStorage.getItem('vqa_targetUrl');
    const productUrls = Object.values(activeProduct.environments);
    if (!stored || !productUrls.includes(stored)) {
      const defaultUrl = activeProduct.environments[activeProduct.default_environment] ?? productUrls[0] ?? "";
      setTargetUrl(defaultUrl);
    }
  }, [activeProduct]);

  // Reset role to the first valid role for the active product when the product changes.
  // Prevents stale localStorage role (e.g. "account_executive") from being sent
  // with a product that doesn't support it (e.g. "vpromotions" → 400).
  useEffect(() => {
    if (!activeProduct) return;
    const productRoles = activeProduct.roles ?? [];
    if (productRoles.length > 0 && !productRoles.includes(role)) {
      const firstRole = productRoles[0] as RoleKey;
      setRole(firstRole);
      localStorage.setItem('vqa_role', firstRole);
    }
  }, [activeProduct, role]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const runCredCheck = useCallback(
    (ticketId: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      setCredCheck(null);
      setMissingFieldValue("");
      if (ticketId.length >= 3) {
        setCredCheckLoading(true);
        debounceRef.current = setTimeout(async () => {
          const result = await onCheckCredentials(ticketId);
          setCredCheck(result);
          setCredCheckLoading(false);
        }, 500);
      }
    },
    [onCheckCredentials],
  );

  const handleSelectTicket = async (ticket: JiraTicketSummary) => {
    setSelectedTicket(ticket);
    setSearchQuery("");
    setIsDropdownOpen(false);
    runCredCheck(ticket.id);

    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/playwright/match/${ticket.id}?product=${encodeURIComponent(productSlug)}`);
      if (!response.ok) {
        throw new Error(`Error fetching match: ${response.status}`);
      }
      const data: { matched: boolean; tests: PlaywrightTest[] } = await response.json();
      if (data.matched && data.tests.length > 0) {
        setPlaywrightMatch(data);
        setSelectedTestId(data.tests[0].id);
      } else {
        // No match: proceed directly to AI Review mode (existing flow)
        onTicketSelected(ticket, {
          role,
          targetUrl,
          expectLoginFailure,
          useCustomCreds,
          customEmail: useCustomCreds ? customEmail : undefined,
          customPassword: useCustomCreds ? customPassword : undefined,
          preParseGuidance
        });
      }
    } catch (err) {
      console.error("Playwright match check failed, falling back to AI flow:", err);
      // Fallback gracefully on network error or any failure
      onTicketSelected(ticket, {
        role,
        targetUrl,
        expectLoginFailure,
        useCustomCreds,
        customEmail: useCustomCreds ? customEmail : undefined,
        customPassword: useCustomCreds ? customPassword : undefined,
        preParseGuidance
      });
    }
  };

  const handleClearTicket = () => {
    setSelectedTicket(null);
    setSearchQuery("");
    setCredCheck(null);
    setMissingFieldValue("");
    setPlaywrightMatch(null);
    setSelectedTestId("");
    setTimeout(() => searchRef.current?.focus(), 50);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
  };

  // AC-HAPPY-2: Filter roles to those belonging to the active product.
  // Falls back to ALL_ROLES when the product has no roles configured (stub products).
  const availableRoles = (activeProduct?.roles?.length ?? 0) > 0
    ? ALL_ROLES.filter((r) => activeProduct!.roles.includes(r))
    : ALL_ROLES;

  const filteredTickets = Array.isArray(tickets) ? (searchQuery.trim()
    ? tickets.filter(
        (t) =>
          t.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
          t.summary.toLowerCase().includes(searchQuery.toLowerCase()),
      )
    : tickets) : [];

  const isPartial = credCheck?.status === "partial";
  const missingField = isPartial ? (credCheck?.email_found ? "password" : "email") : null;
  // const partialBlocked = isPartial && !missingFieldValue.trim();
  // const customCredsBlocked = useCustomCreds && (!customEmail.trim() || !customPassword.trim());
  // const isDisabled = isLoading || !selectedTicket;

  const renderCredBadge = () => {
    if (credCheckLoading) return <span className="cred-badge cred-checking">🔍 Checking...</span>;
    if (!credCheck || credCheck.status === "none") return <span className="cred-badge cred-none">ℹ️ Role creds</span>;
    if (credCheck.status === "complete") return <span className="cred-badge cred-complete">✅ In ticket</span>;
    if (credCheck.status === "partial") return <span className="cred-badge cred-partial">⚠️ Partial</span>;
    return null;
  };

  return (
    <div className="select-view-container">
      <div className="panel select-card">
        <div className="panel-header">
          <h2>Start a New Test</h2>
          <span className="panel-badge">SELECT MODE</span>
        </div>

        <form onSubmit={handleSubmit} className="execution-form">
          {/* Test As + Environment Grid */}
          <div className="form-grid-2">
            <div className="form-group">
              <label htmlFor="role-select">Test As</label>
              <select
                id="role-select"
                value={role}
                onChange={(e) => {
                  const r = e.target.value as RoleKey;
                  setRole(r);
                  localStorage.setItem('vqa_role', r);
                }}
                className="form-select"
                disabled={credCheck?.status === "complete" || useCustomCreds}
              >
                {availableRoles.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_DISPLAY_NAMES[r]}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label htmlFor="env-select">Environment</label>
              <select
                id="env-select"
                value={targetUrl}
                onChange={(e) => {
                  setTargetUrl(e.target.value);
                  localStorage.setItem('vqa_targetUrl', e.target.value);
                }}
                className="form-select"
              >
                {activeProduct && Object.keys(activeProduct.environments).length > 0
                  ? Object.entries(activeProduct.environments).map(([envName, url]) => (
                      <option key={url} value={url}>
                        {envName.charAt(0).toUpperCase() + envName.slice(1)} — {url}
                      </option>
                    ))
                  : (
                    <option value={targetUrl || ""}>
                      {targetUrl || "Loading environments…"}
                    </option>
                  )
                }
              </select>
            </div>
          </div>

          {/* Ticket Search */}
          <div className="form-group">
            <label htmlFor="ticket-search">Jira Ticket</label>
            <div className="ticket-combobox" ref={dropdownRef}>
              {selectedTicket ? (
                <div className="ticket-selected-chip">
                  <span className="chip-id">{selectedTicket.id}</span>
                  <span className="chip-summary">{selectedTicket.summary}</span>
                  <button
                    type="button"
                    className="chip-clear"
                    onClick={handleClearTicket}
                    aria-label="Clear selection"
                  >
                    ✕
                  </button>
                  {renderCredBadge()}
                </div>
              ) : (
                <div className="ticket-search-wrapper">
                  <span className="ticket-search-icon">🔍</span>
                  <input
                    id="ticket-search"
                    ref={searchRef}
                    type="text"
                    placeholder={ticketsLoading ? "Loading tickets…" : "Search by ticket ID or title…"}
                    value={searchQuery}
                    onChange={(e) => {
                      setSearchQuery(e.target.value);
                      setIsDropdownOpen(true);
                    }}
                    onFocus={() => setIsDropdownOpen(true)}
                    className="form-input ticket-search-input"
                    autoComplete="off"
                    autoFocus
                  />
                  {ticketsLoading && <span className="ticket-search-spinner" />}
                </div>
              )}

              {isDropdownOpen && !selectedTicket && (
                <div className="ticket-dropdown">
                  {ticketsError ? (
                    <div className="ticket-dropdown-error">{ticketsError}</div>
                  ) : filteredTickets.length === 0 ? (
                    <div className="ticket-dropdown-empty">
                      {searchQuery ? `No matches for "${searchQuery}"` : "No open tickets found"}
                    </div>
                  ) : (
                    <ul className="ticket-list">
                      {filteredTickets.map((ticket) => (
                        <li key={ticket.id} className="ticket-list-item" onClick={() => handleSelectTicket(ticket)}>
                          <div className="ticket-list-row">
                            <span className="ticket-list-id">{ticket.id}</span>
                            <span className="ticket-list-status" style={{ color: STATUS_COLORS[ticket.status] }}>
                              {ticket.status}
                            </span>
                          </div>
                          <div className="ticket-list-summary">{ticket.summary}</div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </div>

          {playwrightMatch && playwrightMatch.matched && selectedTicket && (
            <div className="playwright-match-banner" data-testid="playwright-match-banner">
              <div className="playwright-match-title">
                <span>🎭</span>
                <span>Static Playwright test found for {selectedTicket.id}</span>
              </div>
              <div className="playwright-match-body">
                {playwrightMatch.tests.length === 1 ? (
                  <div className="playwright-match-details">
                    <span className="playwright-match-test-name">{getTestDisplayName(playwrightMatch.tests[0])}</span>
                    <span className="playwright-match-test-desc">{playwrightMatch.tests[0].description}</span>
                    <span className="playwright-match-test-steps">
                      Steps ({playwrightMatch.tests[0].steps_count}): {playwrightMatch.tests[0].step_names.join(" → ")}
                    </span>
                  </div>
                ) : (
                  <div className="playwright-match-details">
                    <p style={{ margin: "0 0 var(--space-sm) 0" }}>Multiple tests matched. Select one to run:</p>
                    <ul className="playwright-match-test-list">
                      {playwrightMatch.tests.map((test) => (
                        <li
                          key={test.id}
                          className={`playwright-match-test-item ${selectedTestId === test.id ? "selected" : ""}`}
                          onClick={() => setSelectedTestId(test.id)}
                        >
                          <input
                            type="radio"
                            name="playwright-test-select"
                            className="playwright-match-radio"
                            checked={selectedTestId === test.id}
                            onChange={() => setSelectedTestId(test.id)}
                          />
                          <div className="playwright-match-details">
                            <span className="playwright-match-test-name">{getTestDisplayName(test)}</span>
                            <span className="playwright-match-test-desc">{test.description}</span>
                            <span className="playwright-match-test-steps">
                              Steps ({test.steps_count}): {test.step_names.join(" → ")}
                            </span>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                <div className="playwright-match-actions">
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => {
                      const selectedTest = playwrightMatch.tests.find(t => t.id === selectedTestId) || playwrightMatch.tests[0];
                      onStaticTestSelected(selectedTicket, selectedTest, {
                        role,
                        targetUrl,
                        expectLoginFailure,
                        useCustomCreds,
                        customEmail: useCustomCreds ? customEmail : undefined,
                        customPassword: useCustomCreds ? customPassword : undefined,
                        preParseGuidance
                      });
                    }}
                  >
                    Run Playwright Test
                  </button>
                  <button
                    type="button"
                    className="btn-secondary-link"
                    onClick={() => {
                      onTicketSelected(selectedTicket, {
                        role,
                        targetUrl,
                        expectLoginFailure,
                        useCustomCreds,
                        customEmail: useCustomCreds ? customEmail : undefined,
                        customPassword: useCustomCreds ? customPassword : undefined,
                        preParseGuidance
                      });
                    }}
                  >
                    Use AI Agent Instead
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Partial Credential Prompt */}
          {isPartial && missingField && (
            <CredentialPrompt
              missingField={missingField}
              foundEmail={credCheck?.email ?? ""}
              value={missingFieldValue}
              onChange={setMissingFieldValue}
            />
          )}

          {/* Advanced Settings Accordion */}
          <details className="advanced-settings">
            <summary>Advanced Settings</summary>
            <div className="advanced-content">
              {/* Custom Credentials */}
              <div className="form-group">
                <label className="custom-creds-toggle-label">
                  <input
                    type="checkbox"
                    checked={useCustomCreds}
                    onChange={(e) => setUseCustomCreds(e.target.checked)}
                  />
                  Use Custom Credentials
                </label>
                {useCustomCreds && (
                  <div className="custom-creds-fields">
                    <input
                      type="email"
                      placeholder="Email"
                      value={customEmail}
                      onChange={(e) => setCustomEmail(e.target.value)}
                      className="form-input"
                    />
                    <input
                      type="password"
                      placeholder="Password"
                      value={customPassword}
                      onChange={(e) => setCustomPassword(e.target.value)}
                      className="form-input"
                    />
                  </div>
                )}
              </div>

              {/* Run Mode */}
              <div className="form-group">
                <label>Run Mode</label>
                <div className="mode-toggle">
                  <button
                    type="button"
                    className={`mode-btn ${mode === "interactive" ? "active" : ""}`}
                    onClick={() => setMode("interactive")}
                  >
                    Live View
                  </button>
                  <button
                    type="button"
                    className={`mode-btn ${mode === "headless" ? "active" : ""}`}
                    onClick={() => setMode("headless")}
                  >
                    Fast Mode
                  </button>
                </div>
              </div>

              {/* Failed Login Testing */}
              <div className="form-group">
                <label className="failed-login-toggle-label">
                  <input
                    type="checkbox"
                    checked={expectLoginFailure}
                    onChange={(e) => setExpectLoginFailure(e.target.checked)}
                  />
                  Failed Login Testing
                </label>
              </div>

              {/* Guidance Textarea */}
              <div className="form-group">
                <label htmlFor="guidance">Notes for the Agent</label>
                <textarea
                  id="guidance"
                  className="guidance-textarea"
                  value={preParseGuidance}
                  onChange={(e) => setPreParseGuidance(e.target.value)}
                  placeholder="UI quirks, specific data to use, etc."
                  rows={3}
                />
              </div>
            </div>
          </details>

          <div className="form-hint select-footer-hint">
            Picking a ticket will automatically parse its acceptance criteria.
          </div>
        </form>
      </div>
    </div>
  );
}
