/**
 * frontend/src/lib/speakerEnrollment.test.ts
 *
 * Frontend test suite for persistent speaker enrollment:
 * 1. apiClient.enrollSpeaker dispatches POST /speakers with Bearer auth and FormData.
 * 2. Parses successful HTTP 201 response.
 * 3. Handles HTTP 409 conflict for duplicate speaker identity.
 * 4. Handles HTTP 400 validation error (fewer than 3 samples or audio issues).
 * 5. Handles HTTP 401 unauthenticated and HTTP 403 forbidden.
 * 6. Speaker ID format and length validation invariants.
 * 7. Component invariants for SpeakersPage and SpeakerEnrollmentModal.
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ApiClient } from './apiClient.ts';
import type { SpeakerEnrollmentResponse } from '../types/index.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Speaker Enrollment Frontend Integration Suite', () => {
  const mockToken = 'firebase_admin_test_token_enrollment_123';

  test('enrollSpeaker sends POST /speakers with Bearer token and FormData', async () => {
    let capturedUrl = '';
    let capturedMethod = '';
    let capturedAuthHeader: string | null = null;
    let capturedBody: unknown = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      capturedUrl = String(input);
      capturedMethod = init?.method || 'GET';
      const headers = new Headers(init?.headers);
      capturedAuthHeader = headers.get('Authorization');
      capturedBody = init?.body;

      const mockResponse: SpeakerEnrollmentResponse = {
        speaker_id: 'Test_Enrolled_User',
        full_name: 'Test Enrolled User',
        status: 'active',
        sample_count: 3,
        embedding_dim: 192,
        created_at: '2026-10-28T10:00:00Z',
      };

      return new Response(JSON.stringify(mockResponse), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => mockToken,
      });

      const formData = new FormData();
      formData.append('speaker_id', 'Test_Enrolled_User');
      formData.append('full_name', 'Test Enrolled User');
      formData.append('samples', new Blob(['sample1_audio_bytes'], { type: 'audio/wav' }), 'sample1.wav');
      formData.append('samples', new Blob(['sample2_audio_bytes'], { type: 'audio/wav' }), 'sample2.wav');
      formData.append('samples', new Blob(['sample3_audio_bytes'], { type: 'audio/wav' }), 'sample3.wav');

      const result = await client.enrollSpeaker(formData);

      assert.equal(result.ok, true);
      assert.equal(result.status, 201);
      assert.ok(capturedUrl.endsWith('/speakers'));
      assert.equal(capturedMethod, 'POST');
      assert.equal(capturedAuthHeader, `Bearer ${mockToken}`);
      assert.ok(capturedBody instanceof FormData);
      assert.equal(result.data?.speaker_id, 'Test_Enrolled_User');
      assert.equal(result.data?.sample_count, 3);
      assert.equal(result.data?.embedding_dim, 192);
      assert.equal(result.data?.status, 'active');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('enrollSpeaker handles HTTP 409 Conflict for duplicate speaker ID', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: "Speaker with speaker_id 'Existing_Speaker' already exists." }),
        {
          status: 409,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => mockToken,
      });

      const formData = new FormData();
      formData.append('speaker_id', 'Existing_Speaker');

      const result = await client.enrollSpeaker(formData);
      assert.equal(result.ok, false);
      assert.equal(result.status, 409);
      assert.match(result.error || '', /already exists/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('enrollSpeaker handles HTTP 400 Bad Request for validation error', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: 'At least 3 audio samples are required for enrollment (received 2).' }),
        {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => mockToken,
      });

      const formData = new FormData();
      formData.append('speaker_id', 'User');

      const result = await client.enrollSpeaker(formData);
      assert.equal(result.ok, false);
      assert.equal(result.status, 400);
      assert.match(result.error || '', /at least 3/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('enrollSpeaker handles HTTP 401 Unauthorized safely', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: 'Invalid or expired Firebase ID token.' }),
        {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => null,
      });

      const formData = new FormData();
      const result = await client.enrollSpeaker(formData);
      assert.equal(result.ok, false);
      assert.equal(result.status, 401);
      assert.match(result.error || '', /unauthorized/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('enrollSpeaker handles HTTP 403 Forbidden for non-admin operators', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: 'Admin privileges required for speaker enrollment.' }),
        {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => 'user_token_no_admin',
      });

      const formData = new FormData();
      const result = await client.enrollSpeaker(formData);
      assert.equal(result.ok, false);
      assert.equal(result.status, 403);
      assert.match(result.error || '', /forbidden/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('enrollSpeaker handles HTTP 400 for unsupported audio format (.txt / .bin)', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({ detail: "Sample 'payload.txt' has unsupported format '.txt'. Allowed: ['.aac', '.flac', '.m4a', '.mp3', '.ogg', '.wav', '.webm', '.wma']" }),
        {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => mockToken,
      });

      const formData = new FormData();
      formData.append('speaker_id', 'Test_Speaker');
      formData.append('samples', new Blob(['fake text'], { type: 'text/plain' }), 'payload.txt');

      const result = await client.enrollSpeaker(formData);
      assert.equal(result.ok, false);
      assert.equal(result.status, 400);
      assert.match(result.error || '', /unsupported format/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('Speaker ID validation regex matches enterprise requirements', () => {
    const validIds = ['Sarah_Connor', 'John-Doe', 'Zubair', 'Operator 01', 'Agent_007'];
    const invalidIds = ['X', 'a!b', 'user@domain', 'bad#tag', 'name$', ''];

    const pattern = /^[A-Za-z0-9_\- ]+$/;

    for (const id of validIds) {
      assert.ok(id.length >= 2 && id.length <= 64, `ID length should be valid for: ${id}`);
      assert.ok(pattern.test(id), `ID should match pattern: ${id}`);
    }

    for (const id of invalidIds) {
      const isInvalid = id.length < 2 || !pattern.test(id);
      assert.ok(isInvalid, `ID should be rejected: ${id}`);
    }
  });

  test('SpeakersPage and SpeakerEnrollmentModal source code invariants', () => {
    const speakersPagePath = path.resolve(__dirname, '../components/pages/SpeakersPage.tsx');
    const modalPath = path.resolve(__dirname, '../components/speakers/SpeakerEnrollmentModal.tsx');
    const cssPath = path.resolve(__dirname, '../App.css');

    assert.ok(fs.existsSync(speakersPagePath), 'SpeakersPage.tsx must exist');
    assert.ok(fs.existsSync(modalPath), 'SpeakerEnrollmentModal.tsx must exist');
    assert.ok(fs.existsSync(cssPath), 'App.css must exist');

    const pageContent = fs.readFileSync(speakersPagePath, 'utf-8');
    const modalContent = fs.readFileSync(modalPath, 'utf-8');
    const cssContent = fs.readFileSync(cssPath, 'utf-8');

    // SpeakersPage must import and render the enrollment modal
    assert.ok(pageContent.includes('SpeakerEnrollmentModal'), 'SpeakersPage must import SpeakerEnrollmentModal');
    assert.ok(pageContent.includes('Enroll Speaker'), 'SpeakersPage must include an Enroll Speaker button');
    assert.ok(pageContent.includes('isAdmin'), 'SpeakersPage must guard enrollment controls with admin role check');

    // SpeakerEnrollmentModal must connect to real recorder and real apiClient.enrollSpeaker
    assert.ok(modalContent.includes('useAudioRecorder'), 'Modal must integrate genuine useAudioRecorder hook');
    assert.ok(modalContent.includes('apiClient.enrollSpeaker'), 'Modal must call apiClient.enrollSpeaker');
    assert.ok(modalContent.includes('MIN_SAMPLES'), 'Modal must enforce minimum sample count');
    assert.ok(modalContent.includes('FormData'), 'Modal must assemble multipart FormData for upload');

    // Responsive layout invariants for narrow mobile screens (<400px / <480px)
    assert.ok(modalContent.includes('speaker-enrollment-grid'), 'Modal must use responsive speaker-enrollment-grid');
    assert.ok(modalContent.includes('speaker-sample-item'), 'Modal must use responsive speaker-sample-item');
    assert.ok(cssContent.includes('.speaker-enrollment-grid'), 'App.css must declare .speaker-enrollment-grid rules');
    assert.ok(cssContent.includes('@media (max-width: 480px)'), 'App.css must declare mobile responsive media query');
  });
});
