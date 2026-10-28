'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { NAV_ITEMS } from '@/lib/config';

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const pathname = usePathname();

  const navGradients = [
    'from-purple-500 to-pink-500',
    'from-blue-500 to-cyan-500',
    'from-emerald-500 to-teal-500',
    'from-orange-500 to-red-500',
    'from-indigo-500 to-purple-500',
  ];

  return (
    <div className="h-full flex flex-col overflow-y-auto">
      {/* Logo Section */}
      <div className="p-6 border-b border-slate-700/50">
        <div className="flex items-center gap-3 mb-1">
          <div className="w-11 h-11 rounded-lg bg-gradient-to-br from-purple-400 via-pink-400 to-cyan-400 flex items-center justify-center shadow-lg">
            <span className="text-white font-bold text-lg">🎤</span>
          </div>
          <div>
            <h1 className="text-lg font-bold text-transparent bg-clip-text bg-gradient-to-r from-purple-300 to-pink-300">
              VoiceLock
            </h1>
            <p className="text-xs text-slate-400">Voice Auth</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2">
        {NAV_ITEMS.map((item, index) => {
          const isActive = pathname === item.href;
          const gradient = navGradients[index % navGradients.length];

          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onClose}
              className={`block px-4 py-3 rounded-lg text-sm font-medium transition-all duration-300 relative overflow-hidden group ${
                isActive
                  ? `bg-gradient-to-r ${gradient} text-white shadow-lg`
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/50'
              }`}
            >
              {!isActive && (
                <div className="absolute inset-0 bg-gradient-to-r opacity-0 group-hover:opacity-5 rounded-lg transition-opacity" />
              )}
              <span className="relative flex items-center">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Status Footer */}
      <div className="p-4 border-t border-slate-700/50">
        <div className="flex items-center gap-2 px-2">
          <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse shadow-lg shadow-green-400/50" />
          <span className="text-xs text-slate-400 font-medium">Ready</span>
        </div>
      </div>
    </div>
  );
}