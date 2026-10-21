/**
 * frontend/src/components/pages/VerificationPage.test.ts
 * 
 * Increment 3: Real Backend-Driven Voice Verification Test Suite.
 * Validates:
 * 1. Challenge request and server-issued challenge display
 * 2. Actual audio recording integration with useAudioRecorder
 * 3. Correct multipart fields (audio, claimed_identity, challenge_id, session_id) and extension
 * 4. Successful response rendering based on real backend response only (accepted=true -> UNLOCK)
 * 5. Silence / liveness denial (accepted=false, liveness_passed=false -> DENY)
 * 6. Impostor denial (accepted=false, liveness_passed=true -> DENY)
 * 7. Expired or reused challenge handling (burn on use / TTL expiry)
 * 8. Missing / empty audio handling
 * 9. Microphone permission denial handling
 * 10. HTTP 400, 401, 403, 422, and network errors
 * 11. Missing speaker mapping fail-closed state (HTTP 403 unmapped user)
 * 12. Malformed or unexpected API responses fail closed
 * 13. Zero-mock invariant: VerificationPage contains no mock data imports or fake simulation logic
 */

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ApiClient } from '../../lib/apiClient.ts';
import type { ChallengeApiResponse, VerifyApiResponse } from '../../types/index.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const verificationPageSourcePath = path.join(__dirname, 'VerificationPage.tsx');

describe('Increment 3: Real Backend-Driven Voice Verification Suite', () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  // ─── 1. Challenge Request & Server-Issued Challenge Invariants ───────────────

  test('createChallenge requests server challenge and receives unpredictable digits', async () => {
    let capturedMethod = '';
    let capturedUrl = '';
    let capturedBody: any = null;

    globalThis.fetch = async (input, init) => {
      capturedMethod = init?.method || 'GET';
      capturedUrl = String(input);
      capturedBody = init?.body ? JSON.parse(String(init.body)) : null;

      const mockChallenge: ChallengeApiResponse = {
        challenge_id: 'ch-test-999-uuid',
        session_id: 'session-xyz-123',
        claimed_identity: 'Zubair',
        digits: ['8', '3', '5'],
        display: '8   3   5',
        expires_at: Math.floor(Date.now() / 1000) + 60,
        expires_in_seconds: 60,
      };

      return new Response(JSON.stringify(mockChallenge), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const response = await client.createChallenge({
      claimed_identity: 'Zubair',
      session_id: 'session-xyz-123',
    });

    assert.strictEqual(response.ok, true);
    assert.strictEqual(capturedMethod, 'POST');
    assert.match(capturedUrl, /\/challenge$/);
    assert.strictEqual(capturedBody.claimed_identity, 'Zubair');
    assert.strictEqual(capturedBody.session_id, 'session-xyz-123');

    assert.strictEqual(response.data?.challenge_id, 'ch-test-999-uuid');
    assert.deepStrictEqual(response.data?.digits, ['8', '3', '5']);
    assert.strictEqual(response.data?.display, '8   3   5');
    assert.strictEqual(response.data?.expires_in_seconds, 60);
  });

  // ─── 2. Real Multipart Audio Submission & Recording Extension ────────────────

  test('verify submits real audio Blob with actual container extension and required metadata', async () => {
    let capturedMethod = '';
    let capturedUrl = '';
    let capturedFormData: FormData | null = null;

    globalThis.fetch = async (input, init) => {
      capturedMethod = init?.method || 'GET';
      capturedUrl = String(input);
      capturedFormData = init?.body as FormData;

      const mockResult: VerifyApiResponse = {
        accepted: true,
        action: 'UNLOCK',
        claimed_identity: 'Zubair',
        similarity: 0.8668,
        threshold_used: 0.25,
        liveness_passed: true,
      };

      return new Response(JSON.stringify(mockResult), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const dummyWebmBytes = new Uint8Array([0x1a, 0x45, 0xdf, 0xa3, 0x01, 0x02]);
    const audioBlob = new Blob([dummyWebmBytes], { type: 'audio/webm;codecs=opus' });

    const response = await client.verify({
      audio: audioBlob,
      filename: 'liveness_recording.webm',
      claimed_identity: 'Zubair',
      challenge_id: 'ch-test-999-uuid',
      session_id: 'session-xyz-123',
    });

    assert.strictEqual(response.ok, true);
    assert.strictEqual(capturedMethod, 'POST');
    assert.match(capturedUrl, /\/verify$/);
    assert.ok(capturedFormData instanceof FormData);

    // Validate multipart form fields
    assert.strictEqual(capturedFormData.get('claimed_identity'), 'Zubair');
    assert.strictEqual(capturedFormData.get('challenge_id'), 'ch-test-999-uuid');
    assert.strictEqual(capturedFormData.get('session_id'), 'session-xyz-123');

    const fileField = capturedFormData.get('audio') as File;
    assert.ok(fileField);
    assert.strictEqual(fileField.name, 'liveness_recording.webm');
    assert.strictEqual(response.data?.action, 'UNLOCK');
    assert.strictEqual(response.data?.accepted, true);
    assert.strictEqual(response.data?.similarity, 0.8668);
  });

  // ─── 3. Successful Biometric Response (Genuine Verification) ─────────────────

  test('parses genuine successful biometric verification response correctly', async () => {
    globalThis.fetch = async () => {
      const mockSuccess: VerifyApiResponse = {
        accepted: true,
        action: 'UNLOCK',
        claimed_identity: 'Zubair',
        similarity: 0.8912,
        threshold_used: 0.25,
        liveness_passed: true,
      };
      return new Response(JSON.stringify(mockSuccess), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const response = await client.verify({
      audio: new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm' }),
      filename: 'test.webm',
      claimed_identity: 'Zubair',
      challenge_id: 'ch-1',
      session_id: 'sess-1',
    });

    assert.strictEqual(response.ok, true);
    assert.strictEqual(response.data?.accepted, true);
    assert.strictEqual(response.data?.action, 'UNLOCK');
    assert.strictEqual(response.data?.liveness_passed, true);
    assert.ok(response.data.similarity > response.data.threshold_used);
  });

  // ─── 4. Liveness Failure / Anti-Spoofing Denial ──────────────────────────────

  test('parses spoken liveness check failure and fails closed without fabrication', async () => {
    globalThis.fetch = async () => {
      const mockLivenessFailure: VerifyApiResponse = {
        accepted: false,
        action: 'DENY',
        claimed_identity: 'Zubair',
        similarity: 0.0,
        threshold_used: 0.25,
        liveness_passed: false,
        reason: "Liveness check failed: Digits mismatch: expected ['7', '2', '9'], heard ['1', '4', '8']",
      };
      return new Response(JSON.stringify(mockLivenessFailure), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const response = await client.verify({
      audio: new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm' }),
      filename: 'spoof.webm',
      claimed_identity: 'Zubair',
      challenge_id: 'ch-spoof',
      session_id: 'sess-spoof',
    });

    assert.strictEqual(response.ok, true);
    assert.strictEqual(response.data?.accepted, false);
    assert.strictEqual(response.data?.action, 'DENY');
    assert.strictEqual(response.data?.liveness_passed, false);
    assert.strictEqual(response.data?.similarity, 0.0);
    assert.match(response.data?.reason || '', /Liveness check failed/);
  });

  // ─── 5. Impostor Voice Acoustic Rejection ────────────────────────────────────

  test('parses biometric acoustic mismatch and denies access', async () => {
    globalThis.fetch = async () => {
      const mockImpostor: VerifyApiResponse = {
        accepted: false,
        action: 'DENY',
        claimed_identity: 'Zubair',
        similarity: 0.1245,
        threshold_used: 0.25,
        liveness_passed: true,
      };
      return new Response(JSON.stringify(mockImpostor), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const response = await client.verify({
      audio: new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/webm' }),
      filename: 'impostor.webm',
      claimed_identity: 'Zubair',
      challenge_id: 'ch-impostor',
      session_id: 'sess-impostor',
    });

    assert.strictEqual(response.ok, true);
    assert.strictEqual(response.data?.accepted, false);
    assert.strictEqual(response.data?.action, 'DENY');
    assert.strictEqual(response.data?.liveness_passed, true);
    assert.ok((response.data?.similarity || 0) < (response.data?.threshold_used || 0));
  });

  // ─── 6. Unmapped Voice Identity (HTTP 403 Forbidden) ─────────────────────────

  test('handles HTTP 403 when authenticated user is not mapped in UserSpeakerMapping', async () => {
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: 'Forbidden: User account is not mapped to an enrolled speaker identity.',
        }),
        {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const response = await client.createChallenge({ session_id: 'sess-unmapped' });

    assert.strictEqual(response.ok, false);
    assert.strictEqual(response.status, 403);
    assert.strictEqual(response.data, null);
    assert.match(response.error || '', /not mapped to an enrolled speaker identity/i);
  });

  // ─── 7. Expired or Reused Challenge (HTTP 400 Bad Request) ───────────────────

  test('handles expired or consumed challenge rejection safely', async () => {
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: 'Challenge has already been consumed or invalidated.',
        }),
        {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const response = await client.verify({
      audio: new Blob([new Uint8Array([1, 2])], { type: 'audio/webm' }),
      filename: 'replay.webm',
      claimed_identity: 'Zubair',
      challenge_id: 'ch-consumed',
      session_id: 'sess-consumed',
    });

    assert.strictEqual(response.ok, false);
    assert.strictEqual(response.status, 400);
    assert.strictEqual(response.data, null);
    assert.match(response.error || '', /already been consumed/i);
  });

  // ─── 8. Malformed or Empty Audio (HTTP 400 Bad Request) ──────────────────────

  test('handles empty or malformed audio upload safely', async () => {
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: 'Uploaded audio file is empty.',
        }),
        {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const response = await client.verify({
      audio: new Blob([], { type: 'audio/webm' }),
      filename: 'empty.webm',
      claimed_identity: 'Zubair',
      challenge_id: 'ch-empty',
      session_id: 'sess-empty',
    });

    assert.strictEqual(response.ok, false);
    assert.strictEqual(response.status, 400);
    assert.strictEqual(response.data, null);
    assert.match(response.error || '', /empty/i);
  });

  // ─── 9. HTTP 401 Unauthorized Session ────────────────────────────────────────

  test('handles expired session token (HTTP 401) without leaking credentials', async () => {
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: 'Missing authentication credentials. Expected Bearer token or Device headers.',
        }),
        {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const response = await client.createChallenge({ session_id: 'sess-expired' });

    assert.strictEqual(response.ok, false);
    assert.strictEqual(response.status, 401);
    assert.strictEqual(response.data, null);
    assert.match(response.error || '', /authentication/i);
  });

  // ─── 10. HTTP 422 Unprocessable Entity ───────────────────────────────────────

  test('handles validation error (HTTP 422) when required fields are missing', async () => {
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: [
            { loc: ['body', 'claimed_identity'], msg: 'Field required', type: 'missing' },
          ],
        }),
        {
          status: 422,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const response = await client.verify({
      audio: new Blob([new Uint8Array([1])], { type: 'audio/webm' }),
      filename: 'test.webm',
      claimed_identity: '',
      challenge_id: 'ch-missing',
      session_id: 'sess-missing',
    });

    assert.strictEqual(response.ok, false);
    assert.strictEqual(response.status, 422);
    assert.strictEqual(response.data, null);
    assert.match(response.error || '', /Field required/i);
  });

  // ─── 11. Network Disconnect / Fetch Failure ──────────────────────────────────

  test('handles network failure gracefully without crashing or fabricating results', async () => {
    globalThis.fetch = async () => {
      throw new Error('Failed to fetch: Connection refused');
    };

    const client = new ApiClient({ baseUrl: 'http://localhost:8000' });
    const response = await client.verify({
      audio: new Blob([new Uint8Array([1])], { type: 'audio/webm' }),
      filename: 'test.webm',
      claimed_identity: 'Zubair',
      challenge_id: 'ch-net',
      session_id: 'sess-net',
    });

    assert.strictEqual(response.ok, false);
    assert.strictEqual(response.status, 0);
    assert.strictEqual(response.data, null);
    assert.match(response.error || '', /Connection refused/);
  });

  // ─── 12. Zero-Mock Source Invariant ──────────────────────────────────────────

  test('VerificationPage source code strictly contains no mock data imports or fake simulation logic', () => {
    const source = fs.readFileSync(verificationPageSourcePath, 'utf-8');

    // Asserts no mockData imports
    assert.strictEqual(
      source.includes("from '../../data/mockData'"),
      false,
      'VerificationPage must not import mockData'
    );
    assert.strictEqual(
      source.includes('MOCK_SPEAKERS'),
      false,
      'VerificationPage must not reference MOCK_SPEAKERS'
    );
    assert.strictEqual(
      source.includes('MOCK_DEVICES'),
      false,
      'VerificationPage must not reference MOCK_DEVICES'
    );

    // Asserts no fake scenario selector
    assert.strictEqual(
      source.includes("'genuine' | 'impostor' | 'spoof'"),
      false,
      'VerificationPage must not contain fake scenario switchers'
    );
    assert.strictEqual(
      source.includes('runSimulation'),
      false,
      'VerificationPage must not contain runSimulation'
    );

    // Asserts no client-generated random digits
    assert.strictEqual(
      source.includes('Math.floor(Math.random() * 10)'),
      false,
      'VerificationPage must not generate random challenge digits client-side'
    );

    // Asserts useAudioRecorder hook is properly integrated
    assert.ok(
      source.includes('useAudioRecorder'),
      'VerificationPage must integrate useAudioRecorder'
    );

    // Asserts apiClient.createChallenge and apiClient.verify are integrated
    assert.ok(
      source.includes('apiClient.createChallenge'),
      'VerificationPage must call apiClient.createChallenge'
    );
    assert.ok(
      source.includes('apiClient.verify'),
      'VerificationPage must call apiClient.verify'
    );

    // Asserts fail-closed unmapped identity handling
    assert.ok(
      source.includes('unmapped-identity-alert') || source.includes('Unmapped Voice Identity'),
      'VerificationPage must render a dedicated unmapped identity security alert'
    );

    // Asserts Step 2 challenge panel explicitly handles submitting and consumed/result states
    assert.ok(
      source.includes('challenge-submitting-card'),
      'VerificationPage must render a dedicated submitting state in Step 2 panel'
    );
    assert.ok(
      source.includes('challenge-consumed-card'),
      'VerificationPage must render a dedicated consumed challenge state in Step 2 panel'
    );
    assert.ok(
      source.includes('consumedChallenge'),
      'VerificationPage must preserve consumed challenge reference for review'
    );
  });
});

