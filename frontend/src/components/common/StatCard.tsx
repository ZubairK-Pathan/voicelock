import React from 'react';

interface StatCardProps {
  title: string;
  value: string | number;
  subtitle: string;
  icon: React.ReactNode;
  iconBgColor?: string;
  trend?: {
    value: string;
    isPositive: boolean;
  };
}

export const StatCard: React.FC<StatCardProps> = ({
  title,
  value,
  subtitle,
  icon,
  iconBgColor = 'rgba(59, 130, 246, 0.15)',
  trend,
}) => {
  return (
    <div className="stat-card">
      <div className="stat-card-header">
        <span className="text-secondary text-sm font-medium">{title}</span>
        <div
          className="stat-card-icon"
          style={{ backgroundColor: iconBgColor }}
        >
          {icon}
        </div>
      </div>
      <div>
        <div className="stat-card-value font-mono">{value}</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '6px' }}>
          {trend && (
            <span
              className="text-xs font-semibold"
              style={{
                color: trend.isPositive ? '#34D399' : '#F87171',
                display: 'inline-flex',
                alignItems: 'center',
              }}
            >
              {trend.isPositive ? '↑' : '↓'} {trend.value}
            </span>
          )}
          <span className="text-xs text-muted">{subtitle}</span>
        </div>
      </div>
    </div>
  );
};
