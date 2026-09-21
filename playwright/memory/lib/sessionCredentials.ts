export const DEFAULT_RITUAL_ADMIN_EMAIL = 'syed@vcreativeinc.com';

export interface MemoryWatchCredentials {
    storageUser: string;
    email: string;
    password: string;
}

/**
 * Strip wrapping quotes from an env value (dotenvx can keep them).
 *
 * @param value - Raw env string
 * @returns Unquoted trimmed string
 */
export function unquoteEnvValue(value: string): string {
    const trimmed = (value ?? '').trim();
    if (trimmed.length < 2) {
        return trimmed;
    }
    const start = trimmed[0];
    const end = trimmed[trimmed.length - 1];
    if ((start === '"' && end === '"') || (start === "'" && end === "'")) {
        return trimmed.slice(1, -1);
    }
    return trimmed;
}

/**
 * Storage-state file stem from an email or role shorthand.
 *
 * @param email - Login email or username
 * @returns Safe file stem
 */
export function storageUserFromEmail(email: string): string {
    const raw = (email ?? '').trim();
    if (!raw.includes('@')) {
        return raw || 'user';
    }
    const local = raw.split('@')[0] ?? 'user';
    return local.replace(/[^A-Za-z0-9]+/g, '_') || 'user';
}

/**
 * Resolve who Memory Watch should log in as.
 *
 * Ritual needs a vCreative admin (`firm_id` 1) so the Angular ghost
 * panel is on the top bar. Demo role accounts do not have it.
 *
 * @param ritual - True for qo-open-close-snapshot
 * @returns Storage stem, email, and password
 */
export function resolveMemoryWatchCredentials(ritual: boolean): MemoryWatchCredentials {
    const envEmail = unquoteEnvValue(process.env.MEMORY_WATCH_EMAIL ?? '');
    const envPassword = unquoteEnvValue(process.env.MEMORY_WATCH_PASSWORD ?? '');
    const shared = unquoteEnvValue(process.env.SHARED_TEST_PASSWORD ?? '');
    if (ritual) {
        const email = envEmail || DEFAULT_RITUAL_ADMIN_EMAIL;
        if (!envPassword) {
            throw new Error(
                'Set MEMORY_WATCH_PASSWORD in .env to log in as the vCreative admin for ghosting.'
            );
        }
        return {
            storageUser: storageUserFromEmail(email),
            email,
            password: envPassword,
        };
    }
    return {
        storageUser: 'DemoProdDirector',
        email: envEmail || 'DemoProdDirector',
        password: envPassword || shared || 'Ep!cVCteam2026$',
    };
}
