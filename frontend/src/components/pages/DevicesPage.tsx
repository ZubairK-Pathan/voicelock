import React, { useState } from 'react';
import {
  Cpu,
  Plus,
  MapPin,
  AlertTriangle,
  Info,
} from 'lucide-react';
import { SearchBar } from '../common/SearchBar';
import { Badge } from '../common/Badge';
import { Modal } from '../common/Modal';
import { MOCK_DEVICES } from '../../data/mockData';
import type { Device, EntityStatus } from '../../types';

export const DevicesPage: React.FC = () => {
  const [devices] = useState<Device[]>(MOCK_DEVICES);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | EntityStatus>('all');
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [isRegisterModalOpen, setIsRegisterModalOpen] = useState(false);

  const filteredDevices = devices.filter((dev) => {
    const matchesSearch =
      dev.name.toLowerCase().includes(search.toLowerCase()) ||
      dev.device_id.toLowerCase().includes(search.toLowerCase()) ||
      dev.location.toLowerCase().includes(search.toLowerCase()) ||
      dev.ip_address.includes(search);
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
        }}
      >
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          <Info size={18} color="#60A5FA" style={{ flexShrink: 0 }} />
          <span className="text-xs text-secondary">
            Physical Access Terminals are authenticated server-side via <strong>HMAC-SHA256</strong> (Scheme A) with timestamp drift checks and atomic nonce replay resistance. Revoked or suspended terminals are rejected with HTTP 401 at the database layer.
          </span>
        </div>
      </div>

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
            placeholder="Search by terminal name, ID, or IP..."
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

        <button
          onClick={() => setIsRegisterModalOpen(true)}
          className="btn btn-primary"
        >
          <Plus size={16} /> Register New Terminal
        </button>
      </div>

      {/* Terminals Table */}
      <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
        <div className="table-container">
          <table className="enterprise-table">
            <thead>
              <tr>
                <th>Terminal Identity</th>
                <th>Physical Location</th>
                <th>Network IP</th>
                <th>Authentication Scheme</th>
                <th>Key Version</th>
                <th>Status</th>
                <th>Last Active</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredDevices.length > 0 ? (
                filteredDevices.map((dev) => (
                  <tr key={dev.id}>
                    <td>
                      <div className="font-semibold text-primary">{dev.name}</div>
                      <div className="font-mono text-xs text-muted" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Cpu size={11} /> {dev.device_id}
                      </div>
                    </td>
                    <td>
                      <div className="text-secondary" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <MapPin size={12} color="var(--text-muted)" /> {dev.location}
                      </div>
                    </td>
                    <td className="font-mono text-xs text-secondary">
                      {dev.ip_address}
                    </td>
                    <td>
                      <span
                        className="font-mono text-xs font-semibold"
                        style={{
                          color: dev.auth_scheme === 'HMAC-SHA256' ? '#60A5FA' : '#FBBF24',
                          background: dev.auth_scheme === 'HMAC-SHA256' ? 'rgba(59, 130, 246, 0.12)' : 'rgba(245, 158, 11, 0.12)',
                          padding: '3px 8px',
                          borderRadius: '4px',
                        }}
                      >
                        {dev.auth_scheme}
                      </span>
                    </td>
                    <td className="font-mono text-xs text-secondary">
                      v{dev.key_version}
                    </td>
                    <td>
                      <Badge value={dev.status} />
                    </td>
                    <td className="font-mono text-xs text-muted">
                      {dev.last_seen_at}
                    </td>
                    <td>
                      <button
                        onClick={() => setSelectedDevice(dev)}
                        className="btn btn-secondary"
                        style={{ padding: '4px 10px', fontSize: '12px' }}
                      >
                        Terminal Details
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', padding: '48px 20px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                      <Cpu size={32} color="var(--text-muted)" />
                      <div className="text-sm font-semibold text-primary">No access terminals found</div>
                      <p className="text-xs text-muted">
                        No hardware terminals matched your query "{search}".
                      </p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Terminal Details Modal */}
      {selectedDevice && (
        <Modal
          isOpen={true}
          onClose={() => setSelectedDevice(null)}
          title={`Terminal: ${selectedDevice.name}`}
          subtitle={`Hardware Device ID: ${selectedDevice.device_id}`}
          footer={
            <button
              onClick={() => setSelectedDevice(null)}
              className="btn btn-secondary"
            >
              Close
            </button>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Cryptographic Authentication</span>
                <div className="font-mono text-sm font-semibold text-primary" style={{ marginTop: '2px' }}>
                  {selectedDevice.auth_scheme}
                </div>
              </div>
              <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Signing Key Version</span>
                <div className="font-mono text-sm font-semibold text-primary" style={{ marginTop: '2px' }}>
                  v{selectedDevice.key_version} (SHA-256 Verifier)
                </div>
              </div>
              <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Firmware Version</span>
                <div className="font-mono text-sm font-semibold text-primary" style={{ marginTop: '2px' }}>
                  {selectedDevice.firmware_version}
                </div>
              </div>
              <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Lifecycle Status</span>
                <div style={{ marginTop: '4px' }}>
                  <Badge value={selectedDevice.status} />
                </div>
              </div>
            </div>

            <div style={{ padding: '12px', background: 'rgba(8, 12, 20, 0.6)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
              <div className="text-xs font-semibold text-secondary" style={{ marginBottom: '6px' }}>
                Database Credential Hygiene
              </div>
              <p className="text-xs text-muted" style={{ lineHeight: '1.5' }}>
                In accordance with <code>SECURITY.md</code>, raw pre-shared keys and HMAC secrets are <strong>never stored in plaintext</strong>. The database <code>devices.secret_hash</code> column contains only a one-way salted SHA-256 digest verifier.
              </p>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', background: 'rgba(14, 20, 34, 0.5)', borderRadius: 'var(--radius-sm)' }}>
              <span className="text-xs text-secondary">Total Verifications Logged:</span>
              <span className="font-mono text-sm font-bold text-primary">{selectedDevice.total_verifications.toLocaleString()}</span>
            </div>
          </div>
        </Modal>
      )}

      {/* Terminal Registration Modal Placeholder */}
      {isRegisterModalOpen && (
        <Modal
          isOpen={true}
          onClose={() => setIsRegisterModalOpen(false)}
          title="Register Physical Access Terminal (Prototype)"
          subtitle="Hardware Terminal Onboarding Interface"
          footer={
            <>
              <button
                onClick={() => setIsRegisterModalOpen(false)}
                className="btn btn-secondary"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  alert("Prototype Notice: Terminal registration interface is in prototype mode. Hardware device credentials and secrets must be provisioned via secure administrative provisioning.");
                  setIsRegisterModalOpen(false);
                }}
                className="btn btn-primary"
              >
                Register Terminal (Mock)
              </button>
            </>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div
              style={{
                padding: '12px 16px',
                background: 'rgba(245, 158, 11, 0.1)',
                border: '1px solid rgba(245, 158, 11, 0.3)',
                borderRadius: 'var(--radius-sm)',
                display: 'flex',
                gap: '10px',
                alignItems: 'flex-start',
              }}
            >
              <AlertTriangle size={18} color="#F59E0B" style={{ marginTop: '2px' }} />
              <div>
                <div className="text-xs font-semibold" style={{ color: '#FBBF24' }}>
                  Administrative Privilege Required
                </div>
                <div className="text-xs text-secondary" style={{ marginTop: '2px' }}>
                  Registering a hardware terminal binds a cryptographic secret to a physical access relay. Changes in this mock interface will not alter persistent backend state.
                </div>
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
                Terminal Friendly Name
              </label>
              <input
                type="text"
                className="search-input"
                style={{ width: '100%' }}
                placeholder="e.g. North Gate RFID & Biometric Portal"
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
                Hardware Device Identifier
              </label>
              <input
                type="text"
                className="search-input font-mono"
                style={{ width: '100%' }}
                placeholder="e.g. esp32-terminal-north-gate"
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
                Physical Installation Location
              </label>
              <input
                type="text"
                className="search-input"
                style={{ width: '100%' }}
                placeholder="e.g. Building A, Floor 2, Server Room"
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
                Authentication Protocol
              </label>
              <select
                className="search-input"
                style={{ width: '100%', cursor: 'pointer' }}
                defaultValue="HMAC-SHA256"
              >
                <option value="HMAC-SHA256">Scheme A: HMAC-SHA256 (Anti-Replay Nonce + Timestamp)</option>
                <option value="Pre-Shared Key">Scheme B: Pre-Shared Secret Key (Constrained MCU)</option>
              </select>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
