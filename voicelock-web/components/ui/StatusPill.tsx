export type StatusType = 'success' | 'error' | 'warning' | 'info' | 'pending';

interface StatusPillProps {
  status: StatusType;
  label: string;
}

const statusConfig = {
  success: { 
    bg: 'bg-emerald-500/20',
    text: 'text-emerald-300',
    border: 'border-emerald-500/30',
    dot: 'bg-emerald-400',
  },
  error: { 
    bg: 'bg-pink-500/20',
    text: 'text-pink-300',
    border: 'border-pink-500/30',
    dot: 'bg-pink-400',
  },
  warning: { 
    bg: 'bg-amber-500/20',
    text: 'text-amber-300',
    border: 'border-amber-500/30',
    dot: 'bg-amber-400',
  },
  info: { 
    bg: 'bg-blue-500/20',
    text: 'text-blue-300',
    border: 'border-blue-500/30',
    dot: 'bg-blue-400',
  },
  pending: { 
    bg: 'bg-purple-500/20',
    text: 'text-purple-300',
    border: 'border-purple-500/30',
    dot: 'bg-purple-400',
  },
};

export function StatusPill({ status, label }: StatusPillProps) {
  const config = statusConfig[status];
  return (
    <span className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold ${config.bg} ${config.text} border ${config.border}`}>
      <span className={`w-2 h-2 rounded-full ${config.dot} animate-pulse`} />
      {label}
    </span>
  );
}