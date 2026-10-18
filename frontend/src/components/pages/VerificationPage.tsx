import React, { useState, useEffect } from 'react';
import {
  MicOff,
  Radio,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  RefreshCw,
  Play,
  Volume2,
  Info,
} from 'lucide-react';
import { Badge } from '../common/Badge';
import { MOCK_SPEAKERS, MOCK_DEVICES } from '../../data/mockData';

type SimulationState = 'idle' | 'challenge_ready' | 'processing' | 'result';

interface SimulationResult {
  claimed_speaker: string;
  matched_speaker: string;
  similarity_score: number;
  threshold: number;
  liveness_digits: string;
  spoken_digits: string;
  liveness_pass: boolean;
  verdict: 'GRANTED' | 'DENIED' | 'SPOOF_DETECTED';
  explanation: string;
  latency_ms: number;
}

export const VerificationPage: React.FC = () => {
  const [selectedSpeakerId, setSelectedSpeakerId] = useState('Zubair');
  const [selectedDeviceId, setSelectedDeviceId] = useState('esp32-terminal-main-entrance');
  const [simulationState, setSimulationState] = useState<SimulationState>('idle');
  const [challengeDigits, setChallengeDigits] = useState('7 4 1 9');
  const [challengeTtl, setChallengeTtl] = useState(60);
  const [scenario, setScenario] = useState<'genuine' | 'impostor' | 'spoof'>('genuine');
  const [result, setResult] = useState<SimulationResult | null>(null);

  // Challenge countdown timer
  useEffect(() => {
    if (simulationState !== 'challenge_ready') return;

    const timer = window.setInterval(() => {
      setChallengeTtl((prev) => {
        if (prev <= 1) {
          setSimulationState('idle');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [simulationState]);

  const generateChallenge = () => {
    const d1 = Math.floor(Math.random() * 10);
    const d2 = Math.floor(Math.random() * 10);
    const d3 = Math.floor(Math.random() * 10);
    const d4 = Math.floor(Math.random() * 10);
    setChallengeDigits(`${d1} ${d2} ${d3} ${d4}`);
    setChallengeTtl(60);
    setSimulationState('challenge_ready');
    setResult(null);
  };

  const runSimulation = () => {
    setSimulationState('processing');

    setTimeout(() => {
      let simResult: SimulationResult;

      if (scenario === 'genuine') {
        simResult = {
          claimed_speaker: selectedSpeakerId,
          matched_speaker: selectedSpeakerId,
          similarity_score: 0.8668,
          threshold: 0.25,
          liveness_digits: challengeDigits,
          spoken_digits: challengeDigits,
          liveness_pass: true,
          verdict: 'GRANTED',
          explanation: `Acoustic voiceprint similarity (0.8668) securely exceeds server threshold (0.25). Spoken liveness digits (${challengeDigits}) recognized correctly. Physical door relay pulsed.`,
          latency_ms: 118,
        };
      } else if (scenario === 'impostor') {
        simResult = {
          claimed_speaker: selectedSpeakerId,
          matched_speaker: 'Unenrolled / Impostor Voice',
          similarity_score: 0.1842,
          threshold: 0.25,
          liveness_digits: challengeDigits,
          spoken_digits: challengeDigits,
          liveness_pass: true,
          verdict: 'DENIED',
          explanation: `Acoustic voiceprint match failed: Similarity score 0.1842 is below the required 0.25 threshold. Access denied to protect biometric boundary.`,
          latency_ms: 124,
        };
      } else {
        // Spoof / Liveness failure
        simResult = {
          claimed_speaker: selectedSpeakerId,
          matched_speaker: selectedSpeakerId,
          similarity_score: 0.8310,
          threshold: 0.25,
          liveness_digits: challengeDigits,
          spoken_digits: '0 0 0 0',
          liveness_pass: false,
          verdict: 'SPOOF_DETECTED',
          explanation: `Spoken liveness failed: Expected digits "${challengeDigits}", but speech recognition detected wrong sequence. Possible replay attack or synthetic voice clone. Single-use challenge burned.`,
          latency_ms: 139,
        };
      }

      setResult(simResult);
      setSimulationState('result');
    }, 1200);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      {/* Explicit Prototype & Security Disclaimer */}
      <div
        className="card"
        style={{
          background: 'rgba(59, 130, 246, 0.08)',
          borderLeft: '4px solid var(--color-brand)',
          padding: '16px 20px',
        }}
      >
        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
          <Info size={20} color="#60A5FA" style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>
            <div className="text-sm font-semibold text-primary">
              Interactive Biometric Simulator (Prototype Mode)
            </div>
            <p className="text-xs text-secondary" style={{ marginTop: '3px', lineHeight: '1.5' }}>
              This portal demonstrates the end-to-end VoiceLock biometric workflow: dynamic CSPRNG challenge generation, single-use burn-on-use liveness verification with Vosk, and ECAPA-TDNN acoustic scoring. In this milestone, verification uses controlled simulations rather than browser microphone streams.
            </p>
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '20px' }}>
        {/* Step 1 & 2: Controls & Terminal Configuration */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          <div>
            <span className="text-xs font-semibold text-muted font-mono" style={{ textTransform: 'uppercase' }}>
              Step 1: Context & Claim
            </span>
            <h3 className="text-base font-semibold text-primary" style={{ marginTop: '2px' }}>
              Target Access Terminal & Speaker
            </h3>
          </div>

          <div>
            <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
              Physical Access Terminal (ESP32)
            </label>
            <select
              className="search-input"
              style={{ width: '100%', cursor: 'pointer' }}
              value={selectedDeviceId}
              onChange={(e) => setSelectedDeviceId(e.target.value)}
            >
              {MOCK_DEVICES.filter((d) => d.status === 'active').map((dev) => (
                <option key={dev.id} value={dev.device_id}>
                  {dev.name} ({dev.device_id})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
              Claimed Speaker Identity
            </label>
            <select
              className="search-input"
              style={{ width: '100%', cursor: 'pointer' }}
              value={selectedSpeakerId}
              onChange={(e) => setSelectedSpeakerId(e.target.value)}
            >
              {MOCK_SPEAKERS.filter((s) => s.status === 'active').map((spk) => (
                <option key={spk.id} value={spk.speaker_id}>
                  {spk.name} ({spk.speaker_id})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
              Test Simulation Scenario
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
              <button
                onClick={() => setScenario('genuine')}
                className="btn btn-secondary"
                style={{
                  fontSize: '11px',
                  padding: '8px 4px',
                  textAlign: 'center',
                  borderColor: scenario === 'genuine' ? '#10B981' : 'var(--border-subtle)',
                  background: scenario === 'genuine' ? 'rgba(16, 185, 129, 0.12)' : 'transparent',
                  color: scenario === 'genuine' ? '#34D399' : 'var(--text-secondary)',
                }}
              >
                Genuine User
              </button>
              <button
                onClick={() => setScenario('impostor')}
                className="btn btn-secondary"
                style={{
                  fontSize: '11px',
                  padding: '8px 4px',
                  textAlign: 'center',
                  borderColor: scenario === 'impostor' ? '#EF4444' : 'var(--border-subtle)',
                  background: scenario === 'impostor' ? 'rgba(239, 68, 68, 0.12)' : 'transparent',
                  color: scenario === 'impostor' ? '#F87171' : 'var(--text-secondary)',
                }}
              >
                Impostor Voice
              </button>
              <button
                onClick={() => setScenario('spoof')}
                className="btn btn-secondary"
                style={{
                  fontSize: '11px',
                  padding: '8px 4px',
                  textAlign: 'center',
                  borderColor: scenario === 'spoof' ? '#8B5CF6' : 'var(--border-subtle)',
                  background: scenario === 'spoof' ? 'rgba(139, 92, 246, 0.15)' : 'transparent',
                  color: scenario === 'spoof' ? '#A78BFA' : 'var(--text-secondary)',
                }}
              >
                Liveness Spoof
              </button>
            </div>
          </div>

          {/* Action Trigger */}
          <div style={{ paddingTop: '8px', borderTop: '1px solid var(--border-subtle)' }}>
            {simulationState === 'idle' ? (
              <button
                onClick={generateChallenge}
                className="btn btn-primary"
                style={{ width: '100%', padding: '10px' }}
              >
                <Radio size={16} /> Request Liveness Challenge
              </button>
            ) : (
              <button
                onClick={generateChallenge}
                className="btn btn-secondary"
                style={{ width: '100%', padding: '10px' }}
              >
                <RefreshCw size={14} /> Re-Generate Challenge Sequence
              </button>
            )}
          </div>
        </div>

        {/* Step 2: Challenge Presentation & Audio Capture Simulation */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
          <div>
            <span className="text-xs font-semibold text-muted font-mono" style={{ textTransform: 'uppercase' }}>
              Step 2: Spoken Liveness Challenge
            </span>
            <h3 className="text-base font-semibold text-primary" style={{ marginTop: '2px' }}>
              Challenge-Response Verification Display
            </h3>
          </div>

          {simulationState === 'idle' ? (
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
                Click "Request Liveness Challenge" to simulate the terminal issuing a randomized 4-digit spoken sequence.
              </p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {/* Challenge Digits Display */}
              <div
                style={{
                  background: 'linear-gradient(135deg, rgba(59, 130, 246, 0.12) 0%, rgba(14, 20, 34, 0.8) 100%)',
                  border: '1px solid var(--color-brand)',
                  borderRadius: 'var(--radius-md)',
                  padding: '24px',
                  textAlign: 'center',
                }}
              >
                <div className="text-xs text-muted font-mono" style={{ textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  Please Speak Clearly Into Terminal:
                </div>
                <div
                  className="font-mono text-3xl font-bold"
                  style={{
                    color: '#60A5FA',
                    letterSpacing: '0.35em',
                    marginTop: '10px',
                    textShadow: '0 0 20px rgba(59, 130, 246, 0.4)',
                  }}
                >
                  {challengeDigits}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', marginTop: '14px' }}>
                  <Clock size={13} color="#94A3B8" />
                  <span className="text-xs font-mono text-muted">
                    Time-to-Live (TTL):{' '}
                    <strong style={{ color: challengeTtl < 15 ? '#EF4444' : '#10B981' }}>
                      {challengeTtl}s
                    </strong>{' '}
                    (Single-use burn)
                  </span>
                </div>
              </div>

              {/* Simulated Audio Waveform Bar */}
              <div
                style={{
                  background: 'rgba(14, 20, 34, 0.6)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                }}
              >
                <Volume2 size={18} color="#60A5FA" />
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '4px', height: '24px' }}>
                  {[12, 24, 18, 30, 16, 28, 22, 14, 32, 20, 26, 15, 29, 19, 25, 13, 27, 21].map((h, i) => (
                    <div
                      key={i}
                      style={{
                        flex: 1,
                        height: `${simulationState === 'processing' ? h : 4}px`,
                        backgroundColor: simulationState === 'processing' ? '#3B82F6' : 'rgba(255, 255, 255, 0.1)',
                        borderRadius: '2px',
                        transition: 'height 0.2s ease',
                      }}
                    />
                  ))}
                </div>
                <span className="font-mono text-xs text-muted">16kHz PCM</span>
              </div>

              {/* Execute Verification Button */}
              <button
                onClick={runSimulation}
                disabled={simulationState === 'processing' || challengeTtl <= 0}
                className="btn btn-primary"
                style={{ width: '100%', padding: '12px' }}
              >
                {simulationState === 'processing' ? (
                  <>
                    <RefreshCw size={16} className="animate-spin" /> Performing Biometric Inference...
                  </>
                ) : (
                  <>
                    <Play size={16} /> Submit Audio & Execute Verification
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Step 3: Verification Result Card */}
      {result && (
        <div
          className="card"
          style={{
            border: `1px solid ${
              result.verdict === 'GRANTED'
                ? 'rgba(16, 185, 129, 0.4)'
                : result.verdict === 'DENIED'
                ? 'rgba(239, 68, 68, 0.4)'
                : 'rgba(139, 92, 246, 0.4)'
            }`,
            background:
              result.verdict === 'GRANTED'
                ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.08) 0%, rgba(14, 20, 34, 0.9) 100%)'
                : result.verdict === 'DENIED'
                ? 'linear-gradient(135deg, rgba(239, 68, 68, 0.08) 0%, rgba(14, 20, 34, 0.9) 100%)'
                : 'linear-gradient(135deg, rgba(139, 92, 246, 0.08) 0%, rgba(14, 20, 34, 0.9) 100%)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              {result.verdict === 'GRANTED' ? (
                <div style={{ width: '40px', height: '40px', borderRadius: '50%', background: 'rgba(16, 185, 129, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <CheckCircle2 size={24} color="#34D399" />
                </div>
              ) : result.verdict === 'DENIED' ? (
                <div style={{ width: '40px', height: '40px', borderRadius: '50%', background: 'rgba(239, 68, 68, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <XCircle size={24} color="#F87171" />
                </div>
              ) : (
                <div style={{ width: '40px', height: '40px', borderRadius: '50%', background: 'rgba(139, 92, 246, 0.2)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <AlertTriangle size={24} color="#A78BFA" />
                </div>
              )}
              <div>
                <h3 className="text-lg font-bold text-primary">
                  Verification Verdict: {result.verdict}
                </h3>
                <p className="text-xs text-secondary">{result.explanation}</p>
              </div>
            </div>
            <Badge value={result.verdict} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px', marginTop: '16px' }}>
            <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
              <span className="text-xs text-muted">Cosine Similarity</span>
              <div className="font-mono text-lg font-bold" style={{ color: result.similarity_score >= result.threshold ? '#34D399' : '#F87171', marginTop: '2px' }}>
                {result.similarity_score.toFixed(4)}
              </div>
              <span className="text-xs text-muted font-mono">Server Threshold: {result.threshold.toFixed(2)}</span>
            </div>

            <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
              <span className="text-xs text-muted">Spoken Challenge Check</span>
              <div className="font-mono text-lg font-bold" style={{ color: result.liveness_pass ? '#34D399' : '#A78BFA', marginTop: '2px' }}>
                {result.liveness_pass ? 'PASSED' : 'SPOOF DETECTED'}
              </div>
              <span className="text-xs text-muted font-mono">Vosk STT Liveness Model</span>
            </div>

            <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
              <span className="text-xs text-muted">Identified Speaker Profile</span>
              <div className="font-mono text-base font-semibold text-primary" style={{ marginTop: '2px' }}>
                {result.matched_speaker}
              </div>
              <span className="text-xs text-muted font-mono">Claimed: {result.claimed_speaker}</span>
            </div>

            <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
              <span className="text-xs text-muted">Total Processing Latency</span>
              <div className="font-mono text-lg font-bold text-primary" style={{ marginTop: '2px' }}>
                {result.latency_ms} ms
              </div>
              <span className="text-xs text-muted font-mono">Audio Spool + ECAPA-TDNN</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
