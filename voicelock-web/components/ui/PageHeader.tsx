export interface PageHeaderProps {
  title: string;
  description?: string;
  action?: {
    label: string;
    onClick: () => void;
  };
}

export function PageHeader({ title, description, action }: PageHeaderProps) {
  return (
    <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6 mb-10">
      <div className="flex-1">
        <h1 className="text-5xl font-bold text-transparent bg-clip-text bg-gradient-to-r from-purple-300 via-pink-300 to-cyan-300 leading-tight mb-3">
          {title}
        </h1>
        {description && (
          <p className="text-slate-400 text-lg leading-relaxed">{description}</p>
        )}
      </div>
      {action && (
        <button
          onClick={action.onClick}
          className="btn btn-primary whitespace-nowrap"
        >
          + {action.label}
        </button>
      )}
    </div>
  );
}