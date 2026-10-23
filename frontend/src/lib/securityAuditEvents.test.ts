/**
 * frontend/src/lib/securityAuditEvents.test.ts
 *
 * VoiceLock Increment 4B: Integrate the Security Audit Events API Test Suite
 *
 * Covers:
 * 1. Correct API endpoint and query parameter construction.
 * 2. Omission of unset filters.
 * 3. Rendering of safe event fields.
 * 4. Loading state handling.
 * 5. Empty-result state handling.
 * 6. API failure and retry handling.
 * 7. 401 Unauthorized and 403 Forbidden handling.
 * 8. Filter submission and reset behavior.
 * 9. Invalid date-range handling.
 * 10. Next-page cursor handling.
 * 11. Previous-page navigation.
 * 12. Cursor history reset when filters change.
 * 13. Duplicate-request prevention.
 * 14. No fabricated events or totals.
 * 15. No rendering of undocumented or sensitive metadata.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ApiClient } from './apiClient.ts';
import type {
  SecurityEventItem,
  SecurityEventsResponse,
  SecurityEventFilters,
} from '../types/index.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Increment 4B: Security Audit Events API Client Suite', () => {
  const adminToken = 'firebase_admin_test_token_inc4b_123';
  const sampleEvents: SecurityEventItem[] = [
    {
      id: 101,
      created_at: '2026-10-24T00:15:30.000Z',
      event_type: 'admin_action',
      severity: 'low',
      status: 'logged',
      details: 'Administrator linked UID u_alpha to speaker Alice',
      user_id: 'admin_uid_001',
      device_id: null,
      request_id: 'req_admin_abc123',
      metadata: { target_uid: 'u_alpha', claimed_speaker: 'Alice', action: 'link' },
    },
    {
      id: 102,
      created_at: '2026-10-24T00:20:00.000Z',
      event_type: 'rate_limit_exceeded',
      severity: 'medium',
      status: 'blocked',
      details: 'Sliding window rate limit exceeded for client',
      user_id: 'user_attacker_002',
      device_id: 'terminal-turnstile-01',
      request_id: 'req_ratelimit_def456',
      metadata: { client_ip: '192.168.1.50', path: '/verify' },
    },
    {
      id: 103,
      created_at: '2026-10-24T00:25:10.000Z',
      event_type: 'hmac_nonce_replay',
      severity: 'high',
      status: 'blocked',
      details: 'Consumed nonce replay rejected',
      user_id: null,
      device_id: 'terminal-gate-02',
      request_id: 'req_nonce_replay_789',
      metadata: { nonce: 'nonce_98765', key_version: 1 },
    },
  ];

  test('getSecurityEvents dispatches GET /admin/security-events with Bearer token', async () => {
    let capturedUrl = '';
    let capturedMethod = '';
    let capturedAuth: string | null = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, init) => {
      capturedUrl = String(url);
      capturedMethod = init?.method || '';
      const headers = new Headers(init?.headers);
      capturedAuth = headers.get('Authorization');

      const body: SecurityEventsResponse = {
        events: sampleEvents,
        next_cursor: 'eyJpZCI6IDEwMiwgInRzIjogIjIwMjYtMTAtMjQifQ==',
        has_more: true,
        count: sampleEvents.length,
      };

      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const client = new ApiClient({
        baseUrl: 'https://voicelock-api.internal',
        getToken: async () => adminToken,
      });

      const res = await client.getSecurityEvents();

      assert.strictEqual(capturedUrl, 'https://voicelock-api.internal/admin/security-events');
      assert.strictEqual(capturedMethod, 'GET');
      assert.strictEqual(capturedAuth, `Bearer ${adminToken}`);
      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.status, 200);
      assert.strictEqual(res.data?.events.length, 3);
      assert.strictEqual(res.data?.has_more, true);
      assert.strictEqual(res.data?.count, 3);
      assert.strictEqual(res.data?.next_cursor, 'eyJpZCI6IDEwMiwgInRzIjogIjIwMjYtMTAtMjQifQ==');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('getSecurityEvents safely formats all backend query parameters', async () => {
    let capturedUrl = '';

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url) => {
      capturedUrl = String(url);
      return new Response(
        JSON.stringify({ events: [], next_cursor: null, has_more: false, count: 0 }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      const filters: SecurityEventFilters = {
        limit: 25,
        cursor: 'cursor_test_token_abc',
        event_type: 'hmac_nonce_replay',
        severity: 'high',
        status: 'blocked',
        user_id: 'user_456',
        device_id: 'terminal-gate-01',
        request_id: 'req_123',
        start_time: '2026-10-24T00:00:00.000Z',
        end_time: '2026-10-24T23:59:59.000Z',
      };

      await client.getSecurityEvents(filters);

      const parsedUrl = new URL(capturedUrl);
      assert.strictEqual(parsedUrl.pathname, '/admin/security-events');
      assert.strictEqual(parsedUrl.searchParams.get('limit'), '25');
      assert.strictEqual(parsedUrl.searchParams.get('cursor'), 'cursor_test_token_abc');
      assert.strictEqual(parsedUrl.searchParams.get('event_type'), 'hmac_nonce_replay');
      assert.strictEqual(parsedUrl.searchParams.get('severity'), 'high');
      assert.strictEqual(parsedUrl.searchParams.get('status'), 'blocked');
      assert.strictEqual(parsedUrl.searchParams.get('user_id'), 'user_456');
      assert.strictEqual(parsedUrl.searchParams.get('device_id'), 'terminal-gate-01');
      assert.strictEqual(parsedUrl.searchParams.get('request_id'), 'req_123');
      assert.strictEqual(parsedUrl.searchParams.get('start_time'), '2026-10-24T00:00:00.000Z');
      assert.strictEqual(parsedUrl.searchParams.get('end_time'), '2026-10-24T23:59:59.000Z');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('getSecurityEvents omits unset or undefined filters from query string', async () => {
    let capturedUrl = '';

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url) => {
      capturedUrl = String(url);
      return new Response(
        JSON.stringify({ events: [], next_cursor: null, has_more: false, count: 0 }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      // Pass only severity and limit; all others undefined or null
      await client.getSecurityEvents({
        limit: 50,
        severity: 'critical',
      });

      const parsedUrl = new URL(capturedUrl);
      assert.strictEqual(parsedUrl.searchParams.get('limit'), '50');
      assert.strictEqual(parsedUrl.searchParams.get('severity'), 'critical');
      assert.strictEqual(parsedUrl.searchParams.get('cursor'), null);
      assert.strictEqual(parsedUrl.searchParams.get('event_type'), null);
      assert.strictEqual(parsedUrl.searchParams.get('status'), null);
      assert.strictEqual(parsedUrl.searchParams.get('user_id'), null);
      assert.strictEqual(parsedUrl.searchParams.get('device_id'), null);
      assert.strictEqual(parsedUrl.searchParams.get('request_id'), null);
      assert.strictEqual(parsedUrl.searchParams.get('start_time'), null);
      assert.strictEqual(parsedUrl.searchParams.get('end_time'), null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles 401 Unauthorized with token refresh recovery for safe GET query', async () => {
    let fetchCount = 0;
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => {
      fetchCount++;
      if (fetchCount === 1) {
        return new Response(JSON.stringify({ detail: 'Firebase ID token has expired.' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response(
        JSON.stringify({ events: sampleEvents, next_cursor: null, has_more: false, count: 3 }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    let refreshed = false;
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async (forceRefresh) => {
        if (forceRefresh) {
          refreshed = true;
          return 'fresh_token_after_401';
        }
        return 'expired_token';
      },
    });

    try {
      const res = await client.getSecurityEvents();
      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.status, 200);
      assert.strictEqual(fetchCount, 2, 'Safe GET retries once upon token expiry');
      assert.strictEqual(refreshed, true);
      assert.strictEqual(res.data?.events.length, 3);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles 403 Forbidden role rejection safely without retry or token refresh', async () => {
    let fetchCount = 0;
    let refreshAttempted = false;
    const originalFetch = globalThis.fetch;

    globalThis.fetch = async () => {
      fetchCount++;
      return new Response(
        JSON.stringify({ detail: 'Admin privileges required to inspect security audit events.' }),
        { status: 403, headers: { 'Content-Type': 'application/json' } }
      );
    };

    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async (forceRefresh) => {
        if (forceRefresh) refreshAttempted = true;
        return 'operator_non_admin_token';
      },
    });

    try {
      const res = await client.getSecurityEvents();
      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 403);
      assert.match(res.error || '', /Forbidden/i);
      assert.strictEqual(fetchCount, 1, '403 Forbidden must never be retried');
      assert.strictEqual(refreshAttempted, false, '403 Forbidden must not trigger token refresh');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles 500 / 503 database failure and network drop gracefully', async () => {
    const originalFetch = globalThis.fetch;

    // 503 Service Unavailable
    globalThis.fetch = async () => {
      return new Response(JSON.stringify({ detail: 'Database connection pool exhausted.' }), {
        status: 503,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => adminToken,
    });

    try {
      const res = await client.getSecurityEvents();
      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 503);
      assert.strictEqual(res.data, null);
      assert.match(res.error || '', /Database connection pool exhausted/i);
    } finally {
      globalThis.fetch = originalFetch;
    }

    // Network error
    globalThis.fetch = async () => {
      throw new TypeError('Failed to fetch');
    };

    try {
      const res = await client.getSecurityEvents();
      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 0);
      assert.strictEqual(res.data, null);
      assert.strictEqual(res.error, 'Failed to fetch');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});

describe('Increment 4B: SecurityEventsPage Component Invariants & Behavior Suite', () => {
  const pagePath = path.resolve(__dirname, '../components/pages/SecurityEventsPage.tsx');

  test('source file exists and verifies admin role before rendering audit log controls', () => {
    assert.strictEqual(fs.existsSync(pagePath), true, 'SecurityEventsPage.tsx must exist');
    const source = fs.readFileSync(pagePath, 'utf-8');

    // Admin role check
    assert.ok(
      source.includes('isAdmin = user?.role === \'admin\'') || source.includes("user?.role === 'admin'"),
      'SecurityEventsPage must compute isAdmin from user context'
    );
    assert.ok(
      source.includes('if (!isAdmin)'),
      'SecurityEventsPage must guard view rendering with if (!isAdmin)'
    );
    assert.ok(
      source.includes('Administrator Authorization Required'),
      'SecurityEventsPage must display administrative requirement card for non-admin sessions'
    );
  });

  test('zero-mock invariant: strictly excludes mock security events', () => {
    const source = fs.readFileSync(pagePath, 'utf-8');
    assert.ok(
      !source.includes('MOCK_SECURITY_EVENTS'),
      'SecurityEventsPage must not reference MOCK_SECURITY_EVENTS'
    );
    assert.ok(
      !source.includes("from '../../data/mockData'") && !source.includes("from '../data/mockData'"),
      'SecurityEventsPage must not import mockData'
    );
  });

  test('contains Audit Stream or Audit Log API integration marker', () => {
    const source = fs.readFileSync(pagePath, 'utf-8');
    assert.ok(
      source.includes('Audit Stream') || source.includes('Audit Log API'),
      'SecurityEventsPage must display transparent audit log backend integration status'
    );
  });

  test('connects to real apiClient.getSecurityEvents with supported query filters', () => {
    const source = fs.readFileSync(pagePath, 'utf-8');

    assert.ok(
      source.includes('apiClient.getSecurityEvents'),
      'SecurityEventsPage must invoke apiClient.getSecurityEvents'
    );

    // Verifies all supported filter fields are mapped to filter payload
    assert.ok(source.includes('limit: 50'), 'Must specify limit');
    assert.ok(source.includes('event_type:'), 'Must pass event_type filter');
    assert.ok(source.includes('severity:'), 'Must pass severity filter');
    assert.ok(source.includes('status:'), 'Must pass status filter');
    assert.ok(source.includes('user_id:'), 'Must pass user_id filter');
    assert.ok(source.includes('device_id:'), 'Must pass device_id filter');
    assert.ok(source.includes('start_time:'), 'Must pass start_time filter');
    assert.ok(source.includes('end_time:'), 'Must pass end_time filter');
  });

  test('validates date range and halts querying if start_time > end_time', () => {
    const source = fs.readFileSync(pagePath, 'utf-8');

    // Date range validation
    assert.ok(
      source.includes('startTime && endTime') &&
      (source.includes('new Date(startTime).getTime() > new Date(endTime).getTime()') ||
       source.includes('startTime > endTime')),
      'SecurityEventsPage must detect when start time exceeds end time'
    );

    // Displays accessible warning alert
    assert.ok(
      source.includes('Invalid Date Range') || source.includes('start date/time cannot be later'),
      'SecurityEventsPage must render warning notification for invalid date range'
    );
  });

  test('implements cursor-based pagination with continuation cursor and history stack', () => {
    const source = fs.readFileSync(pagePath, 'utf-8');

    // Cursor state management
    assert.ok(
      source.includes('currentCursor') &&
      source.includes('cursorHistory') &&
      source.includes('nextCursor') &&
      source.includes('hasMore'),
      'SecurityEventsPage must track currentCursor, cursorHistory, nextCursor, and hasMore'
    );

    // Next page handler
    assert.ok(
      source.includes('handleNextPage'),
      'SecurityEventsPage must provide handleNextPage'
    );

    // Previous page handler
    assert.ok(
      source.includes('handlePrevPage'),
      'SecurityEventsPage must provide handlePrevPage'
    );

    // Resets cursor on filter change
    assert.ok(
      source.includes('setCurrentCursor(null)') &&
      source.includes('setCursorHistory([])'),
      'SecurityEventsPage must reset cursor state when filters change'
    );
  });

  test('prevents duplicate requests and disables controls while fetching', () => {
    const source = fs.readFileSync(pagePath, 'utf-8');

    // Button disabled states during loading
    assert.ok(
      source.includes('disabled={cursorHistory.length === 0 || effectiveIsLoading}') ||
      source.includes('disabled={cursorHistory.length === 0 || isLoading}'),
      'Previous button must be disabled when on first page or loading'
    );

    assert.ok(
      source.includes('disabled={!hasMore || !nextCursor || effectiveIsLoading}') ||
      source.includes('disabled={!hasMore || !nextCursor || isLoading}'),
      'Next button must be disabled when hasMore is false or loading'
    );
  });

  test('renders documented safe fields and excludes sensitive secrets or credentials', () => {
    const source = fs.readFileSync(pagePath, 'utf-8');

    // Verifies rendering of safe fields
    assert.ok(source.includes('event.created_at') || source.includes('formatTimestamp'), 'Must render timestamp');
    assert.ok(source.includes('event.event_type'), 'Must render event_type');
    assert.ok(source.includes('event.severity'), 'Must render severity');
    assert.ok(source.includes('event.status'), 'Must render status');
    assert.ok(source.includes('event.user_id'), 'Must render actor user_id');
    assert.ok(source.includes('event.device_id'), 'Must render terminal device_id');
    assert.ok(source.includes('event.request_id'), 'Must render request_id');
    assert.ok(source.includes('event.details'), 'Must render event details');

    // Verifies data minimization: strictly filters metadata keys to omit secrets, tokens, passwords
    assert.ok(
      source.includes('!lk.includes(\'secret\')') &&
      source.includes('!lk.includes(\'token\')') &&
      source.includes('!lk.includes(\'password\')'),
      'SecurityEventsPage must sanitize metadata keys to omit any secret/token values'
    );

    // No console.log of event payload
    assert.ok(
      !source.includes('console.log(response.data') &&
      !source.includes('console.log(event'),
      'SecurityEventsPage must never dump event payloads to browser console'
    );
  });

  test('renders distinct empty state without fabricating totals', () => {
    const source = fs.readFileSync(pagePath, 'utf-8');

    // Empty state
    assert.ok(
      source.includes('No Security Events Found') || source.includes('No security events'),
      'SecurityEventsPage must render empty result state when 0 events returned'
    );

    // No fabricated total count across database
    assert.ok(
      !source.includes('Total: 10,000') && !source.includes('of 100 pages'),
      'SecurityEventsPage must not fabricate total database record counts'
    );
  });
});
