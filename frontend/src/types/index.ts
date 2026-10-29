export type NavigationTab = 'overview' | 'speakers' | 'verification' | 'devices' | 'events' | 'identities';

export type EntityStatus = 'active' | 'suspended' | 'revoked';

export interface CreateMappingRequest {
  firebase_uid: string;
  speaker_id: string;
  notes?: string;
  metadata_json?: string;
}

export interface UserSpeakerMappingItem {
  id: number;
  firebase_uid: string;
  speaker_id: string;
  assigned_by: string | null;
  created_at: string;
  updated_at: string;
  speaker_name: string | null;
  speaker_status: EntityStatus | string | null;
  sample_count: number | null;
}

export interface MappingsListResponse {
  mappings: UserSpeakerMappingItem[];
  count: number;
}

export interface UnmappedSpeakerItem {
  speaker_id: string;
  full_name: string | null;
  status: EntityStatus | string;
  sample_count: number;
  created_at: string;
}

export interface UnmappedSpeakersResponse {
  unmapped_speakers: UnmappedSpeakerItem[];
  count: number;
}

export interface MappingOperationResponse {
  success: boolean;
  message: string;
  mapping?: UserSpeakerMappingItem | null;
}

export interface SpeakersApiResponse {
  registered_speakers: string[];
  count: number;
}

export interface SpeakerEnrollmentResponse {
  speaker_id: string;
  full_name: string | null;
  status: string;
  sample_count: number;
  embedding_dim: number;
  created_at: string;
}

export interface HealthApiResponse {
  status: string;
  service: string;
  version: string;
  threshold?: number | null;
  enrolled_speakers?: number | null;
}

export interface DeviceSummaryItem {
  device_id: string;
  name: string | null;
  status: EntityStatus;
  key_version: number;
}

export interface DevicesApiResponse {
  devices: DeviceSummaryItem[];
  total: number;
  active_count: number;
}

export interface VerificationMetricsResponse {
  total: number;
  verified: number;
  rejected: number;
  challenge_failed: number;
  error: number;
  success_rate: number;
  start_time: string | null;
  end_time: string | null;
  verification_flow: string | null;
}

export type EventSeverity = 'low' | 'medium' | 'high' | 'critical';

export interface Speaker {
  id: string;
  speaker_id: string;
  name: string;
  department: string;
  status: EntityStatus;
  embedding_dim: number;
  sample_count: number;
  last_verified_at: string;
  created_at: string;
  firebase_uid: string | null;
  security_clearance: 'Tier 1 - Standard' | 'Tier 2 - Restricted' | 'Tier 3 - Critical';
}

export interface Device {
  id: string;
  device_id: string;
  name: string;
  location: string;
  ip_address: string;
  status: EntityStatus;
  auth_scheme: 'HMAC-SHA256' | 'Pre-Shared Key';
  key_version: number;
  last_seen_at: string;
  firmware_version: string;
  total_verifications: number;
}

export interface SecurityEventItem {
  id: number;
  created_at: string;
  event_type: string;
  severity: EventSeverity | string;
  status: 'blocked' | 'detected' | 'logged' | 'resolved' | string;
  details: string | null;
  user_id: string | null;
  device_id: string | null;
  request_id: string | null;
  metadata: Record<string, unknown> | null;
}

export interface SecurityEventsResponse {
  events: SecurityEventItem[];
  next_cursor: string | null;
  has_more: boolean;
  count: number;
}

export interface SecurityEventFilters {
  limit?: number;
  cursor?: string | null;
  event_type?: string;
  severity?: EventSeverity | string;
  status?: string;
  user_id?: string;
  device_id?: string;
  request_id?: string;
  start_time?: string;
  end_time?: string;
}

export interface SecurityEvent {
  id: string;
  timestamp: string;
  event_type: 
    | 'BIOMETRIC_VERIFY_SUCCESS'
    | 'BIOMETRIC_VERIFY_FAILURE'
    | 'LIVENESS_CHALLENGE_FAILED'
    | 'HMAC_NONCE_REPLAY'
    | 'UNKNOWN_DEVICE_REJECTED'
    | 'REVOKED_DEVICE_BLOCKED'
    | 'RATE_LIMIT_EXCEEDED'
    | 'ADMIN_SPEAKER_ENROLLED';
  severity: EventSeverity;
  source: string;
  speaker_id?: string;
  device_id?: string;
  details: string;
}

export interface VerificationRecord {
  id: string;
  timestamp: string;
  speaker_name: string;
  speaker_id: string;
  similarity_score: number;
  threshold: number;
  liveness_digits: string;
  liveness_pass: boolean;
  result: 'GRANTED' | 'DENIED' | 'SPOOF_DETECTED';
  device_id: string;
  device_name: string;
  latency_ms: number;
}

export interface OverviewMetrics {
  total_speakers: number;
  active_speakers: number;
  total_devices: number;
  active_devices: number;
  success_rate_percent: number;
  verifications_today: number;
  critical_alerts: number;
  avg_latency_ms: number;
}

export interface ChallengeRequest {
  claimed_identity?: string;
  session_id?: string;
}

export interface ChallengeApiResponse {
  challenge_id: string;
  session_id: string;
  claimed_identity: string | null;
  digits: string[];
  display: string;
  expires_at: number;
  expires_in_seconds: number;
}

export interface VerifyRequest {
  audio: Blob | File;
  claimed_identity: string;
  challenge_id: string;
  session_id: string;
  filename?: string;
}

export interface VerifyApiResponse {
  accepted: boolean;
  action: 'UNLOCK' | 'DENY';
  claimed_identity: string;
  similarity: number;
  threshold_used: number;
  liveness_passed: boolean;
  reason?: string | null;
}
