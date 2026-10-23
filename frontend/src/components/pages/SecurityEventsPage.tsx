import React, { useState, useEffect, useCallback, useId } from 'react';
import {
  ShieldAlert,
  RefreshCw,
  Lock,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  Filter,
  AlertTriangle,
  AlertCircle,
  Database,
} from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Alert, AlertTitle, AlertDescription } from '../ui/Alert';
import { useAuth } from '../../context/useAuth';
import { apiClient } from '../../lib/apiClient';
import type { SecurityEventItem, SecurityEventFilters } from '../../types';

function formatTimestamp(isoString: string): string {
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString;
    return d.toISOString().replace('T', ' ').substring(0, 19) + ' UTC';
  } catch {
    return isoString;
  }
}

function getSeverityBadgeVariant(severity: string): 'destructive' | 'warning' | 'secondary' | 'default' {
  switch (severity?.toLowerCase()) {
    case 'critical':
    case 'high':
      return 'destructive';
    case 'medium':
      return 'warning';
    case 'low':
      return 'secondary';
    default:
      return 'default';
  }
}

function getStatusBadgeVariant(status: string): 'destructive' | 'warning' | 'success' | 'secondary' | 'default' {
  switch (status?.toLowerCase()) {
    case 'blocked':
      return 'destructive';
    case 'detected':
      return 'warning';
    case 'resolved':
      return 'success';
    case 'logged':
      return 'secondary';
    default:
      return 'default';
  }
}

export const SecurityEventsPage: React.FC = () => {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  // State for events data and network
  const [events, setEvents] = useState<SecurityEventItem[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [refreshTrigger, setRefreshTrigger] = useState<number>(0);

  // Filter state
  const [eventType, setEventType] = useState<string>('');
  const [severity, setSeverity] = useState<string>('');
  const [status, setStatus] = useState<string>('');
  const [userId, setUserId] = useState<string>('');
  const [deviceId, setDeviceId] = useState<string>('');
  const [startTime, setStartTime] = useState<string>('');
  const [endTime, setEndTime] = useState<string>('');

  // Pagination state (cursor-based)
  const [currentCursor, setCurrentCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState<boolean>(false);

  // Accessible unique IDs for form labels
  const eventTypeId = useId();
  const severityId = useId();
  const statusId = useId();
  const userIdInputId = useId();
  const deviceIdInputId = useId();
  const startTimeId = useId();
  const endTimeId = useId();

  // Validate date range
  const isDateRangeInvalid = Boolean(
    startTime && endTime && new Date(startTime).getTime() > new Date(endTime).getTime()
  );

  const effectiveIsLoading = isLoading && !isDateRangeInvalid;

  // Active filters count
  const activeFiltersCount = [
    eventType,
    severity,
    status,
    userId.trim(),
    deviceId.trim(),
    startTime,
    endTime,
  ].filter(Boolean).length;

  const handleRefresh = useCallback(() => {
    setIsRefreshing(true);
    setRefreshTrigger((prev) => prev + 1);
  }, []);

  const handleFilterChange = (setter: (val: string) => void, val: string) => {
    setter(val);
    setCurrentCursor(null);
    setCursorHistory([]);
  };

  const handleResetFilters = () => {
    setEventType('');
    setSeverity('');
    setStatus('');
    setUserId('');
    setDeviceId('');
    setStartTime('');
    setEndTime('');
    setCurrentCursor(null);
    setCursorHistory([]);
  };

  const handleNextPage = () => {
    if (!hasMore || !nextCursor || effectiveIsLoading) return;
    setCursorHistory((prev) => [...prev, currentCursor]);
    setCurrentCursor(nextCursor);
  };

  const handlePrevPage = () => {
    if (cursorHistory.length === 0 || effectiveIsLoading) return;
    const prev = cursorHistory[cursorHistory.length - 1];
    setCursorHistory((prevList) => prevList.slice(0, -1));
    setCurrentCursor(prev);
  };

  // Main data fetching effect
  useEffect(() => {
    if (!isAdmin || isDateRangeInvalid) {
      return;
    }

    let ignore = false;

    async function fetchEvents() {
      if (refreshTrigger > 0) {
        setIsRefreshing(true);
      } else {
        setIsLoading(true);
      }
      setError(null);
      setErrorStatus(null);

      const filterPayload: SecurityEventFilters = {
        limit: 50,
        cursor: currentCursor || undefined,
        event_type: eventType || undefined,
        severity: severity || undefined,
        status: status || undefined,
        user_id: userId.trim() || undefined,
        device_id: deviceId.trim() || undefined,
        start_time: startTime ? new Date(startTime).toISOString() : undefined,
        end_time: endTime ? new Date(endTime).toISOString() : undefined,
      };

      try {
        const response = await apiClient.getSecurityEvents(filterPayload);
        if (ignore) return;

        if (response.ok && response.data) {
          setEvents(response.data.events || []);
          setNextCursor(response.data.next_cursor || null);
          setHasMore(Boolean(response.data.has_more));
          setError(null);
          setErrorStatus(null);
        } else {
          setErrorStatus(response.status);
          if (response.status === 401) {
            setError('Your operator session has expired or authentication is invalid. Please sign in again.');
          } else if (response.status === 403) {
            setError('Administrator authorization required. You do not have permission to inspect the security audit stream.');
          } else {
            setError(response.error || 'Failed to retrieve security audit events from server.');
          }
          setEvents([]);
        }
      } catch {
        if (!ignore) {
          setError('Network failure while communicating with the security audit events API.');
          setEvents([]);
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
          setIsRefreshing(false);
        }
      }
    }

    fetchEvents();

    return () => {
      ignore = true;
    };
  }, [
    isAdmin,
    isDateRangeInvalid,
    currentCursor,
    eventType,
    severity,
    status,
    userId,
    deviceId,
    startTime,
    endTime,
    refreshTrigger,
  ]);

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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Top Banner & Header */}
      <div
        className="card"
        style={{
          padding: '18px 22px',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          background: 'rgba(14, 20, 34, 0.65)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '14px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ShieldAlert size={20} color="#60A5FA" />
              <h1 className="text-base font-bold text-primary" style={{ margin: 0 }}>
                Enterprise Security Audit Log API
              </h1>
              <Badge variant="default">Audit Stream Active</Badge>
            </div>
            <p className="text-xs text-secondary" style={{ marginTop: '4px', lineHeight: 1.5 }}>
              Immutable PostgreSQL journal of authenticated security incidents, rate limiting events, replay attempts, and administrative actions.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleRefresh}
              disabled={effectiveIsLoading || isRefreshing}
              aria-label="Refresh security audit log"
            >
              <RefreshCw size={13} className={isRefreshing ? 'animate-spin' : ''} />
              {isRefreshing ? 'Refreshing...' : 'Refresh'}
            </Button>
          </div>
        </div>
      </div>

      {/* Date Range Validation Warning */}
      {isDateRangeInvalid && (
        <Alert variant="warning">
          <AlertTitle>
            <AlertTriangle size={16} /> Invalid Date Range
          </AlertTitle>
          <AlertDescription>
            The selected start date/time cannot be later than the end date/time. Please adjust the filters to resume querying.
          </AlertDescription>
        </Alert>
      )}

      {/* Error Alert with Retry */}
      {error && (
        <Alert variant="destructive">
          <AlertTitle>
            <AlertCircle size={16} /> Audit Query Failed {errorStatus ? `(HTTP ${errorStatus})` : ''}
          </AlertTitle>
          <AlertDescription style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap' }}>
            <span>{error}</span>
            <Button
              variant="destructive"
              size="sm"
              onClick={handleRefresh}
              disabled={effectiveIsLoading || isRefreshing}
            >
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      )}

      {/* Filter Controls Card */}
      <div
        className="card"
        style={{
          padding: '16px 20px',
          display: 'flex',
          flexDirection: 'column',
          gap: '14px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Filter size={15} color="#94A3B8" />
            <span className="text-xs font-semibold text-primary" style={{ textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Filter Security Telemetry
            </span>
            {activeFiltersCount > 0 && (
              <Badge variant="default">{activeFiltersCount} Active</Badge>
            )}
          </div>
          {activeFiltersCount > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleResetFilters}
              style={{ fontSize: '11px', height: '26px', padding: '0 8px' }}
            >
              <RotateCcw size={12} /> Reset Filters
            </Button>
          )}
        </div>

        {/* Filter inputs grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: '12px',
          }}
        >
          {/* Event Type Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label htmlFor={eventTypeId} className="text-xs text-muted font-mono">
              Event Type
            </label>
            <select
              id={eventTypeId}
              value={eventType}
              onChange={(e) => handleFilterChange(setEventType, e.target.value)}
              className="search-input"
              style={{ width: '100%', padding: '6px 10px', height: '34px' }}
            >
              <option value="">All Event Types</option>
              <option value="admin_action">admin_action</option>
              <option value="rate_limit_exceeded">rate_limit_exceeded</option>
              <option value="hmac_nonce_replay">hmac_nonce_replay</option>
              <option value="unauthorized_speaker_claim">unauthorized_speaker_claim</option>
              <option value="unauthorized_access">unauthorized_access</option>
              <option value="payload_too_large">payload_too_large</option>
            </select>
          </div>

          {/* Severity Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label htmlFor={severityId} className="text-xs text-muted font-mono">
              Severity
            </label>
            <select
              id={severityId}
              value={severity}
              onChange={(e) => handleFilterChange(setSeverity, e.target.value)}
              className="search-input"
              style={{ width: '100%', padding: '6px 10px', height: '34px' }}
            >
              <option value="">All Severities</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>

          {/* Status Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label htmlFor={statusId} className="text-xs text-muted font-mono">
              Status
            </label>
            <select
              id={statusId}
              value={status}
              onChange={(e) => handleFilterChange(setStatus, e.target.value)}
              className="search-input"
              style={{ width: '100%', padding: '6px 10px', height: '34px' }}
            >
              <option value="">All Statuses</option>
              <option value="blocked">Blocked</option>
              <option value="detected">Detected</option>
              <option value="logged">Logged</option>
              <option value="resolved">Resolved</option>
            </select>
          </div>

          {/* Actor UID Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label htmlFor={userIdInputId} className="text-xs text-muted font-mono">
              Actor UID
            </label>
            <input
              id={userIdInputId}
              type="text"
              placeholder="e.g. firebase-uid-..."
              value={userId}
              onChange={(e) => handleFilterChange(setUserId, e.target.value)}
              className="search-input"
              style={{ width: '100%', padding: '6px 10px', height: '34px' }}
            />
          </div>

          {/* Device ID Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label htmlFor={deviceIdInputId} className="text-xs text-muted font-mono">
              Terminal ID
            </label>
            <input
              id={deviceIdInputId}
              type="text"
              placeholder="e.g. terminal-gate-01"
              value={deviceId}
              onChange={(e) => handleFilterChange(setDeviceId, e.target.value)}
              className="search-input"
              style={{ width: '100%', padding: '6px 10px', height: '34px' }}
            />
          </div>

          {/* Start Time Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label htmlFor={startTimeId} className="text-xs text-muted font-mono">
              Start Date/Time
            </label>
            <input
              id={startTimeId}
              type="datetime-local"
              value={startTime}
              onChange={(e) => handleFilterChange(setStartTime, e.target.value)}
              className="search-input"
              style={{ width: '100%', padding: '6px 10px', height: '34px' }}
            />
          </div>

          {/* End Time Filter */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            <label htmlFor={endTimeId} className="text-xs text-muted font-mono">
              End Date/Time
            </label>
            <input
              id={endTimeId}
              type="datetime-local"
              value={endTime}
              onChange={(e) => handleFilterChange(setEndTime, e.target.value)}
              className="search-input"
              style={{ width: '100%', padding: '6px 10px', height: '34px' }}
            />
          </div>
        </div>
      </div>

      {/* Events Table Card */}
      <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
        <div className="table-container">
          <table className="enterprise-table" aria-label="Security Audit Events">
            <thead>
              <tr>
                <th scope="col">Timestamp</th>
                <th scope="col">Event Type</th>
                <th scope="col">Severity</th>
                <th scope="col">Status</th>
                <th scope="col">Actor UID</th>
                <th scope="col">Terminal</th>
                <th scope="col">Request ID</th>
                <th scope="col">Summary & Telemetry</th>
              </tr>
            </thead>
            <tbody>
              {effectiveIsLoading && events.length === 0 ? (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', padding: '36px', color: 'var(--text-muted)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                      <RefreshCw size={16} className="animate-spin" /> Querying security audit stream...
                    </div>
                  </td>
                </tr>
              ) : events.length > 0 ? (
                events.map((event) => (
                  <tr key={event.id}>
                    <td>
                      <span className="font-mono text-xs text-secondary" style={{ whiteSpace: 'nowrap' }}>
                        {formatTimestamp(event.created_at)}
                      </span>
                    </td>
                    <td>
                      <span className="font-mono text-xs font-semibold text-primary">
                        {event.event_type}
                      </span>
                    </td>
                    <td>
                      <Badge variant={getSeverityBadgeVariant(event.severity)}>
                        {event.severity?.toUpperCase()}
                      </Badge>
                    </td>
                    <td>
                      <Badge variant={getStatusBadgeVariant(event.status)}>
                        {event.status?.toUpperCase()}
                      </Badge>
                    </td>
                    <td>
                      {event.user_id ? (
                        <span
                          className="font-mono text-xs text-primary"
                          title={event.user_id}
                          style={{
                            maxWidth: '120px',
                            display: 'inline-block',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {event.user_id}
                        </span>
                      ) : (
                        <span className="text-muted text-xs">—</span>
                      )}
                    </td>
                    <td>
                      {event.device_id ? (
                        <span
                          className="font-mono text-xs text-primary"
                          title={event.device_id}
                          style={{
                            maxWidth: '120px',
                            display: 'inline-block',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {event.device_id}
                        </span>
                      ) : (
                        <span className="text-muted text-xs">—</span>
                      )}
                    </td>
                    <td>
                      {event.request_id ? (
                        <span
                          className="font-mono text-xs text-muted"
                          title={event.request_id}
                          style={{
                            maxWidth: '100px',
                            display: 'inline-block',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {event.request_id}
                        </span>
                      ) : (
                        <span className="text-muted text-xs">—</span>
                      )}
                    </td>
                    <td>
                      <div style={{ maxWidth: '360px', display: 'flex', flexDirection: 'column', gap: '3px' }}>
                        <span className="text-xs text-secondary" style={{ lineHeight: 1.4 }}>
                          {event.details || '—'}
                        </span>
                        {event.metadata && Object.keys(event.metadata).length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '2px' }}>
                            {Object.entries(event.metadata)
                              .filter(([k]) => {
                                const lk = k.toLowerCase();
                                return !lk.includes('secret') && !lk.includes('token') && !lk.includes('password') && !lk.includes('key');
                              })
                              .map(([k, v]) => (
                                <span
                                  key={k}
                                  className="font-mono text-xs"
                                  style={{
                                    background: 'rgba(255, 255, 255, 0.05)',
                                    padding: '1px 5px',
                                    borderRadius: '3px',
                                    color: 'var(--text-muted)',
                                    fontSize: '10px',
                                    border: '1px solid var(--border-subtle)',
                                  }}
                                >
                                  {k}: {String(v)}
                                </span>
                              ))}
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-muted)' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                      <Database size={32} color="var(--text-muted)" />
                      <div className="text-sm font-semibold text-primary">No Security Events Found</div>
                      <div className="text-xs text-secondary" style={{ maxWidth: '380px' }}>
                        {activeFiltersCount > 0
                          ? 'No audit events matched your active filter parameters. Adjust your filters or reset them to query all telemetry.'
                          : 'No security events are currently recorded in the database.'}
                      </div>
                      {activeFiltersCount > 0 && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={handleResetFilters}
                          style={{ marginTop: '8px' }}
                        >
                          <RotateCcw size={13} /> Reset Filter Criteria
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Cursor Pagination Controls Footer */}
        <div
          style={{
            padding: '12px 20px',
            borderTop: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '12px',
            background: 'rgba(14, 20, 34, 0.4)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span className="text-xs text-secondary">
              Page {cursorHistory.length + 1}
            </span>
            <span className="text-xs text-muted">•</span>
            <span className="text-xs text-secondary">
              Showing {events.length} event{events.length === 1 ? '' : 's'}
              {hasMore ? ' (more available)' : ''}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Button
              variant="secondary"
              size="sm"
              onClick={handlePrevPage}
              disabled={cursorHistory.length === 0 || effectiveIsLoading}
              aria-label="Previous page of security events"
            >
              <ChevronLeft size={14} /> Previous
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleNextPage}
              disabled={!hasMore || !nextCursor || effectiveIsLoading}
              aria-label="Next page of security events"
            >
              Next <ChevronRight size={14} />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};
