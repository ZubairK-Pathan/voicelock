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
} from '../types';

export interface ApiClientConfig {
  baseUrl: string;
  getToken?: () => Promise<string | null>;
}

export interface ApiResponse<T = unknown> {
  data: T | null;
  status: number;
  ok: boolean;
  error?: string;
}

export class ApiClient {
  private baseUrl: string;
  private getTokenFn?: () => Promise<string | null>;

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

  public setTokenProvider(provider: () => Promise<string | null>): void {
    this.getTokenFn = provider;
  }

  public getBaseUrl(): string {
    return this.baseUrl;
  }

  /**
   * Constructs request headers attaching Bearer ID token when available.
   * Never leaks raw token into console logs or error payloads.
   */
  public async buildHeaders(
    customHeaders?: HeadersInit,
    requiresAuth: boolean = true
  ): Promise<Headers> {
    const headers = new Headers(customHeaders || {});

    if (!headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }

    if (requiresAuth && this.getTokenFn) {
      try {
        const token = await this.getTokenFn();
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
    options: RequestInit & { requiresAuth?: boolean } = {}
  ): Promise<ApiResponse<T>> {
    const { requiresAuth = true, ...fetchOptions } = options;
    const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    const url = `${this.baseUrl}${cleanEndpoint}`;

    try {
      const headers = await this.buildHeaders(fetchOptions.headers, requiresAuth);

      const response = await fetch(url, {
        ...fetchOptions,
        headers,
      });

      const status = response.status;
      const ok = response.ok;

      if (status === 401) {
        return {
          data: null,
          status,
          ok: false,
          error: 'Unauthorized: Missing or invalid authentication token.',
        };
      }

      if (status === 403) {
        return {
          data: null,
          status,
          ok: false,
          error: 'Forbidden: Insufficient role permissions or speaker identity mismatch.',
        };
      }

      let data: T | null = null;
      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        data = (await response.json()) as T;
      }

      if (!ok) {
        const errorDetail =
          data && typeof data === 'object' && 'detail' in data
            ? String((data as { detail: unknown }).detail)
            : `Request failed with HTTP status ${status}`;
        return { data: null, status, ok, error: errorDetail };
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
    return this.request<T>(endpoint, {
      ...options,
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    });
  }
}

export const apiClient = new ApiClient();
