import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Mic,
  MicOff,
  Radio,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  RefreshCw,
  Play,
  Square,
  Trash2,
  Volume2,
  ShieldAlert,
  UserCheck,
} from 'lucide-react';
import { Badge } from '../common/Badge';
import { useAuth } from '../../context/useAuth';
import { apiClient } from '../../lib/apiClient';
import { useAudioRecorder } from '../../hooks/useAudioRecorder';
import type { ChallengeApiResponse, VerifyApiResponse } from '../../types';

type PageState =
  | 'idle'
  | 'requesting_challenge'
  | 'challenge_active'
  | 'challenge_expired'
  | 'submitting'
  | 'result'
  | 'error';

function generateSessionId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

export const VerificationPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  // Page lifecycle state
  const [pageState, setPageState] = useState<PageState>('idle');
  const [selectedSpeakerId, setSelectedSpeakerId] = useState<string>('Zubair');
  const [registeredSpeakers, setRegisteredSpeakers] = useState<string[]>([]);
  const [speakersLoading, setSpeakersLoading] = useState<boolean>(false);

  // Active server challenge
  const [challenge, setChallenge] = useState<ChallengeApiResponse | null>(null);
  const [consumedChallenge, setConsumedChallenge] = useState<ChallengeApiResponse | null>(null);
  const [challengeTtl, setChallengeTtl] = useState<number>(60);

  // Backend verification result or error
  const [verificationResult, setVerificationResult] = useState<VerifyApiResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);

  // Real browser microphone recording hook
  const recorder = useAudioRecorder({
    maxDurationSeconds: 10,
    baseFilename: 'liveness_recording',
  });

  // Playback URL for recorded audio blob (revoked automatically on cleanup)
  const audioPlaybackUrl = useMemo(() => {
    if (!recorder.recordedAudio) return null;
    return URL.createObjectURL(recorder.recordedAudio.blob);
  }, [recorder.recordedAudio]);

  useEffect(() => {
    return () => {
      if (audioPlaybackUrl) {
        URL.revokeObjectURL(audioPlaybackUrl);
      }
    };
  }, [audioPlaybackUrl]);

  // Load real registered speakers for admin operator context
  useEffect(() => {
    if (!isAdmin) return;

    let mounted = true;

    apiClient
      .getSpeakers()
      .then((res) => {
        if (!mounted) return;
        if (res.ok && res.data?.registered_speakers) {
          const list = res.data.registered_speakers;
          setRegisteredSpeakers(list);
          if (list.length > 0 && !list.includes(selectedSpeakerId)) {
            setSelectedSpeakerId(list[0]);
          }
        }
      })
      .catch(() => {
        // Fallback gracefully; admin can still use selected speaker
      })
      .finally(() => {
        if (mounted) setSpeakersLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [isAdmin, selectedSpeakerId]);

  // Challenge expiration countdown timer
  useEffect(() => {
    if (pageState !== 'challenge_active' || !challenge) return;

    const interval = window.setInterval(() => {
      setChallengeTtl((prev) => {
        if (prev <= 1) {
          setPageState('challenge_expired');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [pageState, challenge]);

  // Request real cryptographic challenge from POST /challenge
  const handleRequestChallenge = useCallback(async () => {
    setPageState('requesting_challenge');
    setErrorMessage(null);
    setErrorStatus(null);
    setVerificationResult(null);
    setConsumedChallenge(null);
    recorder.clearRecording();

    const sessionId = generateSessionId();
    const payload = isAdmin
      ? { claimed_identity: selectedSpeakerId, session_id: sessionId }
      : { session_id: sessionId };

    try {
      const response = await apiClient.createChallenge(payload);

      if (response.ok && response.data) {
        setChallenge(response.data);
        setChallengeTtl(response.data.expires_in_seconds || 60);
        setPageState('challenge_active');
      } else {
        setChallenge(null);
        setErrorStatus(response.status);
        setErrorMessage(
          response.error || 'Failed to obtain liveness challenge from server.'
        );
        setPageState('error');
      }
    } catch (err: unknown) {
      setChallenge(null);
      setErrorStatus(0);
      setErrorMessage(
        err instanceof Error
          ? err.message
          : 'Network error connecting to verification service.'
      );
      setPageState('error');
    }
  }, [isAdmin, selectedSpeakerId, recorder]);

  // Submit audio and challenge tokens to POST /verify
  const handleSubmitVerification = useCallback(async () => {
    if (!challenge) {
      setErrorMessage('No active challenge found. Please request a new challenge.');
      setPageState('error');
      return;
    }

    if (!recorder.recordedAudio) {
      setErrorMessage('No audio recording captured. Please record the challenge digits first.');
      setPageState('error');
      return;
    }

    if (challengeTtl <= 0 || pageState === 'challenge_expired') {
      setErrorMessage('Challenge has expired. Challenges are single-use and valid for 60 seconds.');
      setPageState('challenge_expired');
      return;
    }

    const claimed = challenge.claimed_identity || selectedSpeakerId;
    const activeChallengeId = challenge.challenge_id;
    const activeSessionId = challenge.session_id;

    // Single-attempt invalidation: Burn local challenge state immediately upon submission
    // Preserve evaluated challenge reference for display during verification and review
    setConsumedChallenge(challenge);
    setChallenge(null);
    setPageState('submitting');
    setErrorMessage(null);
    setErrorStatus(null);

    try {
      const response = await apiClient.verify({
        audio: recorder.recordedAudio.blob,
        filename: recorder.recordedAudio.filename,
        claimed_identity: claimed,
        challenge_id: activeChallengeId,
        session_id: activeSessionId,
      });

      if (response.ok && response.data) {
        setVerificationResult(response.data);
        setPageState('result');
      } else {
        setErrorStatus(response.status);
        setErrorMessage(
          response.error || 'Biometric verification rejected or failed on server.'
        );
        setPageState('error');
      }
    } catch (err: unknown) {
      setErrorStatus(0);
      setErrorMessage(
        err instanceof Error
          ? err.message
          : 'Network error submitting biometric verification.'
      );
      setPageState('error');
    }
  }, [challenge, recorder.recordedAudio, challengeTtl, pageState, selectedSpeakerId]);

  // Reset verification workflow
  const handleReset = useCallback(() => {
    setPageState('idle');
    setChallenge(null);
    setConsumedChallenge(null);
    setVerificationResult(null);
    setErrorMessage(null);
    setErrorStatus(null);
    recorder.clearRecording();
  }, [recorder]);

  // Is this an unmapped user identity error?
  const isUnmappedIdentityError =
    errorStatus === 403 &&
    (errorMessage?.toLowerCase().includes('not mapped') ||
      errorMessage?.toLowerCase().includes('forbidden'));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      {/* Real Verification Live Status Banner */}
      <div
        className="card"
        style={{
          background: 'rgba(59, 130, 246, 0.08)',
          borderLeft: '4px solid var(--color-brand)',
          padding: '16px 20px',
        }}
      >
        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
          <UserCheck size={20} color="#60A5FA" style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>
            <div className="text-sm font-semibold text-primary">
              Live Biometric Voice Verification
            </div>
            <p className="text-xs text-secondary" style={{ marginTop: '3px', lineHeight: '1.5' }}>
              Real server-driven authentication powered by Vosk speech-to-text liveness challenge-response and SpeechBrain ECAPA-TDNN acoustic embeddings. Captures authentic browser microphone audio without simulation or hardcoded outcomes.
            </p>
          </div>
        </div>
      </div>

      {/* Unmapped Identity Security Alert (Fail-Closed) */}
      {isUnmappedIdentityError && (
        <div
          className="card"
          data-testid="unmapped-identity-alert"
          style={{
            background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.12) 0%, rgba(14, 20, 34, 0.95) 100%)',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            padding: '20px',
          }}
        >
          <div style={{ display: 'flex', gap: '14px', alignItems: 'flex-start' }}>
            <div
              style={{
                width: '42px',
                height: '42px',
                borderRadius: '50%',
                background: 'rgba(239, 68, 68, 0.2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <ShieldAlert size={24} color="#EF4444" />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <h3 className="text-base font-bold text-primary">
                  Access Denied: Unmapped Voice Identity
                </h3>
                <Badge value="DENIED" />
              </div>
              <p className="text-xs text-secondary" style={{ marginTop: '6px', lineHeight: '1.6' }}>
                Your authenticated account (<strong className="text-primary">{user?.email || user?.uid}</strong>) has no bound speaker identity in the database (<code className="font-mono">UserSpeakerMapping</code>). In accordance with zero-trust security policy, ordinary authenticated users are strictly prohibited from verifying arbitrary speaker profiles.
              </p>
              <div
                style={{
                  background: 'rgba(0, 0, 0, 0.4)',
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-sm)',
                  marginTop: '12px',
                  fontFamily: 'monospace',
                  fontSize: '11px',
                  color: '#94A3B8',
                }}
              >
                Required Setup: An administrator must link this Firebase UID to an active speaker record via the UserSpeakerRepository before biometric authentication can be authorized.
              </div>
              <div style={{ marginTop: '14px' }}>
                <button
                  onClick={handleReset}
                  className="btn btn-secondary"
                  style={{ fontSize: '12px', padding: '6px 14px' }}
                >
                  Dismiss & Return
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Verification Workspace Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '20px' }}>
        {/* Step 1: Identity & Challenge Generation */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          <div>
            <span className="text-xs font-semibold text-muted font-mono" style={{ textTransform: 'uppercase' }}>
              Step 1: Identity & Authentication Context
            </span>
            <h3 className="text-base font-semibold text-primary" style={{ marginTop: '2px' }}>
              {isAdmin ? 'Administrative Speaker Selection' : 'Authenticated User Identity'}
            </h3>
          </div>

          {isAdmin ? (
            <div>
              <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
                Enrolled Speaker Identity (Admin Authorized)
              </label>
              {speakersLoading ? (
                <div className="text-xs text-muted" style={{ padding: '8px 0' }}>
                  Loading registered speakers from database...
                </div>
              ) : (
                <select
                  data-testid="speaker-select"
                  className="search-input"
                  style={{ width: '100%', cursor: 'pointer' }}
                  value={selectedSpeakerId}
                  disabled={pageState === 'challenge_active' || pageState === 'submitting'}
                  onChange={(e) => setSelectedSpeakerId(e.target.value)}
                >
                  {registeredSpeakers.length > 0 ? (
                    registeredSpeakers.map((spk) => (
                      <option key={spk} value={spk}>
                        {spk}
                      </option>
                    ))
                  ) : (
                    <option value="Zubair">Zubair</option>
                  )}
                </select>
              )}
              <span className="text-xs text-muted" style={{ display: 'block', marginTop: '6px' }}>
                Administrators are authorized to challenge and verify enrolled speaker identities.
              </span>
            </div>
          ) : (
            <div
              style={{
                background: 'rgba(14, 20, 34, 0.5)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '12px 14px',
              }}
            >
              <div className="text-xs font-semibold text-muted font-mono" style={{ textTransform: 'uppercase' }}>
                Bound User Principal
              </div>
              <div className="text-sm font-bold text-primary" style={{ marginTop: '4px' }}>
                {user?.email || user?.displayName || 'Authenticated User'}
              </div>
              <div className="text-xs text-muted font-mono" style={{ marginTop: '4px' }}>
                UID: {user?.uid || 'anonymous'}
              </div>
              <span className="text-xs text-muted" style={{ display: 'block', marginTop: '8px', lineHeight: '1.4' }}>
                Server automatically binds liveness challenges to your registered voice identity.
              </span>
            </div>
          )}

          {/* Trigger Challenge Generation */}
          <div style={{ paddingTop: '8px', borderTop: '1px solid var(--border-subtle)' }}>
            <button
              data-testid="request-challenge-btn"
              onClick={handleRequestChallenge}
              disabled={pageState === 'requesting_challenge' || pageState === 'submitting'}
              className="btn btn-primary"
              style={{ width: '100%', padding: '10px' }}
            >
              {pageState === 'requesting_challenge' ? (
                <>
                  <RefreshCw size={16} className="animate-spin" /> Requesting Server Challenge...
                </>
              ) : pageState === 'challenge_active' ? (
                <>
                  <RefreshCw size={14} /> Request New Challenge
                </>
              ) : (
                <>
                  <Radio size={16} /> Request Liveness Challenge
                </>
              )}
            </button>
          </div>
        </div>

        {/* Step 2: Spoken Liveness Challenge & Microphone Recording */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          <div>
            <span className="text-xs font-semibold text-muted font-mono" style={{ textTransform: 'uppercase' }}>
              Step 2: Spoken Liveness & Audio Capture
            </span>
            <h3 className="text-base font-semibold text-primary" style={{ marginTop: '2px' }}>
              Challenge Display & Microphone Input
            </h3>
          </div>

          {pageState === 'idle' || pageState === 'requesting_challenge' ? (
            <div
              style={{
                flex: 1,
                minHeight: '220px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '12px',
                background: 'rgba(14, 20, 34, 0.4)',
                borderRadius: 'var(--radius-md)',
                border: '1px dashed var(--border-subtle)',
                padding: '24px',
                textAlign: 'center',
              }}
            >
              <MicOff size={36} color="var(--text-muted)" />
              <div className="text-sm font-semibold text-primary">Challenge Not Active</div>
              <p className="text-xs text-muted" style={{ maxWidth: '280px' }}>
                Click "Request Liveness Challenge" to obtain an unpredictable, cryptographically generated 3-digit sequence from the backend.
              </p>
            </div>
          ) : pageState === 'challenge_expired' ? (
            <div
              style={{
                flex: 1,
                minHeight: '220px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '12px',
                background: 'rgba(239, 68, 68, 0.05)',
                borderRadius: 'var(--radius-md)',
                border: '1px dashed rgba(239, 68, 68, 0.4)',
                padding: '24px',
                textAlign: 'center',
              }}
            >
              <Clock size={36} color="#EF4444" />
              <div className="text-sm font-semibold text-primary">Liveness Challenge Expired</div>
              <p className="text-xs text-secondary" style={{ maxWidth: '280px' }}>
                Single-use challenge time-to-live (60s) has elapsed. The token has been invalidated to mitigate replay attacks.
              </p>
              <button
                onClick={handleRequestChallenge}
                className="btn btn-secondary"
                style={{ fontSize: '12px', padding: '6px 14px', marginTop: '6px' }}
              >
                Request Fresh Challenge
              </button>
            </div>
          ) : pageState === 'submitting' ? (
            <div
              data-testid="challenge-submitting-card"
              style={{
                flex: 1,
                minHeight: '220px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '14px',
                background: 'linear-gradient(135deg, rgba(59, 130, 246, 0.08) 0%, rgba(14, 20, 34, 0.7) 100%)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid rgba(59, 130, 246, 0.3)',
                padding: '24px',
                textAlign: 'center',
              }}
            >
              <RefreshCw size={36} className="animate-spin" color="#60A5FA" />
              <div className="text-sm font-semibold text-primary">Verifying Biometric Audio...</div>
              <p className="text-xs text-secondary" style={{ maxWidth: '320px', lineHeight: '1.5' }}>
                Server is performing offline Vosk STT speech transcription to verify spoken challenge digits and evaluating SpeechBrain ECAPA-TDNN acoustic embeddings.
              </p>
            </div>
          ) : pageState === 'result' ? (
            <div
              data-testid="challenge-consumed-card"
              style={{
                flex: 1,
                minHeight: '220px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '12px',
                background: 'rgba(14, 20, 34, 0.5)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
                padding: '24px',
                textAlign: 'center',
              }}
            >
              {consumedChallenge ? (
                <>
                  <div className="text-xs text-muted font-mono" style={{ textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    Evaluated Challenge Sequence (Consumed)
                  </div>
                  <div
                    data-testid="consumed-challenge-digits"
                    className="font-mono text-3xl font-bold"
                    style={{
                      color: '#94A3B8',
                      letterSpacing: '0.35em',
                      marginTop: '4px',
                    }}
                  >
                    {consumedChallenge.display || consumedChallenge.digits.join('   ')}
                  </div>
                </>
              ) : (
                <div className="text-sm font-semibold text-primary">Challenge Consumed</div>
              )}
              <p className="text-xs text-secondary" style={{ maxWidth: '320px', lineHeight: '1.5', marginTop: '4px' }}>
                Single-attempt liveness challenge has been evaluated by the server and invalidated to mitigate replay attacks. Review the detailed biometric verification result below.
              </p>
              <button
                data-testid="request-fresh-challenge-btn"
                onClick={handleRequestChallenge}
                className="btn btn-primary"
                style={{ fontSize: '12px', padding: '8px 18px', marginTop: '6px' }}
              >
                <Radio size={14} /> Request Fresh Challenge
              </button>
            </div>
          ) : challenge ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {/* Server-Issued Challenge Display */}
              <div
                data-testid="challenge-display-card"
                style={{
                  background: 'linear-gradient(135deg, rgba(59, 130, 246, 0.12) 0%, rgba(14, 20, 34, 0.8) 100%)',
                  border: '1px solid var(--color-brand)',
                  borderRadius: 'var(--radius-md)',
                  padding: '20px 24px',
                  textAlign: 'center',
                }}
              >
                <div className="text-xs text-muted font-mono" style={{ textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  Please Speak Clearly Into Microphone:
                </div>
                <div
                  data-testid="challenge-digits-display"
                  className="font-mono text-4xl font-bold"
                  style={{
                    color: '#60A5FA',
                    letterSpacing: '0.45em',
                    marginTop: '10px',
                    textShadow: '0 0 20px rgba(59, 130, 246, 0.5)',
                  }}
                >
                  {challenge.display || challenge.digits.join('   ')}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', marginTop: '14px' }}>
                  <Clock size={13} color="#94A3B8" />
                  <span className="text-xs font-mono text-muted">
                    Time-to-Live:{' '}
                    <strong
                      data-testid="challenge-ttl"
                      style={{ color: challengeTtl < 15 ? '#EF4444' : '#10B981' }}
                    >
                      {challengeTtl}s
                    </strong>{' '}
                    (Single-use burn)
                  </span>
                </div>
              </div>

              {/* Microphone Recorder Control Area */}
              <div
                style={{
                  background: 'rgba(14, 20, 34, 0.6)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '14px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px',
                }}
              >
                {/* Recorder State Indicator */}
                {recorder.isRecording ? (
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span
                        style={{
                          width: '10px',
                          height: '10px',
                          borderRadius: '50%',
                          backgroundColor: '#EF4444',
                          animation: 'pulse 1.5s infinite',
                        }}
                      />
                      <span className="text-xs font-semibold" style={{ color: '#F87171' }}>
                        Recording Audio: {recorder.duration}s / 10s max
                      </span>
                    </div>
                    <button
                      data-testid="stop-recording-btn"
                      onClick={recorder.stopRecording}
                      className="btn btn-secondary"
                      style={{ fontSize: '12px', padding: '6px 12px', borderColor: '#EF4444', color: '#F87171' }}
                    >
                      <Square size={14} /> Stop Recording
                    </button>
                  </div>
                ) : recorder.recordedAudio ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Volume2 size={16} color="#34D399" />
                        <span className="text-xs font-semibold text-primary">
                          Recorded Waveform Captured
                        </span>
                        <span className="badge badge-active" style={{ fontSize: '10px', padding: '2px 6px' }}>
                          {recorder.recordedAudio.extension.toUpperCase()} ({recorder.recordedAudio.mimeType})
                        </span>
                      </div>
                      <span className="text-xs font-mono text-muted">
                        {(recorder.recordedAudio.sizeBytes / 1024).toFixed(1)} KB • {recorder.recordedAudio.durationSeconds}s
                      </span>
                    </div>

                    {/* Audio Preview Player */}
                    {audioPlaybackUrl && (
                      <audio
                        data-testid="audio-preview"
                        controls
                        src={audioPlaybackUrl}
                        style={{ width: '100%', height: '36px', marginTop: '4px' }}
                      />
                    )}

                    <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                      <button
                        data-testid="discard-recording-btn"
                        onClick={recorder.clearRecording}
                        className="btn btn-secondary"
                        style={{ flex: 1, fontSize: '12px', padding: '8px' }}
                      >
                        <Trash2 size={14} /> Discard & Re-Record
                      </button>
                      <button
                        data-testid="submit-verify-btn"
                        onClick={handleSubmitVerification}
                        disabled={challengeTtl <= 0}
                        className="btn btn-primary"
                        style={{ flex: 2, fontSize: '12px', padding: '8px' }}
                      >
                        <Play size={14} /> Submit for Verification
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {recorder.error && (
                      <div
                        data-testid="recorder-error"
                        className="text-xs"
                        style={{
                          color: '#F87171',
                          background: 'rgba(239, 68, 68, 0.1)',
                          padding: '8px 12px',
                          borderRadius: 'var(--radius-sm)',
                        }}
                      >
                        {recorder.error}
                      </div>
                    )}
                    <button
                      data-testid="start-recording-btn"
                      onClick={recorder.startRecording}
                      disabled={challengeTtl <= 0}
                      className="btn btn-secondary"
                      style={{
                        width: '100%',
                        padding: '12px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '8px',
                      }}
                    >
                      <Mic size={18} color="#60A5FA" /> Start Microphone Recording
                    </button>
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div
              style={{
                flex: 1,
                minHeight: '220px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '12px',
                background: 'rgba(14, 20, 34, 0.4)',
                borderRadius: 'var(--radius-md)',
                border: '1px dashed var(--border-subtle)',
                padding: '24px',
                textAlign: 'center',
              }}
            >
              <MicOff size={36} color="var(--text-muted)" />
              <div className="text-sm font-semibold text-primary">Challenge Not Active</div>
              <p className="text-xs text-muted" style={{ maxWidth: '280px' }}>
                Click "Request Liveness Challenge" to obtain an unpredictable, cryptographically generated 3-digit sequence from the backend.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Verification Error Card (Non-2xx / Network Failures) */}
      {pageState === 'error' && errorMessage && !isUnmappedIdentityError && (
        <div
          className="card"
          data-testid="verification-error-card"
          style={{
            background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.1) 0%, rgba(14, 20, 34, 0.95) 100%)',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            padding: '18px 20px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div
                style={{
                  width: '38px',
                  height: '38px',
                  borderRadius: '50%',
                  background: 'rgba(239, 68, 68, 0.2)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <XCircle size={22} color="#F87171" />
              </div>
              <div>
                <h3 className="text-base font-bold text-primary">
                  Verification Failure: Denied
                </h3>
                <p className="text-xs text-secondary">{errorMessage}</p>
              </div>
            </div>
            <Badge value="DENIED" />
          </div>
          <div style={{ marginTop: '14px' }}>
            <button
              onClick={handleReset}
              className="btn btn-secondary"
              style={{ fontSize: '12px', padding: '6px 14px' }}
            >
              Start New Verification Attempt
            </button>
          </div>
        </div>
      )}

      {/* Step 3: Verified Result Card (Rendered Strictly From Real Backend Payload) */}
      {pageState === 'result' && verificationResult && (
        <div
          className="card"
          data-testid="verification-result-card"
          style={{
            border: `1px solid ${
              verificationResult.accepted
                ? 'rgba(16, 185, 129, 0.4)'
                : !verificationResult.liveness_passed
                ? 'rgba(139, 92, 246, 0.4)'
                : 'rgba(239, 68, 68, 0.4)'
            }`,
            background: verificationResult.accepted
              ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(14, 20, 34, 0.9) 100%)'
              : !verificationResult.liveness_passed
              ? 'linear-gradient(135deg, rgba(139, 92, 246, 0.08) 0%, rgba(14, 20, 34, 0.9) 100%)'
              : 'linear-gradient(135deg, rgba(239, 68, 68, 0.08) 0%, rgba(14, 20, 34, 0.9) 100%)',
            padding: '22px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              {verificationResult.accepted ? (
                <div style={{ width: '42px', height: '42px', borderRadius: '50%', background: 'rgba(16, 185, 129, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <CheckCircle2 size={26} color="#34D399" />
                </div>
              ) : !verificationResult.liveness_passed ? (
                <div style={{ width: '42px', height: '42px', borderRadius: '50%', background: 'rgba(139, 92, 246, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <AlertTriangle size={26} color="#A78BFA" />
                </div>
              ) : (
                <div style={{ width: '42px', height: '42px', borderRadius: '50%', background: 'rgba(239, 68, 68, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <XCircle size={26} color="#F87171" />
                </div>
              )}
              <div>
                <h3 className="text-lg font-bold text-primary">
                  {verificationResult.accepted
                    ? 'Biometric Verification Verified: UNLOCK'
                    : !verificationResult.liveness_passed
                    ? 'Liveness Challenge Failed: DENY'
                    : 'Acoustic Voiceprint Mismatch: DENY'}
                </h3>
                <p className="text-xs text-secondary" style={{ marginTop: '2px' }}>
                  {verificationResult.accepted
                    ? `Acoustic voiceprint similarity (${verificationResult.similarity.toFixed(4)}) exceeds server threshold (${verificationResult.threshold_used.toFixed(2)}). Spoken challenge verified.`
                    : !verificationResult.liveness_passed
                    ? verificationResult.reason || 'Spoken challenge sequence did not match expected digits. Anti-spoofing triggered.'
                    : `Voiceprint similarity (${verificationResult.similarity.toFixed(4)}) is below required threshold (${verificationResult.threshold_used.toFixed(2)}). Access denied.`}
                </p>
              </div>
            </div>
            <Badge
              value={
                verificationResult.accepted
                  ? 'GRANTED'
                  : !verificationResult.liveness_passed
                  ? 'SPOOF_DETECTED'
                  : 'DENIED'
              }
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px', marginTop: '16px' }}>
            <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
              <span className="text-xs text-muted">Cosine Similarity</span>
              <div
                className="font-mono text-lg font-bold"
                style={{
                  color: verificationResult.similarity >= verificationResult.threshold_used ? '#34D399' : '#F87171',
                  marginTop: '2px',
                }}
              >
                {verificationResult.similarity.toFixed(4)}
              </div>
              <span className="text-xs text-muted font-mono">Server Threshold: {verificationResult.threshold_used.toFixed(2)}</span>
            </div>

            <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
              <span className="text-xs text-muted">Spoken Liveness Check</span>
              <div
                className="font-mono text-lg font-bold"
                style={{
                  color: verificationResult.liveness_passed ? '#34D399' : '#A78BFA',
                  marginTop: '2px',
                }}
              >
                {verificationResult.liveness_passed ? 'PASSED' : 'FAILED'}
              </div>
              <span className="text-xs text-muted font-mono">Vosk STT Model</span>
            </div>

            <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
              <span className="text-xs text-muted">Claimed Speaker Profile</span>
              <div className="font-mono text-base font-semibold text-primary" style={{ marginTop: '2px' }}>
                {verificationResult.claimed_identity}
              </div>
              <span className="text-xs text-muted font-mono">Status: {verificationResult.action}</span>
            </div>

            <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
              <span className="text-xs text-muted">Verification Action</span>
              <div
                className="font-mono text-lg font-bold"
                style={{
                  color: verificationResult.action === 'UNLOCK' ? '#34D399' : '#F87171',
                  marginTop: '2px',
                }}
              >
                {verificationResult.action}
              </div>
              <span className="text-xs text-muted font-mono">Relay Trigger State</span>
            </div>
          </div>

          <div style={{ marginTop: '18px', paddingTop: '14px', borderTop: '1px solid var(--border-subtle)' }}>
            <button
              data-testid="new-verification-btn"
              onClick={handleReset}
              className="btn btn-secondary"
              style={{ fontSize: '12px', padding: '8px 16px' }}
            >
              <RefreshCw size={14} /> Start New Verification
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
