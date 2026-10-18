import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient } from './apiClient.ts';

describe('ApiClient Authentication & Request Security Suite', () => {
  test('attaches Bearer token when token provider returns token', async () => {
    const mockToken = 'mock_rs256_id_token_xyz123';
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => mockToken,
    });

    const headers = await client.buildHeaders({}, true);
    assert.strictEqual(headers.get('Authorization'), `Bearer ${mockToken}`);
    assert.strictEqual(headers.get('Content-Type'), 'application/json');
  });

  test('does not attach Bearer token when requiresAuth is false', async () => {
    const mockToken = 'mock_rs256_id_token_xyz123';
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => mockToken,
    });

    const headers = await client.buildHeaders({}, false);
    assert.strictEqual(headers.get('Authorization'), null);
    assert.strictEqual(headers.get('Content-Type'), 'application/json');
  });

  test('handles token acquisition failure gracefully without leaking error', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => {
        throw new Error('Internal Firebase network failure');
      },
    });

    const headers = await client.buildHeaders({}, true);
    // Should not throw, and should omit Authorization header
    assert.strictEqual(headers.get('Authorization'), null);
  });

  test('handles 401 Unauthorized safely without leaking sensitive tokens', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'test_token',
    });

    // Mock global fetch
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(JSON.stringify({ detail: 'Token expired or revoked' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const response = await client.get('/speakers');
      assert.strictEqual(response.ok, false);
      assert.strictEqual(response.status, 401);
      assert.match(response.error || '', /Unauthorized/i);
      assert.strictEqual(response.data, null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles 403 Forbidden role rejection safely', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'test_token',
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(JSON.stringify({ detail: 'Insufficient permissions' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const response = await client.get('/admin/audit');
      assert.strictEqual(response.ok, false);
      assert.strictEqual(response.status, 403);
      assert.match(response.error || '', /Forbidden/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('parses successful JSON response cleanly', async () => {
    const client = new ApiClient({
      baseUrl: 'http://localhost:8000',
      getToken: async () => 'test_token',
    });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(JSON.stringify({ status: 'ok', speakers: ['Zubair', 'Advait'] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const response = await client.get<{ status: string; speakers: string[] }>('/speakers');
      assert.strictEqual(response.ok, true);
      assert.strictEqual(response.status, 200);
      assert.deepStrictEqual(response.data?.speakers, ['Zubair', 'Advait']);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });
});
