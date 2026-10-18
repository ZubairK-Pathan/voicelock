import React, { useState, useMemo } from 'react';
import {
  Users,
  UserPlus,
  FileAudio,
  Key,
  Info,
  AlertCircle,
} from 'lucide-react';
import { SearchBar } from '../common/SearchBar';
import { Badge } from '../common/Badge';
import { Modal } from '../common/Modal';
import { MOCK_SPEAKERS } from '../../data/mockData';
import type { Speaker, EntityStatus } from '../../types';

export const SpeakersPage: React.FC = () => {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | EntityStatus>('all');
  const [selectedSpeaker, setSelectedSpeaker] = useState<Speaker | null>(null);
  const [isEnrollModalOpen, setIsEnrollModalOpen] = useState(false);

  const filteredSpeakers = useMemo(() => {
    return MOCK_SPEAKERS.filter((speaker) => {
      const matchesSearch =
        speaker.name.toLowerCase().includes(search.toLowerCase()) ||
        speaker.speaker_id.toLowerCase().includes(search.toLowerCase()) ||
        speaker.department.toLowerCase().includes(search.toLowerCase());
      const matchesStatus =
        statusFilter === 'all' || speaker.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [search, statusFilter]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Page Actions & Search Header */}
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
            placeholder="Search by name, ID, or department..."
            count={filteredSpeakers.length}
          />
          {/* Status Filter Buttons */}
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
          onClick={() => setIsEnrollModalOpen(true)}
          className="btn btn-primary"
        >
          <UserPlus size={16} /> Enroll New Speaker
        </button>
      </div>

      {/* Speakers Table */}
      <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
        <div className="table-container">
          <table className="enterprise-table">
            <thead>
              <tr>
                <th>Speaker Identity</th>
                <th>Department</th>
                <th>Status</th>
                <th>Biometric Samples</th>
                <th>Clearance Tier</th>
                <th>User UID Binding</th>
                <th>Last Verified</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredSpeakers.length > 0 ? (
                filteredSpeakers.map((speaker) => (
                  <tr key={speaker.id}>
                    <td>
                      <div className="font-semibold text-primary">{speaker.name}</div>
                      <div className="font-mono text-xs text-muted">id: {speaker.speaker_id}</div>
                    </td>
                    <td className="text-secondary">{speaker.department}</td>
                    <td>
                      <Badge value={speaker.status} />
                    </td>
                    <td>
                      <div className="font-mono text-xs text-primary font-medium">
                        {speaker.sample_count} audio files
                      </div>
                      <div className="text-xs text-muted font-mono">
                        {speaker.embedding_dim}-dim vector
                      </div>
                    </td>
                    <td>
                      <span className="text-xs font-medium text-secondary">
                        {speaker.security_clearance}
                      </span>
                    </td>
                    <td>
                      {speaker.firebase_uid ? (
                        <div className="font-mono text-xs text-secondary" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                          <Key size={11} color="#60A5FA" /> {speaker.firebase_uid}
                        </div>
                      ) : (
                        <span className="text-xs text-muted italic">Unmapped</span>
                      )}
                    </td>
                    <td className="font-mono text-xs text-muted">
                      {speaker.last_verified_at}
                    </td>
                    <td>
                      <button
                        onClick={() => setSelectedSpeaker(speaker)}
                        className="btn btn-secondary"
                        style={{ padding: '4px 10px', fontSize: '12px' }}
                      >
                        Inspect Voiceprint
                      </button>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', padding: '48px 20px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                      <Users size={32} color="var(--text-muted)" />
                      <div className="text-sm font-semibold text-primary">No speaker identities found</div>
                      <p className="text-xs text-muted">
                        No enrolled speakers matched your query "{search}". Try searching by another keyword.
                      </p>
                      <button
                        onClick={() => {
                          setSearch('');
                          setStatusFilter('all');
                        }}
                        className="btn btn-secondary"
                        style={{ marginTop: '8px', fontSize: '12px' }}
                      >
                        Clear Filters
                      </button>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Speaker Details Modal */}
      {selectedSpeaker && (
        <Modal
          isOpen={true}
          onClose={() => setSelectedSpeaker(null)}
          title={`Speaker Voiceprint: ${selectedSpeaker.name}`}
          subtitle={`Speaker ID: ${selectedSpeaker.speaker_id} | Enrolled: ${selectedSpeaker.created_at}`}
          footer={
            <button
              onClick={() => setSelectedSpeaker(null)}
              className="btn btn-secondary"
            >
              Close
            </button>
          }
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Acoustic Model</span>
                <div className="font-mono text-sm font-semibold text-primary" style={{ marginTop: '2px' }}>
                  ECAPA-TDNN (VoxCeleb)
                </div>
              </div>
              <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Embedding Dimensions</span>
                <div className="font-mono text-sm font-semibold text-primary" style={{ marginTop: '2px' }}>
                  192 dimensions
                </div>
              </div>
              <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Enrollment Utterances</span>
                <div className="font-mono text-sm font-semibold text-primary" style={{ marginTop: '2px' }}>
                  {selectedSpeaker.sample_count} Clean Utterances
                </div>
              </div>
              <div style={{ padding: '12px', background: 'rgba(14, 20, 34, 0.6)', borderRadius: 'var(--radius-sm)' }}>
                <span className="text-xs text-muted">Lifecycle Status</span>
                <div style={{ marginTop: '4px' }}>
                  <Badge value={selectedSpeaker.status} />
                </div>
              </div>
            </div>

            {/* Simulated Voiceprint Vector Visualization */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span className="text-xs font-semibold text-secondary">
                  Voiceprint Embedding Vector (192-d Sample Preview)
                </span>
                <span className="text-xs font-mono text-muted">L2 Normalized</span>
              </div>
              <div
                style={{
                  background: 'rgba(8, 12, 20, 0.8)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '12px',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: '#60A5FA',
                  maxHeight: '110px',
                  overflowY: 'auto',
                  lineHeight: '1.6',
                }}
              >
                [0.0842, -0.1942, 0.4419, 0.0125, -0.2819, 0.1502, 0.0891, -0.0418, 0.3291, -0.1194, 0.0541, 0.2291, -0.1802, 0.0921, 0.1189, -0.0712, 0.2891, 0.0041, -0.1542, 0.3812, 0.0912, -0.0123, 0.1824, -0.0941, 0.2190, ... +167 dimensions]
              </div>
            </div>

            <div style={{ padding: '10px 14px', background: 'rgba(59, 130, 246, 0.08)', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(59, 130, 246, 0.2)', display: 'flex', gap: '10px', alignItems: 'center' }}>
              <Info size={16} color="#60A5FA" />
              <span className="text-xs text-secondary">
                This voice identity is authorized to verify at physical access terminals configured for {selectedSpeaker.security_clearance}.
              </span>
            </div>
          </div>
        </Modal>
      )}

      {/* Enrollment Placeholder Modal */}
      {isEnrollModalOpen && (
        <Modal
          isOpen={true}
          onClose={() => setIsEnrollModalOpen(false)}
          title="Enroll New Speaker Identity (Prototype Interface)"
          subtitle="Biometric Enrollment Placeholder — VoiceLock Enterprise"
          footer={
            <>
              <button
                onClick={() => setIsEnrollModalOpen(false)}
                className="btn btn-secondary"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  alert("Prototype Notice: Real biometric enrollment requires multi-utterance 16kHz audio capture and will be integrated with the FastAPI backend in Milestone 4B/4C.");
                  setIsEnrollModalOpen(false);
                }}
                className="btn btn-primary"
              >
                Confirm Mock Enrollment
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
              <AlertCircle size={18} color="#F59E0B" style={{ marginTop: '2px' }} />
              <div>
                <div className="text-xs font-semibold" style={{ color: '#FBBF24' }}>
                  Decoupled Prototype Mode
                </div>
                <div className="text-xs text-secondary" style={{ marginTop: '2px' }}>
                  This form demonstrates the speaker enrollment workflow. No changes will be written to the database until the API endpoint is bound.
                </div>
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
                Full Legal Name
              </label>
              <input
                type="text"
                className="search-input"
                style={{ width: '100%' }}
                placeholder="e.g. Zainab Ali"
                defaultValue=""
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
                Speaker Identifier (Alphanumeric)
              </label>
              <input
                type="text"
                className="search-input font-mono"
                style={{ width: '100%' }}
                placeholder="e.g. Zainab"
                defaultValue=""
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
                Department / Access Group
              </label>
              <input
                type="text"
                className="search-input"
                style={{ width: '100%' }}
                placeholder="e.g. Embedded Security Systems"
                defaultValue=""
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-secondary" style={{ display: 'block', marginBottom: '6px' }}>
                Security Clearance Level
              </label>
              <select
                className="search-input"
                style={{ width: '100%', cursor: 'pointer' }}
                defaultValue="Tier 1 - Standard"
              >
                <option value="Tier 1 - Standard">Tier 1 - Standard Access</option>
                <option value="Tier 2 - Restricted">Tier 2 - Restricted Datacenter</option>
                <option value="Tier 3 - Critical">Tier 3 - Critical Core Operations</option>
              </select>
            </div>

            <div style={{ padding: '16px', background: 'rgba(14, 20, 34, 0.5)', border: '1px dashed var(--border-subtle)', borderRadius: 'var(--radius-sm)', textAlign: 'center' }}>
              <FileAudio size={24} color="#60A5FA" style={{ margin: '0 auto 8px' }} />
              <div className="text-xs font-semibold text-primary">Required Audio Utterances (3 to 5 Files)</div>
              <p className="text-xs text-muted" style={{ marginTop: '4px' }}>
                16,000 Hz, 16-bit PCM Mono audio format normalized with peak [-1, 1]
              </p>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
};
