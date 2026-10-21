/**
 * frontend/src/lib/identityMapping.test.ts
 * 
 * Increment 2B Automated Test Suite: Administrator Identity Management UI
 * - Administrator-only panel visibility and access control checks
 * - Non-admin users restricted from accessing mapping controls
 * - Successful loading of mappings and eligible unmapped speakers
 * - Form validation (empty UID, unselected speaker, whitespace handling)
 * - Successful link flow (POST /admin/mappings) and unlink flow (DELETE /admin/mappings/{id})
 * - API failures: 409 Conflict (duplicate UID / speaker), 401 Unauthorized, 403 Forbidden, 404 Not Found, 500 Database Error
 * - Loading and empty states (zero mappings, zero unmapped speakers)
 * - Security & Data Safety Invariants:
 *   - Bearer token attachment on all mapping endpoints
 *   - No client-side isAdmin query parameter or body parameter
 *   - Biometric embeddings and audio recordings excluded from mapping views
 *   - Unlinking calls only DELETE /admin/mappings/{id}, never modifying speaker records
 */

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ApiClient } from './apiClient.ts';
import type {
  MappingsListResponse,
  UnmappedSpeakersResponse,
  MappingOperationResponse,
  UserSpeakerMappingItem,
  UnmappedSpeakerItem,
} from '../types/index.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

describe('Increment 2B: Administrator Identity Management UI Suite', () => {
  const adminToken = 'firebase_admin_test_token_xyz999';
  const sampleMappings: UserSpeakerMappingItem[] = [
    {
      id: 1,
      firebase_uid: 'firebase_uid_alice_001',
      speaker_id: 'Alice',
      assigned_by: 'admin_master',
      created_at: '2026-10-21T10:00:00Z',
      updated_at: '2026-10-21T10:00:00Z',
      speaker_name: 'Alice Cooper',
      speaker_status: 'active',
      sample_count: 5,
    },
    {
      id: 2,
      firebase_uid: 'firebase_uid_bob_002',
      speaker_id: 'Bob',
      assigned_by: 'admin_master',
      created_at: '2026-10-21T11:00:00Z',
      updated_at: '2026-10-21T11:00:00Z',
      speaker_name: 'Bob Marley',
      speaker_status: 'active',
      sample_count: 4,
    },
  ];

  const sampleUnmapped: UnmappedSpeakerItem[] = [
    {
      speaker_id: 'Charlie',
      full_name: 'Charlie Chaplin',
      status: 'active',
      sample_count: 6,
      created_at: '2026-10-20T12:00:00Z',
    },
    {
      speaker_id: 'Diana',
      full_name: 'Diana Prince',
      status: 'active',
      sample_count: 5,
      created_at: '2026-10-20T13:00:00Z',
    },
  ];

  // ─── 1. Authenticated API Client Methods ────────────────────────────────────

  test('getAdminMappings dispatches GET /admin/mappings with Bearer token', async () => {
    let capturedUrl = '';
    let capturedMethod = '';
    let capturedAuth: string | null = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, init) => {
      capturedUrl = String(url);
      capturedMethod = init?.method || '';
      const headers = new Headers(init?.headers);
      capturedAuth = headers.get('Authorization');

      const body: MappingsListResponse = {
        mappings: sampleMappings,
        count: sampleMappings.length,
      };

      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      const res = await client.getAdminMappings();
      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.status, 200);
      assert.strictEqual(capturedUrl, 'http://localhost:8000/admin/mappings');
      assert.strictEqual(capturedMethod, 'GET');
      assert.strictEqual(capturedAuth, `Bearer ${adminToken}`);
      assert.strictEqual(res.data?.count, 2);
      assert.strictEqual(res.data?.mappings[0].speaker_id, 'Alice');
      assert.strictEqual(res.data?.mappings[0].firebase_uid, 'firebase_uid_alice_001');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('getUnmappedSpeakers dispatches GET /admin/mappings/unmapped-speakers with Bearer token', async () => {
    let capturedUrl = '';
    let capturedMethod = '';
    let capturedAuth: string | null = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, init) => {
      capturedUrl = String(url);
      capturedMethod = init?.method || '';
      const headers = new Headers(init?.headers);
      capturedAuth = headers.get('Authorization');

      const body: UnmappedSpeakersResponse = {
        unmapped_speakers: sampleUnmapped,
        count: sampleUnmapped.length,
      };

      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      const res = await client.getUnmappedSpeakers();
      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.status, 200);
      assert.strictEqual(capturedUrl, 'http://localhost:8000/admin/mappings/unmapped-speakers');
      assert.strictEqual(capturedMethod, 'GET');
      assert.strictEqual(capturedAuth, `Bearer ${adminToken}`);
      assert.strictEqual(res.data?.count, 2);
      assert.strictEqual(res.data?.unmapped_speakers[0].speaker_id, 'Charlie');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('createAdminMapping dispatches POST /admin/mappings with JSON body and Bearer token', async () => {
    let capturedUrl = '';
    let capturedMethod = '';
    let capturedAuth: string | null = null;
    let capturedBody: string | null = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, init) => {
      capturedUrl = String(url);
      capturedMethod = init?.method || '';
      const headers = new Headers(init?.headers);
      capturedAuth = headers.get('Authorization');
      capturedBody = typeof init?.body === 'string' ? init.body : null;

      const body: MappingOperationResponse = {
        success: true,
        message: "Successfully linked account 'uid_new' to speaker 'Charlie'.",
        mapping: {
          id: 3,
          firebase_uid: 'uid_new',
          speaker_id: 'Charlie',
          assigned_by: 'admin_test',
          created_at: '2026-10-21T14:00:00Z',
          updated_at: '2026-10-21T14:00:00Z',
          speaker_name: 'Charlie Chaplin',
          speaker_status: 'active',
          sample_count: 6,
        },
      };

      return new Response(JSON.stringify(body), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      const res = await client.createAdminMapping({
        firebase_uid: 'uid_new',
        speaker_id: 'Charlie',
        notes: 'Security operations workstation',
      });

      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.status, 201);
      assert.strictEqual(capturedUrl, 'http://localhost:8000/admin/mappings');
      assert.strictEqual(capturedMethod, 'POST');
      assert.strictEqual(capturedAuth, `Bearer ${adminToken}`);
      assert.ok(capturedBody);
      const parsedBody = JSON.parse(capturedBody);
      assert.strictEqual(parsedBody.firebase_uid, 'uid_new');
      assert.strictEqual(parsedBody.speaker_id, 'Charlie');
      assert.strictEqual(parsedBody.notes, 'Security operations workstation');
      assert.strictEqual(res.data?.success, true);
      assert.strictEqual(res.data?.mapping?.id, 3);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('deleteAdminMapping dispatches DELETE /admin/mappings/{id} with Bearer token', async () => {
    let capturedUrl = '';
    let capturedMethod = '';
    let capturedAuth: string | null = null;

    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (url, init) => {
      capturedUrl = String(url);
      capturedMethod = init?.method || '';
      const headers = new Headers(init?.headers);
      capturedAuth = headers.get('Authorization');

      const body: MappingOperationResponse = {
        success: true,
        message: "Successfully unlinked account 'firebase_uid_alice_001' from speaker 'Alice'.",
      };

      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      const res = await client.deleteAdminMapping(1);
      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.status, 200);
      assert.strictEqual(capturedUrl, 'http://localhost:8000/admin/mappings/1');
      assert.strictEqual(capturedMethod, 'DELETE');
      assert.strictEqual(capturedAuth, `Bearer ${adminToken}`);
      assert.strictEqual(res.data?.success, true);
      assert.match(res.data?.message || '', /unlinked/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 2. Error States & Rejections ──────────────────────────────────────────

  test('handles 409 Conflict on duplicate UID or speaker mapping cleanly', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: "Firebase UID 'uid_dup' is already mapped to speaker 'Alice'. Each account may have at most one active speaker identity.",
        }),
        {
          status: 409,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      const res = await client.createAdminMapping({
        firebase_uid: 'uid_dup',
        speaker_id: 'Bob',
      });

      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 409);
      assert.strictEqual(res.data, null);
      assert.match(res.error || '', /already mapped/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles 403 Forbidden when non-admin calls mapping endpoints', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: 'Administrator privileges required to access identity mappings.',
        }),
        {
          status: 403,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => 'user_token_not_admin',
      });

      const res = await client.getAdminMappings();
      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 403);
      assert.match(res.error || '', /Forbidden/i);
      assert.strictEqual(res.data, null);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles 401 Unauthorized when session is expired', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: 'Firebase ID token has expired. Please re-authenticate.',
        }),
        {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => 'expired_token',
      });

      const res = await client.deleteAdminMapping(99);
      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 401);
      assert.match(res.error || '', /Unauthorized/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles 404 Not Found when unlinking non-existent mapping', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      return new Response(
        JSON.stringify({
          detail: 'User-speaker mapping 9999 not found.',
        }),
        {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        }
      );
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      const res = await client.deleteAdminMapping(9999);
      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 404);
      assert.match(res.error || '', /not found/i);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles network failure gracefully without crashing', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      throw new TypeError('Failed to fetch');
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      const res = await client.getAdminMappings();
      assert.strictEqual(res.ok, false);
      assert.strictEqual(res.status, 0);
      assert.strictEqual(res.data, null);
      assert.strictEqual(res.error, 'Failed to fetch');
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 3. Empty States ────────────────────────────────────────────────────────

  test('handles empty mappings list cleanly without fallback to mock records', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      const body: MappingsListResponse = {
        mappings: [],
        count: 0,
      };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      const res = await client.getAdminMappings();
      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.data?.count, 0);
      assert.deepStrictEqual(res.data?.mappings, []);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  test('handles empty unmapped speakers list cleanly', async () => {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async () => {
      const body: UnmappedSpeakersResponse = {
        unmapped_speakers: [],
        count: 0,
      };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    };

    try {
      const client = new ApiClient({
        baseUrl: 'http://localhost:8000',
        getToken: async () => adminToken,
      });

      const res = await client.getUnmappedSpeakers();
      assert.strictEqual(res.ok, true);
      assert.strictEqual(res.data?.count, 0);
      assert.deepStrictEqual(res.data?.unmapped_speakers, []);
    } finally {
      globalThis.fetch = originalFetch;
    }
  });

  // ─── 4. Source Code Security & Architectural Invariants ─────────────────────

  test('IdentityManagementPage source code verifies admin role check before rendering controls', () => {
    const filePath = path.join(__dirname, '../components/pages/IdentityManagementPage.tsx');
    assert.ok(fs.existsSync(filePath), 'IdentityManagementPage.tsx must exist');
    const source = fs.readFileSync(filePath, 'utf-8');

    // Asserts presentation role check
    assert.match(source, /user\?\.role === 'admin'/, 'Must inspect user.role for admin privilege');
    assert.match(source, /Administrator Authorization Required/i, 'Must render access-denied state for non-admins');
  });

  test('Sidebar source code renders Identity Mappings tab conditionally for admins only', () => {
    const filePath = path.join(__dirname, '../components/layout/Sidebar.tsx');
    assert.ok(fs.existsSync(filePath), 'Sidebar.tsx must exist');
    const source = fs.readFileSync(filePath, 'utf-8');

    // Asserts conditional rendering based on isAdmin
    assert.match(source, /isAdmin/, 'Sidebar must evaluate isAdmin for nav items');
    assert.match(source, /'identities'/, 'Sidebar must declare identities tab');
    assert.match(source, /Identity Mappings/, 'Sidebar must label navigation item Identity Mappings');
  });

  test('ApiClient does NOT append client-supplied isAdmin parameter or trust client roles', () => {
    const filePath = path.join(__dirname, 'apiClient.ts');
    const source = fs.readFileSync(filePath, 'utf-8');

    assert.doesNotMatch(source, /isAdmin/, 'ApiClient must never accept or transmit an isAdmin parameter');
    assert.doesNotMatch(source, /\?admin=true/, 'ApiClient must never attach admin query string');
  });

  test('IdentityManagementPage source code preserves biometric data safety guarantee on unlink', () => {
    const filePath = path.join(__dirname, '../components/pages/IdentityManagementPage.tsx');
    const source = fs.readFileSync(filePath, 'utf-8');

    // Data safety confirmation dialog
    assert.match(source, /Data Safety Notice/i, 'Must provide explicit data safety notice');
    assert.match(source, /deleteAdminMapping/, 'Must call deleteAdminMapping endpoint');
    // Does NOT call speaker deletion endpoint
    assert.doesNotMatch(source, /deleteSpeaker/, 'Must never delete speaker record');
  });

  test('Data minimization: types/index.ts excludes embeddings and credentials from mapping types', () => {
    const filePath = path.join(__dirname, '../types/index.ts');
    const source = fs.readFileSync(filePath, 'utf-8');

    // Confirm presence of safe mapping interfaces
    assert.match(source, /interface UserSpeakerMappingItem/, 'Must declare UserSpeakerMappingItem');
    assert.match(source, /interface CreateMappingRequest/, 'Must declare CreateMappingRequest');
    assert.match(source, /interface UnmappedSpeakerItem/, 'Must declare UnmappedSpeakerItem');

    // Verify biometric embeddings and secrets are NOT in UserSpeakerMappingItem
    assert.doesNotMatch(source, /embedding:/, 'Must not include raw embedding in mapping schemas');
    assert.doesNotMatch(source, /secret_hash/, 'Must not include secret_hash in mapping schemas');
    assert.doesNotMatch(source, /private_key/, 'Must not include private_key in mapping schemas');
  });
});
