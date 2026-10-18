import React from 'react';
import { Info, Radio, Database } from 'lucide-react';
import type { NavigationTab } from '../../types';

interface HeaderProps {
  activeTab: NavigationTab;
  onOpenQuickVerification?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ activeTab, onOpenQuickVerification }) => {
  const titles: Record<NavigationTab, { title: string; subtitle: string }> = {
    overview: {
      title: 'Operations Dashboard',
      subtitle: 'Real-time biometric access control, terminal health, and threat mitigation',
    },
    speakers: {
      title: 'Enrolled Speaker Identities',
      subtitle: '192-dimensional acoustic voiceprint registry and authorization mappings',
    },
    verification: {
      title: 'Voice Verification Testing Portal',
      subtitle: 'Simulate challenge-response liveness detection and ECAPA-TDNN inference',
    },
    devices: {
      title: 'Physical Access Terminals',
      subtitle: 'Registered hardware access points (ESP32 terminals) and HMAC-SHA256 credentials',
    },
    events: {
      title: 'Security Audit Log',
      subtitle: 'Comprehensive audit stream: liveness checks, replay alerts, and auth decisions',
    },
  };

  const { title, subtitle } = titles[activeTab];

  return (
    <header className="top-header">
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <h1 className="text-xl font-bold text-primary" style={{ letterSpacing: '-0.01em' }}>
            {title}
          </h1>
          <span
            className="badge badge-prototype"
            style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}
          >
            <Info size={11} /> Prototype Mode (Mock Data)
          </span>
        </div>
        <p className="text-xs text-muted" style={{ marginTop: '2px' }}>
          {subtitle}
        </p>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        {/* System Telemetry Badge */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            background: 'rgba(14, 20, 34, 0.8)',
            border: '1px solid var(--border-subtle)',
            padding: '6px 12px',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <span
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: '#10B981',
              boxShadow: '0 0 8px #10B981',
              display: 'inline-block',
            }}
          />
          <span className="text-xs font-mono font-medium text-secondary">
            FastAPI :8000
          </span>
          <span className="text-xs text-muted">|</span>
          <Database size={13} color="#94A3B8" />
          <span className="text-xs font-mono text-secondary">
            Postgres / SQLite
          </span>
        </div>

        {/* Quick action button */}
        {activeTab !== 'verification' && onOpenQuickVerification && (
          <button
            onClick={onOpenQuickVerification}
            className="btn btn-primary"
            style={{ padding: '6px 14px', fontSize: '12px' }}
          >
            <Radio size={14} /> Simulate Verification
          </button>
        )}
      </div>
    </header>
  );
};
