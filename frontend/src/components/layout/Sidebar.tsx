import React from 'react';
import {
  LayoutDashboard,
  Users,
  Mic,
  Cpu,
  ShieldAlert,
  Shield,
  Activity,
  Sliders,
  UserCheck,
  User,
} from 'lucide-react';
import type { NavigationTab } from '../../types';
import { useAuth } from '../../context/useAuth';
import { Badge } from '../ui/Badge';

interface SidebarProps {
  activeTab: NavigationTab;
  onTabChange: (tab: NavigationTab) => void;
  counts: {
    speakers?: number;
    devices?: number;
    alerts?: number;
    mappings?: number;
  };
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onTabChange,
  counts,
}) => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  // Role-Aware Navigation:
  // Regular operators only see personal overview and voice verification.
  // Administrative operators see full system and management tabs.
  const navItems = [
    {
      id: 'overview' as NavigationTab,
      label: isAdmin ? 'System Overview' : 'Overview',
      icon: <LayoutDashboard size={18} />,
    },
    {
      id: 'verification' as NavigationTab,
      label: 'Voice Verification',
      icon: <Mic size={18} />,
    },
    ...(isAdmin
      ? [
          {
            id: 'speakers' as NavigationTab,
            label: 'Enrolled Speakers',
            icon: <Users size={18} />,
            badge: counts.speakers,
          },
          {
            id: 'identities' as NavigationTab,
            label: 'Identity Mappings',
            icon: <UserCheck size={18} />,
            badge: counts.mappings,
          },
          {
            id: 'devices' as NavigationTab,
            label: 'Access Terminals',
            icon: <Cpu size={18} />,
            badge: counts.devices,
          },
          {
            id: 'events' as NavigationTab,
            label: 'Security Audit Log',
            icon: <ShieldAlert size={18} />,
            badge: counts.alerts !== undefined && counts.alerts > 0 ? counts.alerts : undefined,
            badgeColor: '#EF4444',
          },
        ]
      : []),
  ];

  return (
    <aside className="sidebar">
      {/* Brand */}
      <div className="sidebar-brand">
        <div className="sidebar-logo-icon">
          <Shield size={20} color="#FFFFFF" />
        </div>
        <div>
          <div className="font-bold text-base text-primary" style={{ letterSpacing: '-0.02em', lineHeight: '1.2' }}>
            VoiceLock
          </div>
          <div className="text-xs font-mono" style={{ color: '#60A5FA', letterSpacing: '0.05em' }}>
            ENTERPRISE SEC
          </div>
        </div>
      </div>

      {/* Authenticated Operator Identity Card */}
      {user && (
        <div
          style={{
            padding: '12px 14px',
            margin: '12px 12px 0 12px',
            background: 'rgba(255, 255, 255, 0.03)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-sm)',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
          }}
        >
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-sm)',
              background: isAdmin ? 'rgba(59, 130, 246, 0.15)' : 'rgba(16, 185, 129, 0.15)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <User size={16} color={isAdmin ? '#60A5FA' : '#34D399'} />
          </div>
          <div style={{ flex: 1, minWidth: 0, lineHeight: 1.3 }}>
            <div
              className="text-xs font-semibold text-primary"
              style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
            >
              {user.displayName || user.email?.split('@')[0] || 'Operator'}
            </div>
            <div style={{ marginTop: '2px' }}>
              <Badge variant={isAdmin ? 'default' : 'success'}>
                {isAdmin ? 'SECURITY ADMIN' : 'OPERATOR'}
              </Badge>
            </div>
          </div>
        </div>
      )}

      {/* Navigation */}
      <nav className="sidebar-nav">
        <div className="text-xs font-semibold text-muted" style={{ padding: '8px 14px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          {isAdmin ? 'Operations & Control' : 'Access Portal'}
        </div>
        {navItems.map((item) => {
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onTabChange(item.id)}
              className={`nav-link ${isActive ? 'active' : ''}`}
            >
              <div className="nav-link-left">
                <span style={{ color: isActive ? 'var(--color-brand)' : 'inherit' }}>
                  {item.icon}
                </span>
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && (
                <span
                  className="font-mono text-xs font-semibold"
                  style={{
                    backgroundColor: item.badgeColor ? 'rgba(239, 68, 68, 0.2)' : 'rgba(255, 255, 255, 0.08)',
                    color: item.badgeColor || 'var(--text-secondary)',
                    padding: '1px 7px',
                    borderRadius: '10px',
                  }}
                >
                  {item.badge}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* System Telemetry Metadata */}
      <div className="sidebar-footer">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <span className="text-xs text-muted font-medium" style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
            <Activity size={12} color="#10B981" /> ML Engine Active
          </span>
          <span className="text-xs font-mono" style={{ color: '#10B981', fontWeight: 600 }}>
            v2.4-tdnn
          </span>
        </div>
        <div className="card" style={{ padding: '10px 12px', background: 'rgba(14, 20, 34, 0.6)', border: '1px solid rgba(255, 255, 255, 0.06)' }}>
          <div className="text-xs text-muted font-mono" style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span>Architecture</span>
            <span className="text-secondary">ECAPA-TDNN</span>
          </div>
          <div className="text-xs text-muted font-mono" style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
            <span>Embedding Dim</span>
            <span className="text-secondary">192-d mono</span>
          </div>
          <div className="text-xs text-muted font-mono" style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>Calibrated EER</span>
            <span className="text-secondary" style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
              <Sliders size={10} /> 0.2500
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
};
