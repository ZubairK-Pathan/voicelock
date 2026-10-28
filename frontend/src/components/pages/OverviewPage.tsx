import React, { useState, useEffect, useCallback } from 'react';
import {
  Users,
  Cpu,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  ShieldCheck,
  ShieldAlert,
  Sliders,
  Radio,
  Database,
  RefreshCw,
  Lock,
  User,
  Mic,
  KeyRound,
} from 'lucide-react';
import { StatCard } from '../common/StatCard';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../ui/Card';
import { Alert, AlertTitle, AlertDescription } from '../ui/Alert';
import { useAuth } from '../../context/useAuth';
import { apiClient } from '../../lib/apiClient';
import type { NavigationTab, VerificationMetricsResponse } from '../../types';

interface OverviewPageProps {
  onNavigate: (tab: NavigationTab) => void;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({ onNavigate }) => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  // ─── Administrator Overview State ──────────────────────────────────────────
  const [speakersCount, setSpeakersCount] = useState<number | null>(null);
  const [devicesCount, setDevicesCount] = useState<number | null>(null);
  const [activeDevicesCount, setActiveDevicesCount] = useState<number | null>(null);
  const [verificationMetrics, setVerificationMetrics] = useState<VerificationMetricsResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [statusCode, setStatusCode] = useState<number | null>(null);
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);

  // ─── Regular User Overview State ───────────────────────────────────────────
  const [userMappingStatus, setUserMappingStatus] = useState<'checking' | 'mapped' | 'unmapped' | 'error'>('checking');
  const [linkedSpeakerName, setLinkedSpeakerName] = useState<string | null>(null);

  const handleRefresh = useCallback(() => {
    setIsLoading(true);
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  // ─── Telemetry Fetching ───────────────────────────────────────────────────
  useEffect(() => {
    let ignore = false;

    async function loadTelemetry() {
      setIsLoading(true);
      setError(null);
      setStatusCode(null);

      if (isAdmin) {
        // Administrator Telemetry Loading
        try {
          const [speakersRes, devicesRes, metricsRes] = await Promise.all([
            apiClient.getSpeakers(),
            apiClient.getDevices(),
            apiClient.getVerificationMetrics(),
          ]);

          if (ignore) return;

          // Check for 401 Unauthorized across any endpoint
          if (
            speakersRes.status === 401 ||
            devicesRes.status === 401 ||
            metricsRes.status === 401
          ) {
            setStatusCode(401);
            setError(
              'Your operator session has expired or is unauthenticated. Please re-authenticate to view live system metrics.'
            );
            setSpeakersCount(null);
            setDevicesCount(null);
            setActiveDevicesCount(null);
            setVerificationMetrics(null);
            return;
          }

          // Check for 403 Forbidden across any endpoint
          if (
            speakersRes.status === 403 ||
            devicesRes.status === 403 ||
            metricsRes.status === 403
          ) {
            setStatusCode(403);
            setError(
              'Administrative privileges are required to retrieve system telemetry and registries. Non-administrative operators are restricted.'
            );
            setSpeakersCount(null);
            setDevicesCount(null);
            setActiveDevicesCount(null);
            setVerificationMetrics(null);
            return;
          }

          if (speakersRes.ok && speakersRes.data) {
            setSpeakersCount(speakersRes.data.count);
          } else {
            setSpeakersCount(null);
          }

          if (devicesRes.ok && devicesRes.data) {
            setDevicesCount(devicesRes.data.total);
            setActiveDevicesCount(devicesRes.data.active_count);
          } else {
            setDevicesCount(null);
            setActiveDevicesCount(null);
          }

          if (metricsRes.ok && metricsRes.data) {
            setVerificationMetrics(metricsRes.data);
          } else {
            setVerificationMetrics(null);
          }

          if (!speakersRes.ok && !devicesRes.ok && !metricsRes.ok) {
            setStatusCode(speakersRes.status || devicesRes.status || metricsRes.status);
            setError(
              speakersRes.error ||
                devicesRes.error ||
                metricsRes.error ||
                'Failed to retrieve system metrics from the database backend.'
            );
          } else if (!metricsRes.ok && (speakersRes.ok || devicesRes.ok)) {
            setError(
              metricsRes.error || 'Verification telemetry endpoint returned an error.'
            );
            setStatusCode(metricsRes.status);
          }
        } catch {
          if (!ignore) {
            setStatusCode(0);
            setError('Network communication failed while connecting to the VoiceLock API backend.');
            setSpeakersCount(null);
            setDevicesCount(null);
            setActiveDevicesCount(null);
            setVerificationMetrics(null);
          }
        } finally {
          if (!ignore) {
            setIsLoading(false);
          }
        }
      } else {
        // Regular User Enrollment Status Probe
        // Checks whether user account is mapped to an enrolled voice identity without calling admin APIs
        try {
          const probeSessionId = `probe-${Date.now()}`;
          const res = await apiClient.createChallenge({ session_id: probeSessionId });
          if (ignore) return;

          if (res.ok && res.data) {
            setUserMappingStatus('mapped');
            setLinkedSpeakerName(res.data.claimed_identity);
          } else if (res.status === 403) {
            setUserMappingStatus('unmapped');
            setLinkedSpeakerName(null);
          } else if (res.status === 401) {
            setUserMappingStatus('error');
            setError('Your operator session has expired. Please sign in again.');
          } else {
            setUserMappingStatus('error');
            setError(res.error || 'Failed to determine biometric enrollment status.');
          }
        } catch {
          if (!ignore) {
            setUserMappingStatus('error');
            setError('Network communication failure while verifying account status.');
          }
        } finally {
          if (!ignore) {
            setIsLoading(false);
          }
        }
      }
    }

    loadTelemetry();

    return () => {
      ignore = true;
    };
  }, [isAdmin, refreshTrigger]);

  // ─── Subtitles for Administrator View ──────────────────────────────────────
  const getSpeakersSubtitle = () => {
    if (isLoading) return 'Querying biometric registry...';
    if (statusCode === 401) return 'Session unauthenticated';
    if (statusCode === 403) return 'Admin authorization required';
    if (speakersCount === null) return 'Registry unavailable';
    if (speakersCount === 0) return '0 enrolled profiles (Database empty)';
    return `${speakersCount} active biometric profiles in database`;
  };

  const getDevicesSubtitle = () => {
    if (isLoading) return 'Querying terminal registry...';
    if (statusCode === 401) return 'Session unauthenticated';
    if (statusCode === 403) return 'Admin authorization required';
    if (devicesCount === null) return 'Registry unavailable';
    if (devicesCount === 0) return '0 terminals registered (Awaiting provisioning)';
    return `${activeDevicesCount ?? 0} online of ${devicesCount} registered units`;
  };

  const getSuccessRateValue = () => {
    if (isLoading) return '—';
    if (verificationMetrics !== null) {
      return `${verificationMetrics.success_rate.toFixed(1)}%`;
    }
    return '—';
  };

  const getSuccessRateSubtitle = () => {
    if (isLoading) return 'Querying verification telemetry...';
    if (statusCode === 401) return 'Session unauthenticated';
    if (statusCode === 403) return 'Admin authorization required';
    if (verificationMetrics === null) return 'Telemetry unavailable';
    if (verificationMetrics.total === 0) return '0 attempts recorded (Journal empty)';
    const evaluated =
      verificationMetrics.verified +
      verificationMetrics.rejected +
      verificationMetrics.challenge_failed;
    return `${verificationMetrics.verified} verified of ${evaluated} evaluated attempts`;
  };

  // ═══════════════════════════════════════════════════════════════════════════
  // REGULAR OPERATOR VIEW
  // ═══════════════════════════════════════════════════════════════════════════
  if (!isAdmin) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        {/* User Welcome & Portal Header */}
        <div
          className="card"
          style={{
            background: 'linear-gradient(90deg, rgba(59, 130, 246, 0.08) 0%, rgba(14, 20, 34, 0.8) 100%)',
            borderLeft: '4px solid var(--color-brand)',
            padding: '18px 22px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '14px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: 'var(--radius-sm)',
                background: 'rgba(59, 130, 246, 0.15)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'var(--color-brand)',
              }}
            >
              <User size={22} />
            </div>
            <div>
              <div className="text-base font-semibold text-primary">
                Operator Portal — {user?.displayName || user?.email}
              </div>
              <div className="text-xs text-secondary" style={{ marginTop: '2px' }}>
                VoiceLock Enterprise Biometric Access Control & Physical Security
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Badge variant="default">OPERATOR ROLE</Badge>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleRefresh}
              disabled={isLoading}
            >
              <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} /> Refresh
            </Button>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <Alert variant="destructive">
            <AlertTitle>Authentication Status Notice</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {/* Grid: Identity Card + Primary Verification CTA */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '20px' }}>
          {/* Biometric Identity Binding Status */}
          <Card>
            <CardHeader>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <CardTitle>Biometric Voiceprint Status</CardTitle>
                {isLoading ? (
                  <Badge variant="secondary">Verifying...</Badge>
                ) : userMappingStatus === 'mapped' ? (
                  <Badge variant="success">ENROLLED & ACTIVE</Badge>
                ) : userMappingStatus === 'unmapped' ? (
                  <Badge variant="warning">UNMAPPED ACCOUNT</Badge>
                ) : (
                  <Badge variant="destructive">PROBE FAILED</Badge>
                )}
              </div>
              <CardDescription>
                Persistent account association in the enterprise UserSpeakerMapping registry
              </CardDescription>
            </CardHeader>
            <CardContent>
              {isLoading ? (
                <div style={{ padding: '24px 0', textAlign: 'center', color: 'var(--text-muted)' }}>
                  <RefreshCw size={18} className="animate-spin" style={{ margin: '0 auto 8px' }} />
                  <div className="text-xs">Resolving identity mapping from server...</div>
                </div>
              ) : userMappingStatus === 'mapped' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div
                    style={{
                      padding: '14px 16px',
                      background: 'rgba(16, 185, 129, 0.08)',
                      border: '1px solid rgba(16, 185, 129, 0.2)',
                      borderRadius: 'var(--radius-sm)',
                    }}
                  >
                    <div className="text-xs font-semibold" style={{ color: '#34D399' }}>
                      Linked Voiceprint Profile
                    </div>
                    <div className="font-mono text-xl font-bold text-primary" style={{ marginTop: '4px' }}>
                      {linkedSpeakerName}
                    </div>
                    <div className="text-xs text-secondary" style={{ marginTop: '4px' }}>
                      Authorized for 1-to-1 challenge verification at all enrolled terminals.
                    </div>
                  </div>
                  <div className="text-xs text-muted" style={{ lineHeight: 1.5 }}>
                    Your Firebase account UID (<span className="font-mono text-secondary">{user?.uid}</span>) is bound to this speaker voiceprint. All verification attempts are validated server-side against this registered mapping.
                  </div>
                </div>
              ) : userMappingStatus === 'unmapped' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div
                    style={{
                      padding: '14px 16px',
                      background: 'rgba(245, 158, 11, 0.08)',
                      border: '1px solid rgba(245, 158, 11, 0.2)',
                      borderRadius: 'var(--radius-sm)',
                    }}
                  >
                    <div className="text-xs font-semibold" style={{ color: '#FBBF24', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <AlertTriangle size={14} /> Action Required: Identity Unmapped
                    </div>
                    <p className="text-xs text-secondary" style={{ marginTop: '6px', lineHeight: 1.5 }}>
                      Your authenticated account has not yet been linked to an enrolled speaker voiceprint in the database.
                    </p>
                  </div>
                  <div
                    style={{
                      background: 'rgba(0, 0, 0, 0.3)',
                      padding: '10px 14px',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '11px',
                      fontFamily: 'monospace',
                      color: '#94A3B8',
                    }}
                  >
                    Account UID: {user?.uid}
                  </div>
                  <p className="text-xs text-muted" style={{ lineHeight: 1.5, margin: 0 }}>
                    Please provide your Firebase UID to a VoiceLock administrator. Once linked via the Identity Management panel, your voice biometric verification will be authorized automatically.
                  </p>
                </div>
              ) : (
                /* userMappingStatus === 'error' */
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div
                    style={{
                      padding: '14px 16px',
                      background: 'rgba(239, 68, 68, 0.08)',
                      border: '1px solid rgba(239, 68, 68, 0.25)',
                      borderRadius: 'var(--radius-sm)',
                    }}
                  >
                    <div className="text-xs font-semibold" style={{ color: '#F87171', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <AlertTriangle size={14} /> Biometric Enrollment Status Unavailable
                    </div>
                    <p className="text-xs text-secondary" style={{ marginTop: '6px', lineHeight: 1.5 }}>
                      {error || 'A network, authentication, or server error occurred while probing identity mapping. This is a connectivity or session issue, not a confirmed unmapped account.'}
                    </p>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                    <div className="text-xs font-mono text-muted">Account UID: {user?.uid}</div>
                    <Button variant="secondary" size="sm" onClick={handleRefresh}>
                      Retry Status Check
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Quick Verification Entry Point Card */}
          <Card>
            <CardHeader>
              <CardTitle>Voice Biometric Verification</CardTitle>
              <CardDescription>
                Verify identity using cryptographic challenge-response and ECAPA-TDNN AI
              </CardDescription>
            </CardHeader>
            <CardContent style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div
                style={{
                  padding: '16px',
                  background: 'rgba(59, 130, 246, 0.06)',
                  border: '1px solid rgba(59, 130, 246, 0.2)',
                  borderRadius: 'var(--radius-sm)',
                  display: 'flex',
                  gap: '12px',
                  alignItems: 'flex-start',
                }}
              >
                <Mic size={22} color="#60A5FA" style={{ flexShrink: 0, marginTop: '2px' }} />
                <div>
                  <div className="text-xs font-semibold text-primary">
                    Spoken Liveness Challenge-Response
                  </div>
                  <p className="text-xs text-secondary" style={{ marginTop: '4px', lineHeight: 1.5 }}>
                    When verifying, the server issues a single-use 3-digit randomized sequence with a 60-second time-to-live. Offline Vosk STT confirms spoken digits before SpeechBrain runs biometric matching to mitigate simple replay attacks.
                  </p>
                </div>
              </div>

              <div style={{ marginTop: 'auto' }}>
                <Button
                  variant="default"
                  size="lg"
                  onClick={() => onNavigate('verification')}
                  style={{ width: '100%' }}
                >
                  <Mic size={16} /> Open Voice Verification Terminal <ArrowRight size={16} />
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Security & Privacy Disclosures Card */}
        <Card>
          <CardHeader>
            <CardTitle>Biometric Security & Privacy Disclosures</CardTitle>
            <CardDescription>
              Architectural implementation disclosures and privacy boundaries enforced by VoiceLock Enterprise
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
              <div style={{ padding: '12px 14px', background: 'rgba(14, 20, 34, 0.4)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                <div className="text-xs font-semibold text-primary" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <ShieldCheck size={14} color="#10B981" /> Temporary Audio Processing
                </div>
                <p className="text-xs text-secondary" style={{ marginTop: '6px', lineHeight: 1.4 }}>
                  Voice recordings submitted during verification are written to temporary server storage solely for duration of processing, evaluated by STT and acoustic inference, and unlinked upon completion. Raw audio is not stored in the database.
                </p>
              </div>

              <div style={{ padding: '12px 14px', background: 'rgba(14, 20, 34, 0.4)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                <div className="text-xs font-semibold text-primary" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <KeyRound size={14} color="#60A5FA" /> Liveness Challenge & Replay Mitigation
                </div>
                <p className="text-xs text-secondary" style={{ marginTop: '6px', lineHeight: 1.4 }}>
                  Liveness protection uses a randomized spoken-digit challenge designed to mitigate simple audio replay attacks. It does not guarantee protection against sophisticated voice cloning, deepfakes, or all presentation attacks.
                </p>
              </div>

              <div style={{ padding: '12px 14px', background: 'rgba(14, 20, 34, 0.4)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border-subtle)' }}>
                <div className="text-xs font-semibold text-primary" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Lock size={14} color="#8B5CF6" /> Server-Enforced Identity Binding
                </div>
                <p className="text-xs text-secondary" style={{ marginTop: '6px', lineHeight: 1.4 }}>
                  Server-side role-based access control restricts non-administrative operators to their bound speaker identity. Verification requests for unmapped identities or mismatched claims are rejected with HTTP 403.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // ADMINISTRATOR SYSTEM OVERVIEW
  // ═══════════════════════════════════════════════════════════════════════════
  return (
    <div className="operations-page">
      {/* Top Banner Notice */}
      <div
        className="card operations-intro"
        style={{
          background: 'linear-gradient(90deg, rgba(59, 130, 246, 0.08) 0%, rgba(14, 20, 34, 0.8) 100%)',
          borderLeft: '4px solid var(--color-brand)',
          padding: '16px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '36px',
              height: '36px',
              borderRadius: 'var(--radius-sm)',
              background: 'rgba(59, 130, 246, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--color-brand)',
            }}
          >
            <ShieldCheck size={20} />
          </div>
          <div>
            <div className="text-sm font-semibold text-primary">
              VoiceLock Enterprise Core Engine Online
            </div>
            <div className="text-xs text-secondary" style={{ marginTop: '2px' }}>
              Acoustic Speaker Recognition (ECAPA-TDNN) & Vosk Offline STT Challenge-Response Liveness Detection
            </div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span className={`badge ${isLoading ? 'badge-suspended' : 'badge-active'} font-mono`}>
            {isLoading ? 'Syncing...' : 'Live Engine Active'}
          </span>
          <button
            onClick={handleRefresh}
            className="btn btn-secondary"
            style={{ fontSize: '12px', padding: '6px 12px' }}
            title="Refresh live metrics"
            disabled={isLoading}
          >
            <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} /> Refresh
          </button>
          <button
            onClick={() => onNavigate('verification')}
            className="btn btn-primary"
            style={{ fontSize: '12px', padding: '6px 14px' }}
          >
            Launch Verification Simulator <ArrowRight size={14} />
          </button>
        </div>
      </div>

      {/* Error & Warning Banners */}
      {error && (
        <div
          className="card"
          style={{
            padding: '14px 18px',
            borderRadius: 'var(--radius-sm)',
            borderLeft: `4px solid ${
              statusCode === 401 ? '#F59E0B' : statusCode === 403 ? '#EF4444' : '#F87171'
            }`,
            background:
              statusCode === 401
                ? 'rgba(245, 158, 11, 0.08)'
                : 'rgba(239, 68, 68, 0.08)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {statusCode === 401 ? (
              <Lock size={18} color="#F59E0B" style={{ flexShrink: 0 }} />
            ) : statusCode === 403 ? (
              <ShieldAlert size={18} color="#EF4444" style={{ flexShrink: 0 }} />
            ) : (
              <AlertTriangle size={18} color="#F87171" style={{ flexShrink: 0 }} />
            )}
            <div>
              <div
                className="text-xs font-semibold"
                style={{
                  color:
                    statusCode === 401
                      ? '#FBBF24'
                      : statusCode === 403
                      ? '#F87171'
                      : '#FCA5A5',
                }}
              >
                {statusCode === 401
                  ? 'Authentication Required'
                  : statusCode === 403
                  ? 'Administrative Access Restricted'
                  : 'Backend Telemetry Error'}
              </div>
              <div className="text-xs text-secondary" style={{ marginTop: '2px' }}>
                {error}
              </div>
            </div>
          </div>
          <button
            onClick={handleRefresh}
            className="btn btn-secondary"
            style={{ fontSize: '11px', padding: '4px 10px' }}
          >
            Retry Query
          </button>
        </div>
      )}

      {/* KPI Cards Grid */}
      <div className="operations-metrics">
        <StatCard
          title="Enrolled Biometric Profiles"
          value={isLoading ? '—' : speakersCount !== null ? speakersCount : '—'}
          subtitle={getSpeakersSubtitle()}
          icon={<Users size={20} />}
        />
        <StatCard
          title="Physical Access Terminals"
          value={isLoading ? '—' : devicesCount !== null ? devicesCount : '—'}
          subtitle={getDevicesSubtitle()}
          icon={<Cpu size={20} />}
        />
        <StatCard
          title="Biometric Success Rate"
          value={getSuccessRateValue()}
          subtitle={getSuccessRateSubtitle()}
          icon={<CheckCircle2 size={20} />}
        />
        <StatCard
          title="Total Verification Attempts"
          value={isLoading ? '—' : verificationMetrics !== null ? verificationMetrics.total : '—'}
          subtitle={
            isLoading
              ? 'Querying verification log...'
              : verificationMetrics !== null
              ? `${verificationMetrics.verified} verified, ${verificationMetrics.rejected} rejected`
              : 'Audit log uninstrumented'
          }
          icon={<Radio size={20} />}
        />
      </div>

      {/* Verification Telemetry Breakdown Card */}
      <div className="card operations-panel operations-telemetry">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' }}>
          <div>
            <h3 className="text-base font-semibold text-primary">Biometric Decision Telemetry</h3>
            <p className="text-xs text-muted" style={{ marginTop: '2px' }}>
              Persistent outcome categorization from VerificationEvent records
            </p>
          </div>
          <span className="badge badge-active font-mono">
            {verificationMetrics ? `${verificationMetrics.total} Total Attempts` : 'Live Telemetry'}
          </span>
        </div>

        <div className="operations-outcomes">
          {/* Verified */}
          <div className="operation-outcome outcome-verified"
            style={{
              padding: '14px 16px',
              borderRadius: 'var(--radius-sm)',
              background: 'rgba(16, 185, 129, 0.08)',
              border: '1px solid rgba(16, 185, 129, 0.2)',
              display: 'flex',
              flexDirection: 'column',
              gap: '4px',
            }}
          >
            <div className="text-xs font-semibold" style={{ color: '#34D399' }}>
              Verified (Access Granted)
            </div>
            <div className="font-mono text-xl font-bold" style={{ color: '#10B981' }}>
              {isLoading ? '—' : verificationMetrics !== null ? verificationMetrics.verified : '—'}
            </div>
            <div className="text-xs text-secondary">
              Biometric match &ge; threshold (0.25)
            </div>
          </div>

          {/* Biometric Rejected */}
          <div className="operation-outcome outcome-rejected"
            style={{
              padding: '14px 16px',
              borderRadius: 'var(--radius-sm)',
              background: 'rgba(239, 68, 68, 0.08)',
              border: '1px solid rgba(239, 68, 68, 0.2)',
              display: 'flex',
              flexDirection: 'column',
              gap: '4px',
            }}
          >
            <div className="text-xs font-semibold" style={{ color: '#F87171' }}>
              Biometric Rejected
            </div>
            <div className="font-mono text-xl font-bold" style={{ color: '#EF4444' }}>
              {isLoading ? '—' : verificationMetrics !== null ? verificationMetrics.rejected : '—'}
            </div>
            <div className="text-xs text-secondary">
              Similarity below threshold (&lt; 0.25)
            </div>
          </div>

          {/* Challenge Failed */}
          <div className="operation-outcome outcome-challenge"
            style={{
              padding: '14px 16px',
              borderRadius: 'var(--radius-sm)',
              background: 'rgba(245, 158, 11, 0.08)',
              border: '1px solid rgba(245, 158, 11, 0.2)',
              display: 'flex',
              flexDirection: 'column',
              gap: '4px',
            }}
          >
            <div className="text-xs font-semibold" style={{ color: '#FBBF24' }}>
              Challenge Failed (Spoof / STT)
            </div>
            <div className="font-mono text-xl font-bold" style={{ color: '#F59E0B' }}>
              {isLoading ? '—' : verificationMetrics !== null ? verificationMetrics.challenge_failed : '—'}
            </div>
            <div className="text-xs text-secondary">
              Liveness challenge digits unverified
            </div>
          </div>

          {/* Processing Error */}
          <div className="operation-outcome outcome-processing"
            style={{
              padding: '14px 16px',
              borderRadius: 'var(--radius-sm)',
              background: 'rgba(100, 116, 139, 0.08)',
              border: '1px solid rgba(100, 116, 139, 0.2)',
              display: 'flex',
              flexDirection: 'column',
              gap: '4px',
            }}
          >
            <div className="text-xs font-semibold" style={{ color: '#94A3B8' }}>
              Processing Errors
            </div>
            <div className="font-mono text-xl font-bold" style={{ color: '#CBD5E1' }}>
              {isLoading ? '—' : verificationMetrics !== null ? verificationMetrics.error : '—'}
            </div>
            <div className="text-xs text-secondary">
              Excluded from success-rate denominator
            </div>
          </div>
        </div>

        {/* Footer info note */}
        <div
          style={{
            marginTop: '14px',
            paddingTop: '12px',
            borderTop: '1px solid rgba(255, 255, 255, 0.05)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '8px',
          }}
        >
          <div className="text-xs text-muted" style={{ lineHeight: '1.4' }}>
            Success Rate Formula:{' '}
            <span className="font-mono text-secondary">
              verified / (verified + rejected + challenge_failed) &times; 100
            </span>
            . Processing errors represent audio decode or server faults and are excluded.
          </div>
          {verificationMetrics && (
            <div className="text-xs font-mono text-secondary">
              Computed Rate: {verificationMetrics.success_rate.toFixed(2)}%
            </div>
          )}
        </div>
      </div>

      {/* Middle Split: Biometric Calibration & Security Alerts */}
      <div className="operations-split">
        {/* ML Calibration Status */}
        <div className="card operations-panel calibration-panel">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <div>
              <h3 className="text-base font-semibold text-primary">Biometric Model Calibration</h3>
              <p className="text-xs text-muted" style={{ marginTop: '2px' }}>
                Offline baseline calibration & decision boundary (SpeechBrain ECAPA-TDNN)
              </p>
            </div>
            <span className="badge badge-active font-mono">Calibrated</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="text-xs text-secondary">Server Decision Threshold</span>
              <span className="font-mono text-xs font-semibold text-primary" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Sliders size={12} color="#3B82F6" /> 0.2500 (SERVER_THRESHOLD)
              </span>
            </div>
            {/* Visual Threshold Bar */}
            <div style={{ position: 'relative', width: '100%', height: '10px', background: 'rgba(255, 255, 255, 0.05)', borderRadius: '5px', overflow: 'hidden' }}>
              <div style={{ position: 'absolute', left: '0', width: '25%', height: '100%', background: 'linear-gradient(90deg, #EF4444, #F59E0B)' }} />
              <div style={{ position: 'absolute', left: '25%', width: '75%', height: '100%', background: 'linear-gradient(90deg, #10B981, #059669)' }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-muted)' }}>
              <span>0.00 (Reject Impostor)</span>
              <span style={{ color: '#3B82F6', fontWeight: 600 }}>Threshold: 0.25</span>
              <span>1.00 (Genuine Match)</span>
            </div>

            <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.5)', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(255, 255, 255, 0.05)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
              <div>
                <div className="text-xs text-muted">Genuine Mean Score</div>
                <div className="font-mono text-sm font-semibold" style={{ color: '#34D399' }}>0.8136</div>
              </div>
              <div>
                <div className="text-xs text-muted">Worst Impostor Score</div>
                <div className="font-mono text-sm font-semibold" style={{ color: '#F87171' }}>0.2520</div>
              </div>
              <div>
                <div className="text-xs text-muted">Feature Dimension</div>
                <div className="font-mono text-sm text-secondary">192-d ECAPA</div>
              </div>
              <div>
                <div className="text-xs text-muted">Sampling Rate</div>
                <div className="font-mono text-sm text-secondary">16,000 Hz Mono</div>
              </div>
            </div>

            <div className="text-xs text-muted" style={{ lineHeight: '1.4' }}>
              Calibrated against sentence-disjoint evaluation split. The server threshold is authoritative and cannot be lowered by client requests.
            </div>
          </div>
        </div>

        {/* Threat & Replay Monitoring */}
        <div className="card operations-panel threat-panel">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <div>
              <h3 className="text-base font-semibold text-primary">Threat & Replay Monitoring</h3>
              <p className="text-xs text-muted" style={{ marginTop: '2px' }}>
                Runtime security controls & incident telemetry
              </p>
            </div>
            <button
              onClick={() => onNavigate('events')}
              className="btn btn-secondary"
              style={{ fontSize: '11px', padding: '4px 10px' }}
            >
              View Audit Console
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div
              style={{
                padding: '12px',
                background: 'rgba(14, 20, 34, 0.5)',
                border: '1px solid rgba(255, 255, 255, 0.05)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                gap: '12px',
                alignItems: 'flex-start',
              }}
            >
              <div style={{ marginTop: '2px' }}>
                <ShieldCheck size={16} color="#34D399" />
              </div>
              <div style={{ flex: 1 }}>
                <div className="text-xs font-semibold text-primary">
                  In-Memory Security Controls Active
                </div>
                <p className="text-xs text-secondary" style={{ marginTop: '2px', lineHeight: '1.4' }}>
                  60-second CSPRNG digit challenges with atomic burn-on-use, sliding-window HMAC nonce verification, and ASGI upload size rate limits are actively enforced.
                </p>
              </div>
            </div>

            {/* Security Disclosure: Absence of events does not imply zero threat */}
            <div
              style={{
                padding: '12px',
                background: 'rgba(239, 68, 68, 0.06)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                gap: '12px',
                alignItems: 'flex-start',
              }}
            >
              <div style={{ marginTop: '2px' }}>
                <ShieldAlert size={16} color="#F87171" />
              </div>
              <div style={{ flex: 1 }}>
                <div className="text-xs font-semibold" style={{ color: '#F87171' }}>
                  Security Disclosure: Event Journal Uninstrumented
                </div>
                <p className="text-xs text-secondary" style={{ marginTop: '2px', lineHeight: '1.4' }}>
                  The absence of logged incidents reflects uninstrumented event storage in this increment, not the absence of attacks or verified zero-failure operations.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Recent Biometric Access Attempts Table / Uninstrumented State */}
      <div className="card operations-panel activity-panel">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
          <div>
            <h3 className="text-base font-semibold text-primary">Recent Biometric Access Attempts</h3>
            <p className="text-xs text-muted" style={{ marginTop: '2px' }}>
              Live verification attempt streaming across physical terminals
            </p>
          </div>
          <button
            onClick={() => onNavigate('verification')}
            className="btn btn-secondary"
            style={{ fontSize: '12px', padding: '6px 12px' }}
          >
            <Radio size={14} /> Open Verification Console
          </button>
        </div>

        <div
          style={{
            padding: '36px 20px',
            textAlign: 'center',
            background: 'rgba(14, 20, 34, 0.3)',
            borderRadius: 'var(--radius-sm)',
            border: '1px dashed rgba(255, 255, 255, 0.08)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '12px',
          }}
        >
          <div
            style={{
              width: '44px',
              height: '44px',
              borderRadius: '50%',
              background: 'rgba(59, 130, 246, 0.1)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#60A5FA',
            }}
          >
            <Database size={22} />
          </div>
          <div>
            <div className="text-sm font-semibold text-primary">
              Biometric Access Journal Uninstrumented
            </div>
            <p className="text-xs text-secondary" style={{ maxWidth: '460px', margin: '4px auto 0', lineHeight: '1.5' }}>
              Biometric verification attempts are evaluated in real time by the SpeechBrain ECAPA-TDNN model and Vosk STT engine. Persistent verification audit logs will be provisioned in an upcoming milestone.
            </p>
          </div>
          <button
            onClick={() => onNavigate('verification')}
            className="btn btn-primary"
            style={{ fontSize: '12px', padding: '6px 14px', marginTop: '4px' }}
          >
            Launch Verification Simulator
          </button>
        </div>
      </div>
    </div>
  );
};
