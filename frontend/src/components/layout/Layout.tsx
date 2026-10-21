import React from 'react';
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
  return (
    <div className="app-container">
      <Sidebar
        activeTab={activeTab}
        onTabChange={onTabChange}
        counts={counts}
      />
      <div className="main-content">
        <Header
          activeTab={activeTab}
          onOpenQuickVerification={() => onTabChange('verification')}
        />
        <main className="page-wrapper">{children}</main>
      </div>
    </div>
  );
};
