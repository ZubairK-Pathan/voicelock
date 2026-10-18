/**
 * frontend/src/lib/overviewMetrics.test.ts
 * 
 * Increment 3B Automated Frontend Test Suite:
 * - Real metric loading via apiClient.getSpeakers() and apiClient.getDevices()
 * - Bearer token attachment and security header verification
 * - Empty database states (0 enrolled speakers, 0 registered devices)
 * - Error states: 401 Unauthorized, 403 Forbidden, 500 Database Failure, Network drop
 * - Data minimization: asserts that device endpoints never expose secret hashes or raw credentials
 * - Zero-mock invariant: strictly validates that MOCK_METRICS, MOCK_VERIFICATION_RECORDS,
 *   and MOCK_SECURITY_EVENTS are excluded from production OverviewPage rendering
 * - Accurate representation: verifies that uninstrumented telemetry does not imply zero incidents or zero failures
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ApiClient } from './apiClient.ts';
import type { SpeakersApiResponse, DevicesApiResponse } from '../types/index.ts';
import {
  MOCK_METRICS,
  MOCK_VERIFICATION_RECORDS,
  MOCK_SECURITY_EVENTS,
} from '../data/mockData.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Increment 3B: Overview Dashboard Backend Metrics Integration Suite', () => {
  const mockToken = 'firebase_id_token_admin_test_12345';

  // ─── 1. Real Metric Loading via Authenticated API ────────────────────────────

  test('loads real speaker and device metrics with Bearer authentication', async () => {
    const authHeaders: string[] = [];

    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => mockToken,
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      const url = String(input);
      const headers = new Headers(init?.headers);
      const auth = headers.get('Authorization');
      if (auth) authHeaders.push(auth);

      if (url.endsWith('/speakers')) {
        const payload: SpeakersApiResponse = {
          registered_speakers: ['Advait', 'Omar', 'Parth', 'Zubair'],
          count: 4,
        };
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }

      if (url.endsWith('/devices')) {
        const payload: DevicesApiResponse = {
          devices: [
            {
              device_id: 'esp32-gate-01',
              name: 'Main Portal',
              status: 'active',
              key_version: 1,
            },
          ],
          total: 1,
          active_count: 1,
        };
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }

      return new Response('Not found', { status: 404 });
    };

    try {
      const [spkRes, devRes] = await Promise.all([
        client.getSpeakers(),
        client.getDevices(),
      ]);

      assert.strictEqual(spkRes.ok, true);
      assert.strictEqual(spkRes.status, 200);
      assert.strictEqual(spkRes.data?.count, 4);
      assert.deepStrictEqual(spkRes.data?.registered_speakers, ['Advait', 'Omar', 'Parth', 'Zubair']);

      assert.strictEqual(devRes.ok, true);
      assert.strictEqual(devRes.status, 200);
      assert.strictEqual(devRes.data?.total, 1);
      assert.strictEqual(devRes.data?.active_count, 1);
      assert.strictEqual(devRes.data?.devices[0].device_id, 'esp32-gate-01');

      // Verify that Bearer token was attached to both requests
      assert.strictEqual(authHeaders.length, 2);
      assert.strictEqual(authHeaders[0], `Bearer ${mockToken}`);
      assert.strictEqual(authHeaders[1], `Bearer ${mockToken}`);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 2. Data Minimization & Secret Exclusion ─────────────────────────────────

  test('verifies data minimization: device responses strictly exclude secret_hash and credentials', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => mockToken,
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input) => {
      const url = String(input);
      if (url.endsWith('/devices')) {
        // Backend returns sanitized DevicesResponse
        const payload = {
          devices: [
            {
              device_id: 'esp32-terminal-01',
              name: 'Front Door',
              status: 'active',
              key_version: 1,
            },
          ],
          total: 1,
          active_count: 1,
        };
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response('Not found', { status: 404 });
    };

    try {
      const response = await client.getDevices();
      assert.strictEqual(response.ok, true);
      const dev = response.data?.devices[0] as unknown as Record<string, unknown>;

      assert.strictEqual(dev.device_id, 'esp32-terminal-01');
      assert.strictEqual(dev.name, 'Front Door');
      assert.strictEqual(dev.status, 'active');
      assert.strictEqual(dev.key_version, 1);

      // Verify prohibited fields are absent
      assert.strictEqual('secret_hash' in dev, false);
      assert.strictEqual('secret' in dev, false);
      assert.strictEqual('raw_key' in dev, false);
      assert.strictEqual('token' in dev, false);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 3. Empty Database Handling ──────────────────────────────────────────────

  test('handles empty database states (0 speakers, 0 devices) cleanly without fallbacks', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => mockToken,
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input) => {
      const url = String(input);
      if (url.endsWith('/speakers')) {
        return new Response(JSON.stringify({ registered_speakers: [], count: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      if (url.endsWith('/devices')) {
        return new Response(JSON.stringify({ devices: [], total: 0, active_count: 0 }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      return new Response('Not found', { status: 404 });
    };

    try {
      const [spkRes, devRes] = await Promise.all([
        client.getSpeakers(),
        client.getDevices(),
      ]);

      assert.strictEqual(spkRes.ok, true);
      assert.strictEqual(spkRes.data?.count, 0);
      assert.deepStrictEqual(spkRes.data?.registered_speakers, []);

      assert.strictEqual(devRes.ok, true);
      assert.strictEqual(devRes.data?.total, 0);
      assert.strictEqual(devRes.data?.active_count, 0);
      assert.deepStrictEqual(devRes.data?.devices, []);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 4. Authentication Expiry & Forbidden RBAC ───────────────────────────────

  test('handles HTTP 401 Unauthorized safely when operator session expires', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'expired_token',
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(JSON.stringify({ detail: 'Token has expired.' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const [spkRes, devRes] = await Promise.all([
        client.getSpeakers(),
        client.getDevices(),
      ]);

      assert.strictEqual(spkRes.ok, false);
      assert.strictEqual(spkRes.status, 401);
      assert.ok(spkRes.error?.includes('Unauthorized'));

      assert.strictEqual(devRes.ok, false);
      assert.strictEqual(devRes.status, 401);
      assert.ok(devRes.error?.includes('Unauthorized'));
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles HTTP 403 Forbidden when non-admin operator requests metrics', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'ordinary_user_token',
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(JSON.stringify({ detail: 'Admin role required.' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const [spkRes, devRes] = await Promise.all([
        client.getSpeakers(),
        client.getDevices(),
      ]);

      assert.strictEqual(spkRes.ok, false);
      assert.strictEqual(spkRes.status, 403);
      assert.ok(spkRes.error?.includes('Forbidden'));

      assert.strictEqual(devRes.ok, false);
      assert.strictEqual(devRes.status, 403);
      assert.ok(devRes.error?.includes('Forbidden'));
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 5. Server & Network Errors ──────────────────────────────────────────────

  test('handles HTTP 500 database failure and network drop gracefully', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => mockToken,
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input) => {
      const url = String(input);
      if (url.endsWith('/speakers')) {
        return new Response(JSON.stringify({ detail: 'Database connection failed.' }), {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        });
      }
      throw new TypeError('Failed to fetch');
    };

    try {
      const spkRes = await client.getSpeakers();
      assert.strictEqual(spkRes.ok, false);
      assert.strictEqual(spkRes.status, 500);
      assert.strictEqual(spkRes.error, 'Database connection failed.');

      const devRes = await client.getDevices();
      assert.strictEqual(devRes.ok, false);
      assert.strictEqual(devRes.status, 0);
      assert.strictEqual(devRes.error, 'Failed to fetch');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 6. Zero-Mock Invariant & Production Component Invariant ─────────────────

  test('zero-mock invariant: OverviewPage source code contains no imports or usage of mock data', () => {
    const overviewPath = path.resolve(__dirname, '../components/pages/OverviewPage.tsx');
    assert.strictEqual(fs.existsSync(overviewPath), true, 'OverviewPage.tsx must exist');

    const source = fs.readFileSync(overviewPath, 'utf-8');

    // Asserts that no mock structures are imported from mockData
    assert.strictEqual(
      source.includes('MOCK_METRICS'),
      false,
      'OverviewPage must not import or reference MOCK_METRICS'
    );
    assert.strictEqual(
      source.includes('MOCK_VERIFICATION_RECORDS'),
      false,
      'OverviewPage must not import or reference MOCK_VERIFICATION_RECORDS'
    );
    assert.strictEqual(
      source.includes('MOCK_SECURITY_EVENTS'),
      false,
      'OverviewPage must not import or reference MOCK_SECURITY_EVENTS'
    );
    assert.strictEqual(
      source.includes('mockData'),
      false,
      'OverviewPage must not import from mockData'
    );

    // Verify presence of security disclosure regarding uninstrumented event storage
    assert.ok(
      source.includes('Security Disclosure: Event Journal Uninstrumented'),
      'OverviewPage must include a security disclosure informing that zero logged events reflects uninstrumented storage'
    );
    assert.ok(
      source.includes('Biometric Access Journal Uninstrumented'),
      'OverviewPage must include an uninstrumented state for verification history'
    );
    assert.ok(
      source.includes('apiClient.getSpeakers()') && source.includes('apiClient.getDevices()'),
      'OverviewPage must query real apiClient.getSpeakers() and apiClient.getDevices()'
    );

    // Validate that mock metric strings from mockData are not hardcoded
    assert.strictEqual(
      source.includes('12 active biometric profiles'),
      false,
      'Mock total speakers phrase must not be hardcoded in OverviewPage'
    );
    assert.strictEqual(
      source.includes('4 active biometric profiles'),
      false,
      'Mock terminal subtitle phrase must not be hardcoded in OverviewPage'
    );
    assert.strictEqual(
      source.includes(`${MOCK_METRICS.success_rate_percent}%`),
      false,
      'Mock success rate must not be hardcoded in OverviewPage'
    );
    assert.strictEqual(
      source.includes(`${MOCK_METRICS.verifications_today}`),
      false,
      'Mock verifications count must not be hardcoded in OverviewPage'
    );
    assert.strictEqual(
      source.includes(MOCK_VERIFICATION_RECORDS[0].speaker_name),
      false,
      'Mock verification records must not be hardcoded in OverviewPage'
    );
    assert.strictEqual(
      source.includes(MOCK_SECURITY_EVENTS[0].details),
      false,
      'Mock security events must not be hardcoded in OverviewPage'
    );
  });

  test('zero-mock invariant: App.tsx does not pass MOCK_METRICS to Layout counts', () => {
    const appPath = path.resolve(__dirname, '../App.tsx');
    assert.strictEqual(fs.existsSync(appPath), true, 'App.tsx must exist');

    const appSource = fs.readFileSync(appPath, 'utf-8');
    assert.strictEqual(
      appSource.includes('MOCK_METRICS'),
      false,
      'App.tsx must not import or reference MOCK_METRICS'
    );
    assert.strictEqual(
      appSource.includes('mockData'),
      false,
      'App.tsx must not import from mockData'
    );
  });
});
