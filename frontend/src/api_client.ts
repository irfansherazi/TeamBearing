import { API_BASE_URL } from "./types";
import { authStorage } from "./auth/authStorage";

/**
 * vQA — API Client
 * ==================
 * Utility for making authenticated fetch requests.
 * Sends both Bearer SSO token and X-VQA-API-Key so that whichever
 * auth method the backend validates first will succeed.
 */

// Build-time API key (set via VITE_API_KEY env var in Dockerfile.frontend)
export const VITE_API_KEY = import.meta.env.VITE_API_KEY as string | undefined;

export async function authenticatedFetch(path: string, options: RequestInit = {}): Promise<Response> {
    const token = authStorage.getSsoToken() || authStorage.getAppToken();

    const headers = new Headers(options.headers || {});
    if (token) {
        headers.set('Authorization', `Bearer ${token}`);
    }
    if (VITE_API_KEY) {
        headers.set('X-VQA-API-Key', VITE_API_KEY);
    }

    // Handle relative paths by prepending API_BASE_URL
    const url = (path.startsWith('http') || (API_BASE_URL && path.startsWith(API_BASE_URL)))
        ? path
        : `${API_BASE_URL}${path.startsWith('/') ? '' : '/'}${path}`;

    return fetch(url, { ...options, headers });
}

