/**
 * vQA — Agent Thinking Card
 * ==========================
 * Module: frontend/src/components/ThinkingCard.tsx
 *
 * Displays the agent's live reasoning text with a typewriter animation
 * and animated gradient border while it is planning the next action.
 *
 * Shown between steps (when isThinking = true), hidden once an action
 * executes and the corresponding step card takes its place.
 */

import { useEffect, useRef, useState } from "react";

interface ThinkingCardProps {
  text: string;
  acStep: number;
  acTotal: number;
  isThinking: boolean;
}

/**
 * Animated "Agent Thinking..." card.
 *
 * Features:
 * - Pulsing 🧠 brain icon
 * - Typewriter reveal of reasoning text
 * - Animated gradient border (cycling hues)
 * - Smooth fade-in/out
 */
export function ThinkingCard({ text, acStep, acTotal, isThinking }: ThinkingCardProps) {
  const [displayedText, setDisplayedText] = useState("");
  const [visible, setVisible] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const charIndexRef = useRef(0);

  // Fade in/out
  useEffect(() => {
    if (isThinking) {
      setVisible(true);
    } else {
      // Give a moment before hiding so final state is readable
      const t = setTimeout(() => setVisible(false), 600);
      return () => clearTimeout(t);
    }
  }, [isThinking]);

  // Typewriter animation: reset and replay whenever text changes
  useEffect(() => {
    if (!text) return;

    // Clear existing interval
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }

    charIndexRef.current = 0;
    setDisplayedText("");

    intervalRef.current = setInterval(() => {
      charIndexRef.current += 3; // reveal 3 chars per tick for snappiness
      const slice = text.slice(0, charIndexRef.current);
      setDisplayedText(slice);

      if (charIndexRef.current >= text.length) {
        if (intervalRef.current) clearInterval(intervalRef.current);
      }
    }, 16); // ~60fps

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [text]);

  if (!visible && !isThinking) return null;

  const progressLabel = acTotal > 0 ? `Step ${acStep} / ${acTotal}` : "";

  return (
    <div className={`thinking-card ${isThinking ? "thinking-active" : "thinking-fading"}`}>
      <div className="thinking-header">
        <div className="thinking-title">
          <span className="thinking-brain">🧠</span>
          <span className="thinking-label">Agent Thinking</span>
          <span className="thinking-dots">
            <span /><span /><span />
          </span>
        </div>
        {progressLabel && (
          <span className="thinking-progress">{progressLabel}</span>
        )}
      </div>
      <div className="thinking-body">
        <p className="thinking-text">
          {displayedText}
          <span className="thinking-cursor" />
        </p>
      </div>
    </div>
  );
}
