import React from 'react';
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
} from 'lucide-react';
import { StatCard } from '../common/StatCard';
import { Badge } from '../common/Badge';
import {
  MOCK_METRICS,
  MOCK_VERIFICATION_RECORDS,
  MOCK_SECURITY_EVENTS,
} from '../../data/mockData';
import type { NavigationTab } from '../../types';

interface OverviewPageProps {
  onNavigate: (tab: NavigationTab) => void;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({ onNavigate }) => {
  const recentVerifications = MOCK_VERIFICATION_RECORDS.slice(0, 5);
  const criticalEvents = MOCK_SECURITY_EVENTS.filter(
    (e) => e.severity === 'critical' || e.severity === 'high'
  ).slice(0, 3);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* Top Banner Notice */}
      <div
        className="card"
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
          <span className="badge badge-prototype">Prototype Mock Data</span>
          <button
            onClick={() => onNavigate('verification')}
            className="btn btn-primary"
            style={{ fontSize: '12px', padding: '6px 14px' }}
          >
            Launch Verification Simulator <ArrowRight size={14} />
          </button>
        </div>
      </div>

      {/* Primary Telemetry Grid */}
      <div className="stat-grid">
        <StatCard
          title="Registered Speakers"
          value={MOCK_METRICS.total_speakers}
          subtitle={`${MOCK_METRICS.active_speakers} active biometric profiles`}
          icon={<Users size={20} color="#3B82F6" />}
          iconBgColor="rgba(59, 130, 246, 0.15)"
          trend={{ value: '+2 this month', isPositive: true }}
        />
        <StatCard
          title="Access Terminals"
          value={MOCK_METRICS.total_devices}
          subtitle={`${MOCK_METRICS.active_devices} online HMAC-SHA256 ESP32 units`}
          icon={<Cpu size={20} color="#10B981" />}
          iconBgColor="rgba(16, 185, 129, 0.15)"
          trend={{ value: '1 suspended', isPositive: false }}
        />
        <StatCard
          title="Verification Success Rate"
          value={`${MOCK_METRICS.success_rate_percent}%`}
          subtitle={`${MOCK_METRICS.verifications_today} attempts logged today`}
          icon={<CheckCircle2 size={20} color="#34D399" />}
          iconBgColor="rgba(52, 211, 153, 0.15)"
          trend={{ value: '+1.2% vs baseline', isPositive: true }}
        />
        <StatCard
          title="Security Incidents"
          value={MOCK_METRICS.critical_alerts}
          subtitle="Replay & revoked device blocks"
          icon={<AlertTriangle size={20} color="#EF4444" />}
          iconBgColor="rgba(239, 68, 68, 0.15)"
        />
      </div>

      {/* Middle Split: Biometric Calibration & Security Alerts */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: '20px' }}>
        {/* ML Calibration Status */}
        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <div>
              <h3 className="text-base font-semibold text-primary">Biometric Model Calibration</h3>
              <p className="text-xs text-muted" style={{ marginTop: '2px' }}>
                Statistical thresholding & cosine similarity distribution
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
          </div>
        </div>

        {/* Urgent Security Alerts */}
        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <div>
              <h3 className="text-base font-semibold text-primary">Threat & Replay Monitoring</h3>
              <p className="text-xs text-muted" style={{ marginTop: '2px' }}>
                Latest security interventions and blocked attacks
              </p>
            </div>
            <button
              onClick={() => onNavigate('events')}
              className="btn btn-secondary"
              style={{ fontSize: '11px', padding: '4px 10px' }}
            >
              View Full Audit Log
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {criticalEvents.map((event) => (
              <div
                key={event.id}
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
                  {event.severity === 'critical' ? (
                    <ShieldAlert size={16} color="#EF4444" />
                  ) : (
                    <AlertTriangle size={16} color="#F59E0B" />
                  )}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' }}>
                    <span className="font-mono text-xs font-semibold text-primary">
                      {event.event_type}
                    </span>
                    <Badge value={event.severity} />
                  </div>
                  <p className="text-xs text-secondary" style={{ lineHeight: '1.4' }}>
                    {event.details}
                  </p>
                  <div style={{ display: 'flex', gap: '12px', marginTop: '6px' }} className="text-xs text-muted font-mono">
                    <span>{event.timestamp}</span>
                    <span>Source: {event.source}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recent Biometric Verifications Table */}
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
          <div>
            <h3 className="text-base font-semibold text-primary">Recent Biometric Access Attempts</h3>
            <p className="text-xs text-muted" style={{ marginTop: '2px' }}>
              Live verification stream across physical terminals
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

        <div className="table-container">
          <table className="enterprise-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Speaker Claim</th>
                <th>Terminal</th>
                <th>Cosine Similarity</th>
                <th>Liveness Digits</th>
                <th>Result</th>
                <th>Latency</th>
              </tr>
            </thead>
            <tbody>
              {recentVerifications.map((row) => (
                <tr key={row.id}>
                  <td className="font-mono text-xs text-muted">{row.timestamp}</td>
                  <td>
                    <div className="font-semibold text-primary">{row.speaker_name}</div>
                    <div className="text-xs text-muted font-mono">id: {row.speaker_id}</div>
                  </td>
                  <td>
                    <div className="text-secondary">{row.device_name}</div>
                    <div className="text-xs text-muted font-mono">{row.device_id}</div>
                  </td>
                  <td>
                    <div className="font-mono font-semibold" style={{ color: row.similarity_score >= row.threshold ? '#34D399' : '#F87171' }}>
                      {row.similarity_score.toFixed(4)}
                    </div>
                    <div className="text-xs text-muted font-mono">Threshold: {row.threshold.toFixed(2)}</div>
                  </td>
                  <td className="font-mono text-xs">
                    <span style={{ letterSpacing: '0.15em', fontWeight: 600 }}>
                      {row.liveness_digits}
                    </span>
                    <span style={{ marginLeft: '8px', color: row.liveness_pass ? '#34D399' : '#F87171' }}>
                      {row.liveness_pass ? '✓ Pass' : '✗ Failed'}
                    </span>
                  </td>
                  <td>
                    <Badge value={row.result} />
                  </td>
                  <td className="font-mono text-xs text-muted">
                    {row.latency_ms} ms
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
