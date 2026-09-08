/**
 * vQA — Playwright Dashboard Page
 * =================================
 * Module: frontend/src/pages/PlaywrightPage.tsx
 *
 * Full-page Playwright Standard Library dashboard with:
 *   - Test library browser (40+ tests from playwright_index.json)
 *   - Execution config panel (env × user × browser)
 *   - Real-time terminal log streaming via WebSocket
 *   - Storage state status matrix (13×4 with regeneration)
 *
 * FEAT-052 / TASK-060 — AC-FE-1 through AC-FE-9
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { authenticatedFetch } from "../api_client";
import { getTestDisplayName } from "../lib/testFormatting";
import { useProductContext } from "../context/ProductContext";
import { SuiteResultsPanel } from "../components/SuiteResultsPanel";
import { RecordDemoModal } from "../components/RecordDemoModal";
import { RecordDemoTicketPickerModal } from "../components/RecordDemoTicketPickerModal";
import { authStorage } from "../auth/authStorage";
import {
  API_BASE_URL,
  WS_BASE_URL,
  type PlaywrightTest,
  type PlaywrightRunRequest,
  type PlaywrightRunResponse,
  type PlaywrightStorageStatusResponse,
  type PlaywrightStorageGenerateStatusResponse,
  type StorageStateStatus,
  type PlaywrightGroupRunRequest,
  type PlaywrightSuiteRunRequest,
  type PlaywrightSuiteRunResponse,
  type PlaywrightSuiteReportResponse,
} from "../types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ENVS = ["prod", "test", "smoke", "qa"] as const;
type Env = typeof ENVS[number];

const BROWSERS = ["chromium", "firefox", "webkit"] as const;
type Browser = typeof BROWSERS[number];

// All demo users across products — value is the storage-state username,
// label is the human-readable name shown in dropdowns.
const USERS: { value: string; label: string }[] = [
  { value: "Admin", label: "Admin" },
  { value: "DemoProdDirector", label: "Demo Prod Director" },
  { value: "DemoTrafficDirector", label: "Demo Traffic Director" },
  { value: "DemoSalesExec", label: "Demo Sales Exec" },
  { value: "DemoProdMan", label: "Demo Prod Man" },
  { value: "DemoProdWoman", label: "Demo Prod Woman" },
  { value: "DemoDigitalDir", label: "Demo Digital Dir" },
  { value: "DemoDigitalProd", label: "Demo Digital Prod" },
  { value: "DemoVoicer", label: "Demo Voicer" },
  { value: "DemoGM", label: "Demo GM" },
  { value: "DemoGraphicArtist", label: "Demo Graphic Artist" },
  { value: "writer", label: "Writer" },
  { value: "DemoTrafficAssnt", label: "Demo Traffic Assnt" },

  // vPPO users
  { value: "vppo_account_executive", label: "vPPO Account Executive" },
  { value: "vppo_digital_director", label: "vPPO Digital Director" },
  { value: "vppo_dubber", label: "vPPO Dubber" },
  { value: "vppo_gm_gsm", label: "vPPO GM / GSM" },
  { value: "vppo_producer", label: "vPPO Producer" },
  { value: "vppo_production_manager", label: "vPPO Production Manager" },
  { value: "vppo_sales_assistant", label: "vPPO Sales Assistant" },
  { value: "vppo_sales_manager", label: "vPPO Sales Manager" },
  { value: "vppo_traffic_manager", label: "vPPO Traffic Manager" },
  { value: "vppo_voicer", label: "vPPO Voicer" },
  { value: "vppo_writer", label: "vPPO Writer" },
  { value: "SalesExec", label: "vPPO Sales Exec" },
  { value: "DigitalDir", label: "vPPO Digital Dir" },
  { value: "PMJock", label: "vPPO PM Jock (Dubber)" },
  { value: "GenMan", label: "vPPO Gen Man" },
  { value: "OtherProd", label: "vPPO Other Prod" },
  { value: "ProductionDir", label: "vPPO Production Dir" },
  { value: "SalesAssistant", label: "vPPO Sales Assistant" },
  { value: "SalesManager", label: "vPPO Sales Manager" },
  { value: "TrafficDir", label: "vPPO Traffic Dir" },
  { value: "Voicing", label: "vPPO Voicing" },
  { value: "CopyWriter", label: "vPPO CopyWriter" },
];

const STATUS_COLORS: Record<StorageStateStatus, string> = {
  valid: "var(--success)",
  expired: "var(--warning, #f59e0b)",
  missing: "var(--error)",
};

const STATUS_ICONS: Record<StorageStateStatus, string> = {
  valid: "✓",
  expired: "⚠",
  missing: "✗",
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Search/filter header for the test library */
function TestSearchBar({
  query,
  onChange,
  totalCount,
}: {
  query: string;
  onChange: (q: string) => void;
  totalCount: number;
}) {
  return (
    <div className="pw-search-bar">
      <div className="pw-search-input-wrap">
        <span className="pw-search-icon">🔍</span>
        <input
          id="pw-test-search"
          type="text"
          className="pw-search-input"
          placeholder="Filter by ID, Jira key, or description…"
          value={query}
          onChange={(e) => onChange(e.target.value)}
        />
        {query && (
          <button
            className="pw-search-clear"
            onClick={() => onChange("")}
            title="Clear search"
          >
            ×
          </button>
        )}
      </div>
      <span className="pw-test-count">{totalCount} tests</span>
    </div>
  );
}

/** Individual test card in the library */
function TestCard({
  test,
  selected,
  inGroup,
  onSelect,
  onToggleGroup,
  disabled,
}: {
  test: PlaywrightTest;
  selected: boolean;
  inGroup: boolean;
  onSelect: (id: string) => void;
  onToggleGroup: (id: string) => void;
  disabled: boolean;
}) {
  return (
    <div
      className={`pw-test-card ${selected ? "selected" : ""} ${inGroup ? "in-group" : ""} ${disabled ? "disabled" : ""}`}
      onClick={() => !disabled && onSelect(test.id)}
      role="button"
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !disabled) {
          onSelect(test.id);
        }
      }}
      aria-selected={selected}
      aria-disabled={disabled}
    >
      <div className="pw-card-header">
        <span className="pw-card-icon">🎭</span>
        <div className="pw-card-meta">
          <div className="pw-card-title">{getTestDisplayName(test)}</div>
          <div className="pw-card-id" style={{ marginTop: "2px", fontSize: "0.7rem", color: "var(--text-secondary)" }}>{test.id}</div>
          {test.jira_keys.length > 0 && (
            <div className="pw-card-jira">
              {test.jira_keys.map((k) => (
                <span key={k} className="pw-jira-badge">{k}</span>
              ))}
            </div>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          {selected && <span className="pw-card-check">✓</span>}
          <input
            type="checkbox"
            checked={inGroup}
            disabled={disabled}
            title="Add to group run"
            style={{ width: "1rem", height: "1rem", cursor: disabled ? "not-allowed" : "pointer", accentColor: "var(--primary-alt, #4f46e5)" }}
            onClick={(e) => e.stopPropagation()}
            onChange={() => !disabled && onToggleGroup(test.id)}
          />
        </div>
      </div>
      <div className="pw-card-description">{test.description}</div>
      {test.steps_count > 0 && (
        <div className="pw-card-steps">
          <span className="pw-steps-count">{test.steps_count} step{test.steps_count !== 1 ? "s" : ""}</span>
          <span className="pw-steps-preview">
            {test.step_names.slice(0, 2).join(" → ")}
            {test.step_names.length > 2 ? " →…" : ""}
          </span>
        </div>
      )}
    </div>
  );
}

/** Config sidebar: env, user, browser */
function RunConfigPanel({
  env,
  user,
  browser,
  onEnvChange,
  onUserChange,
  onBrowserChange,
  disabled,
}: {
  env: Env;
  user: string;
  browser: Browser;
  onEnvChange: (e: Env) => void;
  onUserChange: (u: string) => void;
  onBrowserChange: (b: Browser) => void;
  disabled: boolean;
}) {
  return (
    <div className="pw-config-panel">
      <h3 className="pw-config-title">⚙ Run Configuration</h3>

      <div className="pw-config-field">
        <label htmlFor="pw-env" className="pw-label">Environment</label>
        <div className="pw-button-group">
          {ENVS.map((e) => (
            <button
              key={e}
              id={`pw-env-${e}`}
              className={`pw-pill ${env === e ? "active" : ""}`}
              onClick={() => onEnvChange(e)}
              disabled={disabled}
            >
              {e}
            </button>
          ))}
        </div>
      </div>

      <div className="pw-config-field">
        <label htmlFor="pw-user" className="pw-label">User</label>
        <select
          id="pw-user"
          className="pw-select"
          value={user}
          onChange={(e) => onUserChange(e.target.value)}
          disabled={disabled}
        >
          {USERS.map((u) => (
            <option key={u.value} value={u.value}>{u.label}</option>
          ))}
        </select>
      </div>

      <div className="pw-config-field">
        <label className="pw-label">Browser</label>
        <div className="pw-button-group">
          {BROWSERS.map((b) => (
            <button
              key={b}
              id={`pw-browser-${b}`}
              className={`pw-pill ${browser === b ? "active" : ""}`}
              onClick={() => onBrowserChange(b)}
              disabled={disabled}
            >
              {b === "chromium" ? "🔵 Chromium" : b === "firefox" ? "🦊 Firefox" : "🧭 WebKit"}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Terminal output log panel */
function TerminalLog({
  lines,
  runId,
  status,
}: {
  lines: { line: string; stream: "stdout" | "stderr" }[];
  runId: string | null;
  status: "idle" | "running" | "passed" | "failed";
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines]);

  const statusLabels = {
    idle: "",
    running: "⏳ Running…",
    passed: "✅ Passed",
    failed: "❌ Failed",
  };

  return (
    <div className="pw-terminal">
      <div className="pw-terminal-header">
        <span className="pw-terminal-title">
          🖥 Terminal Output
          {runId && <span className="pw-terminal-run-id"> [{runId}]</span>}
        </span>
        {status !== "idle" && (
          <span className={`pw-terminal-status ${status}`}>
            {statusLabels[status]}
          </span>
        )}
      </div>
      <div className="pw-terminal-body" id="pw-terminal-body">
        {lines.length === 0 && (
          <div className="pw-terminal-empty">
            Select a test and press Run to see output here.
          </div>
        )}
        {lines.map((entry, i) => (
          <div
            key={i}
            className={`pw-terminal-line ${entry.stream === "stderr" ? "stderr" : "stdout"}`}
          >
            {entry.line}
          </div>
        ))}
        <div ref={endRef} />
      </div>
    </div>
  );
}

/** Session storage status matrix (13 users × 4 envs) */
function StorageMatrix({
  status,
  loading,
  generating,
  generateProgress,
  onRefresh,
  onGenerate,
}: {
  status: PlaywrightStorageStatusResponse | null;
  loading: boolean;
  generating: boolean;
  generateProgress: PlaywrightStorageGenerateStatusResponse | null;
  onRefresh: () => void;
  onGenerate: (envs: Env[]) => void;
}) {
  const [selectedEnvs, setSelectedEnvs] = useState<Env[]>(["test"]);

  const toggleEnv = (env: Env) => {
    setSelectedEnvs((prev) =>
      prev.includes(env) ? prev.filter((e) => e !== env) : [...prev, env]
    );
  };

  if (loading) {
    return (
      <div className="pw-storage-matrix">
        <div className="pw-loading">Loading session status…</div>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="pw-storage-matrix">
        <div className="pw-storage-error">
          Could not load session status. <button onClick={onRefresh} className="pw-link-btn">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="pw-storage-matrix">
      <div className="pw-matrix-header">
        <h3 className="pw-section-title">🔐 Session States</h3>
        <div className="pw-matrix-actions">
          <button onClick={onRefresh} disabled={loading || generating} className="pw-btn-ghost" title="Refresh status">
            🔄 Refresh
          </button>
          <div className="pw-generate-group">
            <div className="pw-generate-env-toggles">
              {ENVS.map((e) => (
                <button
                  key={e}
                  className={`pw-pill small ${selectedEnvs.includes(e) ? "active" : ""}`}
                  onClick={() => toggleEnv(e)}
                  disabled={generating}
                >
                  {e}
                </button>
              ))}
            </div>
            <button
              id="pw-generate-btn"
              onClick={() => onGenerate(selectedEnvs)}
              disabled={generating || selectedEnvs.length === 0}
              className="pw-btn-primary"
            >
              {generating ? "⏳ Generating…" : "⚡ Generate"}
            </button>
          </div>
        </div>
      </div>

      {/* Generation progress indicator */}
      {generating && generateProgress && generateProgress.status === "running" && (
        <div className="pw-generate-progress">
          <div className="pw-progress-bar">
            <div
              className="pw-progress-fill"
              style={{
                width: `${generateProgress.envs_requested.length > 0
                  ? ((generateProgress.envs_completed.length + generateProgress.envs_failed.length) / generateProgress.envs_requested.length) * 100
                  : 0}%`,
              }}
            />
          </div>
          <span className="pw-progress-text">
            Generating: {generateProgress.envs_completed.length}/{generateProgress.envs_requested.length} envs
            {generateProgress.envs_completed.length > 0 && (
              <> — done: {generateProgress.envs_completed.join(", ")}</>      
            )}
          </span>
        </div>
      )}

      <div className="pw-matrix-scroll">
        <table className="pw-matrix-table">
          <thead>
            <tr>
              <th className="pw-matrix-user-col">User</th>
              {ENVS.map((env) => (
                <th key={env} className="pw-matrix-env-col">{env}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(() => {
              const knownKeys = new Set(USERS.map((u) => u.value));
              const dynamicKeys: string[] = [];
              if (status?.environments) {
                Object.values(status.environments).forEach((envUsers) => {
                  if (envUsers) {
                    Object.keys(envUsers).forEach((u) => {
                      if (!knownKeys.has(u) && !dynamicKeys.includes(u)) {
                        dynamicKeys.push(u);
                      }
                    });
                  }
                });
              }
              const allUserRows = [
                ...USERS,
                ...dynamicKeys.map((k) => ({ value: k, label: k })),
              ];
              return allUserRows.map(({ value: username, label }) => (
                <tr key={username}>
                  <td className="pw-matrix-user">{label}</td>
                  {ENVS.map((env) => {
                    const cellStatus: StorageStateStatus =
                      status.environments[env]?.[username] ?? "missing";
                    return (
                      <td
                        key={env}
                        className={`pw-matrix-cell ${cellStatus}`}
                        title={`${username}/${env}: ${cellStatus}`}
                        style={{ color: STATUS_COLORS[cellStatus] }}
                      >
                        {STATUS_ICONS[cellStatus]}
                      </td>
                    );
                  })}
                </tr>
              ));
            })()}
          </tbody>
        </table>
      </div>

      <div className="pw-matrix-legend">
        <span className="pw-legend-item valid">{STATUS_ICONS.valid} Valid (&lt;24h)</span>
        <span className="pw-legend-item expired">{STATUS_ICONS.expired} Expired</span>
        <span className="pw-legend-item missing">{STATUS_ICONS.missing} Missing</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export function PlaywrightPage() {
  const { activeSlug: productSlug } = useProductContext();

  // Library state
  const [tests, setTests] = useState<PlaywrightTest[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(true);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTestId, setSelectedTestId] = useState<string | null>(null);

  // Config state — persisted in localStorage for sticky selection
  const [env, setEnv] = useState<Env>(() => {
    const saved = localStorage.getItem("vqa_pw_env");
    return (saved && (ENVS as readonly string[]).includes(saved)) ? saved as Env : "test";
  });
  const [user, setUser] = useState<string>(() => {
    const saved = localStorage.getItem("vqa_pw_user");
    return (saved && USERS.some(u => u.value === saved)) ? saved : "DemoSalesExec";
  });
  const [browser, setBrowser] = useState<Browser>(() => {
    const saved = localStorage.getItem("vqa_pw_browser");
    return (saved && (BROWSERS as readonly string[]).includes(saved)) ? saved as Browser : "chromium";
  });


  // Persist config selections to localStorage
  useEffect(() => { localStorage.setItem("vqa_pw_env", env); }, [env]);
  useEffect(() => { localStorage.setItem("vqa_pw_user", user); }, [user]);
  useEffect(() => { localStorage.setItem("vqa_pw_browser", browser); }, [browser]);

  // Run state
  const [runId, setRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState<"idle" | "running" | "passed" | "failed">("idle");
  const runStatusRef = useRef<"idle" | "running" | "passed" | "failed">("idle");
  const setRunStatusSafe = useCallback((s: "idle" | "running" | "passed" | "failed") => {
    runStatusRef.current = s;
    setRunStatus(s);
  }, []);
  const [terminalLines, setTerminalLines] = useState<{ line: string; stream: "stdout" | "stderr" }[]>([]);
  const [novncUrl, setNovncUrl] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Group selection state
  const [groupSelectedIds, setGroupSelectedIds] = useState<Set<string>>(new Set());

  const handleToggleGroup = useCallback((id: string) => {
    setGroupSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const handleClearGroup = useCallback(() => {
    setGroupSelectedIds(new Set());
  }, []);

  // Parallel Headless Suite Runner State (TASK-114)
  // Prefer ?suite_run_id=X in the URL (nightly Slack "View Report" deep link)
  // over the previously-active run in localStorage, so operators land on the
  // exact run the notification is about.
  const [suiteRunId, setSuiteRunId] = useState<string | null>(() => {
    const urlParam = new URLSearchParams(window.location.search).get("suite_run_id");
    if (urlParam) {
      localStorage.setItem("vqa_active_suite_run_id", urlParam);
      return urlParam;
    }
    return localStorage.getItem("vqa_active_suite_run_id");
  });
  const [suiteRunMode, setSuiteRunMode] = useState<"suite" | "group">(() => {
    return (localStorage.getItem("vqa_active_suite_run_mode") as "suite" | "group") ?? "suite";
  });
  const [suiteReport, setSuiteReport] = useState<PlaywrightSuiteReportResponse | null>(null);
  const [suiteRunStatus, setSuiteRunStatus] = useState<"idle" | "running" | "completed" | "failed">("idle");

  const suiteRunStatusRef = useRef(suiteRunStatus);
  useEffect(() => {
    suiteRunStatusRef.current = suiteRunStatus;
  }, [suiteRunStatus]);

  // Storage state
  const [storageStatus, setStorageStatus] = useState<PlaywrightStorageStatusResponse | null>(null);
  const [storageLoading, setStorageLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // Active tab within page
  const [activePanel, setActivePanel] = useState<"library" | "sessions">("library");

  // Record-a-test flow: picker → RecordDemoModal
  const [showRecordPicker, setShowRecordPicker] = useState(false);
  const [pendingRecord, setPendingRecord] = useState<
    { ticketId: string; ticketSummary: string; targetUrl: string } | null
  >(null);

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  const loadLibrary = useCallback(async () => {
    setLibraryLoading(true);
    setLibraryError(null);
    try {
      const r = await authenticatedFetch(`${API_BASE_URL}/playwright/tests?product=${encodeURIComponent(productSlug)}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data: PlaywrightTest[] = await r.json();
      setTests(data);
    } catch (err) {
      setLibraryError(err instanceof Error ? err.message : "Failed to load tests");
    } finally {
      setLibraryLoading(false);
    }
  }, [productSlug]);

  const loadStorageStatus = useCallback(async () => {
    setStorageLoading(true);
    try {
      const r = await authenticatedFetch(`${API_BASE_URL}/playwright/storage/status`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data: PlaywrightStorageStatusResponse = await r.json();
      setStorageStatus(data);
    } catch (err) {
      console.error("Storage status failed:", err);
      setStorageStatus(null);
    } finally {
      setStorageLoading(false);
    }
  }, []);

  useEffect(() => {
    loadLibrary();
    loadStorageStatus();
  }, [loadLibrary, loadStorageStatus]);

  // ---------------------------------------------------------------------------
  // Filtered tests
  // ---------------------------------------------------------------------------

  const filteredTests = tests.filter((t) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      t.id.toLowerCase().includes(q) ||
      t.description.toLowerCase().includes(q) ||
      t.jira_keys.some((k) => k.toLowerCase().includes(q)) ||
      t.step_names.some((s) => s.toLowerCase().includes(q))
    );
  });

  // ---------------------------------------------------------------------------
  // Run test
  // ---------------------------------------------------------------------------

  const handleRun = useCallback(async () => {
    if (!selectedTestId || runStatus === "running") return;

    setRunError(null);
    setTerminalLines([]);
    setRunStatusSafe("running");

    const req: PlaywrightRunRequest = {
      test_id: selectedTestId,
      env,
      user,
      browser,
    };

    try {
      const r = await authenticatedFetch(`${API_BASE_URL}/playwright/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });

      if (!r.ok) {
        const body = await r.json().catch(() => ({ detail: "Unknown error" }));
        throw new Error(body.detail || `HTTP ${r.status}`);
      }

      const data: PlaywrightRunResponse = await r.json();
      setRunId(data.run_id);
      setNovncUrl(data.novnc_url ?? null);

      // Connect WebSocket for streaming output
      const wsUrl = `${WS_BASE_URL}/ws/${data.run_id}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      // Watchdog: if the WS opens but no messages arrive within 15s,
      // the subprocess likely failed before the client connected and
      // the buffer flush may not have reached us.  Surface an error.
      let receivedFirstMessage = false;
      const noMessageTimer = setTimeout(() => {
        if (!receivedFirstMessage && runStatusRef.current === "running") {
          setRunError(
            "No output received within 15 s — the test may have failed to start. Check backend logs."
          );
          setRunStatusSafe("failed");
          ws.close();
        }
      }, 15_000);

      ws.onmessage = (event) => {
        receivedFirstMessage = true;
        clearTimeout(noMessageTimer);
        try {
          const msg = JSON.parse(event.data);

          if (msg.type === "terminal_log") {
            setTerminalLines((prev) => [
              ...prev,
              { line: msg.line, stream: msg.stream || "stdout" },
            ]);
          } else if (msg.type === "completed") {
            setRunStatusSafe("passed");
            ws.close();
          } else if (msg.type === "failed") {
            setRunStatusSafe("failed");
            ws.close();
          }
        } catch {
          // Non-JSON message — add raw to terminal
          setTerminalLines((prev) => [...prev, { line: event.data, stream: "stdout" }]);
        }
      };

      ws.onerror = () => {
        clearTimeout(noMessageTimer);
        setRunStatusSafe("failed");
        setRunError("WebSocket connection error");
      };

      ws.onclose = () => {
        clearTimeout(noMessageTimer);
        // Only transition to failed if we didn't explicitly set passed/failed
        if (runStatusRef.current === "running") {
          setRunStatusSafe("failed");
        }
      };
    } catch (err) {
      setRunStatusSafe("failed");
      setRunError(err instanceof Error ? err.message : "Failed to start test");
    }
  }, [selectedTestId, env, user, browser, setRunStatusSafe]);

  const handleStop = useCallback(async () => {
    if (runId) {
      try {
        await authenticatedFetch(`${API_BASE_URL}/playwright/run/${runId}/stop`, { method: "POST" });
      } catch {
        // Subprocess may have already finished — safe to ignore
      }
    }
    wsRef.current?.close();
    setRunStatusSafe("failed");
    setTerminalLines((prev) => [...prev, { line: "⚠ Run stopped by user.", stream: "stderr" }]);
  }, [runId, setRunStatusSafe]);

  // ---------------------------------------------------------------------------
  // Parallel Suite Run Polling & Controls (TASK-114)
  // ---------------------------------------------------------------------------

  const pollReport = useCallback(async (runId: string) => {
    try {
      const r = await authenticatedFetch(`${API_BASE_URL}/playwright/run-all/${runId}/report`);
      if (!r.ok) {
        if (r.status === 404) {
          localStorage.removeItem("vqa_active_suite_run_id");
          setSuiteRunId(null);
          setSuiteRunStatus("idle");
          setSuiteReport(null);
          return true; // stop polling
        }
        throw new Error(`HTTP ${r.status}`);
      }
      const data: PlaywrightSuiteReportResponse = await r.json();
      setSuiteReport(data);
      setSuiteRunStatus(data.status);
      if (data.status === "completed" || data.status === "failed") {
        return true; // stop polling
      }
      return false; // keep polling
    } catch (err) {
      console.error("Failed to poll suite report:", err);
      return false;
    }
  }, []);

  useEffect(() => {
    if (!suiteRunId) return;

    let isMounted = true;
    let timerId: ReturnType<typeof setTimeout> | null = null;

    const runPolling = async () => {
      if (!isMounted) return;
      const isFinished = await pollReport(suiteRunId);
      if (!isFinished && isMounted) {
        timerId = setTimeout(runPolling, 1500);
      }
    };

    runPolling();

    const handleBeforeUnload = () => {
      if (suiteRunStatusRef.current === "running") {
        const token = authStorage.getAppToken() || authStorage.getSsoToken();
        const headers: Record<string, string> = {
          "Content-Type": "application/json"
        };
        if (token) {
          headers["Authorization"] = `Bearer ${token}`;
        }
        const apiKey = import.meta.env.VITE_API_KEY as string | undefined;
        if (apiKey) {
          headers["X-VQA-API-Key"] = apiKey;
        }

        const url = `${API_BASE_URL}/playwright/run-all/${suiteRunId}/stop`;
        
        // Use fetch with keepalive: true to survive page teardown / reload
        fetch(url, {
          method: "POST",
          headers,
          keepalive: true
        });

        localStorage.removeItem("vqa_active_suite_run_id");
      }
    };

    window.addEventListener("beforeunload", handleBeforeUnload);

    return () => {
      isMounted = false;
      if (timerId) clearTimeout(timerId);
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [suiteRunId, pollReport]);

  const handleRunAll = useCallback(async () => {
    if (suiteRunStatus === "running") return;

    setSuiteRunStatus("running");
    setSuiteReport(null);

    const req: PlaywrightSuiteRunRequest = {
      env,
      user,
      browser,
    };

    try {
      const r = await authenticatedFetch(`${API_BASE_URL}/playwright/run-all`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });

      if (!r.ok) {
        if (r.status === 429) {
          alert("Suite run already in progress.");
        } else {
          const body = await r.json().catch(() => ({ detail: "Unknown error" }));
          alert(`Failed to start suite: ${body.detail || "Unknown error"}`);
        }
        setSuiteRunStatus("idle");
        return;
      }

      const data: PlaywrightSuiteRunResponse = await r.json();
      setSuiteRunId(data.suite_run_id);
      setSuiteRunMode("suite");
      localStorage.setItem("vqa_active_suite_run_id", data.suite_run_id);
      localStorage.setItem("vqa_active_suite_run_mode", "suite");
    } catch (err) {
      alert(`Error starting suite run: ${err instanceof Error ? err.message : "Unknown error"}`);
      setSuiteRunStatus("idle");
    }
  }, [env, user, browser, suiteRunStatus]);

  const handleRunGroup = useCallback(async () => {
    if (groupSelectedIds.size === 0 || suiteRunStatus === "running") return;

    setSuiteRunStatus("running");
    setSuiteReport(null);

    const req: PlaywrightGroupRunRequest = {
      test_ids: Array.from(groupSelectedIds),
      env,
      user,
      browser,
    };

    try {
      const r = await authenticatedFetch(`${API_BASE_URL}/playwright/run-group`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });

      if (!r.ok) {
        if (r.status === 429) {
          alert("A suite run is already in progress.");
        } else {
          const body = await r.json().catch(() => ({ detail: "Unknown error" }));
          alert(`Failed to start group run: ${body.detail || "Unknown error"}`);
        }
        setSuiteRunStatus("idle");
        return;
      }

      const data: PlaywrightSuiteRunResponse = await r.json();
      setSuiteRunId(data.suite_run_id);
      setSuiteRunMode("group");
      localStorage.setItem("vqa_active_suite_run_id", data.suite_run_id);
      localStorage.setItem("vqa_active_suite_run_mode", "group");
    } catch (err) {
      alert(`Error starting group run: ${err instanceof Error ? err.message : "Unknown error"}`);
      setSuiteRunStatus("idle");
    }
  }, [groupSelectedIds, env, user, browser, suiteRunStatus]);

  const handleBackToLibrary = useCallback(() => {
    localStorage.removeItem("vqa_active_suite_run_id");
    localStorage.removeItem("vqa_active_suite_run_mode");
    setSuiteRunId(null);
    setSuiteReport(null);
    setSuiteRunStatus("idle");
    setSuiteRunMode("suite");
  }, []);

  const handleStopSuite = useCallback(async () => {
    if (!suiteRunId) return;
    const confirmStop = window.confirm("Are you sure you want to stop the running test suite?");
    if (!confirmStop) return;

    try {
      const r = await authenticatedFetch(`${API_BASE_URL}/playwright/run-all/${suiteRunId}/stop`, {
        method: "POST",
      });
      if (!r.ok) {
        throw new Error(`HTTP ${r.status}`);
      }
      const data: PlaywrightSuiteReportResponse = await r.json();
      setSuiteReport(data);
      setSuiteRunStatus(data.status);
    } catch (err) {
      alert(`Failed to stop suite run: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  }, [suiteRunId]);

  // ---------------------------------------------------------------------------
  // Storage generation
  // ---------------------------------------------------------------------------

  const generateProgressRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [generateProgress, setGenerateProgress] = useState<PlaywrightStorageGenerateStatusResponse | null>(null);

  const handleGenerate = useCallback(async (envs: Env[]) => {
    if (generating) return;
    setGenerating(true);
    setGenerateProgress(null);
    try {
      const r = await authenticatedFetch(`${API_BASE_URL}/playwright/storage/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ envs }),
      });
      if (r.status === 429) {
        alert("Storage generation already in progress. Please wait.");
        setGenerating(false);
        return;
      }
      if (!r.ok) {
        const body = await r.json().catch(() => ({ detail: "Error" }));
        alert(`Generation failed: ${body.detail || "Unknown error"}`);
        setGenerating(false);
        return;
      }

      // Poll generation status until complete
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await authenticatedFetch(
            `${API_BASE_URL}/playwright/storage/generate/status`
          );
          if (!statusRes.ok) return;
          const progress: PlaywrightStorageGenerateStatusResponse = await statusRes.json();
          setGenerateProgress(progress);

          if (progress.status === "done" || progress.status === "error") {
            clearInterval(pollInterval);
            generateProgressRef.current = null;

            if (progress.status === "error") {
              alert(`Generation failed: ${progress.error || "Unknown error"}`);
            }

            // Refresh status matrix now that generation is truly done
            await loadStorageStatus();
            setGenerating(false);
            // Clear progress after a short delay so user sees the 100% state
            setTimeout(() => setGenerateProgress(null), 2000);
          }
        } catch {
          // Silently retry on network errors
        }
      }, 3000);

      generateProgressRef.current = pollInterval;
    } catch (err) {
      alert(`Generation error: ${err instanceof Error ? err.message : "Unknown"}`);
      setGenerating(false);
    }
  }, [generating, loadStorageStatus]);

  // Cleanup WS and polling on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close();
      if (generateProgressRef.current) {
        clearInterval(generateProgressRef.current);
      }
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Selected test metadata
  // ---------------------------------------------------------------------------

  const selectedTest = tests.find((t) => t.id === selectedTestId);

  const isRunning = runStatus === "running";

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="pw-page">
      {/* ── Page Header ─────────────────────────────────────────────── */}
      <header className="pw-page-header">
        <div className="pw-header-left">
          <h1 className="pw-page-title">
            <span className="pw-title-icon">🎭</span>
            Playwright Library
          </h1>
          <span className="pw-page-subtitle">Static test suite — {tests.length} tests</span>
        </div>
        <div className="pw-header-tabs">
          <button
            className={`pw-header-tab ${activePanel === "library" ? "active" : ""}`}
            onClick={() => setActivePanel("library")}
          >
            📋 Test Library
          </button>
          <button
            className={`pw-header-tab ${activePanel === "sessions" ? "active" : ""}`}
            onClick={() => setActivePanel("sessions")}
          >
            🔐 Sessions
          </button>
        </div>
      </header>

      {/* ── Sessions Panel ─────────────────────────────────────────── */}
      {activePanel === "sessions" && (
        <div className="pw-sessions-container">
          <StorageMatrix
            status={storageStatus}
            loading={storageLoading}
            generating={generating}
            generateProgress={generateProgress}
            onRefresh={loadStorageStatus}
            onGenerate={handleGenerate}
          />
        </div>
      )}

      {/* ── Record-a-test overlays ─────────────────────────────────── */}
      {showRecordPicker && !pendingRecord && (
        <RecordDemoTicketPickerModal
          onCancel={() => setShowRecordPicker(false)}
          onStart={({ ticketId, ticketSummary, targetUrl }) => {
            setPendingRecord({ ticketId, ticketSummary, targetUrl });
            setShowRecordPicker(false);
          }}
        />
      )}
      {pendingRecord && (
        <RecordDemoModal
          ticketId={pendingRecord.ticketId}
          ticketSummary={pendingRecord.ticketSummary}
          targetUrl={pendingRecord.targetUrl}
          onClose={() => {
            setPendingRecord(null);
            loadLibrary();
          }}
        />
      )}

      {/* ── Library Panel ──────────────────────────────────────────── */}
      {activePanel === "library" && (
        <div className="pw-library-layout">
          {/* Left: Test library */}
          <div className="pw-library-column">
            <TestSearchBar
              query={searchQuery}
              onChange={setSearchQuery}
              totalCount={filteredTests.length}
            />

            {libraryLoading && (
              <div className="pw-loading">
                <span className="pw-spinner" /> Loading tests…
              </div>
            )}

            {libraryError && (
              <div className="pw-error-banner">
                <span>⚠ {libraryError}</span>
                <button onClick={loadLibrary} className="pw-link-btn">Retry</button>
              </div>
            )}

            {!libraryLoading && !libraryError && groupSelectedIds.size > 0 && (
              <div className="pw-group-bar" style={{ display: "flex", alignItems: "center", gap: "0.5rem", padding: "0.5rem 0.75rem", background: "var(--bg-secondary, #1e1e2e)", borderRadius: "6px", marginBottom: "0.5rem", border: "1px solid var(--primary-alt, #4f46e5)" }}>
                <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--primary-alt, #4f46e5)" }}>
                  {groupSelectedIds.size} test{groupSelectedIds.size !== 1 ? "s" : ""} selected
                </span>
                <button
                  className="pw-btn-run-all"
                  onClick={handleRunGroup}
                  disabled={isRunning || suiteRunStatus === "running"}
                  style={{ padding: "0.3rem 0.8rem", background: "var(--primary-alt, #4f46e5)", color: "#fff", border: "none", borderRadius: "4px", fontWeight: 600, cursor: "pointer", fontSize: "0.85rem" }}
                >
                  ▶ Run Group ({groupSelectedIds.size})
                </button>
                <button
                  onClick={handleClearGroup}
                  disabled={isRunning || suiteRunStatus === "running"}
                  style={{ padding: "0.3rem 0.6rem", background: "transparent", color: "var(--text-secondary)", border: "1px solid var(--border)", borderRadius: "4px", cursor: "pointer", fontSize: "0.8rem" }}
                >
                  Clear
                </button>
              </div>
            )}

            {!libraryLoading && !libraryError && (
              <div className="pw-test-list" id="pw-test-list">
                {filteredTests.length === 0 ? (
                  <div className="pw-empty-state">
                    <span className="pw-empty-icon">🔍</span>
                    <p>No tests match "<strong>{searchQuery}</strong>"</p>
                  </div>
                ) : (
                  filteredTests.map((test) => (
                    <TestCard
                      key={test.id}
                      test={test}
                      selected={test.id === selectedTestId}
                      inGroup={groupSelectedIds.has(test.id)}
                      onSelect={setSelectedTestId}
                      onToggleGroup={handleToggleGroup}
                      disabled={isRunning || suiteRunStatus === "running"}
                    />
                  ))
                )}
              </div>
            )}
          </div>

          {/* Right: Config + Terminal */}
          <div className="pw-run-column">
            {suiteRunId ? (
              suiteReport ? (
                <SuiteResultsPanel
                  report={suiteReport}
                  label={suiteRunMode === "group" ? "Group Run (Sequential)" : undefined}
                  onBack={handleBackToLibrary}
                  onStop={handleStopSuite}
                />
              ) : (
                <div className="pw-loading" style={{ padding: "2rem", textAlign: "center" }}>
                  <span className="pw-spinner" /> Loading suite report...
                </div>
              )
            ) : (
              <>
                {/* Selected test info */}
                {selectedTest && (
                  <div className="pw-selected-test">
                    <div className="pw-selected-test-id">{selectedTest.id}</div>
                    <div className="pw-selected-test-desc">{selectedTest.description}</div>
                  </div>
                )}

                <RunConfigPanel
                  env={env}
                  user={user}
                  browser={browser}
                  onEnvChange={setEnv}
                  onUserChange={setUser}
                  onBrowserChange={setBrowser}
                  disabled={isRunning || suiteRunStatus === "running"}
                />

                {/* Run / Stop buttons */}
                <div className="pw-run-controls" style={{ display: "flex", gap: "0.5rem" }}>
                  <button
                    id="pw-run-btn"
                    className={`pw-btn-run ${isRunning ? "running" : ""}`}
                    onClick={isRunning ? handleStop : handleRun}
                    disabled={(!selectedTestId && !isRunning) || suiteRunStatus === "running"}
                  >
                    {isRunning ? "⏹ Stop" : "▶ Run Test"}
                  </button>

                  <button
                    id="pw-run-all-btn"
                    className="pw-btn-run-all"
                    onClick={handleRunAll}
                    disabled={isRunning || suiteRunStatus === "running"}
                    style={{
                      padding: "0.5rem 1rem",
                      background: "var(--primary-alt, #4f46e5)",
                      color: "#fff",
                      border: "none",
                      borderRadius: "4px",
                      fontWeight: 600,
                      cursor: "pointer",
                      opacity: (isRunning || suiteRunStatus === "running") ? 0.5 : 1,
                      transition: "background 0.2s",
                    }}
                  >
                    ▶ Run All Tests
                  </button>

                  <button
                    id="pw-record-demo-btn"
                    className="btn-record-demo"
                    onClick={() => setShowRecordPicker(true)}
                    disabled={isRunning || suiteRunStatus === "running"}
                    style={{ marginTop: 0 }}
                  >
                    🔴 Record a Playwright Test
                  </button>

                  {runStatus === "passed" && (
                    <span className="pw-run-result passed">✅ Passed</span>
                  )}
                  {runStatus === "failed" && (
                    <span className="pw-run-result failed">❌ Failed</span>
                  )}
                </div>

                {runError && (
                  <div className="pw-run-error">
                    <span>⚠ {runError}</span>
                  </div>
                )}

                {/* Live Browser View — shown when test runs headed (Docker/ECS via noVNC) */}
                {isRunning && novncUrl && (
                  <div className="pw-browser-frame">
                    <div className="pw-browser-label">🖥️ Live Browser</div>
                    <iframe
                      src={novncUrl}
                      title="Live Browser"
                      className="pw-browser-iframe"
                      style={{
                        width: "100%",
                        height: "500px",
                        border: "none",
                        background: "#000",
                        borderRadius: "4px",
                        marginBottom: "0.75rem",
                      }}
                    />
                  </div>
                )}

                <TerminalLog
                  lines={terminalLines}
                  runId={runId}
                  status={runStatus}
                />
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default PlaywrightPage;
