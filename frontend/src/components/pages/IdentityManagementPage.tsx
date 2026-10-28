import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  UserCheck,
  RefreshCw,
  AlertCircle,
  AlertTriangle,
  Lock,
  Plus,
  Unlink,
  CheckCircle2,
  Database,
  Search,
  Users,
} from 'lucide-react';
import { Modal } from '../common/Modal';
import { Badge } from '../common/Badge';
import { useAuth } from '../../context/useAuth';
import { apiClient } from '../../lib/apiClient';
import type {
  UserSpeakerMappingItem,
  UnmappedSpeakerItem,
} from '../../types';

export const IdentityManagementPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  // Data state
  const [mappings, setMappings] = useState<UserSpeakerMappingItem[]>([]);
  const [unmappedSpeakers, setUnmappedSpeakers] = useState<UnmappedSpeakerItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(() => Boolean(user?.role === 'admin'));
  const [error, setError] = useState<string | null>(null);
  const [successNotice, setSuccessNotice] = useState<string | null>(null);
  const [search, setSearch] = useState<string>('');
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);

  // Link Modal state
  const [isLinkModalOpen, setIsLinkModalOpen] = useState<boolean>(false);
  const [formUid, setFormUid] = useState<string>('');
  const [formSpeakerId, setFormSpeakerId] = useState<string>('');
  const [formNotes, setFormNotes] = useState<string>('');
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmittingLink, setIsSubmittingLink] = useState<boolean>(false);

  // Unlink Modal state
  const [mappingToUnlink, setMappingToUnlink] = useState<UserSpeakerMappingItem | null>(null);
  const [unlinkError, setUnlinkError] = useState<string | null>(null);
  const [isSubmittingUnlink, setIsSubmittingUnlink] = useState<boolean>(false);

  const handleRefresh = useCallback(() => {
    setIsLoading(true);
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  // Fetch mappings and unmapped speakers
  useEffect(() => {
    if (!isAdmin) {
      return;
    }

    let ignore = false;

    async function loadData() {
      try {
        const [mappingsRes, unmappedRes] = await Promise.all([
          apiClient.getAdminMappings(),
          apiClient.getUnmappedSpeakers(),
        ]);

        if (ignore) return;

        if (mappingsRes.ok && mappingsRes.data) {
          setMappings(mappingsRes.data.mappings || []);
          setError(null);
        } else {
          if (mappingsRes.status === 401) {
            setError('Your session has expired. Please sign in again with an administrator account.');
          } else if (mappingsRes.status === 403) {
            setError('Administrative privileges are required to inspect user-to-speaker mappings.');
          } else {
            setError(mappingsRes.error || 'Failed to load identity mappings from server.');
          }
          setMappings([]);
        }

        if (unmappedRes.ok && unmappedRes.data) {
          setUnmappedSpeakers(unmappedRes.data.unmapped_speakers || []);
        } else {
          setUnmappedSpeakers([]);
        }
      } catch {
        if (!ignore) {
          setError('Network failure while communicating with the identity management API.');
          setMappings([]);
          setUnmappedSpeakers([]);
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    loadData();

    return () => {
      ignore = true;
    };
  }, [isAdmin, refreshTrigger]);

  // Form submission: Link UID to Speaker
  const handleCreateMapping = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanUid = formUid.trim();
    const cleanSpeaker = formSpeakerId.trim();

    if (!cleanUid) {
      setFormError('Firebase User UID is required.');
      return;
    }

    if (!cleanSpeaker) {
      setFormError('Please select an eligible enrolled speaker.');
      return;
    }

    setFormError(null);
    setIsSubmittingLink(true);

    try {
      const response = await apiClient.createAdminMapping({
        firebase_uid: cleanUid,
        speaker_id: cleanSpeaker,
        notes: formNotes.trim() || undefined,
      });

      if (response.ok && response.data) {
        setIsLinkModalOpen(false);
        setFormUid('');
        setFormSpeakerId('');
        setFormNotes('');
        setSuccessNotice(response.data.message || `Successfully linked UID '${cleanUid}' to '${cleanSpeaker}'.`);
        handleRefresh();
      } else {
        if (response.status === 409) {
          setFormError(
            response.error || 'Conflict: This Firebase account or speaker identity is already mapped.'
          );
        } else if (response.status === 403) {
          setFormError('Access denied: Administrator privileges required to create identity mappings.');
        } else if (response.status === 401) {
          setFormError('Session expired. Please re-authenticate.');
        } else {
          setFormError(response.error || 'Failed to create identity mapping.');
        }
      }
    } catch {
      setFormError('Network communication failure while creating mapping.');
    } finally {
      setIsSubmittingLink(false);
    }
  };

  // Unlink submission
  const handleConfirmUnlink = async () => {
    if (!mappingToUnlink) return;

    setUnlinkError(null);
    setIsSubmittingUnlink(true);

    try {
      const response = await apiClient.deleteAdminMapping(mappingToUnlink.id);

      if (response.ok && response.data) {
        const deletedUid = mappingToUnlink.firebase_uid;
        const deletedSpeaker = mappingToUnlink.speaker_id;
        setMappingToUnlink(null);
        setSuccessNotice(
          response.data.message || `Successfully unlinked account '${deletedUid}' from speaker '${deletedSpeaker}'.`
        );
        handleRefresh();
      } else {
        if (response.status === 403) {
          setUnlinkError('Access denied: Administrator privileges required to unlink identities.');
        } else if (response.status === 401) {
          setUnlinkError('Session expired. Please re-authenticate.');
        } else {
          setUnlinkError(response.error || 'Failed to delete identity mapping.');
        }
      }
    } catch {
      setUnlinkError('Network communication failure while unlinking mapping.');
    } finally {
      setIsSubmittingUnlink(false);
    }
  };

  // Filtered mappings
  const filteredMappings = useMemo(() => {
    if (!search.trim()) return mappings;
    const query = search.trim().toLowerCase();
    return mappings.filter(
      (m) =>
        m.firebase_uid.toLowerCase().includes(query) ||
        m.speaker_id.toLowerCase().includes(query) ||
        (m.speaker_name && m.speaker_name.toLowerCase().includes(query)) ||
        (m.assigned_by && m.assigned_by.toLowerCase().includes(query))
    );
  }, [mappings, search]);

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
          maxWidth: '600px',
          margin: '40px auto',
        }}
      >
        <div
          style={{
            width: '56px',
            height: '56px',
            borderRadius: 'var(--radius-md)',
            background: 'rgba(239, 68, 68, 0.12)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            border: '1px solid rgba(239, 68, 68, 0.3)',
          }}
        >
          <Lock size={28} color="#EF4444" />
        </div>
        <div>
          <h2 className="text-lg font-bold text-primary">Administrator Authorization Required</h2>
          <p className="text-sm text-secondary" style={{ marginTop: '8px', lineHeight: '1.6' }}>
            The Identity Management panel is strictly restricted to verified system administrators.
            Ordinary operator accounts cannot inspect, link, or revoke speaker identity mappings.
          </p>
        </div>
        <div
          className="badge badge-revoked"
          style={{ marginTop: '8px', padding: '6px 14px', fontSize: '12px' }}
        >
          Access Level: {user ? user.role.toUpperCase() : 'UNAUTHENTICATED'} (Restricted)
        </div>
      </div>
    );
  }

  return (
    <div className="admin-data-page identity-page">
      {/* Success Notification Banner */}
      {successNotice && (
        <div
          className="card"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 18px',
            background: 'rgba(16, 185, 129, 0.1)',
            border: '1px solid rgba(16, 185, 129, 0.3)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <CheckCircle2 size={18} color="#10B981" />
            <span className="text-sm font-medium" style={{ color: '#34D399' }}>
              {successNotice}
            </span>
          </div>
          <button
            onClick={() => setSuccessNotice(null)}
            className="btn btn-secondary"
            style={{ padding: '4px 8px', fontSize: '11px' }}
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Control Header: Search, Actions, Counters */}
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
          <div className="search-input-wrapper">
            <Search size={15} color="var(--text-muted)" className="search-icon" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by UID or speaker ID..."
              className="search-input"
            />
          </div>

          {!isLoading && !error && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="badge badge-active">
                <UserCheck size={12} />
                {filteredMappings.length} Mapped {filteredMappings.length === 1 ? 'Account' : 'Accounts'}
              </span>
              <span className="badge badge-prototype">
                <Users size={12} />
                {unmappedSpeakers.length} Unmapped Available
              </span>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={() => {
              setFormError(null);
              setIsLinkModalOpen(true);
            }}
            className="btn btn-primary"
            style={{ fontSize: '13px', padding: '8px 16px' }}
          >
            <Plus size={15} />
            Link Account
          </button>

          <button
            onClick={handleRefresh}
            disabled={isLoading}
            className="btn btn-secondary"
            style={{ fontSize: '13px', padding: '8px 14px' }}
            title="Refresh Identity Mappings"
          >
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Error State Banner */}
      {error && (
        <div
          className="card"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            padding: '16px 20px',
            background: 'rgba(239, 68, 68, 0.08)',
            border: '1px solid rgba(239, 68, 68, 0.25)',
          }}
        >
          <AlertCircle size={20} color="#EF4444" style={{ flexShrink: 0 }} />
          <div style={{ flex: 1 }}>
            <div className="text-sm font-semibold" style={{ color: '#F87171' }}>
              Failed to Retrieve Identity Mappings
            </div>
            <div className="text-xs text-muted" style={{ marginTop: '2px' }}>
              {error}
            </div>
          </div>
          <button onClick={handleRefresh} className="btn btn-secondary" style={{ fontSize: '12px', padding: '6px 12px' }}>
            Retry
          </button>
        </div>
      )}

      {/* Loading State */}
      {isLoading && (
        <div
          className="card"
          style={{
            padding: '60px 20px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '14px',
          }}
        >
          <RefreshCw size={24} className="animate-spin" color="var(--color-brand)" />
          <span className="text-sm font-mono text-secondary">
            Loading identity mappings and speaker registry...
          </span>
        </div>
      )}

      {/* Empty State */}
      {!isLoading && !error && mappings.length === 0 && (
        <div
          className="card"
          style={{
            padding: '60px 20px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            gap: '16px',
          }}
        >
          <div
            style={{
              width: '56px',
              height: '56px',
              borderRadius: 'var(--radius-md)',
              background: 'rgba(59, 130, 246, 0.1)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '1px solid rgba(59, 130, 246, 0.25)',
            }}
          >
            <UserCheck size={26} color="var(--color-brand)" />
          </div>
          <div>
            <h3 className="text-base font-bold text-primary">No Identity Mappings Configured</h3>
            <p className="text-xs text-muted" style={{ maxWidth: '440px', marginTop: '6px', lineHeight: '1.5' }}>
              No Firebase user accounts are currently bound to enrolled voice identities.
              Click &quot;Link Account&quot; to associate an authenticated user with an enrolled speaker identity.
            </p>
          </div>
          <button
            onClick={() => {
              setFormError(null);
              setIsLinkModalOpen(true);
            }}
            className="btn btn-primary"
            style={{ fontSize: '13px', padding: '8px 18px', marginTop: '4px' }}
          >
            <Plus size={15} /> Link First Account
          </button>
        </div>
      )}

      {/* Mappings Table */}
      {!isLoading && !error && mappings.length > 0 && (
        <div className="table-container">
          <table className="enterprise-table">
            <thead>
              <tr>
                <th>Firebase User UID</th>
                <th>Enrolled Speaker Identity</th>
                <th>Enrollment Details</th>
                <th>Assigned By</th>
                <th>Created (UTC)</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredMappings.map((m) => (
                <tr key={m.id}>
                  {/* Firebase UID */}
                  <td>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                      <span className="font-mono text-xs font-semibold text-primary" style={{ letterSpacing: '0.02em' }}>
                        {m.firebase_uid}
                      </span>
                      <span className="text-xs text-muted">ID #{m.id}</span>
                    </div>
                  </td>

                  {/* Speaker Identity */}
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <div
                        style={{
                          width: '30px',
                          height: '30px',
                          borderRadius: 'var(--radius-sm)',
                          background: 'rgba(59, 130, 246, 0.15)',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontWeight: 600,
                          fontSize: '12px',
                          color: '#60A5FA',
                        }}
                      >
                        {m.speaker_id.slice(0, 2).toUpperCase()}
                      </div>
                      <div>
                        <div className="font-semibold text-primary text-sm">
                          {m.speaker_id}
                        </div>
                        {m.speaker_name && (
                          <div className="text-xs text-muted">
                            {m.speaker_name}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>

                  {/* Enrollment Details */}
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Badge
                        type="status"
                        value={m.speaker_status || 'active'}
                        showDot={true}
                      />
                      <span className="text-xs text-muted font-mono" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Database size={11} /> {m.sample_count ?? 0} samples
                      </span>
                    </div>
                  </td>

                  {/* Assigned By */}
                  <td>
                    <span className="font-mono text-xs text-secondary">
                      {m.assigned_by || 'System Admin'}
                    </span>
                  </td>

                  {/* Created At */}
                  <td>
                    <span className="font-mono text-xs text-muted">
                      {m.created_at ? new Date(m.created_at).toLocaleString() : 'N/A'}
                    </span>
                  </td>

                  {/* Actions */}
                  <td style={{ textAlign: 'right' }}>
                    <button
                      onClick={() => {
                        setUnlinkError(null);
                        setMappingToUnlink(m);
                      }}
                      className="btn btn-danger"
                      style={{ padding: '5px 10px', fontSize: '11px', gap: '4px' }}
                      title={`Unlink ${m.firebase_uid} from ${m.speaker_id}`}
                    >
                      <Unlink size={12} />
                      Unlink
                    </button>
                  </td>
                </tr>
              ))}

              {filteredMappings.length === 0 && search.trim() && (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)' }}>
                    No identity mappings matched your search query &quot;{search}&quot;.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Link Account Modal */}
      <Modal
        isOpen={isLinkModalOpen}
        onClose={() => {
          if (!isSubmittingLink) {
            setIsLinkModalOpen(false);
            setFormError(null);
          }
        }}
        title="Link Firebase Account to Speaker Identity"
        subtitle="Associates an authenticated Firebase account with an enrolled biometric voiceprint."
        footer={
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', width: '100%' }}>
            <button
              type="button"
              onClick={() => setIsLinkModalOpen(false)}
              disabled={isSubmittingLink}
              className="btn btn-secondary"
            >
              Cancel
            </button>
            <button
              type="submit"
              form="link-mapping-form"
              disabled={isSubmittingLink || unmappedSpeakers.length === 0}
              className="btn btn-primary"
            >
              {isSubmittingLink ? (
                <>
                  <RefreshCw size={14} className="animate-spin" />
                  Linking...
                </>
              ) : (
                <>
                  <Plus size={14} />
                  Confirm Mapping
                </>
              )}
            </button>
          </div>
        }
      >
        <form id="link-mapping-form" onSubmit={handleCreateMapping} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {formError && (
            <div
              style={{
                padding: '10px 14px',
                borderRadius: 'var(--radius-sm)',
                background: 'rgba(239, 68, 68, 0.12)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: '#F87171',
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <AlertCircle size={15} style={{ flexShrink: 0 }} />
              <span>{formError}</span>
            </div>
          )}

          {/* Firebase UID Field */}
          <div>
            <label
              htmlFor="firebase-uid-input"
              className="text-xs font-semibold text-primary"
              style={{ display: 'block', marginBottom: '6px' }}
            >
              Firebase User UID <span style={{ color: '#EF4444' }}>*</span>
            </label>
            <input
              id="firebase-uid-input"
              type="text"
              value={formUid}
              onChange={(e) => setFormUid(e.target.value)}
              placeholder="e.g. 5xXjK9aBcDeFgHiJkLmNoPqRsTu"
              disabled={isSubmittingLink}
              required
              style={{
                width: '100%',
                padding: '9px 12px',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                fontFamily: 'monospace',
                outline: 'none',
              }}
            />
            <p className="text-xs text-muted" style={{ marginTop: '4px' }}>
              The unique UID assigned to the user by Firebase Authentication.
            </p>
          </div>

          {/* Speaker Selector Field */}
          <div>
            <label
              htmlFor="speaker-select"
              className="text-xs font-semibold text-primary"
              style={{ display: 'block', marginBottom: '6px' }}
            >
              Eligible Enrolled Speaker <span style={{ color: '#EF4444' }}>*</span>
            </label>
            {unmappedSpeakers.length > 0 ? (
              <select
                id="speaker-select"
                value={formSpeakerId}
                onChange={(e) => setFormSpeakerId(e.target.value)}
                disabled={isSubmittingLink}
                required
                style={{
                  width: '100%',
                  padding: '9px 12px',
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  outline: 'none',
                }}
              >
                <option value="">-- Select an enrolled speaker --</option>
                {unmappedSpeakers.map((s) => (
                  <option key={s.speaker_id} value={s.speaker_id}>
                    {s.speaker_id} {s.full_name ? `(${s.full_name})` : ''} — {s.sample_count} samples ({s.status})
                  </option>
                ))}
              </select>
            ) : (
              <div
                style={{
                  padding: '10px 12px',
                  borderRadius: 'var(--radius-sm)',
                  background: 'rgba(245, 158, 11, 0.1)',
                  border: '1px solid rgba(245, 158, 11, 0.25)',
                  color: '#FBBF24',
                  fontSize: '12px',
                }}
              >
                No unmapped active speakers are currently available. All enrolled speakers are already assigned to user accounts.
              </div>
            )}
            <p className="text-xs text-muted" style={{ marginTop: '4px' }}>
              Only active, enrolled speakers without an existing account mapping are eligible.
            </p>
          </div>

          {/* Administrative Notes Field */}
          <div>
            <label
              htmlFor="mapping-notes-input"
              className="text-xs font-semibold text-primary"
              style={{ display: 'block', marginBottom: '6px' }}
            >
              Administrative Notes (Optional)
            </label>
            <input
              id="mapping-notes-input"
              type="text"
              value={formNotes}
              onChange={(e) => setFormNotes(e.target.value)}
              placeholder="e.g. Primary operator workstation access"
              disabled={isSubmittingLink}
              maxLength={500}
              style={{
                width: '100%',
                padding: '9px 12px',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--text-primary)',
                fontSize: '13px',
                outline: 'none',
              }}
            />
          </div>
        </form>
      </Modal>

      {/* Unlink Confirmation Modal */}
      <Modal
        isOpen={mappingToUnlink !== null}
        onClose={() => {
          if (!isSubmittingUnlink) {
            setMappingToUnlink(null);
            setUnlinkError(null);
          }
        }}
        title="Confirm Identity Unlink"
        subtitle="Revoke account authorization binding for enrolled voiceprint."
        footer={
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', width: '100%' }}>
            <button
              type="button"
              onClick={() => setMappingToUnlink(null)}
              disabled={isSubmittingUnlink}
              className="btn btn-secondary"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleConfirmUnlink}
              disabled={isSubmittingUnlink}
              className="btn btn-danger"
            >
              {isSubmittingUnlink ? (
                <>
                  <RefreshCw size={14} className="animate-spin" />
                  Unlinking...
                </>
              ) : (
                <>
                  <Unlink size={14} />
                  Confirm Unlink
                </>
              )}
            </button>
          </div>
        }
      >
        {mappingToUnlink && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {unlinkError && (
              <div
                style={{
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-sm)',
                  background: 'rgba(239, 68, 68, 0.12)',
                  border: '1px solid rgba(239, 68, 68, 0.3)',
                  color: '#F87171',
                  fontSize: '12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                }}
              >
                <AlertCircle size={15} style={{ flexShrink: 0 }} />
                <span>{unlinkError}</span>
              </div>
            )}

            <div
              style={{
                display: 'flex',
                gap: '12px',
                padding: '14px',
                borderRadius: 'var(--radius-sm)',
                background: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.25)',
              }}
            >
              <AlertTriangle size={24} color="#EF4444" style={{ flexShrink: 0, marginTop: '2px' }} />
              <div>
                <div className="text-sm font-semibold text-primary">
                  Are you sure you want to unlink this account?
                </div>
                <div className="text-xs text-secondary" style={{ marginTop: '6px', lineHeight: '1.5' }}>
                  You are revoking the voice authorization binding between:
                </div>
                <div
                  style={{
                    margin: '8px 0',
                    padding: '8px 10px',
                    borderRadius: 'var(--radius-sm)',
                    background: 'rgba(0, 0, 0, 0.3)',
                    fontFamily: 'monospace',
                    fontSize: '12px',
                  }}
                >
                  <div>UID: <span style={{ color: '#60A5FA' }}>{mappingToUnlink.firebase_uid}</span></div>
                  <div>Speaker: <span style={{ color: '#34D399' }}>{mappingToUnlink.speaker_id}</span></div>
                </div>
              </div>
            </div>

            {/* Non-negotiable Data Safety Notice */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                padding: '10px 12px',
                borderRadius: 'var(--radius-sm)',
                background: 'rgba(16, 185, 129, 0.08)',
                border: '1px solid rgba(16, 185, 129, 0.2)',
                fontSize: '12px',
                color: '#34D399',
              }}
            >
              <Database size={15} style={{ flexShrink: 0 }} />
              <span>
                <strong>Data Safety Notice:</strong> This operation deletes only the identity mapping record.
                The enrolled speaker voiceprint, 192-dimensional ECAPA-TDNN embedding, and audio training data
                will <strong>never</strong> be deleted or altered.
              </span>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
