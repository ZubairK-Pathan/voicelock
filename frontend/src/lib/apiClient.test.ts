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

describe('ApiClient Challenge & Biometric Verification Methods Suite', () => {
  const mockToken = 'firebase_test_id_token_xyz987';

  test('createChallenge calls POST /challenge with Bearer auth and JSON payload', async () => {
    let capturedUrl = '';
    let capturedMethod = '';
    let capturedHeaders: Headers | null = null;
    let capturedBody = '';

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, init) => {
      capturedUrl = String(url);
      capturedMethod = init?.method || '';
      capturedHeaders = new Headers(init?.headers);
      capturedBody = String(init?.body);

      return new Response(
        JSON.stringify({
          challenge_id: 'ch_test_123',
          session_id: 'sess_test_456',
          claimed_identity: 'Zubair',
          digits: ['7', '4', '1', '9'],
          display: '7   4   1   9',
          expires_at: 1730000000.0,
          expires_in_seconds: 60,
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'https://voicelock-api.internal',
        getToken: async () => mockToken,
      });

      const res = await client.createChallenge({
        claimed_identity: 'Zubair',
        session_id: 'sess_test_456',
      });

      assert.strictEqual(capturedUrl, 'https://voicelock-api.internal/challenge');
      assert.strictEqual(capturedMethod, 'POST');
      assert.strictEqual(capturedHeaders?.get('Authorization'), `Bearer ${mockToken}`);
      assert.strictEqual(capturedHeaders?.get('Content-Type'), 'application/json');

      const parsedBody = JSON.parse(capturedBody);
      assert.strictEqual(parsedBody.claimed_identity, 'Zubair');
      assert.strictEqual(parsedBody.session_id, 'sess_test_456');

      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.status, 200);
      assert.strictEqual(res.data?.challenge_id, 'ch_test_123');
      assert.strictEqual(res.data?.session_id, 'sess_test_456');
      assert.strictEqual(res.data?.claimed_identity, 'Zubair');
      assert.deepStrictEqual(res.data?.digits, ['7', '4', '1', '9']);
      assert.strictEqual(res.data?.display, '7   4   1   9');
      assert.strictEqual(res.data?.expires_in_seconds, 60);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('createChallenge supports omitted payload parameters', async () => {
    let capturedBody = '';

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (_url, init) => {
      capturedBody = String(init?.body);
      return new Response(
        JSON.stringify({
          challenge_id: 'ch_auto_789',
          session_id: 'sess_auto_001',
          claimed_identity: null,
          digits: ['1', '2', '3'],
          display: '1   2   3',
          expires_at: 1730000060.0,
          expires_in_seconds: 60,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    try {
      const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
      const res = await client.createChallenge();

      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.data?.challenge_id, 'ch_auto_789');
      assert.strictEqual(capturedBody, '{}');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('verify sends multipart/form-data with Bearer token without manual Content-Type', async () => {
    let capturedUrl = '';
    let capturedMethod = '';
    let capturedHeaders: Headers | null = null;
    let capturedBody: unknown = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, init) => {
      capturedUrl = String(url);
      capturedMethod = init?.method || '';
      capturedHeaders = new Headers(init?.headers);
      capturedBody = init?.body;

      return new Response(
        JSON.stringify({
          accepted: true,
          action: 'UNLOCK',
          claimed_identity: 'Zubair',
          similarity: 0.8668,
          threshold_used: 0.25,
          liveness_passed: true,
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'https://voicelock-api.internal',
        getToken: async () => mockToken,
      });

      const audioBlob = new Blob([new Uint8Array([0x52, 0x49, 0x46, 0x46])], {
        type: 'audio/wav',
      });

      const res = await client.verify({
        audio: audioBlob,
        claimed_identity: 'Zubair',
        challenge_id: 'ch_live_123',
        session_id: 'sess_live_456',
        filename: 'recording.wav',
      });

      assert.strictEqual(capturedUrl, 'https://voicelock-api.internal/verify');
      assert.strictEqual(capturedMethod, 'POST');
      assert.strictEqual(capturedHeaders?.get('Authorization'), `Bearer ${mockToken}`);

      // Crucial: Content-Type must NOT be application/json so browser/fetch supplies boundary
      assert.strictEqual(capturedHeaders?.get('Content-Type'), null);

      assert.ok(capturedBody instanceof FormData);
      const fd = capturedBody as FormData;
      assert.strictEqual(fd.get('claimed_identity'), 'Zubair');
      assert.strictEqual(fd.get('challenge_id'), 'ch_live_123');
      assert.strictEqual(fd.get('session_id'), 'sess_live_456');
      assert.ok(fd.get('audio') !== null);

      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.status, 200);
      assert.strictEqual(res.data?.accepted, true);
      assert.strictEqual(res.data?.action, 'UNLOCK');
      assert.strictEqual(res.data?.claimed_identity, 'Zubair');
      assert.strictEqual(res.data?.similarity, 0.8668);
      assert.strictEqual(res.data?.threshold_used, 0.25);
      assert.strictEqual(res.data?.liveness_passed, true);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('verify supports direct FormData submission', async () => {
    let capturedFormData: FormData | null = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (_url, init) => {
      capturedFormData = init?.body as FormData;
      return new Response(
        JSON.stringify({
          accepted: false,
          action: 'DENY',
          claimed_identity: 'Zubair',
          similarity: 0.0981,
          threshold_used: 0.25,
          liveness_passed: true,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    try {
      const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
      const rawFd = new FormData();
      rawFd.append('audio', new Blob(['test']), 'custom.wav');
      rawFd.append('claimed_identity', 'Zubair');
      rawFd.append('challenge_id', 'ch_raw_1');
      rawFd.append('session_id', 'sess_raw_2');

      const res = await client.verify(rawFd);
      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.data?.accepted, false);
      assert.strictEqual(res.data?.action, 'DENY');
      assert.strictEqual(res.data?.similarity, 0.0981);
      assert.strictEqual(capturedFormData?.get('claimed_identity'), 'Zubair');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('verifyAudio alias functions identically to verify', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          accepted: true,
          action: 'UNLOCK',
          claimed_identity: 'Zubair',
          similarity: 0.91,
          threshold_used: 0.25,
          liveness_passed: true,
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    try {
      const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
      const res = await client.verifyAudio({
        audio: new Blob(['pcm']),
        claimed_identity: 'Zubair',
        challenge_id: 'ch_alias',
        session_id: 'sess_alias',
      });

      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.data?.action, 'UNLOCK');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('parses legitimate liveness rejection response accurately', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          accepted: false,
          action: 'DENY',
          claimed_identity: 'Zubair',
          similarity: 0.0,
          threshold_used: 0.25,
          liveness_passed: false,
          reason: 'Liveness check failed: No speech detected. Please try again.',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    };

    try {
      const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
      const res = await client.verify({
        audio: new Blob(['silence']),
        claimed_identity: 'Zubair',
        challenge_id: 'ch_silent',
        session_id: 'sess_silent',
      });

      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.status, 200);
      assert.strictEqual(res.data?.accepted, false);
      assert.strictEqual(res.data?.action, 'DENY');
      assert.strictEqual(res.data?.liveness_passed, false);
      assert.match(res.data?.reason || '', /No speech detected/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles 400 Bad Request (e.g. empty audio, missing challenge) safely', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: 'Missing required challenge_id or session_id for verification.' }),
        { status: 400, headers: { 'Content-Type': 'application/json' } }
      );
    };

    try {
      const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
      const res = await client.verify({
        audio: new Blob(['']),
        claimed_identity: 'Zubair',
        challenge_id: '',
        session_id: '',
      });

      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 400);
      assert.strictEqual(res.data, null);
      assert.match(res.error || '', /Missing required challenge_id/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles 422 Unprocessable Entity (missing multipart field) safely', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: [
            {
              loc: ['body', 'audio'],
              msg: 'Field required',
              type: 'missing',
            },
          ],
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } }
      );
    };

    try {
      const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
      const res = await client.verify(new FormData());

      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 422);
      assert.strictEqual(res.data, null);
      assert.match(res.error || '', /Field required/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles network failure gracefully', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      throw new TypeError('Failed to fetch');
    };

    try {
      const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
      const res = await client.verify({
        audio: new Blob(['audio']),
        claimed_identity: 'Zubair',
        challenge_id: 'ch_fail',
        session_id: 'sess_fail',
      });

      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 0);
      assert.strictEqual(res.data, null);
      assert.strictEqual(res.error, 'Failed to fetch');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('invariant: error pathways never manufacture an UNLOCK or accepted result', async () => {
    const errorStatuses = [400, 401, 403, 404, 422, 500, 502];

    for (const status of errorStatuses) {
      const originalFetch = globalThis.fetch;
      globalThis.fetch = async () => {
        return new Response(JSON.stringify({ detail: `Error status ${status}` }), {
          status,
          headers: { 'Content-Type': 'application/json' },
        });
      };

      try {
        const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
        const res = await client.verify({
          audio: new Blob(['audio']),
          claimed_identity: 'Zubair',
          challenge_id: 'ch_test',
          session_id: 'sess_test',
        });

        assert.strictEqual(res.ok, false, `Status ${status} must have ok=false`);
        assert.strictEqual(res.data, null, `Status ${status} must have data=null`);
        assert.ok(res.error, `Status ${status} must have descriptive error`);
      } finally {
        globalThis.fetch = originalFetch;
      }
    }
  });
});

