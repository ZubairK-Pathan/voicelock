import React, { useState } from 'react';
import {
  ShieldAlert,
  Info,
} from 'lucide-react';
import { SearchBar } from '../common/SearchBar';
import { Badge } from '../common/Badge';
import { Modal } from '../common/Modal';
import { MOCK_SECURITY_EVENTS } from '../../data/mockData';
import type { SecurityEvent, EventSeverity } from '../../types';

export const SecurityEventsPage: React.FC = () => {
  const [events] = useState<SecurityEvent[]>(MOCK_SECURITY_EVENTS);
  const [search, setSearch] = useState('');
  const [severityFilter, setSeverityFilter] = useState<'all' | EventSeverity>('all');
  const [selectedEvent, setSelectedEvent] = useState<SecurityEvent | null>(null);

  const filteredEvents = events.filter((evt) => {
    const matchesSearch =
      evt.event_type.toLowerCase().includes(search.toLowerCase()) ||
      evt.details.toLowerCase().includes(search.toLowerCase()) ||
      evt.source.toLowerCase().includes(search.toLowerCase()) ||
      (evt.speaker_id && evt.speaker_id.toLowerCase().includes(search.toLowerCase())) ||
      (evt.device_id && evt.device_id.toLowerCase().includes(search.toLowerCase()));
    const matchesSeverity =
      severityFilter === 'all' || evt.severity === severityFilter;
    return matchesSearch && matchesSeverity;
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
            VoiceLock security logs capture atomic challenge lifecycle events, HMAC nonce replay detections, and biometric threshold evaluations. All timestamps are UTC-synchronized.
          </span>
        </div>
      </div>

      {/* Filter Bar */}
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
            placeholder="Search by event type, IP, device, or details..."
            count={filteredEvents.length}
          />
          <div style={{ display: 'flex', gap: '6px' }}>
            {(['all', 'critical', 'high', 'medium', 'low'] as const).map((sev) => (
              <button
                key={sev}
                onClick={() => setSeverityFilter(sev)}
                className="btn btn-secondary"
                style={{
                  padding: '6px 12px',
                  fontSize: '12px',
                  textTransform: 'capitalize',
                  borderColor:
                    severityFilter === sev
                      ? 'var(--color-brand)'
                      : 'var(--border-subtle)',
                  background:
                    severityFilter === sev
                      ? 'rgba(59, 130, 246, 0.12)'
                      : 'var(--bg-surface)',
                  color:
                    severityFilter === sev
                      ? '#FFFFFF'
                      : 'var(--text-secondary)',
                }}
              >
                {sev}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Audit Log Table */}
      <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
        <div className="table-container">
          <table className="enterprise-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Event Type</th>
                <th>Severity</th>
                <th>Network / Source</th>
                <th>Related Identity / Device</th>
                <th>Details</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.length > 0 ? (
                filteredEvents.map((evt) => (
                  <tr key={evt.id}>
                    <td className="font-mono text-xs text-muted" style={{ whiteSpace: 'nowrap' }}>
                      {evt.timestamp}
                    </td>
                    <td>
                      <span className="font-mono text-xs font-semibold text-primary">
                        {evt.event_type}
                      </span>
                    </td>
                    <td>
                      <Badge value={evt.severity} />
                    </td>
                    <td className="font-mono text-xs text-secondary">
                      {evt.source}
                    </td>
                    <td>
                      {evt.speaker_id && (
                        <div className="text-xs text-primary font-medium">
                          Speaker: {evt.speaker_id}
                        </div>
                      )}
                      {evt.device_id && (
                        <div className="font-mono text-xs text-muted">
                          Terminal: {evt.device_id}
                        </div>
                      )}
                      {!evt.speaker_id && !evt.device_id && (
                        <span className="text-xs text-muted">—</span>
                      )}
                    </td>
                    <td style={{ maxWidth: '360px' }}>
                      <p
                        className="text-xs text-secondary"
                        style={{
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {evt.details}
                      </p>
                    </td>
                    <td>
                      <button
                        onClick={() => setSelectedEvent(evt)}
                        className="btn btn-secondary"
                        style={{ padding: '4px 10px', fontSize: '12px' }}
                      >
                        Inspect
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} style={{ textAlign: 'center', padding: '48px 20px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                      <ShieldAlert size={32} color="var(--text-muted)" />
                      <div className="text-sm font-semibold text-primary">No matching security events found</div>
                      <p className="text-xs text-muted">
                        No events matched your search query "{search}".
                      </p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Event Details Modal */}
      {selectedEvent && (
        <Modal
          isOpen={true}
          onClose={() => setSelectedEvent(null)}
          title={`Security Event: ${selectedEvent.event_type}`}
          subtitle={`Event ID: ${selectedEvent.id} | Timestamp: ${selectedEvent.timestamp}`}
          footer={
            <button
              onClick={() => setSelectedEvent(null)}
              className="btn btn-secondary"
            >
              Close
            </button>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Severity Level</span>
                <div style={{ marginTop: '4px' }}>
                  <Badge value={selectedEvent.severity} />
                </div>
              </div>
              <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Event Source / Origin</span>
                <div className="font-mono text-xs font-semibold text-primary" style={{ marginTop: '4px' }}>
                  {selectedEvent.source}
                </div>
              </div>
            </div>

            <div style={{ padding: '14px', background: 'rgba(8, 12, 20, 0.7)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-sm)' }}>
              <span className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
                Event Log Payload Details:
              </span>
              <p className="text-xs text-primary font-mono" style={{ lineHeight: '1.6' }}>
                {selectedEvent.details}
              </p>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div style={{ padding: '10px 12px', background: 'rgba(14, 20, 34, 0.4)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Associated Speaker</span>
                <div className="text-xs font-semibold text-secondary" style={{ marginTop: '2px' }}>
                  {selectedEvent.speaker_id || 'N/A (Hardware / Network Event)'}
                </div>
              </div>
              <div style={{ padding: '10px 12px', background: 'rgba(14, 20, 34, 0.4)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Associated Terminal</span>
                <div className="font-mono text-xs font-semibold text-secondary" style={{ marginTop: '2px' }}>
                  {selectedEvent.device_id || 'N/A (Console Action)'}
                </div>
              </div>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
