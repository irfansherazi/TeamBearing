import { useEffect, useMemo, useRef, useState } from "react";
import { authenticatedFetch } from "../api_client";
import { API_BASE_URL } from "../types";
import { useProductContext } from "../context/ProductContext";

interface JiraTicketSummary {
  id: string;
  summary: string;
  status: string;
  priority: string;
  issue_type: string;
}

interface RecordDemoTicketPickerModalProps {
  onStart: (args: { ticketId: string; ticketSummary: string; targetUrl: string }) => void;
  onCancel: () => void;
}

export function RecordDemoTicketPickerModal({ onStart, onCancel }: RecordDemoTicketPickerModalProps) {
  const { activeSlug: productSlug, activeProduct } = useProductContext();

  const [tickets, setTickets] = useState<JiraTicketSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [selectedTicket, setSelectedTicket] = useState<JiraTicketSummary | null>(null);
  const [manualId, setManualId] = useState("");
  const [manualSummary, setManualSummary] = useState("");
  const [mode, setMode] = useState<"list" | "manual">("list");

  const envEntries = useMemo(
    () => (activeProduct ? Object.entries(activeProduct.environments) : []),
    [activeProduct],
  );
  const defaultUrl = activeProduct
    ? activeProduct.environments[activeProduct.default_environment] ??
      Object.values(activeProduct.environments)[0] ??
      ""
    : "";
  const [targetUrl, setTargetUrl] = useState<string>(defaultUrl);

  useEffect(() => {
    setTargetUrl(defaultUrl);
  }, [defaultUrl]);

  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (abortRef.current) abortRef.current.abort();
    const ctl = new AbortController();
    abortRef.current = ctl;
    setLoading(true);
    setLoadError(null);
    setTickets([]);
    setSelectedTicket(null);

    authenticatedFetch(`${API_BASE_URL}/tickets?product=${encodeURIComponent(productSlug)}`)
      .then(async (r) => {
        if (ctl.signal.aborted) return;
        if (!r.ok) {
          const err = await r.json().catch(() => ({ detail: `Server error: ${r.status}` }));
          throw new Error(err.detail || `Server error: ${r.status}`);
        }
        return r.json();
      })
      .then((data: JiraTicketSummary[] | undefined) => {
        if (ctl.signal.aborted) return;
        setTickets(data ?? []);
        setLoading(false);
      })
      .catch((err) => {
        if (ctl.signal.aborted) return;
        setLoadError(err instanceof Error ? err.message : "Could not load tickets");
        setLoading(false);
      });

    return () => {
      ctl.abort();
    };
  }, [productSlug]);

  const filteredTickets = useMemo(() => {
    if (!query.trim()) return tickets;
    const q = query.trim().toLowerCase();
    return tickets.filter(
      (t) => t.id.toLowerCase().includes(q) || t.summary.toLowerCase().includes(q),
    );
  }, [tickets, query]);

  const canStart =
    !!targetUrl &&
    (mode === "list"
      ? !!selectedTicket
      : /^[A-Za-z]+-\d+$/.test(manualId.trim()) && !!manualSummary.trim());

  const handleStart = () => {
    if (!canStart) return;
    if (mode === "list" && selectedTicket) {
      onStart({
        ticketId: selectedTicket.id,
        ticketSummary: selectedTicket.summary,
        targetUrl,
      });
    } else if (mode === "manual") {
      onStart({
        ticketId: manualId.trim().toUpperCase(),
        ticketSummary: manualSummary.trim(),
        targetUrl,
      });
    }
  };

  return (
    <div className="record-demo-overlay" role="dialog" aria-modal="true" aria-label="Record a Playwright Test">
      <div
        className="record-demo-modal"
        style={{ maxWidth: 640, maxHeight: "88vh", overflow: "hidden" }}
      >
        <div
          className="record-demo-header"
          style={{ padding: "var(--space-md) var(--space-lg)", display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid var(--border)" }}
        >
          <span className="record-demo-title" style={{ fontWeight: 600 }}>
            🔴 Record a Playwright Test
          </span>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Close"
            style={{ background: "transparent", border: "none", color: "var(--text-secondary)", fontSize: "1.1rem", cursor: "pointer" }}
          >
            ✕
          </button>
        </div>

        <div style={{ padding: "var(--space-lg)", overflowY: "auto", display: "flex", flexDirection: "column", gap: "var(--space-md)" }}>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button
              type="button"
              onClick={() => setMode("list")}
              style={{
                flex: 1,
                padding: "0.4rem 0.75rem",
                background: mode === "list" ? "var(--primary-alt, #4f46e5)" : "transparent",
                color: mode === "list" ? "#fff" : "var(--text-primary)",
                border: "1px solid var(--border)",
                borderRadius: "4px",
                fontWeight: 600,
                cursor: "pointer",
                fontSize: "0.85rem",
              }}
            >
              Pick from board
            </button>
            <button
              type="button"
              onClick={() => setMode("manual")}
              style={{
                flex: 1,
                padding: "0.4rem 0.75rem",
                background: mode === "manual" ? "var(--primary-alt, #4f46e5)" : "transparent",
                color: mode === "manual" ? "#fff" : "var(--text-primary)",
                border: "1px solid var(--border)",
                borderRadius: "4px",
                fontWeight: 600,
                cursor: "pointer",
                fontSize: "0.85rem",
              }}
            >
              Enter ticket manually
            </button>
          </div>

          {mode === "list" && (
            <>
              <input
                type="text"
                placeholder="Filter by ID or summary…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                style={{
                  padding: "0.4rem 0.6rem",
                  background: "var(--bg-primary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                  borderRadius: "4px",
                  fontSize: "0.85rem",
                }}
              />
              <div
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: "4px",
                  background: "var(--bg-primary)",
                  maxHeight: "260px",
                  overflowY: "auto",
                }}
              >
                {loading && (
                  <div style={{ padding: "0.75rem", color: "var(--text-secondary)", fontSize: "0.85rem" }}>
                    Loading tickets…
                  </div>
                )}
                {!loading && loadError && (
                  <div style={{ padding: "0.75rem", color: "var(--error)", fontSize: "0.85rem" }}>
                    ⚠ {loadError}
                  </div>
                )}
                {!loading && !loadError && filteredTickets.length === 0 && (
                  <div style={{ padding: "0.75rem", color: "var(--text-secondary)", fontSize: "0.85rem" }}>
                    No tickets match "{query}".
                  </div>
                )}
                {!loading && !loadError && filteredTickets.map((t) => {
                  const isSelected = selectedTicket?.id === t.id;
                  return (
                    <div
                      key={t.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => setSelectedTicket(t)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSelectedTicket(t);
                        }
                      }}
                      style={{
                        padding: "0.5rem 0.75rem",
                        borderBottom: "1px solid var(--border)",
                        cursor: "pointer",
                        background: isSelected ? "var(--primary-alt, #4f46e5)" : "transparent",
                        color: isSelected ? "#fff" : "var(--text-primary)",
                      }}
                    >
                      <div style={{ fontWeight: 600, fontSize: "0.85rem" }}>{t.id}</div>
                      <div style={{ fontSize: "0.78rem", opacity: 0.85 }}>{t.summary}</div>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {mode === "manual" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              <label style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>
                Ticket ID (e.g. QA-359)
                <input
                  type="text"
                  value={manualId}
                  onChange={(e) => setManualId(e.target.value)}
                  placeholder="QA-123"
                  style={{
                    marginTop: "0.25rem",
                    width: "100%",
                    padding: "0.4rem 0.6rem",
                    background: "var(--bg-primary)",
                    color: "var(--text-primary)",
                    border: "1px solid var(--border)",
                    borderRadius: "4px",
                    fontSize: "0.85rem",
                  }}
                />
              </label>
              <label style={{ fontSize: "0.78rem", color: "var(--text-secondary)" }}>
                Ticket summary
                <input
                  type="text"
                  value={manualSummary}
                  onChange={(e) => setManualSummary(e.target.value)}
                  placeholder="Short description of what this test covers"
                  style={{
                    marginTop: "0.25rem",
                    width: "100%",
                    padding: "0.4rem 0.6rem",
                    background: "var(--bg-primary)",
                    color: "var(--text-primary)",
                    border: "1px solid var(--border)",
                    borderRadius: "4px",
                    fontSize: "0.85rem",
                  }}
                />
              </label>
            </div>
          )}

          <label style={{ fontSize: "0.78rem", color: "var(--text-secondary)", display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            Target URL
            {envEntries.length > 0 ? (
              <select
                value={targetUrl}
                onChange={(e) => setTargetUrl(e.target.value)}
                style={{
                  padding: "0.4rem 0.6rem",
                  background: "var(--bg-primary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                  borderRadius: "4px",
                  fontSize: "0.85rem",
                }}
              >
                {envEntries.map(([name, url]) => (
                  <option key={name} value={url}>
                    {name} — {url}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={targetUrl}
                onChange={(e) => setTargetUrl(e.target.value)}
                placeholder="https://qa.vcreative.net"
                style={{
                  padding: "0.4rem 0.6rem",
                  background: "var(--bg-primary)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                  borderRadius: "4px",
                  fontSize: "0.85rem",
                }}
              />
            )}
          </label>
        </div>

        <div
          style={{
            padding: "var(--space-md) var(--space-lg)",
            borderTop: "1px solid var(--border)",
            display: "flex",
            justifyContent: "flex-end",
            gap: "0.5rem",
          }}
        >
          <button
            type="button"
            onClick={onCancel}
            style={{
              padding: "0.45rem 0.9rem",
              background: "transparent",
              color: "var(--text-secondary)",
              border: "1px solid var(--border)",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "0.85rem",
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canStart}
            onClick={handleStart}
            className="btn-record-demo"
            style={{ marginTop: 0 }}
          >
            🔴 Start Recording
          </button>
        </div>
      </div>
    </div>
  );
}
