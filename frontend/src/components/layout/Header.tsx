import React from 'react';
import { Database, LogOut, User, Mic, Menu, X } from 'lucide-react';
import type { NavigationTab } from '../../types';
import { useAuth } from '../../context/useAuth';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';

interface HeaderProps {
  activeTab: NavigationTab;
  onOpenQuickVerification?: () => void;
  isMobileNavOpen?: boolean;
  onToggleMobileNav?: () => void;
  mobileMenuButtonRef?: React.Ref<HTMLButtonElement>;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  onOpenQuickVerification,
  isMobileNavOpen = false,
  onToggleMobileNav,
  mobileMenuButtonRef,
}) => {
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
      <div className="header-left">
        {/* Mobile menu drawer toggle button */}
        {onToggleMobileNav && (
          <button
            type="button"
            className="mobile-menu-btn"
            ref={mobileMenuButtonRef}
            onClick={onToggleMobileNav}
            aria-label={isMobileNavOpen ? 'Close navigation drawer' : 'Open navigation drawer'}
            aria-expanded={isMobileNavOpen}
            aria-controls="main-navigation"
          >
            {isMobileNavOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        )}

        <div className="header-title-block">
          <div className="header-heading-row">
            <h1 className="header-title">{title}</h1>
            {user?.isDemoUser ? (
              <Badge variant="warning">Local Demonstration</Badge>
            ) : (
              <Badge variant="success">Cloud Operations</Badge>
            )}
          </div>
          <p className="header-subtitle">{subtitle}</p>
        </div>
      </div>

      <div className="header-right">
        {/* Context only: page-level telemetry reports actual API status. */}
        <div className="header-status-pill" title="Authenticated session context; backend status is shown in the active workspace">
          <span className="status-label">SESSION</span>
          <span className="status-divider">|</span>
          <Database size={13} className="status-icon" />
          <span className="status-label">AUTHENTICATED</span>
        </div>

        {/* Authenticated Principal Info */}
        {user && (
          <div className="header-user-pill">
            <div
              className={`header-user-avatar ${isAdmin ? 'avatar-admin' : 'avatar-user'}`}
            >
              <User size={13} />
            </div>
            <div className="header-user-meta">
              <span className="header-user-name">
                {user.displayName || user.email}
              </span>
              <span className={`header-user-role ${isAdmin ? 'role-admin' : 'role-user'}`}>
                {user.role.toUpperCase()}
              </span>
            </div>
            <button
              onClick={() => signOut()}
              title="Sign Out"
              aria-label="Sign Out"
              className="header-signout-btn"
            >
              <LogOut size={13} />
            </button>
          </div>
        )}

        {/* Quick action button */}
        {activeTab !== 'verification' && onOpenQuickVerification && (
          <Button
            variant="default"
            size="sm"
            onClick={onOpenQuickVerification}
            className="header-quick-action"
          >
            <Mic size={14} />
            <span className="quick-action-text">Quick Verification</span>
          </Button>
        )}
      </div>
    </header>
  );
};
