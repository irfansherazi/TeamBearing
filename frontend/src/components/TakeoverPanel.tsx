/**
 * vQA — TakeoverPanel Component
 * ================================
 * Module: frontend/src/components/TakeoverPanel.tsx
 *
 * Displayed when the WebSocket receives a "human_takeover" event.
 * Rebuilt in TASK-085 with live CDP screencast, real-time action echoing,
 * and browser dialog interception.
 */

import { useEffect, useRef, useState } from "react";
import { authenticatedFetch } from "../api_client";
import { useOptionalSession } from "../context/SessionContext";
import { HitlRecordingFeed } from "./HitlRecordingFeed";
import { BrowserDialogPanel } from "./BrowserDialogPanel";
import type { WSHitlDialogMessage, HitlActionRecord } from "../types";

interface TakeoverPanelProps {
  runId: string;
  acStep: string;
  acStepIndex: number;
  errorMessage: string;
  /** The latest screenshot b64 from the agent stream (fallback) */
  screenshotB64: string;
  /** Real-time screencast frame from CDP (base64 JPEG) */
  hitlScreenshot?: string;
  /** Echoed human actions */
  hitlActions?: HitlActionRecord[];
  /** Intercepted browser dialog */
  hitlDialog?: WSHitlDialogMessage | null;
  /** Legacy noVNC URL (from run status). Only used when no SessionProvider is mounted. */
  vncUrl?: string | null;
  onDone: () => void;
  onMinimize?: () => void;
}

// ── Types ──────────────────────────────────────────────────────────────────

type InteractionMode = "normal" | "capture";

interface CapturedElement {
  selector: string;
  element_label: string;
  tag: string;
  role: string;
  text: string;
  match_count: number;
}

// ── Component ──────────────────────────────────────────────────────────────

export function TakeoverPanel({
  runId,
  acStep,
  acStepIndex,
  errorMessage,
  screenshotB64: fallbackScreenshot,
  hitlScreenshot,
  hitlActions = [],
  hitlDialog: externalDialog,
  vncUrl,
  onDone,
  onMinimize,
}: TakeoverPanelProps) {
  // Prefer the session-scoped noVNC URL when a SessionProvider is mounted
  // and the session is attached. Falls back to the legacy prop otherwise.
  // Currently unused for rendering (see the `NOTE: vncUrl is intentionally
  // NOT used` comment below) — but wired so that if we re-enable the iframe
  // path we're already reading from the isolated session, not the run status.
  const _session = useOptionalSession();
  const _effectiveVncUrl =
    _session && _session.sessionState === "attached" && _session.novncUrl
      ? _session.novncUrl
      : vncUrl ?? null;
  void _effectiveVncUrl;
  // ── Core state ────────────────────────────────────────────────────
  const [typeText, setTypeText] = useState("");
  const [explanation, setExplanation] = useState("");
  const [isActing, setIsActing] = useState(false);
  const [isDone, setIsDone] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [timeLeft, setTimeLeft] = useState(300); // 5 minute timeout
  const [activeDialog, setActiveDialog] = useState<WSHitlDialogMessage | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);

  // ── FEAT-102: DOM capture reminder ────────────────────────────────
  // Warn operator when they start typing an explanation but have NOT
  // interacted with the browser (no recorded DOM actions). This prevents
  // operators from submitting a text-only explanation that the agent
  // cannot use to learn — real browser interactions must be recorded.
  const [showDomCaptureReminder, setShowDomCaptureReminder] = useState(false);
  const [domReminderDismissed, setDomReminderDismissed] = useState(false);

  function handleExplanationChange(value: string) {
    setExplanation(value);
    // Show reminder only if: user typed something, no actions recorded, and not dismissed
    if (value.trim() && hitlActions.length === 0 && !domReminderDismissed) {
      setShowDomCaptureReminder(true);
    } else if (!value.trim() || hitlActions.length > 0) {
      setShowDomCaptureReminder(false);
    }
  }

  // ── Click-to-Teach state ──────────────────────────────────────────
  const [mode, setMode] = useState<InteractionMode>("normal");
  const [isCapturing, setIsCapturing] = useState(false);
  const [capturedElement, setCapturedElement] = useState<CapturedElement | null>(null);
  const [teachDescription, setTeachDescription] = useState("");
  const [isTeaching, setIsTeaching] = useState(false);
  const [teachFeedback, setTeachFeedback] = useState("");
  const [selectorOverride, setSelectorOverride] = useState("");
  const [showSelectorEdit, setShowSelectorEdit] = useState(false);

  // ── Effects ───────────────────────────────────────────────────────

  // Sync external dialog state
  useEffect(() => {
    if (externalDialog) {
      setActiveDialog(externalDialog);
    }
  }, [externalDialog]);

  // Timeout countdown
  useEffect(() => {
    const timer = setInterval(() => {
      setTimeLeft(prev => prev > 0 ? prev - 1 : 0);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  // ── Helpers ───────────────────────────────────────────────────────

  /** The selector that will actually be used for Execute & Teach */
  const activeSelector = showSelectorEdit && selectorOverride.trim()
    ? selectorOverride.trim()
    : capturedElement?.selector ?? "";

  /** Switch modes, clear capture state when going back to normal */
  function switchMode(newMode: InteractionMode) {
    setMode(newMode);
    if (newMode === "normal") {
      setCapturedElement(null);
      setTeachFeedback("");
      setSelectorOverride("");
      setShowSelectorEdit(false);
      setTeachDescription("");
    }
  }

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  // ── NORMAL mode: inject browser action ──────────────────────────

  async function sendAction(body: object) {
    setIsActing(true);
    setFeedback("");
    try {
      const res = await authenticatedFetch(`/runs/${runId}/interact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json();
        setFeedback(`⚠️ ${data.error || "Failed to send action"}`);
      }
    } catch {
      setFeedback("⚠️ Failed to send action");
    } finally {
      setIsActing(false);
    }
  }

  // ── CAPTURE mode: auto-detect element from screenshot click ──────

  async function handleCaptureClick(e: React.MouseEvent<HTMLImageElement>) {
    if (isCapturing || isTeaching || isDone) return;

    const rect = imgRef.current!.getBoundingClientRect();
    const x_pct = (e.clientX - rect.left) / rect.width;
    const y_pct = (e.clientY - rect.top) / rect.height;

    setIsCapturing(true);
    setCapturedElement(null);
    setTeachFeedback("");

    try {
      const res = await authenticatedFetch(`/runs/${runId}/teach/capture-click`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x_pct, y_pct }),
      });
      const data = await res.json();

      if (data.ok) {
        setCapturedElement({
          selector: data.selector,
          element_label: data.element_label,
          tag: data.tag,
          role: data.role,
          text: data.text,
          match_count: data.match_count ?? 1,
        });
        setSelectorOverride(data.selector);
        setShowSelectorEdit(false);
        // Pre-fill description if we have element text
        if (data.text && !teachDescription) {
          setTeachDescription(`Click on '${data.text.substring(0, 40)}'`);
        }
      } else {
        setTeachFeedback(`⚠️ ${data.error || "No element found at that position — try again"}`);
      }
    } catch {
      setTeachFeedback("⚠️ Network error — check backend");
    } finally {
      setIsCapturing(false);
    }
  }

  // ── Dispatch screenshot click based on current mode ──────────────

  function handleImageClick(e: React.MouseEvent<HTMLImageElement>) {
    if (isDone) return;
    if (mode === "capture") {
      handleCaptureClick(e);
    } else {
      if (isActing) return;
      const rect = imgRef.current!.getBoundingClientRect();
      const x_pct = (e.clientX - rect.left) / rect.width;
      const y_pct = (e.clientY - rect.top) / rect.height;
      sendAction({ action: "click", x_pct, y_pct });
    }
  }

  // ── Execute captured action + write to KB ────────────────────────

  async function handleExecuteAndTeach() {
    if (!activeSelector || !teachDescription.trim() || isTeaching || isDone) return;
    setIsTeaching(true);
    setTeachFeedback("");

    try {
      const res = await authenticatedFetch(`/runs/${runId}/teach`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          selector: activeSelector,
          action: "click",
          value: "",
          description: teachDescription.trim(),
          ac_step: acStep,
        }),
      });
      const data = await res.json();

      if (data.ok) {
        setTeachFeedback(
          data.kb_written
            ? "✅ Click executed and saved to KB!"
            : "✅ Click executed (KB write had an issue — check logs)"
        );
        // Auto-populate the main explanation field for the Resume step
        setExplanation(prev =>
          prev ? prev
               : `Taught: click '${activeSelector}' — ${teachDescription.trim()}`
        );
      } else {
        setTeachFeedback(`⚠️ ${data.error || "Execution failed"}`);
      }
    } catch {
      setTeachFeedback("⚠️ Network error — check backend logs");
    } finally {
      setIsTeaching(false);
    }
  }

  // ── Normal keyboard / scroll handlers ───────────────────────────

  function handleType() {
    if (!typeText.trim() || isActing || isDone) return;
    sendAction({ action: "type", text: typeText });
    setTypeText("");
  }

  function handleKey(key: string) {
    if (isActing || isDone) return;
    sendAction({ action: "key", key });
  }

  function handleScroll(direction: "up" | "down") {
    if (isActing || isDone) return;
    sendAction({ action: "scroll", direction });
  }

  // ── Done / Skip ──────────────────────────────────────────────────

  async function handleDone(skip: boolean) {
    setIsDone(true);
    setFeedback(skip ? "⏭ Skipping step..." : "✓ Signaling agent to resume...");
    try {
      const res = await authenticatedFetch(`/runs/${runId}/human-takeover/done`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ explanation, skip }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        const errDetail = errBody.detail ||
          (errBody.error === "explanation_required"
            ? "⚠️ No browser actions were captured. Please describe what you did below, then click Done again."
            : `⚠️ Server error ${res.status} — try again.`);
        setFeedback(`⚠️ ${errDetail}`);
        setIsDone(false);
        return;
      }
      setFeedback(skip ? "Step skipped" : "Agent is resuming...");
      setTimeout(onDone, 800);
    } catch {
      setFeedback("⚠️ Failed to signal agent");
      setIsDone(false);
    }
  }

  // ── Cursor / label helpers ────────────────────────────────────────

  const screenshotCursor = isDone
    ? "default"
    : mode === "capture"
      ? (isCapturing ? "wait" : "crosshair")
      : (isActing ? "wait" : "pointer");

  const browserLabel = mode === "capture"
    ? (isCapturing
        ? "⟳ Identifying element..."
        : capturedElement
          ? "✅ Element captured — click again to re-capture"
          : "🎯 Click an element to capture its selector")
    : (isActing ? "⟳ Injecting action..." : "Interactive Browser — click to interact");

  // Determine current image source
  // Prioritize CDP screencast (hitlScreenshot) over static screenshot.
  // NOTE: vncUrl is intentionally NOT used to render an iframe here —
  // the noVNC server is only available in production deployments.
  // In local dev, using the iframe results in a blank view.
  // The CDP screencast path works in all environments.
  const currentImage = hitlScreenshot
    ? `data:image/jpeg;base64,${hitlScreenshot}`
    : fallbackScreenshot
      ? `data:image/png;base64,${fallbackScreenshot}`
      : null;

  // ── Render ────────────────────────────────────────────────────────

  return (
    <div className="takeover-panel">

      {/* ── Header ── */}
      <div className="takeover-header">
        <div className="takeover-title-row">
          <div className="takeover-title">
            <span className="takeover-icon">🤚</span>
            <span>Agent Needs Help</span>
            <span className="takeover-step-badge">Step {acStepIndex + 1}</span>
          </div>
          <div className="takeover-header-actions">
            <div className={`takeover-timer ${timeLeft <= 60 ? "urgent" : ""}`}>
              ⏱ {formatTime(timeLeft)}
            </div>
            {onMinimize && (
              <button className="takeover-minimize-btn" onClick={onMinimize} title="Minimize to banner">
                ─
              </button>
            )}
          </div>
        </div>
        <p className="takeover-step-text">{acStep}</p>
        {errorMessage && (
          <p className="takeover-error">
            <span>Last error:</span> {errorMessage}
          </p>
        )}

        {/* ── Mode toggle pill ── */}
        <div className="takeover-mode-toggle" role="group" aria-label="Interaction mode">
          <button
            className={`takeover-mode-btn ${mode === "normal" ? "active" : ""}`}
            onClick={() => switchMode("normal")}
            disabled={isDone}
            title="Normal HITL: click on screenshot to inject mouse clicks"
          >
            🖱 Normal
          </button>
          <button
            className={`takeover-mode-btn ${mode === "capture" ? "active capture" : ""}`}
            onClick={() => switchMode("capture")}
            disabled={isDone}
            title="Click-to-Teach: auto-detect element selector from your click"
          >
            🎯 Click-to-Teach
          </button>
        </div>
      </div>

      <div className="takeover-main-content">
        {/* ── Left Column: Browser ── */}
        <div className="takeover-col-left">
          <div className="takeover-browser-wrap">
            <div className={`takeover-browser-label ${mode === "capture" ? "capture-mode" : ""}`}>
              {hitlScreenshot ? "🎥 Live Screencast (CDP)" : browserLabel}
            </div>
            <div className={`takeover-browser-frame ${isActing || isCapturing ? "acting" : ""} ${mode === "capture" ? "capture-mode" : ""}`}>
              {currentImage ? (
                <div className="takeover-screenshot-container">
                  <img
                    ref={imgRef}
                    src={currentImage}
                    alt="Live browser view"
                    className="takeover-screenshot"
                    onClick={handleImageClick}
                    style={{ cursor: screenshotCursor }}
                  />
                  {/* Dialog Overlay */}
                  {activeDialog && (
                    <div className="takeover-dialog-overlay">
                      <BrowserDialogPanel
                        runId={runId}
                        message={activeDialog.message}
                        dialogType={activeDialog.dialog_type}
                        defaultValue={activeDialog.default_value}
                        onHandled={() => setActiveDialog(null)}
                      />
                    </div>
                  )}
                </div>
              ) : (
                <div className="takeover-no-screenshot">
                  <p>🖥️ Interact directly in the Playwright browser window on your desktop.</p>
                  <p className="takeover-no-screenshot-hint">
                    Your clicks and interactions are automatically recorded and will be captured
                    when you click ✓ Done — Resume Agent.
                  </p>
                </div>
              )}
            </div>
          </div>

          {/* ── NORMAL mode keyboard / scroll strip ── */}
          {mode === "normal" && (
            <div className="takeover-controls">
              <div className="takeover-type-row">
                <input
                  className="takeover-type-input"
                  type="text"
                  placeholder="Type text, then press → or Enter"
                  value={typeText}
                  disabled={isActing || isDone}
                  onChange={(e) => setTypeText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleType(); }}
                />
                <button className="takeover-key-btn" onClick={handleType} disabled={isActing || isDone || !typeText.trim()} title="Send text">↵ Type</button>
                <button className="takeover-key-btn" onClick={() => handleKey("Enter")} disabled={isActing || isDone} title="Press Enter">⏎ Enter</button>
                <button className="takeover-key-btn" onClick={() => handleKey("Tab")} disabled={isActing || isDone} title="Press Tab">⇥ Tab</button>
                <button className="takeover-key-btn" onClick={() => handleKey("Escape")} disabled={isActing || isDone} title="Press Escape">Esc</button>
              </div>
              <div className="takeover-scroll-row">
                <span className="takeover-label">Scroll:</span>
                <button className="takeover-key-btn" onClick={() => handleScroll("up")} disabled={isActing || isDone}>▲ Up</button>
                <button className="takeover-key-btn" onClick={() => handleScroll("down")} disabled={isActing || isDone}>▼ Down</button>
              </div>
            </div>
          )}
        </div>

        {/* ── Right Column: Recording Feed & Capture ── */}
        <div className="takeover-col-right">
          <HitlRecordingFeed actions={hitlActions} />

          {/* ── Capture mode details ── */}
          {mode === "capture" && (
            <div className="takeover-capture-panel">
              {capturedElement ? (
                <>
                  <div className={`takeover-captured-badge ${capturedElement.match_count > 1 ? "ambiguous" : "unique"}`}>
                    <span className="capture-badge-label">
                      <strong>Captured:</strong> <code>{capturedElement.selector}</code>
                    </span>
                  </div>
                  <div className="capture-why-row">
                    <label className="capture-why-label">💬 Why did you click this?</label>
                    <textarea
                      className="takeover-explanation"
                      rows={2}
                      placeholder={`e.g. "Click the Due/Days column header to sort"`}
                      value={teachDescription}
                      disabled={isTeaching || isDone}
                      onChange={(e) => setTeachDescription(e.target.value)}
                    />
                  </div>
                  <button
                    className="takeover-teach-btn"
                    onClick={handleExecuteAndTeach}
                    disabled={isTeaching || isDone || !activeSelector || !teachDescription.trim()}
                  >
                    {isTeaching ? "⟳ Executing..." : "⚡ Execute & Teach KB"}
                  </button>
                </>
              ) : (
                <div className="capture-waiting">
                  👆 Click any element in the screenshot to capture its selector
                </div>
              )}
              {teachFeedback && <p className="takeover-teach-feedback">{teachFeedback}</p>}
            </div>
          )}
        </div>
      </div>

      {/* ── Explanation + Resume ── */}
      <div className="takeover-footer">

        {/* ── FEAT-102: DOM capture reminder banner ── */}
        {showDomCaptureReminder && !domReminderDismissed && (
          <div className="takeover-dom-capture-reminder" role="alert">
            <span className="takeover-dom-capture-reminder-icon">⚠️</span>
            <span className="takeover-dom-capture-reminder-text">
              <strong>No browser actions captured yet.</strong>{" "}
              Please interact with the browser window above (click, type, scroll) before resuming.
              Text-only explanations cannot be used by the agent to learn this workflow.
            </span>
            <button
              className="takeover-dom-capture-reminder-dismiss"
              onClick={() => {
                setDomReminderDismissed(true);
                setShowDomCaptureReminder(false);
              }}
              title="Dismiss this reminder"
            >
              ✕
            </button>
          </div>
        )}

        <div className="takeover-explanation-wrap">
          <label className="takeover-explanation-label">
            💬 What did you do?
            <span className="takeover-explanation-required">
              {explanation.trim() ? " ✓" : " — describing your actions helps the agent learn"}
            </span>
          </label>
          <textarea
            className="takeover-explanation"
            rows={2}
            placeholder='Describe what you did. e.g. "Clicked the CLIENT column header to sort A-Z."'
            value={explanation}
            disabled={isDone}
            onChange={(e) => handleExplanationChange(e.target.value)}
          />
        </div>
        <div className="takeover-actions">
          <button className="takeover-done-btn" onClick={() => handleDone(false)} disabled={isDone}>
            ✓ Done — Resume Agent
          </button>
          <button className="takeover-skip-btn" onClick={() => handleDone(true)} disabled={isDone}>
            ⏭ Skip This Step
          </button>
        </div>
        {feedback && <p className="takeover-feedback">{feedback}</p>}
      </div>
    </div>
  );
}
