/**
 * vQA — GlobalHitlBanner Component
 * ================================
 * Module: frontend/src/components/GlobalHitlBanner.tsx
 *
 * A prominent, persistent notification banner that appears at the top of
 * the dashboard when the agent initiates a human takeover.
 *
 * On mount (when HITL fires):
 *   1. Fires a browser Notification (visible even when on another tab)
 *   2. Plays a short audio alert via Web Audio API (no file dependency)
 *   3. Renders the fixed top banner with a pulsing attention animation
 */

import { useEffect, useRef } from "react";

interface GlobalHitlBannerProps {
  isVisible: boolean;
  stepText: string;
  onClick: () => void;
}

/** Play a short attention-grabbing beep using Web Audio API (no file needed). */
function playAlertBeep() {
  try {
    const ctx = new AudioContext();
    const beepSequence = [880, 660, 880]; // frequencies in Hz
    let time = ctx.currentTime;

    beepSequence.forEach((freq) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, time);
      gain.gain.setValueAtTime(0.25, time);
      gain.gain.exponentialRampToValueAtTime(0.001, time + 0.18);
      osc.start(time);
      osc.stop(time + 0.2);
      time += 0.22;
    });

    // Close context after sounds finish
    setTimeout(() => ctx.close(), 1000);
  } catch {
    // Web Audio not available — silent fallback
  }
}

/** Fire a browser Notification if permission is granted. */
function fireDesktopNotification(stepText: string, onClick: () => void) {
  if (!("Notification" in window)) return;

  const doNotify = () => {
    const n = new Notification("🤚 vQA needs your help!", {
      body: stepText || "The agent is stuck and requires human intervention.",
      icon: "/favicon.ico",
      requireInteraction: true,
      tag: "vqa-hitl", // replaces previous notification with same tag
    });
    n.onclick = () => {
      window.focus();
      onClick();
      n.close();
    };
  };

  if (Notification.permission === "granted") {
    doNotify();
  } else if (Notification.permission !== "denied") {
    Notification.requestPermission().then((perm) => {
      if (perm === "granted") doNotify();
    });
  }
}

export function GlobalHitlBanner({ isVisible, stepText, onClick }: GlobalHitlBannerProps) {
  const firedRef = useRef(false);
  const titleBlinkRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const originalTitleRef = useRef(document.title);

  useEffect(() => {
    if (isVisible && !firedRef.current) {
      firedRef.current = true;
      playAlertBeep();
      fireDesktopNotification(stepText, onClick);

      // Blink the page title as a cross-tab signal
      originalTitleRef.current = document.title;
      let blink = false;
      titleBlinkRef.current = setInterval(() => {
        document.title = blink ? originalTitleRef.current : "🤚 ACTION REQUIRED — vQA";
        blink = !blink;
      }, 900);
    }

    if (!isVisible) {
      firedRef.current = false;
      if (titleBlinkRef.current) {
        clearInterval(titleBlinkRef.current);
        titleBlinkRef.current = null;
        document.title = originalTitleRef.current;
      }
    }

    return () => {
      if (titleBlinkRef.current) {
        clearInterval(titleBlinkRef.current);
        document.title = originalTitleRef.current;
      }
    };
  }, [isVisible, stepText, onClick]);

  if (!isVisible) return null;

  return (
    <div
      className="global-hitl-banner"
      onClick={onClick}
      role="alert"
      aria-live="assertive"
      aria-label="Agent needs human intervention — click to open takeover panel"
    >
      <div className="banner-content">
        <span className="banner-icon banner-icon-pulse">🤚</span>
        <div className="banner-text-wrap">
          <span className="banner-title">⚠ Agent Needs Your Help — Intervention Required</span>
          <span className="banner-step-text">{stepText || "Click here to take over and help the agent continue."}</span>
        </div>
      </div>
      <div className="banner-actions">
        <button className="banner-btn banner-btn-urgent">
          Open Takeover Panel →
        </button>
      </div>
    </div>
  );
}
