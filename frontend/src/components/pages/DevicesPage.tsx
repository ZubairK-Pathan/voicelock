import React, { useState, useEffect, useCallback } from 'react';
import {
  Cpu,
  Plus,
  RefreshCw,
  Info,
  Lock,
} from 'lucide-react';
import { SearchBar } from '../common/SearchBar';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Modal } from '../common/Modal';
import { useAuth } from '../../context/useAuth';
import { apiClient } from '../../lib/apiClient';
import type { DeviceSummaryItem, EntityStatus } from '../../types';

export const DevicesPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  // Live database state
  const [devices, setDevices] = useState<DeviceSummaryItem[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [activeCount, setActiveCount] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | EntityStatus>('all');
  const [isProvisioningModalOpen, setIsProvisioningModalOpen] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);

  const handleRefresh = useCallback(() => {
    setIsLoading(true);
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  useEffect(() => {
    if (!isAdmin) return;
    let ignore = false;

    async function loadDevices() {
      setIsLoading(true);
      setError(null);

      try {
        const response = await apiClient.getDevices();
        if (ignore) return;

        if (response.ok && response.data) {
          const list = response.data.devices || [];
          setDevices(list);
          setTotalCount(response.data.total ?? list.length);
          setActiveCount(response.data.active_count ?? list.filter((d) => d.status === 'active').length);
        } else {
          if (response.status === 403) {
            setError('Administrative privileges are required to inspect the device registry.');
          } else if (response.status === 401) {
            setError('Your operator session has expired. Please re-authenticate.');
          } else {
            setError(response.error || 'Failed to retrieve terminal registry from the database.');
          }
          setDevices([]);
        }
      } catch {
        if (!ignore) {
          setError('Network failure while communicating with the device registry API.');
          setDevices([]);
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    loadDevices();

    return () => {
      ignore = true;
    };
  }, [isAdmin, refreshTrigger]);

  // Non-admin presentation guard
  if (!isAdmin) {
    return (
      <div
        className="card"
        style={{
          padding: '48px 24px',
          textAlign: 'center',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '16px',
          maxWidth: '560px',
          margin: '40px auto',
        }}
      >
        <div
          style={{
            width: '52px',
            height: '52px',
            borderRadius: 'var(--radius-sm)',
            background: 'rgba(239, 68, 68, 0.12)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: '1px solid rgba(239, 68, 68, 0.3)',
          }}
        >
          <Lock size={26} color="#EF4444" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-primary">Administrator Authorization Required</h2>
          <p className="text-xs text-secondary" style={{ marginTop: '8px', lineHeight: 1.6 }}>
            Hardware access terminals and cryptographic credentials are restricted to verified administrators.
            Standard operators cannot enumerate physical security infrastructure.
          </p>
        </div>
      </div>
    );
  }

  const filteredDevices = devices.filter((dev) => {
    const term = search.toLowerCase();
    const matchesSearch =
      dev.device_id.toLowerCase().includes(term) ||
      (dev.name && dev.name.toLowerCase().includes(term));
    const matchesStatus =
      statusFilter === 'all' || dev.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Banner Notice */}
      <div
        className="card"
        style={{
          background: 'rgba(59, 130, 246, 0.08)',
          borderLeft: '4px solid var(--color-brand)',
          padding: '14px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px',
        }}
      >
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <Info size={18} color="#60A5FA" style={{ flexShrink: 0 }} />
          <span className="text-xs text-secondary">
            Physical Access Terminals are authenticated server-side via <strong>HMAC-SHA256</strong> (Scheme A) with sliding-window nonce verification and 300s timestamp drift checks. Zero pre-shared secrets or hashes are ever transmitted to the frontend.
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRefresh}
            disabled={isLoading}
          >
            <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} /> Refresh
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => setIsProvisioningModalOpen(true)}
          >
            <Plus size={14} /> Provision Terminal
          </Button>
        </div>
      </div>

      {/* Summary Stat Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px' }}>
        <div className="card" style={{ padding: '16px 20px' }}>
          <div className="text-xs text-muted font-mono" style={{ textTransform: 'uppercase' }}>Total Registered Terminals</div>
          <div className="font-mono text-2xl font-bold text-primary" style={{ marginTop: '4px' }}>
            {isLoading ? '—' : totalCount}
          </div>
          <div className="text-xs text-secondary" style={{ marginTop: '4px' }}>Persistent database records</div>
        </div>
        <div className="card" style={{ padding: '16px 20px' }}>
          <div className="text-xs text-muted font-mono" style={{ textTransform: 'uppercase' }}>Active Online Portals</div>
          <div className="font-mono text-2xl font-bold" style={{ marginTop: '4px', color: '#10B981' }}>
            {isLoading ? '—' : activeCount}
          </div>
          <div className="text-xs text-secondary" style={{ marginTop: '4px' }}>Authorized for door unlock operations</div>
        </div>
        <div className="card" style={{ padding: '16px 20px' }}>
          <div className="text-xs text-muted font-mono" style={{ textTransform: 'uppercase' }}>Cryptographic Verifier</div>
          <div className="font-mono text-base font-semibold text-primary" style={{ marginTop: '6px' }}>
            SHA-256 Verifier Hashes
          </div>
          <div className="text-xs text-secondary" style={{ marginTop: '4px' }}>Raw credentials excluded (Data Minimization)</div>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div
          className="card"
          style={{
            background: 'rgba(239, 68, 68, 0.08)',
            borderLeft: '4px solid var(--color-rose)',
            padding: '12px 16px',
            color: '#F87171',
            fontSize: '13px',
          }}
        >
          {error}
        </div>
      )}

      {/* Page Actions & Filters */}
      <div
        className="card"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '14px',
          padding: '16px 20px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
          <SearchBar
            value={search}
            onChange={setSearch}
            placeholder="Search by terminal ID or name..."
            count={filteredDevices.length}
          />
          <div style={{ display: 'flex', gap: '6px' }}>
            {(['all', 'active', 'suspended', 'revoked'] as const).map((status) => (
              <button
                key={status}
                onClick={() => setStatusFilter(status)}
                className="btn btn-secondary"
                style={{
                  padding: '6px 12px',
                  fontSize: '12px',
                  textTransform: 'capitalize',
                  borderColor:
                    statusFilter === status
                      ? 'var(--color-brand)'
                      : 'var(--border-subtle)',
                  background:
                    statusFilter === status
                      ? 'rgba(59, 130, 246, 0.12)'
                      : 'var(--bg-surface)',
                  color:
                    statusFilter === status
                      ? '#FFFFFF'
                      : 'var(--text-secondary)',
                }}
              >
                {status}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Terminals Table */}
      <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
        <div className="table-container">
          <table className="enterprise-table">
            <thead>
              <tr>
                <th>Terminal Identifier</th>
                <th>Installation Location / Label</th>
                <th>Authentication Scheme</th>
                <th>Credential Key Version</th>
                <th>Lifecycle Status</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '36px', color: 'var(--text-muted)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                      <RefreshCw size={16} className="animate-spin" /> Querying terminal registry from database...
                    </div>
                  </td>
                </tr>
              ) : filteredDevices.length > 0 ? (
                filteredDevices.map((dev) => (
                  <tr key={dev.device_id}>
                    <td>
                      <div className="font-mono text-sm font-semibold text-primary" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Cpu size={14} color="#60A5FA" /> {dev.device_id}
                      </div>
                    </td>
                    <td>
                      <div className="text-secondary">
                        {dev.name || <span className="text-muted font-italic">Unlabeled Terminal</span>}
                      </div>
                    </td>
                    <td>
                      <span className="font-mono text-xs font-semibold" style={{ color: '#60A5FA', background: 'rgba(59, 130, 246, 0.1)', padding: '2px 8px', borderRadius: '4px' }}>
                        HMAC-SHA256 (Scheme A)
                      </span>
                    </td>
                    <td>
                      <span className="font-mono text-xs text-secondary">
                        v{dev.key_version} (Active)
                      </span>
                    </td>
                    <td>
                      <Badge variant={dev.status === 'active' ? 'success' : dev.status === 'suspended' ? 'warning' : 'destructive'}>
                        {dev.status.toUpperCase()}
                      </Badge>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--text-muted)' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                      <Cpu size={28} color="var(--text-muted)" />
                      <div className="text-sm font-semibold text-primary">No Registered Terminals Found</div>
                      <div className="text-xs text-secondary" style={{ maxWidth: '380px' }}>
                        {search || statusFilter !== 'all'
                          ? 'No registered access terminals matched your current search filters.'
                          : 'No hardware access points are currently enrolled in the enterprise database. Provision terminals using the VoiceLock CLI.'}
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Provisioning Notice Modal */}
      {isProvisioningModalOpen && (
        <Modal
          isOpen={isProvisioningModalOpen}
          title="Hardware Terminal Provisioning"
          onClose={() => setIsProvisioningModalOpen(false)}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', fontSize: '13px', lineHeight: 1.6 }}>
            <p className="text-secondary">
              Physical access terminals (e.g., ESP32 biometric turnstiles and door controllers) must be provisioned securely to prevent credential tampering:
            </p>
            <div
              style={{
                background: 'rgba(0, 0, 0, 0.4)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                padding: '12px 14px',
                fontFamily: 'monospace',
                fontSize: '12px',
                color: '#60A5FA',
              }}
            >
              python scripts/provision_device.py --device-id terminal-gate-02 --name "South Entrance"
            </div>
            <p className="text-secondary" style={{ fontSize: '12px' }}>
              The provisioning tool generates high-entropy CSPRNG secrets, injects HMAC-SHA256 keys into the terminal firmware via serial or secure flash, and writes the SHA-256 verifier hash to the enterprise database.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '10px' }}>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setIsProvisioningModalOpen(false)}
              >
                Close
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
