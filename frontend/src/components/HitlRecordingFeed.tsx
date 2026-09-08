/**
 * vQA — HitlRecordingFeed Component
 * ==================================
 * Module: frontend/src/components/HitlRecordingFeed.tsx
 *
 * Displays a real-time list of human actions captured during takeover.
 * Allows the user to see what's being recorded for the agent's learning.
 */

import type { HitlActionRecord } from "../types";

interface HitlRecordingFeedProps {
  actions: HitlActionRecord[];
}

export function HitlRecordingFeed({ actions }: HitlRecordingFeedProps) {
  if (actions.length === 0) {
    return (
      <div className="hitl-action-feed empty">
        <p>No actions recorded yet. Interact with the browser to start recording.</p>
      </div>
    );
  }

  return (
    <div className="hitl-action-feed">
      <div className="feed-header">
        <span className="feed-title">🔴 Recorded Actions</span>
        <span className="feed-count">{actions.length} steps</span>
      </div>
      <div className="feed-list">
        {actions.map((action, i) => (
          <div key={i} className="feed-item">
            <span className="feed-item-index">{i + 1}</span>
            <div className="feed-item-content">
              <span className="feed-item-type">{action.event_type}</span>
              <span className="feed-item-desc">
                {action.event_type === "click" && (
                  <>on <code>{action.best_selector?.substring(0, 30)}</code></>
                )}
                {action.event_type === "type" && (
                  <>typed "{action.text}"</>
                )}
                {action.event_type === "key" && (
                  <>pressed {action.key}</>
                )}
                {action.event_type === "scroll" && (
                  <>scrolled {action.direction}</>
                )}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
