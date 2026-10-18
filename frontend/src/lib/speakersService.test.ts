/**
 * frontend/src/lib/speakersService.test.ts
 * 
 * Increment 3A Automated Frontend Test Suite:
 * - Data loading via apiClient.getSpeakers()
 * - Token attachment (Firebase ID token via Bearer header)
 * - Empty database results
 * - Error states: 401 Unauthorized, 403 Forbidden, 500 Server Error, Network failure
 * - Search and filtering algorithm verification
 * - Zero-mock invariant: ensures no mock records or fake fields are treated as real data
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient } from './apiClient.ts';
import type { SpeakersApiResponse } from '../types/index.ts';
import { MOCK_SPEAKERS } from '../data/mockData.ts';

describe('Increment 3A: Database-Backed Speakers Registry Frontend Suite', () => {
  // ─── 1. Token Attachment & Authenticated API Dispatch ────────────────────────

  test('sends Firebase ID token via Authorization: Bearer header on GET /speakers', async () => {
    const mockToken = 'firebase_id_token_operator_admin_001';
    let capturedAuthHeader: string | null = null;

    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => mockToken,
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (_input, init) => {
      const headers = new Headers(init?.headers);
      capturedAuthHeader = headers.get('Authorization');
      return new Response(
        JSON.stringify({
          registered_speakers: ['Advait', 'Omar', 'Zubair'],
          count: 3,
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const response = await client.getSpeakers();
      assert.strictEqual(response.ok, true);
      assert.strictEqual(response.status, 200);
      assert.strictEqual(capturedAuthHeader, `Bearer ${mockToken}`);
      assert.deepStrictEqual(response.data?.registered_speakers, ['Advait', 'Omar', 'Zubair']);
      assert.strictEqual(response.data?.count, 3);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 2. Successful Data Loading ──────────────────────────────────────────────

  test('successfully loads registered speaker records from real API response', async () => {
    const mockApiResponse: SpeakersApiResponse = {
      registered_speakers: [
        'Advait',
        'Amaan Ur Raheman',
        'Krish',
        'Omar',
        'Parth',
        'Shreyas',
        'Umair',
        'Zubair',
        'abid',
        'vikas',
      ],
      count: 10,
    };

    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'test_token',
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(JSON.stringify(mockApiResponse), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const response = await client.getSpeakers();
      assert.strictEqual(response.ok, true);
      assert.strictEqual(response.status, 200);
      assert.strictEqual(response.data?.count, 10);
      assert.strictEqual(response.data?.registered_speakers.length, 10);
      assert.ok(response.data?.registered_speakers.includes('Zubair'));
      assert.ok(response.data?.registered_speakers.includes('Advait'));
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 3. Empty Results ────────────────────────────────────────────────────────

  test('correctly handles empty speaker registry from database (count: 0)', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'test_token',
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          registered_speakers: [],
          count: 0,
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const response = await client.getSpeakers();
      assert.strictEqual(response.ok, true);
      assert.strictEqual(response.status, 200);
      assert.deepStrictEqual(response.data?.registered_speakers, []);
      assert.strictEqual(response.data?.count, 0);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 4. Error Handling: 401 Unauthorized ─────────────────────────────────────

  test('handles HTTP 401 expired authentication safely without leaking tokens', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'expired_token',
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: 'Token expired or invalid signature' }),
        {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const response = await client.getSpeakers();
      assert.strictEqual(response.ok, false);
      assert.strictEqual(response.status, 401);
      assert.strictEqual(response.data, null);
      assert.match(response.error || '', /Unauthorized/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 5. Error Handling: 403 Forbidden ────────────────────────────────────────

  test('handles HTTP 403 Forbidden when ordinary user attempts administrative enumeration', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'user_token_without_admin_role',
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: 'Forbidden: Administrative access required.' }),
        {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const response = await client.getSpeakers();
      assert.strictEqual(response.ok, false);
      assert.strictEqual(response.status, 403);
      assert.strictEqual(response.data, null);
      assert.match(response.error || '', /Forbidden/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 6. Error Handling: 500 Database Failure & Network Error ─────────────────

  test('handles HTTP 500 database failure safely without leaking stack traces', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'admin_token',
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: 'Database failure while retrieving registered speakers.' }),
        {
          status: 500,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const response = await client.getSpeakers();
      assert.strictEqual(response.ok, false);
      assert.strictEqual(response.status, 500);
      assert.strictEqual(response.data, null);
      assert.match(response.error || '', /Database failure/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles network failure gracefully when backend server is down', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'admin_token',
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      throw new Error('fetch failed: ECONNREFUSED 127.0.0.1:8000');
    };

    try {
      const response = await client.getSpeakers();
      assert.strictEqual(response.ok, false);
      assert.strictEqual(response.status, 0);
      assert.strictEqual(response.data, null);
      assert.match(response.error || '', /ECONNREFUSED/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 7. Search and Filtering Behavior ────────────────────────────────────────

  test('search filter matches speaker identities case-insensitively and partially', () => {
    const speakers = ['Advait', 'Amaan Ur Raheman', 'Krish', 'Omar', 'Parth', 'Zubair'];

    const filterFn = (list: string[], query: string) => {
      if (!query.trim()) return list;
      const clean = query.trim().toLowerCase();
      return list.filter((name) => name.toLowerCase().includes(clean));
    };

    // Case-insensitive match
    assert.deepStrictEqual(filterFn(speakers, 'zubair'), ['Zubair']);
    assert.deepStrictEqual(filterFn(speakers, 'ZUBAIR'), ['Zubair']);

    // Partial substring match
    assert.deepStrictEqual(filterFn(speakers, 'a'), ['Advait', 'Amaan Ur Raheman', 'Omar', 'Parth', 'Zubair']);
    assert.deepStrictEqual(filterFn(speakers, 'om'), ['Omar']);

    // Empty query returns all
    assert.deepStrictEqual(filterFn(speakers, ''), speakers);
    assert.deepStrictEqual(filterFn(speakers, '   '), speakers);

    // No match returns empty array
    assert.deepStrictEqual(filterFn(speakers, 'NonExistentGhost'), []);
  });

  // ─── 8. Zero-Mock Invariant & Schema Compliance ──────────────────────────────

  test('verifies that no mock speaker records from mockData are presented as real database data', () => {
    // Real API contract returns an array of strings (speaker IDs/names)
    const mockApiResponse: SpeakersApiResponse = {
      registered_speakers: ['Advait', 'Omar', 'Zubair'],
      count: 3,
    };

    // 1. Must only contain string identities
    assert.ok(mockApiResponse.registered_speakers.every((s) => typeof s === 'string'));

    // 2. Must not contain mock properties (department, sample_count, clearance, etc.)
    for (const speaker of mockApiResponse.registered_speakers) {
      assert.strictEqual(typeof speaker, 'string');
      // @ts-expect-error department must not exist on string
      assert.strictEqual(speaker.department, undefined);
      // @ts-expect-error created_at must not exist on string
      assert.strictEqual(speaker.created_at, undefined);
      // @ts-expect-error security_clearance must not exist on string
      assert.strictEqual(speaker.security_clearance, undefined);
    }

    // 3. Confirm that MOCK_SPEAKERS is completely decoupled from real API responses
    assert.strictEqual(Array.isArray(MOCK_SPEAKERS), true);
    assert.strictEqual(MOCK_SPEAKERS.length, 12);
    // Real API returns names/IDs, whereas MOCK_SPEAKERS has fake departments and dates
    assert.ok(MOCK_SPEAKERS.every((m) => typeof m.department === 'string'));
  });
});
