import React from 'react';
import type { EntityStatus, EventSeverity } from '../../types';

interface BadgeProps {
  type?: 'status' | 'severity' | 'result' | 'custom';
  value: EntityStatus | EventSeverity | 'GRANTED' | 'DENIED' | 'SPOOF_DETECTED' | string;
  label?: string;
  showDot?: boolean;
}

export const Badge: React.FC<BadgeProps> = ({ value, label, showDot = true }) => {
  const normalized = value.toLowerCase();
  const displayLabel = label || value;

  let badgeClass = 'badge-prototype';

  if (['active', 'granted', 'low'].includes(normalized)) {
    badgeClass = 'badge-active';
  } else if (['suspended', 'medium'].includes(normalized)) {
    badgeClass = 'badge-suspended';
  } else if (['revoked', 'denied', 'high', 'critical'].includes(normalized)) {
    badgeClass = 'badge-revoked';
  } else if (['spoof_detected', 'spoof'].includes(normalized)) {
    badgeClass = 'badge-spoof';
  }

  return (
    <span className={`badge ${badgeClass}`}>
      {showDot && (
        <span
          style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            backgroundColor: 'currentColor',
            display: 'inline-block',
          }}
        />
      )}
      {displayLabel}
    </span>
  );
};
