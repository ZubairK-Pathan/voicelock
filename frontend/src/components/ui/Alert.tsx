import React from 'react';
import { cn } from '../../lib/utils';

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'info' | 'warning' | 'destructive';
}

export const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant = 'default', style, children, ...props }, ref) => {
    const isAlert = variant === 'destructive' || variant === 'warning';

    const baseStyle: React.CSSProperties = {
      position: 'relative',
      width: '100%',
      borderRadius: 'var(--radius-sm)',
      border: '1px solid var(--border-subtle)',
      padding: '14px 16px',
      fontSize: '13px',
      lineHeight: 1.5,
      display: 'flex',
      flexDirection: 'column',
      gap: '4px',
    };

    let variantStyle: React.CSSProperties = {};
    if (variant === 'default') {
      variantStyle = {
        background: 'var(--bg-surface)',
        borderColor: 'var(--border-subtle)',
        color: 'var(--text-primary)',
      };
    } else if (variant === 'info') {
      variantStyle = {
        background: 'rgba(59, 130, 246, 0.08)',
        borderColor: 'rgba(59, 130, 246, 0.25)',
        borderLeft: '3px solid var(--color-brand)',
        color: 'var(--text-primary)',
      };
    } else if (variant === 'warning') {
      variantStyle = {
        background: 'rgba(245, 158, 11, 0.08)',
        borderColor: 'rgba(245, 158, 11, 0.25)',
        borderLeft: '3px solid var(--color-amber)',
        color: 'var(--text-primary)',
      };
    } else if (variant === 'destructive') {
      variantStyle = {
        background: 'rgba(239, 68, 68, 0.08)',
        borderColor: 'rgba(239, 68, 68, 0.25)',
        borderLeft: '3px solid var(--color-rose)',
        color: 'var(--text-primary)',
      };
    }

    return (
      <div
        ref={ref}
        role={isAlert ? 'alert' : 'status'}
        className={cn('alert-ui', className)}
        style={{ ...baseStyle, ...variantStyle, ...style }}
        {...props}
      >
        {children}
      </div>
    );
  }
);
Alert.displayName = 'Alert';

export const AlertTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, style, ...props }, ref) => (
    <h5
      ref={ref}
      className={cn('font-semibold leading-none tracking-tight', className)}
      style={{ fontSize: '13px', fontWeight: 600, margin: 0, display: 'flex', alignItems: 'center', gap: '8px', ...style }}
      {...props}
    />
  )
);
AlertTitle.displayName = 'AlertTitle';

export const AlertDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, style, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('text-xs text-secondary', className)}
      style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5, ...style }}
      {...props}
    />
  )
);
AlertDescription.displayName = 'AlertDescription';
