import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import type { NavigationTab } from '../../types';

interface LayoutProps {
  activeTab: NavigationTab;
  onTabChange: (tab: NavigationTab) => void;
  counts: {
    speakers?: number;
    devices?: number;
    alerts?: number;
    mappings?: number;
  };
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({
  activeTab,
  onTabChange,
  counts,
  children,
}) => {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  // Keep keyboard focus within the mobile navigation journey. Returning focus to
  // the trigger makes a backdrop or Escape dismissal predictable for keyboard users.
  useEffect(() => {
    if (!isMobileNavOpen) return;

    const previousOverflow = document.body.style.overflow;
    const menuButton = menuButtonRef.current;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();

    return () => {
      document.body.style.overflow = previousOverflow;
      menuButton?.focus();
    };
  }, [isMobileNavOpen]);

  // Close mobile drawer on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isMobileNavOpen) {
        setIsMobileNavOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isMobileNavOpen]);

  // Handle tab selection with automatic mobile drawer dismissal
  const handleTabChange = useCallback(
    (tab: NavigationTab) => {
      onTabChange(tab);
      setIsMobileNavOpen(false);
      requestAnimationFrame(() => {
        document.querySelector<HTMLElement>('main.page-wrapper')?.focus();
      });
    },
    [onTabChange]
  );

  const handleToggleMobileNav = useCallback(() => {
    setIsMobileNavOpen((prev) => !prev);
  }, []);

  const handleCloseMobileNav = useCallback(() => {
    setIsMobileNavOpen(false);
  }, []);

  return (
    <div className="app-container">
      {/* Accessible Mobile Drawer Backdrop */}
      {isMobileNavOpen && (
        <div
          className="mobile-nav-backdrop"
          onClick={handleCloseMobileNav}
          aria-hidden="true"
        />
      )}

      <Sidebar
        activeTab={activeTab}
        onTabChange={handleTabChange}
        counts={counts}
        isOpen={isMobileNavOpen}
        onClose={handleCloseMobileNav}
        closeButtonRef={closeButtonRef}
      />

      <div className="main-content">
        <Header
          activeTab={activeTab}
          onOpenQuickVerification={() => handleTabChange('verification')}
          isMobileNavOpen={isMobileNavOpen}
          onToggleMobileNav={handleToggleMobileNav}
          mobileMenuButtonRef={menuButtonRef}
        />
        <main className="page-wrapper" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
};
