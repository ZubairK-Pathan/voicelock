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
  X,
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
  isOpen?: boolean;
  onClose?: () => void;
  closeButtonRef?: React.Ref<HTMLButtonElement>;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  onTabChange,
  counts,
  isOpen = false,
  onClose,
  closeButtonRef,
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
    <aside id="main-navigation" className={`sidebar ${isOpen ? 'open' : ''}`} aria-label="Main Navigation">
      {/* Brand */}
      <div className="sidebar-brand">
        <div className="sidebar-brand-content">
          <div className="sidebar-logo-icon">
            <Shield size={18} color="#FFFFFF" />
          </div>
          <div>
            <div className="sidebar-title">
              VoiceLock
            </div>
            <div className="sidebar-subtitle">
              ENTERPRISE SEC
            </div>
          </div>
        </div>

        {/* Mobile close button */}
        {onClose && (
          <button
            type="button"
            className="sidebar-close-btn"
            ref={closeButtonRef}
            onClick={onClose}
            aria-label="Close navigation sidebar"
          >
            <X size={16} />
          </button>
        )}
      </div>

      {/* Authenticated Operator Identity Card */}
      {user && (
        <div className="sidebar-user-card">
          <div
            className={`sidebar-user-avatar ${isAdmin ? 'avatar-admin' : 'avatar-user'}`}
          >
            <User size={15} />
          </div>
          <div className="sidebar-user-details">
            <div className="sidebar-user-name">
              {user.displayName || user.email?.split('@')[0] || 'Operator'}
            </div>
            <div className="sidebar-user-badge">
              <Badge variant={isAdmin ? 'default' : 'success'}>
                {isAdmin ? 'SECURITY ADMIN' : 'OPERATOR'}
              </Badge>
            </div>
          </div>
        </div>
      )}

      {/* Navigation */}
      <nav className="sidebar-nav">
        <div className="sidebar-nav-header">
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
                <span className={`nav-icon ${isActive ? 'nav-icon-active' : ''}`}>
                  {item.icon}
                </span>
                <span className="nav-label">{item.label}</span>
              </div>
              {item.badge !== undefined && (
                <span
                  className="nav-badge font-mono"
                  style={{
                    backgroundColor: item.badgeColor ? 'rgba(239, 68, 68, 0.15)' : 'rgba(255, 255, 255, 0.08)',
                    color: item.badgeColor || 'var(--text-secondary)',
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
        <div className="sidebar-telemetry-status">
          <span className="telemetry-label">
            <Activity size={12} color="var(--color-emerald)" /> Voice model
          </span>
          <span className="telemetry-version font-mono">
            v2.4-tdnn
          </span>
        </div>
        <div className="sidebar-telemetry-box">
          <div className="telemetry-row font-mono">
            <span>Architecture</span>
            <span className="telemetry-value">ECAPA-TDNN</span>
          </div>
          <div className="telemetry-row font-mono">
            <span>Embedding Dim</span>
            <span className="telemetry-value">192-d mono</span>
          </div>
          <div className="telemetry-row font-mono">
            <span>Calibrated EER</span>
            <span className="telemetry-value telemetry-eer">
              <Sliders size={10} /> 0.2500
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
};
