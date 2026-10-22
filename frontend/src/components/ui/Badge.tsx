import React from 'react';
import { cn } from '../../lib/utils';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'secondary' | 'outline' | 'success' | 'destructive' | 'warning';
}

export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant = 'default', style, children, ...props }, ref) => {
    const baseStyle: React.CSSProperties = {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '5px',
      borderRadius: 'var(--radius-sm)',
      padding: '2px 8px',
      fontSize: '11px',
      fontWeight: 600,
      fontFamily: 'var(--font-mono)',
      letterSpacing: '0.02em',
      lineHeight: '16px',
      border: '1px solid transparent',
      userSelect: 'none',
    };

    let variantStyle: React.CSSProperties = {};
    if (variant === 'default') {
      variantStyle = {
        background: 'rgba(59, 130, 246, 0.12)',
        color: '#60A5FA',
        borderColor: 'rgba(59, 130, 246, 0.25)',
      };
    } else if (variant === 'secondary') {
      variantStyle = {
        background: 'rgba(148, 163, 184, 0.1)',
        color: 'var(--text-secondary)',
        borderColor: 'var(--border-subtle)',
      };
    } else if (variant === 'outline') {
      variantStyle = {
        background: 'transparent',
        color: 'var(--text-primary)',
        borderColor: 'var(--border-subtle)',
      };
    } else if (variant === 'success') {
      variantStyle = {
        background: 'rgba(16, 185, 129, 0.12)',
        color: '#34D399',
        borderColor: 'rgba(16, 185, 129, 0.25)',
      };
    } else if (variant === 'destructive') {
      variantStyle = {
        background: 'rgba(239, 68, 68, 0.12)',
        color: '#F87171',
        borderColor: 'rgba(239, 68, 68, 0.25)',
      };
    } else if (variant === 'warning') {
      variantStyle = {
        background: 'rgba(245, 158, 11, 0.12)',
        color: '#FBBF24',
        borderColor: 'rgba(245, 158, 11, 0.25)',
      };
    }

    return (
      <span
        ref={ref}
        className={cn('badge-ui', className)}
        style={{ ...baseStyle, ...variantStyle, ...style }}
        {...props}
      >
        {children}
      </span>
    );
  }
);
Badge.displayName = 'Badge';
