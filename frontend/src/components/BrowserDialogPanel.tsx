/**
 * vQA — BrowserDialogPanel Component
 * ===================================
 * Module: frontend/src/components/BrowserDialogPanel.tsx
 *
 * Intercepts native browser dialogs (alert, confirm, prompt) and shows 
 * them in the UI with Accept/Dismiss buttons.
 */

import { useState } from "react";
import { authenticatedFetch } from "../api_client";

interface BrowserDialogPanelProps {
  runId: string;
  message: string;
  dialogType: string;
  defaultValue?: string;
  onHandled: () => void;
}

export function BrowserDialogPanel({
  runId,
  message,
  dialogType,
  defaultValue = "",
  onHandled,
}: BrowserDialogPanelProps) {
  const [promptText, setPromptText] = useState(defaultValue);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleResponse(accept: boolean) {
    setIsSubmitting(true);
    try {
      const res = await authenticatedFetch(`/runs/${runId}/human-takeover/dialog`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accept, prompt_text: promptText }),
      });
      if (res.ok) {
        onHandled();
      }
    } catch (err) {
      console.error("Failed to handle dialog response:", err);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="browser-dialog-panel">
      <div className="dialog-header">
        <span className="dialog-icon">💬</span>
        <span className="dialog-title">Browser {dialogType}</span>
      </div>
      <div className="dialog-body">
        <p className="dialog-message">{message}</p>
        {dialogType === "prompt" && (
          <input
            className="dialog-input"
            type="text"
            value={promptText}
            onChange={(e) => setPromptText(e.target.value)}
            autoFocus
          />
        )}
      </div>
      <div className="dialog-actions">
        {dialogType !== "alert" && (
          <button
            className="dialog-btn dismiss"
            onClick={() => handleResponse(false)}
            disabled={isSubmitting}
          >
            Cancel
          </button>
        )}
        <button
          className="dialog-btn accept"
          onClick={() => handleResponse(true)}
          disabled={isSubmitting}
        >
          {dialogType === "alert" ? "OK" : "Accept"}
        </button>
      </div>
    </div>
  );
}
