import { useState } from 'react';
import { Layout } from './components/layout/Layout';
import { OverviewPage } from './components/pages/OverviewPage';
import { SpeakersPage } from './components/pages/SpeakersPage';
import { VerificationPage } from './components/pages/VerificationPage';
import { DevicesPage } from './components/pages/DevicesPage';
import { SecurityEventsPage } from './components/pages/SecurityEventsPage';
import type { NavigationTab } from './types';
import { MOCK_METRICS } from './data/mockData';

export function App() {
  const [activeTab, setActiveTab] = useState<NavigationTab>('overview');

  const counts = {
    speakers: MOCK_METRICS.total_speakers,
    devices: MOCK_METRICS.total_devices,
    alerts: MOCK_METRICS.critical_alerts,
  };

  const renderActivePage = () => {
    switch (activeTab) {
      case 'overview':
        return <OverviewPage onNavigate={(tab) => setActiveTab(tab)} />;
      case 'speakers':
        return <SpeakersPage />;
      case 'verification':
        return <VerificationPage />;
      case 'devices':
        return <DevicesPage />;
      case 'events':
        return <SecurityEventsPage />;
      default:
        return <OverviewPage onNavigate={(tab) => setActiveTab(tab)} />;
    }
  };

  return (
    <Layout
      activeTab={activeTab}
      onTabChange={setActiveTab}
      counts={counts}
    >
      {renderActivePage()}
    </Layout>
  );
}

export default App;
