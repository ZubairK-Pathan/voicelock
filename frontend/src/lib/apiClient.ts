/**
 * frontend/src/lib/apiClient.ts — Authenticated API Client for VoiceLock Enterprise.
 * 
 * Securely communicates with FastAPI backend (/speakers, /verify, /challenge, /identify).
 * Strictly attaches Firebase ID tokens via 'Authorization: Bearer <ID_TOKEN>'.
 * Never exposes tokens in URLs, query strings, or debug logs.
 */

import type {
  SpeakersApiResponse,
  DevicesApiResponse,
  VerificationMetricsResponse,
  ChallengeRequest,
  ChallengeApiResponse,
  VerifyRequest,
  VerifyApiResponse,
  CreateMappingRequest,
  MappingsListResponse,
  UnmappedSpeakersResponse,
  MappingOperationResponse,
} from '../types';
import { auth, isFirebaseConfigured } from './firebase.ts';

export interface ApiClientConfig {
  baseUrl: string;
  getToken?: (forceRefresh?: boolean) => Promise<string | null>;
}

export interface ApiResponse<T = unknown> {
  data: T | null;
  status: number;
  ok: boolean;
  error?: string;
}

export class ApiClient {
  private baseUrl: string;
  private getTokenFn?: (forceRefresh?: boolean) => Promise<string | null>;
  private activeRefreshPromise: Promise<string | null> | null = null;

  constructor(config?: Partial<ApiClientConfig>) {
    const envBaseUrl =
      typeof import.meta !== 'undefined' && import.meta.env
        ? import.meta.env.VITE_API_BASE_URL
        : undefined;

    this.baseUrl = (
      config?.baseUrl ||
      envBaseUrl ||
      'http://localhost:8000'
    ).replace(/\/$/, '');
    this.getTokenFn = config?.getToken;
  }

  public setTokenProvider(provider: (forceRefresh?: boolean) => Promise<string | null>): void {
    this.getTokenFn = provider;
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  /**
   * Acquires the authentication ID token.
   * If a custom token provider is configured, invokes it.
   * Otherwise falls back to Firebase SDK auth instance when available.
   */
  public async acquireToken(forceRefresh: boolean = false): Promise<string | null> {
    if (this.getTokenFn) {
      try {
        return await this.getTokenFn(forceRefresh);
      } catch {
        return null;
      }
    }

    // Default fallback to Firebase SDK if initialized
    if (isFirebaseConfigured() && auth) {
      if (typeof auth.authStateReady === 'function') {
        try {
          await auth.authStateReady();
        } catch {
          // ignore
        }
      }
      if (auth.currentUser) {
        try {
          return await auth.currentUser.getIdToken(forceRefresh);
        } catch {
          return null;
        }
      }
    }

    return null;
  }

  /**
   * Refreshes the ID token using deduplication to prevent concurrent refresh stampedes.
   */
  private async refreshAuthToken(): Promise<string | null> {
    if (!this.activeRefreshPromise) {
      this.activeRefreshPromise = this.acquireToken(true).finally(() => {
        this.activeRefreshPromise = null;
      });
    }
    return this.activeRefreshPromise;
  }

  /**
   * Constructs request headers attaching Bearer ID token when available.
   * Never leaks raw token into console logs or error payloads.
   */
  public async buildHeaders(
    customHeaders?: HeadersInit,
    requiresAuth: boolean = true,
    isFormData: boolean = false,
    forcedToken?: string | null
  ): Promise<Headers> {
    const headers = new Headers(customHeaders || {});

    if (!isFormData && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    } else if (isFormData && headers.has('Content-Type')) {
      // Do not manually set multipart Content-Type so fetch generates the boundary
      headers.delete('Content-Type');
    }

    if (requiresAuth) {
      try {
        const token = forcedToken || (await this.acquireToken(false));
        if (token) {
          headers.set('Authorization', `Bearer ${token}`);
        }
      } catch {
        // Suppress token acquisition error to prevent sensitive leak
      }
    }

    return headers;
  }

  /**
   * Dispatches a typed HTTP request.
   */
  public async request<T = unknown>(
    endpoint: string,
    options: RequestInit & { requiresAuth?: boolean; _isRetry?: boolean; _refreshedToken?: string | null } = {}
  ): Promise<ApiResponse<T>> {
    const { requiresAuth = true, _isRetry = false, _refreshedToken = null, ...fetchOptions } = options;
    const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    const url = `${this.baseUrl}${cleanEndpoint}`;

    const isFormData =
      typeof FormData !== 'undefined' && fetchOptions.body instanceof FormData;

    try {
      const headers = await this.buildHeaders(
        fetchOptions.headers,
        requiresAuth,
        isFormData,
        _refreshedToken
      );

      const response = await fetch(url, {
        ...fetchOptions,
        headers,
      });

      const status = response.status;
      const ok = response.ok;

      let data: T | null = null;
      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        data = (await response.json()) as T;
      }

      // Controlled 401 recovery: allow at most one token-refresh retry for safe idempotent read requests
      if (status === 401 && requiresAuth && !_isRetry) {
        const method = (fetchOptions.method || 'GET').toUpperCase();
        // Safe read operations can be retried once with a refreshed token
        if (method === 'GET' || method === 'HEAD' || method === 'OPTIONS') {
          const refreshedToken = await this.refreshAuthToken();
          if (refreshedToken) {
            return this.request<T>(endpoint, {
              ...options,
              _isRetry: true,
              _refreshedToken: refreshedToken,
            });
          }
        }
      }

      if (status === 401) {
        const detail =
          data && typeof data === 'object' && 'detail' in data
            ? `: ${String((data as { detail: unknown }).detail)}`
            : ': Missing or invalid authentication token.';
        return {
          data: null,
          status,
          ok: false,
          error: `Unauthorized${detail}`,
        };
      }

      if (status === 403) {
        const detail =
          data && typeof data === 'object' && 'detail' in data
            ? `: ${String((data as { detail: unknown }).detail)}`
            : ': Insufficient role permissions or speaker identity mismatch.';
        return {
          data: null,
          status,
          ok: false,
          error: `Forbidden${detail}`,
        };
      }

      if (status === 429) {
        return {
          data: null,
          status,
          ok: false,
          error: 'Rate limit exceeded: Too many requests. Please slow down and try again shortly.',
        };
      }


      if (!ok) {
        let errorDetail = `Request failed with HTTP status ${status}`;
        if (data && typeof data === 'object') {
          if ('detail' in data) {
            const detail = (data as { detail: unknown }).detail;
            if (Array.isArray(detail)) {
              errorDetail = detail
                .map((d: unknown) => {
                  if (typeof d === 'object' && d !== null && 'msg' in d) {
                    return String((d as { msg: unknown }).msg);
                  }
                  return JSON.stringify(d);
                })
                .join('; ');
            } else {
              errorDetail = String(detail);
            }
          } else if ('message' in data) {
            errorDetail = String((data as { message: unknown }).message);
          }
        }
        return { data: null, status, ok: false, error: errorDetail };
      }

      return { data, status, ok };
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Network request failed';
      return {
        data: null,
        status: 0,
        ok: false,
        error: message,
      };
    }
  }

  public get<T = unknown>(endpoint: string, options?: RequestInit & { requiresAuth?: boolean }) {
    return this.request<T>(endpoint, { ...options, method: 'GET' });
  }

  public getSpeakers(options?: RequestInit & { requiresAuth?: boolean }) {
    return this.get<SpeakersApiResponse>('/speakers', options);
  }

  public getDevices(options?: RequestInit & { requiresAuth?: boolean }) {
    return this.get<DevicesApiResponse>('/devices', options);
  }

  public getVerificationMetrics(
    params?: {
      start_time?: string;
      end_time?: string;
      verification_flow?: string;
    },
    options?: RequestInit & { requiresAuth?: boolean }
  ) {
    const query = new URLSearchParams();
    if (params?.start_time) query.set('start_time', params.start_time);
    if (params?.end_time) query.set('end_time', params.end_time);
    if (params?.verification_flow) query.set('verification_flow', params.verification_flow);

    const queryString = query.toString();
    const endpoint = queryString
      ? `/metrics/verification?${queryString}`
      : '/metrics/verification';

    return this.get<VerificationMetricsResponse>(endpoint, options);
  }

  public post<T = unknown>(
    endpoint: string,
    body?: unknown,
    options?: RequestInit & { requiresAuth?: boolean }
  ) {
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    return this.request<T>(endpoint, {
      ...options,
      method: 'POST',
      body: isFormData
        ? (body as FormData)
        : body !== undefined
        ? JSON.stringify(body)
        : undefined,
    });
  }

  /**
   * Request a randomized liveness challenge from POST /challenge.
   * Challenge expires in 60s and is bound to the verification session.
   */
  public createChallenge(
    payload?: ChallengeRequest,
    options?: RequestInit & { requiresAuth?: boolean }
  ): Promise<ApiResponse<ChallengeApiResponse>> {
    return this.post<ChallengeApiResponse>('/challenge', payload || {}, options);
  }

  /**
   * Submit recorded audio and challenge tokens to POST /verify.
   * Accepts either a structured VerifyRequest or an existing FormData object.
   * Packages fields as multipart/form-data without manual Content-Type header
   * so browser boundary is preserved.
   */
  public verify(
    payload: VerifyRequest | FormData,
    options?: RequestInit & { requiresAuth?: boolean }
  ): Promise<ApiResponse<VerifyApiResponse>> {
    let formData: FormData;

    if (typeof FormData !== 'undefined' && payload instanceof FormData) {
      formData = payload;
    } else {
      const req = payload as VerifyRequest;
      formData = new FormData();
      const filename =
        req.filename ||
        (typeof File !== 'undefined' && req.audio instanceof File && req.audio.name
          ? req.audio.name
          : 'audio.wav');
      formData.append('audio', req.audio, filename);
      formData.append('claimed_identity', req.claimed_identity);
      formData.append('challenge_id', req.challenge_id);
      formData.append('session_id', req.session_id);
    }

    return this.post<VerifyApiResponse>('/verify', formData, options);
  }

  /**
   * Alias for verify() to support explicit naming.
   */
  public verifyAudio(
    payload: VerifyRequest | FormData,
    options?: RequestInit & { requiresAuth?: boolean }
  ): Promise<ApiResponse<VerifyApiResponse>> {
    return this.verify(payload, options);
  }

  /**
   * Dispatches a typed DELETE request.
   */
  public delete<T = unknown>(
    endpoint: string,
    options?: RequestInit & { requiresAuth?: boolean }
  ): Promise<ApiResponse<T>> {
    return this.request<T>(endpoint, { ...options, method: 'DELETE' });
  }

  /**
   * Fetch all active user-to-speaker mappings.
   * Requires verified administrator session (RBAC).
   */
  public getAdminMappings(
    options?: RequestInit & { requiresAuth?: boolean }
  ): Promise<ApiResponse<MappingsListResponse>> {
    return this.get<MappingsListResponse>('/admin/mappings', options);
  }

  /**
   * Fetch eligible unmapped active speakers for association.
   * Requires verified administrator session (RBAC).
   */
  public getUnmappedSpeakers(
    options?: RequestInit & { requiresAuth?: boolean }
  ): Promise<ApiResponse<UnmappedSpeakersResponse>> {
    return this.get<UnmappedSpeakersResponse>('/admin/mappings/unmapped-speakers', options);
  }

  /**
   * Link an authenticated Firebase user UID to an enrolled speaker identity.
   * Requires verified administrator session (RBAC).
   */
  public createAdminMapping(
    payload: CreateMappingRequest,
    options?: RequestInit & { requiresAuth?: boolean }
  ): Promise<ApiResponse<MappingOperationResponse>> {
    return this.post<MappingOperationResponse>('/admin/mappings', payload, options);
  }

  /**
   * Unlink a user-to-speaker mapping by its primary key identifier.
   * Note: Deletes only the mapping record. Preserves speaker voiceprint embeddings and audio.
   * Requires verified administrator session (RBAC).
   */
  public deleteAdminMapping(
    mappingId: number,
    options?: RequestInit & { requiresAuth?: boolean }
  ): Promise<ApiResponse<MappingOperationResponse>> {
    return this.delete<MappingOperationResponse>(`/admin/mappings/${mappingId}`, options);
  }
}

export const apiClient = new ApiClient();
