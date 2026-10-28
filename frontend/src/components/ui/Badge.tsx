import React from 'react';
import { cn } from '../../lib/utils';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'secondary' | 'outline' | 'success' | 'destructive' | 'warning';
}

export const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant = 'default', style, children, ...props }, ref) => {
    return (
      <span
        ref={ref}
        className={cn('badge-ui', `badge-ui-${variant}`, className)}
        style={style}
        {...props}
      >
        {children}
      </span>
    );
  }
);
Badge.displayName = 'Badge';
