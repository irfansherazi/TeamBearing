/**
 * vQA — Execution Hook
 * =====================
 * Module: frontend/src/hooks/useExecution.ts
 *
 * Custom React hook for managing the vQA test execution lifecycle.
 * Handles:
 *
 * - Sending execute requests to the backend API
 * - Polling run status for progress updates
 * - Coordinating with useWebSocket for real-time logs
 * - Health check for system status display
 *
 * Architecture Context:
 * This hook encapsulates ALL API communication so components
 * only deal with typed state and callback functions.
 */

import { useCallback, useState } from "react";
import type {
  CredentialCheckResponse,
  ExecuteRequest,
  ExecuteResponse,
  HealthResponse,
  StatusResponse,
} from "../types";
import { API_BASE_URL } from "../types";
import { authenticatedFetch } from "../api_client";


/**
 * Payload for the Computer-Use loop endpoint (POST /execute-cu).
 * Independent of ExecuteRequest — the CU loop bypasses the LangGraph pipeline
 * and takes a minimal payload.
 */
export interface ExecuteCURequest {
  jira_ticket_id: string;
  target_url: string;
  /**
   * Login email. Leave empty to have the backend resolve credentials from
   * `user_role` via the role registry. Explicit values here (Ghost Login
   * admin creds, Custom Credentials) take precedence.
   */
  admin_email: string;
  admin_password: string;
  /**
   * Test-As role key (e.g. 'account_executive'). Used by the backend to
   * look up credentials when `admin_email` is empty.
   */
  user_role?: string;
  product?: string;
  max_iterations?: number;
  max_wall_seconds?: number;
  /**
   * AC step texts (from /preview-steps). When provided, the CU runner emits
   * ac_progress WebSocket messages that update the step-row status pills in
   * the UI. Empty/omitted = no step progress broadcasts (status stays
   * "Waiting" for all rows).
   */
  override_steps?: string[];
}

/**
 * Request payload for POST /run/{run_id}/save-as-test.
 * Persists a successfully completed Computer-Use run as a Playwright .spec.ts
 * file on disk. Backend rejects with 409 for runs whose terminal_status != "done".
 */
export interface SaveRunAsTestRequest {
  name: string;
  product?: string;
  user_role?: string;
}

/** Response from POST /run/{run_id}/save-as-test. */
export interface SaveRunAsTestResponse {
  slug: string;
  file_path: string;
  click_at_count: number;
  tool_call_count: number;
  /** Present when the saved test was auto-committed and a PR was opened. */
  pr_url?: string | null;
  branch?: string | null;
  commit_hash?: string | null;
  /** Set when the file saved but PR creation failed (missing token, etc.). */
  pr_error?: string | null;
}

/** Return type of the useExecution hook */
export interface UseExecutionReturn {
  isLoading: boolean;
  error: string | null;
  executeResponse: ExecuteResponse | null;
  statusResponse: StatusResponse | null;
  healthResponse: HealthResponse | null;
  startExecution: (request: ExecuteRequest) => Promise<ExecuteResponse | null>;
  /** Start a Computer-Use loop run (feature/computer-use-loop branch). */
  startComputerUseExecution: (request: ExecuteCURequest) => Promise<ExecuteResponse | null>;
  /**
   * Persist a completed CU run as a Playwright .spec.ts. Only succeeds for
   * runs whose terminal_status == "done"; other terminal states return null
   * and populate `error`.
   */
  saveRunAsTest: (runId: string, request: SaveRunAsTestRequest) => Promise<SaveRunAsTestResponse | null>;
  pollStatus: (runId: string) => Promise<StatusResponse | null>;
  checkHealth: () => Promise<HealthResponse | null>;
  /** Check credential status for a Jira ticket (debounced by caller) */
  checkTicketCredentials: (ticketId: string) => Promise<CredentialCheckResponse | null>;
  /** Pause a running test run */
  pauseExecution: (runId: string) => Promise<boolean>;
  /** Resume a paused test run, optionally with updated steps */
  resumeExecution: (runId: string, overrideSteps?: string[]) => Promise<boolean>;
  clearError: () => void;
  /** Clear the current run result so the UI returns to idle state */
  resetRun: () => void;
}


/**
 * Custom hook for managing vQA test execution.
 *
 * Provides functions for starting test runs, polling status, and
 * checking system health, with loading and error state management.
 *
 * @returns {UseExecutionReturn} Execution state and API functions.
 *
 * @example
 * ```tsx
 * const { startExecution, pollStatus, isLoading, error } = useExecution();
 *
 * const handleStart = async () => {
 *   const response = await startExecution({
 *     jira_ticket_id: "VC2-8967",
 *     role: "account_executive",
 *     target_url: "https://two-test.vcreative.net",
 *     mode: "interactive",
 *   });
 *   if (response) {
 *     console.log("Run started:", response.run_id);
 *   }
 * };
 * ```
 */
export function useExecution(): UseExecutionReturn {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [executeResponse, setExecuteResponse] = useState<ExecuteResponse | null>(null);
  const [statusResponse, setStatusResponse] = useState<StatusResponse | null>(null);
  const [healthResponse, setHealthResponse] = useState<HealthResponse | null>(null);

  /**
   * Start a new test execution via POST /execute.
   *
   * @param request - The execution parameters.
   * @returns The execute response, or null if the request failed.
   */
  const startExecution = useCallback(async (
    request: ExecuteRequest
  ): Promise<ExecuteResponse | null> => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const errorMsg = errorData.detail || `HTTP ${response.status}: ${response.statusText}`;
        throw new Error(errorMsg);
      }

      const data: ExecuteResponse = await response.json();
      setExecuteResponse(data);
      return data;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  /**
   * Start a Computer-Use loop run via POST /execute-cu.
   *
   * The CU loop bypasses the LangGraph pipeline entirely — it drives the
   * browser with a minimal screenshot → Claude → tool loop.
   */
  const startComputerUseExecution = useCallback(async (
    request: ExecuteCURequest
  ): Promise<ExecuteResponse | null> => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/execute-cu`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const errorMsg = errorData.detail || `HTTP ${response.status}: ${response.statusText}`;
        throw new Error(errorMsg);
      }

      const data: ExecuteResponse = await response.json();
      setExecuteResponse(data);
      return data;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  /**
   * Persist a completed Computer-Use run as a Playwright .spec.ts file.
   *
   * The backend does the codegen (transcript → Playwright, LLM-inferred
   * selectors for click_at). This hook is a thin POST wrapper. Sets the
   * shared `error` state on failure so the calling component can render
   * the reason inline (e.g. "Run did not complete successfully").
   */
  const saveRunAsTest = useCallback(async (
    runId: string,
    request: SaveRunAsTestRequest
  ): Promise<SaveRunAsTestResponse | null> => {
    setError(null);
    try {
      const response = await authenticatedFetch(
        `${API_BASE_URL}/run/${encodeURIComponent(runId)}/save-as-test`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(request),
        },
      );
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        const errorMsg = errorData.detail || `HTTP ${response.status}: ${response.statusText}`;
        throw new Error(errorMsg);
      }
      return (await response.json()) as SaveRunAsTestResponse;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setError(msg);
      return null;
    }
  }, []);

  /**
   * Poll the status of a run via GET /status/{run_id}.
   *
   * @param runId - The run to check.
   * @returns The status response, or null if the request failed.
   */
  const pollStatus = useCallback(async (
    runId: string
  ): Promise<StatusResponse | null> => {
    try {
      const response = await fetch(`${API_BASE_URL}/status/${runId}`);

      if (!response.ok) {
        return null;
      }

      const data: StatusResponse = await response.json();
      setStatusResponse(data);
      return data;
    } catch {
      return null;
    }
  }, []);

  /**
   * Check system health via GET /health.
   *
   * @returns The health response, or null if unreachable.
   */
  const checkHealth = useCallback(async (): Promise<HealthResponse | null> => {
    try {
      const response = await fetch(`${API_BASE_URL}/health`);

      if (!response.ok) {
        setHealthResponse({
          status: "degraded",
          mode: "interactive",
          version: "?",
          checks: { jira: "error", s3: "error", bedrock: "error" },
          uptime_seconds: 0,
          active_runs: 0,
          total_runs_completed: 0
        });
        return null;
      }

      const data: HealthResponse = await response.json();
      setHealthResponse(data);
      return data;
    } catch {
      setHealthResponse(null);
      return null;
    }
  }, []);

  /** Clear the error state. */
  const clearError = useCallback(() => setError(null), []);

  /** Reset the current run — clears executeResponse and statusResponse. */
  const resetRun = useCallback(() => {
    setExecuteResponse(null);
    setStatusResponse(null);
    setError(null);
  }, []);

  /**
   * Check credential status for a Jira ticket without starting a run.
   * Call this debounced when ticket ID input changes.
   */
  const checkTicketCredentials = useCallback(async (
    ticketId: string
  ): Promise<CredentialCheckResponse | null> => {
    if (!ticketId.trim()) return null;
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/ticket/${ticketId.trim().toUpperCase()}/credentials`);
      if (!response.ok) return null;
      return await response.json() as CredentialCheckResponse;
    } catch {
      return null;
    }
  }, []);

  /**
   * Pause a running test run.
   */
  const pauseExecution = useCallback(async (runId: string): Promise<boolean> => {
    try {
      const response = await authenticatedFetch(`${API_BASE_URL}/run/${runId}/pause`, {
        method: "POST",
      });
      return response.ok;
    } catch (err) {
      console.error("Failed to pause execution:", err);
      return false;
    }
  }, []);

  /**
   * Resume a paused test run.
   */
  const resumeExecution = useCallback(async (runId: string, overrideSteps?: string[]): Promise<boolean> => {
    try {
      const body = overrideSteps ? JSON.stringify({ override_steps: overrideSteps }) : undefined;
      const response = await authenticatedFetch(`${API_BASE_URL}/run/${runId}/resume`, {
        method: "POST",
        headers: body ? { "Content-Type": "application/json" } : {},
        body,
      });
      return response.ok;
    } catch (err) {
      console.error("Failed to resume execution:", err);
      return false;
    }
  }, []);

  return {
    isLoading,
    error,
    executeResponse,
    statusResponse,
    healthResponse,
    startExecution,
    startComputerUseExecution,
    saveRunAsTest,
    pollStatus,
    checkHealth,
    checkTicketCredentials,
    pauseExecution,
    resumeExecution,
    clearError,
    resetRun,
  };
}
