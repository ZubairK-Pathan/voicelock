import React from 'react';
import {
  Info,
  Lock,
  Database,
} from 'lucide-react';
import { Badge } from '../ui/Badge';
import { useAuth } from '../../context/useAuth';

export const SecurityEventsPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

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
            The enterprise security audit log is restricted to verified administrators.
            Standard operators cannot inspect system security events or threat telemetry.
          </p>
        </div>
      </div>
    );
  }

  const auditTaxonomy = [
    {
      type: 'admin_action',
      label: 'Administrative Actions',
      severity: 'low',
      description: 'Account-to-speaker identity link and unlink operations with actor UID audit bindings.',
      status: 'Active (Journaled in PostgreSQL)',
    },
    {
      type: 'rate_limit_exceeded',
      label: 'Rate Limiting Violations',
      severity: 'medium',
      description: 'Sliding-window threshold exceedance across verification or challenge endpoints.',
      status: 'Enforced in Memory',
    },
    {
      type: 'hmac_nonce_replay',
      label: 'HMAC Nonce Replay Attacks',
      severity: 'high',
      description: 'Detected duplicate nonce consumption on physical access terminal requests.',
      status: 'Enforced in Memory',
    },
    {
      type: 'unauthorized_access',
      label: 'Unauthorized Speaker Claims',
      severity: 'high',
      description: 'Ordinary operators attempting verification against unassigned speaker identities.',
      status: 'Blocked at Database Layer',
    },
    {
      type: 'payload_too_large',
      label: 'Upload Size Violations',
      severity: 'low',
      description: 'Streaming audio bodies exceeding MAX_AUDIO_SIZE_BYTES (10MB limit).',
      status: 'Blocked at ASGI Layer',
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Banner Notice */}
      <div
        className="card"
        style={{
          background: 'rgba(59, 130, 246, 0.08)',
          borderLeft: '4px solid var(--color-brand)',
          padding: '16px 20px',
        }}
      >
        <div style={{ display: 'flex', gap: '14px', alignItems: 'flex-start' }}>
          <Info size={20} color="#60A5FA" style={{ flexShrink: 0, marginTop: '2px' }} />
          <div>
            <div className="text-sm font-semibold text-primary">
              Enterprise Security Journal — Ingestion Active
            </div>
            <p className="text-xs text-secondary" style={{ marginTop: '4px', lineHeight: 1.6 }}>
              VoiceLock journals security-critical incidents directly to the persistent database table <code className="font-mono text-primary">security_events</code>. All administrative identity links and unlinks from Increment 2A/2B are committed atomically in the same transaction.
            </p>
          </div>
        </div>
      </div>

      {/* Deliberate Unintegrated Status Card */}
      <div
        className="card"
        style={{
          padding: '36px 24px',
          textAlign: 'center',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '14px',
          background: 'rgba(14, 20, 34, 0.4)',
          border: '1px dashed rgba(255, 255, 255, 0.1)',
        }}
      >
        <div
          style={{
            width: '48px',
            height: '48px',
            borderRadius: '50%',
            background: 'rgba(59, 130, 246, 0.12)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#60A5FA',
          }}
        >
          <Database size={24} />
        </div>
        <div style={{ maxWidth: '540px' }}>
          <h3 className="text-base font-semibold text-primary">
            Audit Stream Query API Provisioning in Progress
          </h3>
          <p className="text-xs text-secondary" style={{ marginTop: '6px', lineHeight: 1.6 }}>
            The backend audit repository and database migration are active, but the authenticated read endpoint for streaming and searching <code className="font-mono">security_events</code> is scheduled for Increment 4. Prototype mock events have been retired to preserve enterprise data integrity.
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px', marginTop: '6px' }}>
          <Badge variant="success">DB Table: security_events</Badge>
          <Badge variant="default">Alembic Migration: Applied</Badge>
          <Badge variant="secondary">Zero Mock Records</Badge>
        </div>
      </div>

      {/* Configured Audit Policy Taxonomy Table */}
      <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border-subtle)' }}>
          <h3 className="text-sm font-semibold text-primary" style={{ margin: 0 }}>
            Configured Audit Event Taxonomy (Database Policy)
          </h3>
          <p className="text-xs text-muted" style={{ margin: '2px 0 0 0' }}>
            Event classifications actively recognized and handled by the VoiceLock security model
          </p>
        </div>
        <div className="table-container">
          <table className="enterprise-table">
            <thead>
              <tr>
                <th>Event Taxonomy Type</th>
                <th>Classification</th>
                <th>Severity</th>
                <th>Security Boundary & Description</th>
                <th>Enforcement Layer</th>
              </tr>
            </thead>
            <tbody>
              {auditTaxonomy.map((item) => (
                <tr key={item.type}>
                  <td>
                    <span className="font-mono text-xs font-semibold text-primary">
                      {item.type}
                    </span>
                  </td>
                  <td>
                    <div className="text-xs font-semibold text-primary">{item.label}</div>
                  </td>
                  <td>
                    <Badge variant={item.severity === 'high' ? 'destructive' : item.severity === 'medium' ? 'warning' : 'secondary'}>
                      {item.severity.toUpperCase()}
                    </Badge>
                  </td>
                  <td>
                    <div className="text-xs text-secondary" style={{ maxWidth: '420px', lineHeight: 1.4 }}>
                      {item.description}
                    </div>
                  </td>
                  <td>
                    <span className="font-mono text-xs text-muted">
                      {item.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
