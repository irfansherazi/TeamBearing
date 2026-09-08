/**
 * ssoKeepalive.test.ts
 * Unit tests for the SSO keepalive module.
 * Tests cover: successful refresh, network errors, 401/403 logout,
 * stop() clears interval, and double-start prevention.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { createSsoKeepalive } from './ssoKeepalive';

describe('ssoKeepalive', () => {
  let getToken: ReturnType<typeof vi.fn>;
  let setToken: ReturnType<typeof vi.fn>;
  let onSessionInvalid: ReturnType<typeof vi.fn>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.useFakeTimers();
    getToken = vi.fn().mockReturnValue('current-sso-token');
    setToken = vi.fn();
    onSessionInvalid = vi.fn();
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function createKeepalive(overrides = {}) {
    return createSsoKeepalive({
      getToken: getToken as any,
      setToken: setToken as any,
      onSessionInvalid: onSessionInvalid as any,
      baseUrl: 'https://vcapi-test.example.com',
      intervalMs: 15_000,
      ...overrides,
    });
  }

  // --- AC-HAPPY-1: start() begins a 15s interval calling POST /auth/ssoRefresh ---
  it('sends correct request on interval tick', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ssoToken: 'new-token' }),
    });

    const keepalive = createKeepalive();
    keepalive.start();

    // Advance past one interval
    await vi.advanceTimersByTimeAsync(15_000);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe('https://vcapi-test.example.com/auth/ssoRefresh');
    expect(options.method).toBe('POST');
    expect(options.headers['Authorization']).toBe('Bearer current-sso-token');
    expect(options.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(options.body)).toEqual({ spotIdsVisible: [] });

    keepalive.stop();
  });

  // --- AC-HAPPY-2: Successful response with valid ssoToken updates stored token ---
  it('successful refresh updates the token', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ssoToken: 'refreshed-token-abc', otherField: 'ignored' }),
    });

    const keepalive = createKeepalive();
    keepalive.start();

    await vi.advanceTimersByTimeAsync(15_000);

    expect(setToken).toHaveBeenCalledWith('refreshed-token-abc');
    expect(onSessionInvalid).not.toHaveBeenCalled();

    keepalive.stop();
  });

  // --- AC-ERROR-1: Network/temporary errors preserve token and continue interval ---
  it('network failure does not clear the token', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

    const keepalive = createKeepalive();
    keepalive.start();

    await vi.advanceTimersByTimeAsync(15_000);

    expect(setToken).not.toHaveBeenCalled();
    expect(onSessionInvalid).not.toHaveBeenCalled();

    // Verify interval continues — next tick should fire another fetch
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ssoToken: 'recovered-token' }),
    });

    await vi.advanceTimersByTimeAsync(15_000);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(setToken).toHaveBeenCalledWith('recovered-token');

    keepalive.stop();
  });

  // --- AC-ERROR-1 (variant): non-401/403 HTTP error does not clear token ---
  it('500 error does not clear the token', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    });

    const keepalive = createKeepalive();
    keepalive.start();

    await vi.advanceTimersByTimeAsync(15_000);

    expect(setToken).not.toHaveBeenCalled();
    expect(onSessionInvalid).not.toHaveBeenCalled();

    keepalive.stop();
  });

  // --- AC-ERROR-2: 401 triggers logout ---
  it('401 triggers logout', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      json: () => Promise.resolve({}),
    });

    const keepalive = createKeepalive();
    keepalive.start();

    await vi.advanceTimersByTimeAsync(15_000);

    expect(onSessionInvalid).toHaveBeenCalledTimes(1);
    expect(setToken).not.toHaveBeenCalled();
  });

  // --- AC-ERROR-3: 403 triggers logout ---
  it('403 triggers logout', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 403,
      json: () => Promise.resolve({}),
    });

    const keepalive = createKeepalive();
    keepalive.start();

    await vi.advanceTimersByTimeAsync(15_000);

    expect(onSessionInvalid).toHaveBeenCalledTimes(1);
    expect(setToken).not.toHaveBeenCalled();
  });

  // --- AC-ERROR-4: 200 with no valid ssoToken triggers logout ---
  it('200 with missing ssoToken triggers logout', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ someOtherField: 'value' }),
    });

    const keepalive = createKeepalive();
    keepalive.start();

    await vi.advanceTimersByTimeAsync(15_000);

    expect(onSessionInvalid).toHaveBeenCalledTimes(1);
    expect(setToken).not.toHaveBeenCalled();

    keepalive.stop();
  });

  // --- AC-EDGE-1: stop() clears the interval ---
  it('stop() clears the interval', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ssoToken: 'new-token' }),
    });

    const keepalive = createKeepalive();
    keepalive.start();

    // First tick fires
    await vi.advanceTimersByTimeAsync(15_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    keepalive.stop();

    // Advance another interval — should NOT fire
    await vi.advanceTimersByTimeAsync(15_000);
    expect(fetchMock).toHaveBeenCalledTimes(1); // still 1, no new calls
  });

  // --- AC-EDGE-2: calling start() twice does not create duplicate timers ---
  it('calling start() twice does not create duplicate timers', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ssoToken: 'new-token' }),
    });

    const keepalive = createKeepalive();
    keepalive.start();
    keepalive.start(); // Second call should be a no-op

    await vi.advanceTimersByTimeAsync(15_000);

    // Should only fire once, not twice
    expect(fetchMock).toHaveBeenCalledTimes(1);

    keepalive.stop();
  });

  // --- refreshNow() executes immediately ---
  it('refreshNow() executes a refresh immediately', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ ssoToken: 'immediate-token' }),
    });

    const keepalive = createKeepalive();

    await keepalive.refreshNow();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(setToken).toHaveBeenCalledWith('immediate-token');
  });

  // --- No fetch if token is null ---
  it('skips refresh if no token is available', async () => {
    getToken.mockReturnValue(null);

    const keepalive = createKeepalive();
    keepalive.start();

    await vi.advanceTimersByTimeAsync(15_000);

    expect(fetchMock).not.toHaveBeenCalled();

    keepalive.stop();
  });
});
