import React from 'react';
import { Database, LogOut, User, Mic } from 'lucide-react';
import type { NavigationTab } from '../../types';
import { useAuth } from '../../context/useAuth';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';

interface HeaderProps {
  activeTab: NavigationTab;
  onOpenQuickVerification?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ activeTab, onOpenQuickVerification }) => {
  const { user, signOut } = useAuth();
  const isAdmin = user?.role === 'admin';

  const titles: Record<NavigationTab, { title: string; subtitle: string }> = {
    overview: {
      title: isAdmin ? 'System Operations Dashboard' : 'Personal Biometric Access Portal',
      subtitle: isAdmin
        ? 'Real-time biometric access telemetry, hardware status, and threshold calibration'
        : 'Manage your enrolled voice identity and access physical security portals',
    },
    speakers: {
      title: 'Enrolled Speaker Registry',
      subtitle: '192-dimensional acoustic voiceprint registry and authorization records',
    },
    verification: {
      title: 'Voice Verification Portal',
      subtitle: 'Cryptographic challenge-response liveness detection and ECAPA-TDNN speaker verification',
    },
    devices: {
      title: 'Physical Access Terminals',
      subtitle: 'Registered hardware access points (ESP32 terminals) and HMAC-SHA256 credentials',
    },
    events: {
      title: 'Security Audit Log',
      subtitle: 'Enterprise security journal: liveness checks, replay alerts, and administrative actions',
    },
    identities: {
      title: 'Identity Management',
      subtitle: 'Administrator control: link Firebase accounts to enrolled voice identities',
    },
  };

  const { title, subtitle } = titles[activeTab] || titles.overview;

  return (
    <header className="top-header">
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <h1 className="text-xl font-bold text-primary" style={{ letterSpacing: '-0.01em', margin: 0 }}>
            {title}
          </h1>
          {user?.isDemoUser ? (
            <Badge variant="warning">Local Demonstration</Badge>
          ) : (
            <Badge variant="success">Cloud Operations</Badge>
          )}
        </div>
        <p className="text-xs text-muted" style={{ marginTop: '3px', margin: 0 }}>
          {subtitle}
        </p>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
        {/* Backend Connectivity Status */}
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
            Postgres
          </span>
        </div>

        {/* Authenticated Principal Info */}
        {user && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              background: 'rgba(14, 20, 34, 0.8)',
              border: '1px solid var(--border-subtle)',
              padding: '4px 10px 4px 6px',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            <div
              style={{
                width: '26px',
                height: '26px',
                borderRadius: 'var(--radius-sm)',
                background: isAdmin ? 'rgba(59, 130, 246, 0.2)' : 'rgba(16, 185, 129, 0.2)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <User size={14} color={isAdmin ? '#60A5FA' : '#34D399'} />
            </div>
            <div style={{ lineHeight: '1.2' }}>
              <div className="text-xs font-semibold text-primary" style={{ maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {user.displayName || user.email}
              </div>
              <div className="text-xs font-mono" style={{ color: isAdmin ? '#60A5FA' : '#34D399', fontSize: '10px' }}>
                {user.role.toUpperCase()}
              </div>
            </div>
            <button
              onClick={() => signOut()}
              title="Sign Out"
              aria-label="Sign Out"
              className="btn btn-secondary"
              style={{ padding: '4px 6px', marginLeft: '4px', border: 'none', background: 'transparent', cursor: 'pointer' }}
            >
              <LogOut size={14} color="var(--text-muted)" />
            </button>
          </div>
        )}

        {/* Quick action button */}
        {activeTab !== 'verification' && onOpenQuickVerification && (
          <Button
            variant="default"
            size="sm"
            onClick={onOpenQuickVerification}
          >
            <Mic size={14} /> Quick Verification
          </Button>
        )}
      </div>
    </header>
  );
};
