import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Users,
  RefreshCw,
  AlertCircle,
  Lock,
  ShieldAlert,
  Database,
  UserPlus,
  CheckCircle2,
  X,
} from 'lucide-react';
import { SearchBar } from '../common/SearchBar';
import { Badge } from '../common/Badge';
import { apiClient } from '../../lib/apiClient';
import { useAuth } from '../../context/useAuth';
import { SpeakerEnrollmentModal } from '../speakers/SpeakerEnrollmentModal';

export const SpeakersPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [speakers, setSpeakers] = useState<string[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [statusCode, setStatusCode] = useState<number | null>(null);
  const [search, setSearch] = useState<string>('');

  const [isEnrollModalOpen, setIsEnrollModalOpen] = useState<boolean>(false);
  const [enrollSuccessMessage, setEnrollSuccessMessage] = useState<string | null>(null);

  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);

  const handleRefresh = useCallback(() => {
    setIsLoading(true);
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  useEffect(() => {
    let ignore = false;

    async function loadSpeakers() {
      try {
        const response = await apiClient.getSpeakers();
        if (ignore) return;
        setStatusCode(response.status);

        if (response.ok && response.data) {
          const speakerList = response.data.registered_speakers || [];
          setSpeakers(speakerList);
          setTotalCount(response.data.count ?? speakerList.length);
          setError(null);
        } else {
          if (response.status === 401) {
            setError(
              'Your session has expired or is unauthenticated. Please sign in with a valid operator account to access the speaker registry.'
            );
          } else if (response.status === 403) {
            setError(
              'Administrative privileges are required to view the enrolled speaker registry. Ordinary operators are restricted from enumerating voice identities.'
            );
          } else {
            setError(
              response.error ||
                'Unable to load the speaker registry from the database. Please verify backend connectivity.'
            );
          }
          setSpeakers([]);
          setTotalCount(0);
        }
      } catch {
        if (!ignore) {
          setError('Network communication failed while querying the speaker registry.');
          setSpeakers([]);
          setTotalCount(0);
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    }

    loadSpeakers();

    return () => {
      ignore = true;
    };
  }, [refreshTrigger]);

  const filteredSpeakers = useMemo(() => {
    if (!search.trim()) return speakers;
    const query = search.trim().toLowerCase();
    return speakers.filter((speakerName) =>
      speakerName.toLowerCase().includes(query)
    );
  }, [speakers, search]);

  return (
    <div className="admin-data-page speakers-page">
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
            placeholder="Search enrolled speaker identities..."
            count={!isLoading && !error ? filteredSpeakers.length : undefined}
          />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {!isLoading && !error && (
            <span
              className="badge badge-active"
              style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px' }}
            >
              <Database size={13} color="var(--color-emerald)" />
              Database Registry: {totalCount} Enrolled
            </span>
          )}

          {isAdmin && (
            <button
              onClick={() => setIsEnrollModalOpen(true)}
              className="btn btn-primary"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 14px',
                fontSize: '12px',
              }}
              title="Enroll new speaker with biometric samples"
              aria-label="Enroll new speaker"
            >
              <UserPlus size={13} />
              Enroll Speaker
            </button>
          )}

          <button
            onClick={handleRefresh}
            disabled={isLoading}
            className="btn btn-secondary"
            style={{ padding: '6px 14px', fontSize: '12px' }}
            title="Refresh speaker registry from database"
            aria-label="Refresh speaker registry"
          >
            <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {/* Success Notification Banner */}
      {enrollSuccessMessage && (
        <div
          className="card"
          style={{
            padding: '12px 18px',
            borderLeft: '4px solid var(--color-emerald)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            background: 'rgba(16, 185, 129, 0.06)',
          }}
          role="status"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <CheckCircle2 size={18} color="var(--color-emerald)" style={{ flexShrink: 0 }} />
            <div className="text-xs font-semibold text-primary">
              {enrollSuccessMessage}
            </div>
          </div>
          <button
            onClick={() => setEnrollSuccessMessage(null)}
            className="modal-close-btn"
            style={{ padding: '4px' }}
            aria-label="Dismiss notification"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Loading State */}
      {isLoading && (
        <div
          className="card"
          style={{ padding: '48px 20px', textAlign: 'center' }}
          role="status"
          aria-live="polite"
          aria-busy="true"
        >
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
            <RefreshCw size={32} className="animate-spin" color="var(--color-brand)" />
            <div className="text-sm font-semibold text-primary">
              Loading speaker registry from database...
            </div>
            <p className="text-xs text-muted" style={{ maxWidth: '420px' }}>
              Querying persistent database records and verifying active ECAPA-TDNN voiceprint profiles.
            </p>
          </div>
        </div>
      )}

      {/* Recoverable Error States (401, 403, 500 / Network) */}
      {!isLoading && error && (
        <div
          className="card"
          style={{
            padding: '28px 24px',
            borderLeft: `4px solid ${
              statusCode === 401
                ? 'var(--color-amber)'
                : statusCode === 403
                ? 'var(--color-rose)'
                : 'var(--color-rose)'
            }`,
          }}
          role="alert"
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '14px' }}>
            {statusCode === 401 ? (
              <ShieldAlert size={28} color="var(--color-amber)" style={{ flexShrink: 0 }} />
            ) : statusCode === 403 ? (
              <Lock size={28} color="var(--color-rose)" style={{ flexShrink: 0 }} />
            ) : (
              <AlertCircle size={28} color="var(--color-rose)" style={{ flexShrink: 0 }} />
            )}

            <div style={{ flex: 1 }}>
              <div
                className="text-sm font-semibold"
                style={{
                  color:
                    statusCode === 401
                      ? 'var(--color-amber)'
                      : 'var(--color-rose)',
                }}
              >
                {statusCode === 401
                  ? 'Authentication Required (HTTP 401)'
                  : statusCode === 403
                  ? 'Access Restricted: Administrative Role Required (HTTP 403)'
                  : 'Registry Communication Error'}
              </div>

              <p className="text-xs text-secondary" style={{ marginTop: '6px', lineHeight: '1.6' }}>
                {error}
              </p>

              <button
                onClick={handleRefresh}
                className="btn btn-secondary"
                style={{ marginTop: '14px', fontSize: '12px' }}
              >
                <RefreshCw size={13} /> Retry Connection
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Empty Database Registry State */}
      {!isLoading && !error && speakers.length === 0 && (
        <div className="card" style={{ padding: '48px 20px', textAlign: 'center' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
            <Users size={36} color="var(--text-muted)" />
            <div className="text-sm font-semibold text-primary">
              No Enrolled Speakers in Database
            </div>
            <p className="text-xs text-muted" style={{ maxWidth: '440px' }}>
              The persistent speaker registry currently contains no active voice profiles.
              Enroll an authorized speaker identity below or run the safe database seeder to import profiles.
            </p>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginTop: '10px' }}>
              {isAdmin && (
                <button
                  onClick={() => setIsEnrollModalOpen(true)}
                  className="btn btn-primary"
                  style={{
                    fontSize: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 14px',
                  }}
                  title="Enroll new speaker with biometric samples"
                >
                  <UserPlus size={13} />
                  Enroll Speaker
                </button>
              )}
              <button
                onClick={handleRefresh}
                className="btn btn-secondary"
                style={{ fontSize: '12px' }}
              >
                <RefreshCw size={13} /> Check Database Again
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Speakers Table */}
      {!isLoading && !error && speakers.length > 0 && (
        <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
          <div className="table-container">
            <table className="enterprise-table">
              <thead>
                <tr>
                  <th style={{ width: '60px' }}>#</th>
                  <th>Speaker Identity</th>
                  <th>Biometric Registry Status</th>
                  <th>Acoustic Architecture</th>
                </tr>
              </thead>
              <tbody>
                {filteredSpeakers.length > 0 ? (
                  filteredSpeakers.map((speakerName, idx) => (
                    <tr key={speakerName}>
                      <td className="font-mono text-xs text-muted">{idx + 1}</td>
                      <td>
                        <div className="font-semibold text-primary">{speakerName}</div>
                        <div className="font-mono text-xs text-muted">
                          id: {speakerName}
                        </div>
                      </td>
                      <td>
                        <Badge value="active" label="Enrolled & Active" />
                      </td>
                      <td>
                        <div className="font-mono text-xs text-secondary">
                          SpeechBrain ECAPA-TDNN (192-d)
                        </div>
                        <div className="text-xs text-muted">
                          L2-normalized unit vector in persistent database
                        </div>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={4} style={{ textAlign: 'center', padding: '48px 20px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                        <Users size={32} color="var(--text-muted)" />
                        <div className="text-sm font-semibold text-primary">
                          No matching speaker identities
                        </div>
                        <p className="text-xs text-muted">
                          No enrolled speaker matched "{search}".
                        </p>
                        <button
                          onClick={() => setSearch('')}
                          className="btn btn-secondary"
                          style={{ marginTop: '8px', fontSize: '12px' }}
                        >
                          Clear Search
                        </button>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Biometric Speaker Enrollment Modal */}
      <SpeakerEnrollmentModal
        isOpen={isEnrollModalOpen}
        onClose={() => setIsEnrollModalOpen(false)}
        onSuccess={(newSpeakerId) => {
          setEnrollSuccessMessage(`Speaker "${newSpeakerId}" was successfully enrolled into the biometric registry.`);
          handleRefresh();
        }}
      />
    </div>
  );
};
