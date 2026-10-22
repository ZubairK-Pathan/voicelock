import React from 'react';
import { cn } from '../../lib/utils';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'default' | 'secondary' | 'outline' | 'ghost' | 'destructive';
  size?: 'sm' | 'md' | 'lg';
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'default', size = 'md', type = 'button', disabled, style, children, ...props }, ref) => {
    // Determine inline styles for predictable cross-browser appearance matching design tokens
    const baseStyle: React.CSSProperties = {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: '8px',
      borderRadius: 'var(--radius-sm)',
      fontWeight: 500,
      cursor: disabled ? 'not-allowed' : 'pointer',
      opacity: disabled ? 0.6 : 1,
      transition: 'all var(--transition-fast)',
      border: '1px solid transparent',
      textDecoration: 'none',
      userSelect: 'none',
      outline: 'none',
    };

    let variantStyle: React.CSSProperties = {};
    if (variant === 'default') {
      variantStyle = {
        background: 'var(--color-brand)',
        color: '#FFFFFF',
        borderColor: 'var(--color-brand)',
        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.3)',
      };
    } else if (variant === 'secondary') {
      variantStyle = {
        background: 'var(--bg-surface)',
        color: 'var(--text-primary)',
        borderColor: 'var(--border-subtle)',
      };
    } else if (variant === 'outline') {
      variantStyle = {
        background: 'transparent',
        color: 'var(--text-primary)',
        borderColor: 'var(--border-subtle)',
      };
    } else if (variant === 'ghost') {
      variantStyle = {
        background: 'transparent',
        color: 'var(--text-secondary)',
        borderColor: 'transparent',
      };
    } else if (variant === 'destructive') {
      variantStyle = {
        background: 'rgba(239, 68, 68, 0.15)',
        color: '#EF4444',
        borderColor: 'rgba(239, 68, 68, 0.3)',
      };
    }

    let sizeStyle: React.CSSProperties = {};
    if (size === 'sm') {
      sizeStyle = {
        padding: '5px 10px',
        fontSize: '12px',
        lineHeight: '16px',
      };
    } else if (size === 'md') {
      sizeStyle = {
        padding: '8px 14px',
        fontSize: '13px',
        lineHeight: '18px',
      };
    } else if (size === 'lg') {
      sizeStyle = {
        padding: '11px 20px',
        fontSize: '14px',
        lineHeight: '20px',
        fontWeight: 600,
      };
    }

    return (
      <button
        ref={ref}
        type={type}
        disabled={disabled}
        className={cn('btn-ui focus-visible:outline', className)}
        style={{ ...baseStyle, ...variantStyle, ...sizeStyle, ...style }}
        {...props}
      >
        {children}
      </button>
    );
  }
);
Button.displayName = 'Button';
