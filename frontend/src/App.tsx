import { useState, useEffect } from 'react';
import { Shield, RefreshCw } from 'lucide-react';
import { AuthProvider } from './context/AuthContext';
import { useAuth } from './context/useAuth';
import { SignInPage } from './components/auth/SignInPage';
import { Layout } from './components/layout/Layout';
import { OverviewPage } from './components/pages/OverviewPage';
import { SpeakersPage } from './components/pages/SpeakersPage';
import { VerificationPage } from './components/pages/VerificationPage';
import { DevicesPage } from './components/pages/DevicesPage';
import { SecurityEventsPage } from './components/pages/SecurityEventsPage';
import { IdentityManagementPage } from './components/pages/IdentityManagementPage';
import type { NavigationTab } from './types';
import { apiClient } from './lib/apiClient';

function DashboardApp() {
  const { user, loading, getIdToken } = useAuth();
  const [activeTab, setActiveTab] = useState<NavigationTab>('overview');
  const [counts, setCounts] = useState<{
    speakers?: number;
    devices?: number;
    alerts?: number;
    mappings?: number;
  }>({});

  // Bind token provider to ApiClient so authenticated requests attach Bearer tokens
  useEffect(() => {
    apiClient.setTokenProvider(getIdToken);
  }, [getIdToken]);

  // Load live telemetry counts when authenticated
  useEffect(() => {
    if (!user) return;
    let ignore = false;

    async function loadTelemetryCounts() {
      try {
        const isUserAdmin = user?.role === 'admin';
        const [speakersRes, devicesRes, mappingsRes] = await Promise.all([
          apiClient.getSpeakers(),
          apiClient.getDevices(),
          isUserAdmin
            ? apiClient.getAdminMappings()
            : Promise.resolve({ ok: false, data: null, status: 0 }),
        ]);
        if (ignore) return;
        setCounts({
          speakers: speakersRes.ok && speakersRes.data ? speakersRes.data.count : undefined,
          devices: devicesRes.ok && devicesRes.data ? devicesRes.data.total : undefined,
          mappings: mappingsRes.ok && mappingsRes.data ? mappingsRes.data.count : undefined,
          alerts: undefined,
        });
      } catch {
        if (!ignore) {
          setCounts({});
        }
      }
    }

    loadTelemetryCounts();

    return () => {
      ignore = true;
    };
  }, [user]);

  // Loading state preventing flash of dashboard
  if (loading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          width: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '16px',
          backgroundColor: '#080C14',
          color: '#F8FAFC',
        }}
      >
        <div
          style={{
            width: '56px',
            height: '56px',
            borderRadius: 'var(--radius-md)',
            background: 'linear-gradient(135deg, #1D4ED8 0%, #3B82F6 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 30px rgba(59, 130, 246, 0.4)',
          }}
        >
          <Shield size={30} color="#FFFFFF" />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <RefreshCw size={16} className="animate-spin" color="#60A5FA" />
          <span className="text-sm font-semibold font-mono text-secondary">
            Verifying VoiceLock Session...
          </span>
        </div>
      </div>
    );
  }

  // Not signed in -> Render Sign In Page
  if (!user) {
    return <SignInPage />;
  }

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
      case 'identities':
        return <IdentityManagementPage />;
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

export function App() {
  return (
    <AuthProvider>
      <DashboardApp />
    </AuthProvider>
  );
}

export default App;
