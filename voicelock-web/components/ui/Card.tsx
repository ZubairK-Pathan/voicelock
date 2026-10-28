export interface CardProps {
  children: React.ReactNode;
  className?: string;
  gradient?: string;
}

export function Card({ 
  children, 
  className = '', 
  gradient = 'from-slate-800/50 to-slate-700/50' 
}: CardProps) {
  return (
    <div
      className={`relative bg-gradient-to-br ${gradient} rounded-xl p-8 shadow-xl border border-slate-700/30 backdrop-blur-sm hover:border-slate-600/50 transition-all duration-300 hover:shadow-2xl group ${className}`}
    >
      <div className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-5 bg-white transition-opacity pointer-events-none" />
      <div className="relative">{children}</div>
    </div>
  );
}