// playwright/utils/Imail_Test_Email_Check.ts
//
// Utility for verifying email notifications via a Google Apps Script web app.
// The Apps Script searches the testing Gmail account for messages matching
// a recipient + search term, returning a JSON result.
// Supports parsing of multiple vCreative notification types from subject lines.

/**
 * The deployed Apps Script web-app URL.
 * Set via EMAIL_CHECKER_URL env var or uses the default test script deployment.
 */
export const EMAIL_CHECKER_URL = process.env.EMAIL_CHECKER_URL || 'https://script.google.com/macros/s/AKfycbwwJ82CaR-nFgZL93Tknrx3ppuDbpWOdL57B-_-yLt-NATTDfVJDRWpQF9mml4rqZofag/exec';

// ---------------------------------------------------------------------------
// Notification Types
// ---------------------------------------------------------------------------

/** Known vCreative email notification types, derived from subject-line patterns. */
export type NotificationType =
    | 'new_spot'        // "New Spot: <Client>"
    | 'spot_approved'   // "Spot Approved: <Client> - <SpotTitle>"
    | 'spot_update'     // "Spot: <Client> <Event>"
    | 'blog'            // "Blog: <Client> - <Title>"
    | 'voice'           // "Voice: <Client> - <Details>"
    | 'unread_blogs'    // "Unread Blogs: <Title>..."
    | 'weekly_summary'  // "Weekly Summary"
    | 'unknown';

/** Structured data extracted from an email subject line. */
export interface ParsedSubject {
    notificationType: NotificationType;
    /** Client name when identifiable (e.g. "Hanso Foundation"). */
    client?: string;
    /** Additional detail: event, title, or identifier depending on type. */
    detail?: string;
}

/**
 * Parse a vCreative notification subject into structured data.
 * Handles all known subject patterns; falls back to `unknown` for unrecognized formats.
 */
export function parseEmailSubject(subject: string): ParsedSubject {
    if (!subject) return { notificationType: 'unknown' };

    const trimmed = subject.trim();

    // "Weekly Summary" — no client/detail
    if (/^Weekly Summary$/i.test(trimmed)) {
        return { notificationType: 'weekly_summary' };
    }

    // "Unread Blogs: <Title> and more..." or "Unread Blogs: <Title>"
    const unreadBlogs = trimmed.match(/^Unread Blogs:\s*(.+)$/i);
    if (unreadBlogs) {
        return {
            notificationType: 'unread_blogs',
            detail: unreadBlogs[1].trim(),
        };
    }

    // "New Spot: <Client>"
    const newSpot = trimmed.match(/^New Spot:\s*(.+)$/i);
    if (newSpot) {
        return {
            notificationType: 'new_spot',
            client: newSpot[1].trim(),
        };
    }

    // "Spot Approved: <Client> - <SpotTitle>"
    const spotApproved = trimmed.match(/^Spot Approved:\s*(.+?)\s*-\s*(.+)$/i);
    if (spotApproved) {
        return {
            notificationType: 'spot_approved',
            client: spotApproved[1].trim(),
            detail: spotApproved[2].trim(),
        };
    }

    // "Blog: <Client> - <Title>"
    const blog = trimmed.match(/^Blog:\s*(.+?)\s*-\s*(.+)$/i);
    if (blog) {
        return {
            notificationType: 'blog',
            client: blog[1].trim(),
            detail: blog[2].trim(),
        };
    }

    // "Voice: <Client> - <Details>"
    const voice = trimmed.match(/^Voice:\s*(.+?)\s*-\s*(.+)$/i);
    if (voice) {
        return {
            notificationType: 'voice',
            client: voice[1].trim(),
            detail: voice[2].trim(),
        };
    }

    // "Spot: <Client> <Event>" — catch-all for spot updates (Revised, Traffic change, etc.)
    const spotUpdate = trimmed.match(/^Spot:\s*(.+)$/i);
    if (spotUpdate) {
        return {
            notificationType: 'spot_update',
            // The value contains both client and event but we can't reliably
            // split them without knowing client names. Store as combined detail.
            detail: spotUpdate[1].trim(),
        };
    }

    return { notificationType: 'unknown', detail: trimmed };
}

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

/** Shape of the JSON returned by the Apps Script endpoint, enriched with parsed fields. */
export interface EmailCheckResult {
    found: boolean;
    subject?: string;
    body?: string;
    timestamp?: string;
    /** Parsed notification type from the subject line. */
    notificationType?: NotificationType;
    /** Parsed client name (when identifiable). */
    client?: string;
    /** Parsed detail (event, title, identifier). */
    detail?: string;
    message?: string;
    error?: string;
}

export interface CheckEmailOptions {
    /** Override the Apps Script URL (useful for testing). */
    url?: string;
}

export interface WaitForEmailOptions extends CheckEmailOptions {
    /** Maximum time to wait in milliseconds. Default: 90 000 (90s). */
    timeout?: number;
    /** Polling interval in milliseconds. Default: 10 000 (10s). */
    interval?: number;
}

// ---------------------------------------------------------------------------
// Core functions
// ---------------------------------------------------------------------------

/**
 * Single-shot call to the Apps Script endpoint.
 * Returns the parsed JSON response indicating whether a matching email was found.
 * When an email is found, the subject is automatically parsed into structured fields.
 *
 * @param recipient  - The email address the notification was sent to.
 * @param searchTerm - A search term for Gmail (client name, spot title, etc.).
 *                     Sent as the `spotTitle` query param for Apps Script backward compat.
 * @param options    - Optional overrides.
 */
export async function checkEmailReceived(
    recipient: string,
    searchTerm: string,
    options: CheckEmailOptions = {},
): Promise<EmailCheckResult> {
    const baseUrl = options.url || EMAIL_CHECKER_URL;
    if (!baseUrl) {
        throw new Error(
            'EMAIL_CHECKER_URL is not set. Provide it as an env var or pass options.url.',
        );
    }

    // Wire param stays "spotTitle" for backward compat with the Apps Script
    const params = new URLSearchParams({ recipient, spotTitle: searchTerm });
    const fullUrl = `${baseUrl}?${params.toString()}`;

    const response = await fetch(fullUrl, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        // Apps Script redirects on exec — follow them
        redirect: 'follow',
    });

    if (!response.ok) {
        return {
            found: false,
            error: `HTTP ${response.status}: ${response.statusText}`,
        };
    }

    const data: EmailCheckResult = await response.json();

    // Enrich with parsed subject data when an email was found
    if (data.found && data.subject) {
        const parsed = parseEmailSubject(data.subject);
        data.notificationType = parsed.notificationType;
        data.client = parsed.client;
        data.detail = parsed.detail;
    }

    return data;
}

/**
 * Poll the Apps Script endpoint until a matching email is found or the timeout is reached.
 * Logs each attempt for debugging visibility.
 *
 * @param recipient  - The email address the notification was sent to.
 * @param searchTerm - A search term for Gmail (client name, spot title, etc.).
 * @param options    - Timeout and interval overrides.
 */
export async function waitForEmail(
    recipient: string,
    searchTerm: string,
    options: WaitForEmailOptions = {},
): Promise<EmailCheckResult> {
    const timeout = options.timeout ?? 90_000;
    const interval = options.interval ?? 10_000;
    const startTime = Date.now();
    let attempt = 0;

    while (Date.now() - startTime < timeout) {
        attempt++;
        console.log(
            `📧 [waitForEmail] Attempt ${attempt} — checking for "${searchTerm}" → ${recipient}`,
        );

        try {
            const result = await checkEmailReceived(recipient, searchTerm, options);

            if (result.found) {
                console.log(
                    `✅ [waitForEmail] Email found on attempt ${attempt}: [${result.notificationType}] "${result.subject}"`,
                );
                return result;
            }
        } catch (err) {
            console.warn(`⚠️ [waitForEmail] Attempt ${attempt} error:`, err);
        }

        // Wait before next poll (but don't wait past the deadline)
        const remaining = timeout - (Date.now() - startTime);
        if (remaining > 0) {
            await new Promise((resolve) =>
                setTimeout(resolve, Math.min(interval, remaining)),
            );
        }
    }

    console.log(
        `❌ [waitForEmail] Timed out after ${attempt} attempts (${(timeout / 1000).toFixed(0)}s)`,
    );
    return { found: false, message: `Timed out after ${attempt} attempts` };
}

/**
 * Extract an array of HTTP/HTTPS URLs from a given HTML/text body string.
 * @param body The email body from which to extract links.
 * @returns Array of URLs.
 */
export function extractUrlsFromBody(body: string): string[] {
    if (!body) return [];
    // Basic regex to find http/https URLs.
    const urlRegex = /(https?:\/\/[^\s"'>]+)/g;
    const matches = body.match(urlRegex) || [];
    // Remove trailing punctuation that might accidentally be matched
    return matches.map((url) => url.replace(/[.,;)]+$/, ''));
}
