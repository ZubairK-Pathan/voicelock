export type NavigationTab = 'overview' | 'speakers' | 'verification' | 'devices' | 'events';

export type EntityStatus = 'active' | 'suspended' | 'revoked';

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
