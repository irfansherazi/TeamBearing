/**
 * vQA — Session API Client
 * =========================
 * Module: frontend/src/api/session.ts
 *
 * Typed clients for the per-user session isolation endpoints (Phase 6).
 *
 *   POST /api/session/start    — bootstrap a new session, receives vqa_session cookie
 *   POST /api/session/rebind   — re-issue cookie with fresh Max-Age (AC-ASYNC-1)
 *   DELETE /api/session/{id}   — admin-terminate a session
 *   GET  /api/session/{id}/status — read session state
 */

import { API_BASE_URL } from "../types";
import { authenticatedFetch } from "../api_client";

// ---------------------------------------------------------------------------
// Response types
// ---------------------------------------------------------------------------

export interface SessionStartResponse {
  session_id: string;
  state: string;
  /** ISO-8601 timestamp when the JWT should be rebound */
  next_rebind_by: string;
  /** Per-session noVNC URL: /vnc/<session_id>/vnc.html?path=websockify/<session_id> */
  novnc_url: string | null;
  display_num: number;
}

export interface SessionRebindResponse {
  session_id: string;
  state: string;
  next_rebind_by: string;
}

export interface SessionStatusResponse {
  session_id: string;
  state: string;
  jwt_valid_until: number;
  active_run_ids: string[];
  novnc_url: string | null;
  display_num: number;
}

// ---------------------------------------------------------------------------
// API clients
// ---------------------------------------------------------------------------

/**
 * Bootstrap a new session.  Sends the JWT as `Authorization: Bearer <token>`.
 * On success, the server sets the `vqa_session` HttpOnly cookie automatically
 * (browser stores it; subsequent calls carry it automatically).
 *
 * Returns the session bootstrap payload including `novnc_url` and
 * `next_rebind_by` (used to schedule `useRebindTimer`).
 */
export async function startSession(token: string): Promise<SessionStartResponse> {
  // API_BASE_URL already ends in /api; the backend router is mounted at /api
  // and declares /session/*, so the path here must NOT include another /api.
  const response = await fetch(`${API_BASE_URL}/session/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    credentials: "include", // include cookies in the response
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw Object.assign(new Error(detail.detail ?? "Session start failed"), {
      status: response.status,
    });
  }
  return response.json() as Promise<SessionStartResponse>;
}

/**
 * Re-issue the session cookie with fresh `Max-Age` derived from a refreshed JWT.
 * Called by `useRebindTimer` at `next_rebind_by`.
 */
export async function rebindSession(token: string): Promise<SessionRebindResponse> {
  const response = await authenticatedFetch("/session/rebind", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    credentials: "include",
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw Object.assign(new Error(detail.detail ?? "Session rebind failed"), {
      status: response.status,
    });
  }
  return response.json() as Promise<SessionRebindResponse>;
}

/**
 * Admin-terminate a session by ID.  Returns 204 on success.
 */
export async function deleteSession(sessionId: string): Promise<void> {
  const response = await authenticatedFetch(`/session/${sessionId}`, {
    method: "DELETE",
    credentials: "include",
  });

  if (!response.ok && response.status !== 204) {
    throw new Error(`Failed to delete session ${sessionId}: ${response.status}`);
  }
}

/**
 * Fetch the current state of a session.
 */
export async function getSessionStatus(sessionId: string): Promise<SessionStatusResponse> {
  const response = await authenticatedFetch(`/session/${sessionId}/status`, {
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error(`Failed to get session status: ${response.status}`);
  }
  return response.json() as Promise<SessionStatusResponse>;
}
