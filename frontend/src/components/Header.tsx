'use client';

import React from 'react';
import { Film, ShieldCheck, Sparkles, RefreshCw } from 'lucide-react';

interface HeaderProps {
  appState: 'IDLE' | 'PROCESSING' | 'READY';
  sessionId?: string | null;
  onReset?: () => void;
}

export const Header: React.FC<HeaderProps> = ({ appState, sessionId, onReset }) => {
  return (
    <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur-md sticky top-0 z-40 px-6 py-3.5 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
          <Film className="w-5 h-5 text-white" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
              Cutaway
            </h1>
            <span className="text-[10px] uppercase tracking-widest font-semibold px-2 py-0.5 rounded-full bg-cyan-950/80 text-cyan-400 border border-cyan-800/60">
              AI Ad Placement
            </span>
          </div>
          <p className="text-xs text-slate-400 hidden sm:block">
            Context-Aware Video Segmentation & Brand Safety Alignment
          </p>
        </div>
      </div>

      <div className="flex items-center gap-4">
        {sessionId && (
          <div className="hidden md:flex items-center gap-2 text-xs bg-slate-800/60 border border-slate-700/60 px-3 py-1 rounded-full text-slate-300">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="font-mono text-slate-400">Session:</span>
            <span className="font-mono text-cyan-300">{sessionId}</span>
          </div>
        )}

        <div className="flex items-center gap-2">
          <span
            className={`text-xs px-2.5 py-1 rounded-full font-medium border ${
              appState === 'IDLE'
                ? 'bg-slate-800/70 text-slate-300 border-slate-700'
                : appState === 'PROCESSING'
                ? 'bg-amber-950/70 text-amber-400 border-amber-800/80 animate-pulse'
                : 'bg-emerald-950/70 text-emerald-400 border-emerald-800/80'
            }`}
          >
            {appState === 'IDLE' && 'Ready for Ingest'}
            {appState === 'PROCESSING' && 'Pipeline Running...'}
            {appState === 'READY' && 'Manifests Generated'}
          </span>

          {appState !== 'IDLE' && onReset && (
            <button
              onClick={onReset}
              className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1 rounded-lg transition"
              title="Start New Run"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Reset</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
};
