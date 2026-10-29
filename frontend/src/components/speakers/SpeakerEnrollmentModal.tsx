/**
 * frontend/src/components/speakers/SpeakerEnrollmentModal.tsx
 *
 * Administrator modal for persistent biometric speaker profile enrollment.
 * Captures 3 to 10 microphone audio recordings in the browser, displays audio
 * duration, playback previews, sample management (retry/delete), and invokes
 * POST /speakers to generate 192-d ECAPA-TDNN centroid embeddings.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Mic,
  Square,
  Trash2,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Volume2,
  ShieldCheck,
  Plus,
} from 'lucide-react';
import { Modal } from '../common/Modal';
import { useAudioRecorder } from '../../hooks/useAudioRecorder';
import { apiClient } from '../../lib/apiClient';

interface SpeakerSample {
  id: string;
  blob: Blob;
  filename: string;
  durationSeconds: number;
  audioUrl: string;
}

interface SpeakerEnrollmentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (speakerId: string) => void;
}

const MIN_SAMPLES = 3;
const TARGET_SAMPLES = 5;
const MAX_SAMPLES = 10;
const MIN_DURATION_SECONDS = 1.0;

export const SpeakerEnrollmentModal: React.FC<SpeakerEnrollmentModalProps> = ({
  isOpen,
  onClose,
  onSuccess,
}) => {
  const [speakerId, setSpeakerId] = useState('');
  const [fullName, setFullName] = useState('');
  const [samples, setSamples] = useState<SpeakerSample[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [sampleError, setSampleError] = useState<string | null>(null);

  const recorder = useAudioRecorder({
    maxDurationSeconds: 15,
    baseFilename: 'speaker_sample',
  });

  const samplesRef = useRef<SpeakerSample[]>(samples);
  samplesRef.current = samples;

  // Cleanup blob URLs on unmount or reset
  const revokeAllUrls = useCallback(() => {
    samplesRef.current.forEach((s) => {
      URL.revokeObjectURL(s.audioUrl);
    });
  }, []);

  const handleReset = useCallback(() => {
    revokeAllUrls();
    setSpeakerId('');
    setFullName('');
    setSamples([]);
    setErrorMessage(null);
    setSampleError(null);
    setIsSubmitting(false);
    recorder.clearRecording();
  }, [revokeAllUrls, recorder]);

  // Reset form when modal opens
  useEffect(() => {
    if (isOpen) {
      handleReset();
    } else {
      revokeAllUrls();
      if (recorder.isRecording) {
        recorder.cancelRecording();
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // When recorder finishes, collect the new sample
  useEffect(() => {
    if (recorder.state === 'stopped' && recorder.recordedAudio) {
      const audio = recorder.recordedAudio;
      const duration = audio.durationSeconds || recorder.duration;

      if (duration < MIN_DURATION_SECONDS) {
        setSampleError(`Sample was too short (${duration.toFixed(1)}s). Minimum ${MIN_DURATION_SECONDS.toFixed(1)}s required.`);
        recorder.clearRecording();
        return;
      }

      if (samples.length >= MAX_SAMPLES) {
        setSampleError(`Maximum of ${MAX_SAMPLES} samples reached.`);
        recorder.clearRecording();
        return;
      }

      const audioUrl = URL.createObjectURL(audio.blob);
      const newSample: SpeakerSample = {
        id: `sample-${Date.now()}-${samples.length + 1}`,
        blob: audio.blob,
        filename: `sample_${samples.length + 1}.${audio.extension || 'wav'}`,
        durationSeconds: duration,
        audioUrl,
      };

      setSamples((prev) => [...prev, newSample]);
      setSampleError(null);
      recorder.clearRecording();
    }
  }, [recorder.state, recorder.recordedAudio, recorder.duration, samples.length, recorder]);

  const handleRemoveSample = (id: string) => {
    setSamples((prev) => {
      const target = prev.find((s) => s.id === id);
      if (target) {
        URL.revokeObjectURL(target.audioUrl);
      }
      return prev.filter((s) => s.id !== id);
    });
  };

  const handleStartRecording = async () => {
    setSampleError(null);
    setErrorMessage(null);
    if (samples.length >= MAX_SAMPLES) {
      setSampleError(`Maximum of ${MAX_SAMPLES} samples reached.`);
      return;
    }
    await recorder.startRecording();
  };

  const handleStopRecording = () => {
    recorder.stopRecording();
  };

  const validateSpeakerId = (val: string): string | null => {
    const clean = val.trim();
    if (!clean) return 'Speaker ID is required.';
    if (clean.length < 2) return 'Speaker ID must be at least 2 characters.';
    if (clean.length > 64) return 'Speaker ID must be 64 characters or fewer.';
    if (!/^[A-Za-z0-9_\- ]+$/.test(clean)) {
      return 'Speaker ID may only contain letters, numbers, spaces, hyphens, and underscores.';
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSampleError(null);

    const idError = validateSpeakerId(speakerId);
    if (idError) {
      setErrorMessage(idError);
      return;
    }

    if (samples.length < MIN_SAMPLES) {
      setErrorMessage(`At least ${MIN_SAMPLES} audio samples are required for biometric enrollment (currently have ${samples.length}).`);
      return;
    }

    setIsSubmitting(true);

    try {
      const formData = new FormData();
      formData.append('speaker_id', speakerId.trim());
      if (fullName.trim()) {
        formData.append('full_name', fullName.trim());
      }

      samples.forEach((sample) => {
        formData.append('samples', sample.blob, sample.filename);
      });

      const response = await apiClient.enrollSpeaker(formData);

      if (response.ok && response.data) {
        onSuccess(response.data.speaker_id);
        onClose();
      } else {
        if (response.status === 409) {
          setErrorMessage(
            `Speaker identity "${speakerId.trim()}" already exists in the database. Please specify a unique identifier.`
          );
        } else if (response.status === 400) {
          setErrorMessage(
            response.error || 'Audio quality or identity validation failed. Please check samples.'
          );
        } else if (response.status === 401 || response.status === 403) {
          setErrorMessage(
            'Administrative authorization failed. Please verify your administrative session.'
          );
        } else {
          setErrorMessage(
            response.error || 'Failed to complete speaker enrollment. Please try again.'
          );
        }
      }
    } catch {
      setErrorMessage('Network error during speaker enrollment. Please verify connectivity.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const idValidationError = speakerId.trim() ? validateSpeakerId(speakerId) : null;
  const canSubmit =
    !isSubmitting &&
    !recorder.isRecording &&
    !idValidationError &&
    speakerId.trim().length >= 2 &&
    samples.length >= MIN_SAMPLES;

  return (
    <Modal
      isOpen={isOpen}
      onClose={() => {
        if (!isSubmitting) onClose();
      }}
      title="Enroll New Biometric Speaker Profile"
      subtitle="Register an authorized speaker identity with 3 to 10 verified acoustic samples."
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="btn btn-secondary"
            style={{ fontSize: '13px', padding: '8px 16px' }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="btn btn-primary"
            style={{
              fontSize: '13px',
              padding: '8px 20px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            {isSubmitting ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Extracting Embeddings...
              </>
            ) : (
              <>
                <ShieldCheck size={14} />
                Enroll Speaker ({samples.length}/{MIN_SAMPLES} min)
              </>
            )}
          </button>
        </>
      }
    >
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
        {/* Error Alert */}
        {errorMessage && (
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: '10px',
              padding: '12px 14px',
              borderRadius: 'var(--radius-sm)',
              background: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              color: 'var(--color-rose)',
              fontSize: '12px',
              lineHeight: '1.5',
            }}
            role="alert"
          >
            <AlertCircle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
            <div>{errorMessage}</div>
          </div>
        )}

        {/* Identity Inputs */}
        <div className="speaker-enrollment-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '14px' }}>
          <div>
            <label
              htmlFor="enroll-speaker-id"
              className="text-xs font-semibold text-primary"
              style={{ display: 'block', marginBottom: '6px' }}
            >
              Speaker ID <span style={{ color: 'var(--color-rose)' }}>*</span>
            </label>
            <input
              id="enroll-speaker-id"
              type="text"
              value={speakerId}
              onChange={(e) => setSpeakerId(e.target.value)}
              placeholder="e.g. Sarah_Connor"
              disabled={isSubmitting}
              autoComplete="off"
              style={{
                width: '100%',
                padding: '9px 12px',
                background: 'var(--bg-surface)',
                border: `1px solid ${idValidationError ? 'var(--color-rose)' : 'var(--border-subtle)'}`,
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                fontFamily: 'monospace',
                outline: 'none',
              }}
            />
            {idValidationError && (
              <p className="text-xs" style={{ color: 'var(--color-rose)', marginTop: '4px' }}>
                {idValidationError}
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor="enroll-full-name"
              className="text-xs font-semibold text-primary"
              style={{ display: 'block', marginBottom: '6px' }}
            >
              Full Name (Optional)
            </label>
            <input
              id="enroll-full-name"
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="e.g. Sarah Connor"
              disabled={isSubmitting}
              style={{
                width: '100%',
                padding: '9px 12px',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                outline: 'none',
              }}
            />
          </div>
        </div>

        {/* Acoustic Sample Recording Section */}
        <div
          style={{
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '16px',
            background: 'rgba(255, 255, 255, 0.01)',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '12px',
              flexWrap: 'wrap',
              gap: '8px',
            }}
          >
            <div>
              <div className="text-xs font-semibold text-primary" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Volume2 size={14} color="var(--color-brand)" />
                Biometric Voice Samples ({samples.length}/{MAX_SAMPLES})
              </div>
              <p className="text-xs text-muted" style={{ marginTop: '2px' }}>
                Collect {TARGET_SAMPLES} samples for optimal ECAPA-TDNN feature extraction (minimum {MIN_SAMPLES} required).
              </p>
            </div>

            {/* Status indicator badge */}
            <span
              className={`badge ${samples.length >= MIN_SAMPLES ? 'badge-active' : 'badge-pending'}`}
              style={{ fontSize: '11px', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              {samples.length >= MIN_SAMPLES ? (
                <>
                  <CheckCircle2 size={11} color="var(--color-emerald)" />
                  Ready to Enroll
                </>
              ) : (
                `Need ${MIN_SAMPLES - samples.length} more`
              )}
            </span>
          </div>

          {/* Microphone Capture Workspace */}
          <div
            style={{
              padding: '16px',
              borderRadius: 'var(--radius-sm)',
              background: recorder.isRecording
                ? 'rgba(239, 68, 68, 0.06)'
                : 'rgba(255, 255, 255, 0.02)',
              border: recorder.isRecording
                ? '1px solid rgba(239, 68, 68, 0.3)'
                : '1px solid var(--border-subtle)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '14px',
              flexWrap: 'wrap',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div
                style={{
                  width: '36px',
                  height: '36px',
                  borderRadius: '50%',
                  background: recorder.isRecording ? 'var(--color-rose)' : 'rgba(59, 130, 246, 0.1)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: recorder.isRecording ? '#fff' : 'var(--color-brand)',
                  transition: 'all 0.2s ease',
                  animation: recorder.isRecording ? 'pulse 1.5s infinite' : 'none',
                }}
              >
                <Mic size={18} />
              </div>

              <div>
                <div className="text-xs font-semibold text-primary">
                  {recorder.isRecording
                    ? `Recording sample ${samples.length + 1}...`
                    : samples.length >= MAX_SAMPLES
                      ? 'Maximum samples recorded'
                      : `Record sample ${samples.length + 1} of ${TARGET_SAMPLES}`}
                </div>
                <div className="font-mono text-xs text-muted" style={{ marginTop: '2px' }}>
                  {recorder.isRecording
                    ? `Duration: ${recorder.duration.toFixed(1)}s (speak clearly)`
                    : 'Speak a clear sentence (2–5 seconds recommended)'}
                </div>
              </div>
            </div>

            <div>
              {recorder.isRecording ? (
                <button
                  type="button"
                  onClick={handleStopRecording}
                  className="btn btn-secondary"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    color: 'var(--color-rose)',
                    borderColor: 'rgba(239, 68, 68, 0.4)',
                    fontSize: '12px',
                    padding: '7px 14px',
                  }}
                >
                  <Square size={13} fill="currentColor" />
                  Stop Recording
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleStartRecording}
                  disabled={isSubmitting || samples.length >= MAX_SAMPLES}
                  className="btn btn-secondary"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    fontSize: '12px',
                    padding: '7px 14px',
                  }}
                >
                  <Plus size={14} />
                  Record Sample
                </button>
              )}
            </div>
          </div>

          {/* Sample specific error */}
          {(sampleError || recorder.error) && (
            <p className="text-xs" style={{ color: 'var(--color-rose)', marginTop: '8px' }}>
              {sampleError || recorder.error}
            </p>
          )}

          {/* List of Captured Samples */}
          {samples.length > 0 && (
            <div style={{ marginTop: '14px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  paddingBottom: '4px',
                  borderBottom: '1px solid var(--border-subtle)',
                }}
              >
                <span className="text-xs font-semibold text-secondary">
                  Enrolled Audio Buffers
                </span>
                <button
                  type="button"
                  onClick={() => {
                    revokeAllUrls();
                    setSamples([]);
                  }}
                  disabled={isSubmitting}
                  className="btn-text"
                  style={{ fontSize: '11px', color: 'var(--text-muted)' }}
                >
                  Clear All
                </button>
              </div>

              {samples.map((sample, idx) => (
                <div
                  key={sample.id}
                  className="speaker-sample-item"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 12px',
                    background: 'rgba(255, 255, 255, 0.02)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-subtle)',
                    gap: '12px',
                    flexWrap: 'wrap',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span className="font-mono text-xs text-muted" style={{ minWidth: '24px' }}>
                      #{idx + 1}
                    </span>
                    <div>
                      <div className="font-mono text-xs text-primary">
                        {sample.filename}
                      </div>
                      <div className="text-xs text-muted">
                        {sample.durationSeconds.toFixed(1)}s duration
                      </div>
                    </div>
                  </div>

                  <div className="speaker-sample-controls" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <audio
                      src={sample.audioUrl}
                      controls
                      style={{
                        height: '28px',
                        maxWidth: '200px',
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => handleRemoveSample(sample.id)}
                      disabled={isSubmitting}
                      className="modal-close-btn"
                      style={{ padding: '4px' }}
                      title="Remove this sample"
                      aria-label={`Remove sample ${idx + 1}`}
                    >
                      <Trash2 size={13} color="var(--color-rose)" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </form>
    </Modal>
  );
};
