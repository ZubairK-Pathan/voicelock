'use client';

import { PageHeader } from '@/components/ui/PageHeader';
import { Card } from '@/components/ui/Card';
import { StatusPill } from '@/components/ui/StatusPill';
import { ComingSoon, LoadingState, ErrorState } from '@/components/ui/States';
import { useApiResource } from '@/lib/hooks/useApiResource';
import { api } from '@/lib/api/client';

export default function DashboardPage() {
  const health = useApiResource(() => api.health());
  const speakers = useApiResource(() => api.listSpeakers());

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Welcome back! Here's your system overview"
      />

      {/* Status Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        {/* API Status Card */}
        <Card gradient="from-purple-900/40 to-pink-900/40">
          <div className="flex items-start justify-between mb-6">
            <div className="flex-1">
              <p className="text-slate-400 text-sm font-semibold tracking-wide">API STATUS</p>
              <p className="text-4xl font-bold mt-3">
                {health.loading ? '...' : health.error ? 'Down' : 'Healthy'}
              </p>
            </div>
            <div className="text-5xl">
              {health.loading ? '⏳' : health.error ? '🔴' : '🟢'}
            </div>
          </div>

          {!health.loading && (
            <div className="mb-4">
              <StatusPill
                status={health.error ? 'error' : 'success'}
                label={health.error ? 'Offline' : 'Online'}
              />
            </div>
          )}

          {health.data && (
            <div className="space-y-3 pt-4 border-t border-slate-700/30">
              <div className="flex items-center justify-between">
                <span className="text-slate-400 text-sm">Model Status</span>
                <span className={`font-semibold text-sm ${health.data.model_loaded ? 'text-emerald-400' : 'text-slate-500'}`}>
                  {health.data.model_loaded ? '✓ Loaded' : '✗ Loading'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400 text-sm">Profiles</span>
                <span className={`font-semibold text-sm ${health.data.profiles_file_present ? 'text-emerald-400' : 'text-slate-500'}`}>
                  {health.data.profiles_file_present ? '✓ Present' : '✗ Missing'}
                </span>
              </div>
            </div>
          )}
        </Card>

        {/* Speakers Count Card */}
        <Card gradient="from-cyan-900/40 to-blue-900/40">
          <div className="flex items-start justify-between mb-6">
            <div className="flex-1">
              <p className="text-slate-400 text-sm font-semibold tracking-wide">ENROLLED SPEAKERS</p>
              <p className="text-4xl font-bold mt-3">
                {speakers.loading ? '...' : speakers.error ? '✗' : speakers.data?.count || 0}
              </p>
            </div>
            <div className="text-5xl">
              {speakers.loading ? '⏳' : speakers.error ? '🔴' : '👥'}
            </div>
          </div>

          <div className="mb-4">
            <StatusPill
              status={speakers.error ? 'error' : 'success'}
              label={speakers.error ? 'Error Loading' : 'Synced'}
            />
          </div>

          {speakers.data && (
            <div className="pt-4 border-t border-slate-700/30">
              <p className="text-slate-400 text-sm">
                {speakers.data.count} speaker{speakers.data.count !== 1 ? 's' : ''} enrolled in the system
              </p>
            </div>
          )}
        </Card>
      </div>

      {/* Recent Activity Card */}
      <Card gradient="from-emerald-900/40 to-teal-900/40">
        <h2 className="text-xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-emerald-300 to-teal-300 mb-6">
          Recent Activity
        </h2>
        <ComingSoon />
      </Card>
    </>
  );
}