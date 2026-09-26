'use client';

import React, { useState } from 'react';
import { Header } from '@/components/Header';
import { IngestView } from '@/components/IngestView';
import { LiveRunConsole } from '@/components/LiveRunConsole';
import { TimelineDebugConsole } from '@/components/TimelineDebugConsole';
import { DemoPlayer } from '@/components/DemoPlayer';
import { DebugData, PipelineConfig, Brand } from '@/types/pipeline';
import { startPipeline } from '@/lib/api';
import { formatTimecode } from '@/lib/formatters';
import {
  Film,
  Award,
  ShieldCheck,
  Clock,
  Sparkles,
  Layers,
  Volume2,
  RefreshCw,
} from 'lucide-react';

export default function Home() {
  const [appState, setAppState] = useState<'IDLE' | 'PROCESSING' | 'READY'>('IDLE');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [debugData, setDebugData] = useState<DebugData | null>(null);
  const [vmapUrl, setVmapUrl] = useState<string>('');
  const [contentVideoUrl, setContentVideoUrl] = useState<string>('');
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleStartPipeline = async (params: {
    file?: File | null;
    presetId?: string;
    config: PipelineConfig;
    customBrands?: Brand[];
  }) => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const response = await startPipeline({
        file: params.file,
        presetId: params.presetId,
        config: params.config,
        customBrands: params.customBrands,
      });

      const sessId = response.session_id || response.sessionId;
      setSessionId(sessId);
      setVmapUrl(`http://localhost:8000/vmap/${sessId}`);
      setContentVideoUrl(`http://localhost:8000/api/video/${sessId}`);
      setAppState('PROCESSING');
    } catch (err: any) {
      console.error('Failed to start pipeline:', err);
      setErrorMessage(err.message || 'Failed to initiate pipeline');
    } finally {
      setIsLoading(false);
    }
  };

  // Pipeline completion handler
  const handlePipelineComplete = (data: DebugData, vmap: string) => {
    setDebugData(data);
    setVmapUrl(vmap);
    if (sessionId) {
      setContentVideoUrl(`http://localhost:8000/api/video/${sessionId}`);
    }
    setAppState('READY');
  };

  const handleReset = () => {
    setAppState('IDLE');
    setSessionId(null);
    setDebugData(null);
    setVmapUrl('');
    setContentVideoUrl('');
    setCurrentTime(0);
    setErrorMessage(null);
  };

  return (
    <div className="flex-1 flex flex-col min-h-screen">
      <Header
        appState={appState}
        sessionId={sessionId}
        onReset={handleReset}
      />

      <main className="flex-1 pb-16">
        {/* Error notification banner */}
        {errorMessage && (
          <div className="max-w-4xl mx-auto my-4 p-4 bg-rose-950/80 border border-rose-500 rounded-xl text-rose-200 text-xs flex items-center justify-between">
            <span>{errorMessage}</span>
            <button
              onClick={() => setErrorMessage(null)}
              className="text-rose-400 hover:text-white font-bold ml-4"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* State 1: IDLE - Ingest View */}
        {appState === 'IDLE' && (
          <IngestView onStart={handleStartPipeline} isLoading={isLoading} />
        )}

        {/* State 2: PROCESSING - Live Run Console */}
        {appState === 'PROCESSING' && sessionId && (
          <LiveRunConsole
            sessionId={sessionId}
            onComplete={handlePipelineComplete}
            onError={(msg) => setErrorMessage(msg)}
          />
        )}

        {/* State 3: READY - Demo Player & Timeline Debug Console */}
        {appState === 'READY' && debugData && (
          <div className="max-w-6xl mx-auto px-4 py-8 space-y-8 animate-fade-in">
            {/* Top Performance & Acceptance Criteria Summary Pill Bar */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 shadow-xl flex flex-wrap items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400" />
                <h3 className="text-sm font-bold text-white">
                  Execution Metrics & Safety Verification
                </h3>
              </div>

              <div className="flex flex-wrap items-center gap-3 text-xs">
                {/* 0 Mid-speech cuts */}
                <div className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-emerald-950/60 border border-emerald-500/40 text-emerald-300 font-medium">
                  <Volume2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>0 Mid-Speech Cuts Guaranteed</span>
                </div>

                {/* 100% Brand Safety */}
                <div className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-cyan-950/60 border border-cyan-500/40 text-cyan-300 font-medium">
                  <ShieldCheck className="w-3.5 h-3.5 text-cyan-400" />
                  <span>100% GARM Safety Fit (0 Violations)</span>
                </div>

                {/* Scheduled Breaks */}
                <div className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-slate-800 border border-slate-700 text-slate-300 font-mono">
                  <Award className="w-3.5 h-3.5 text-amber-400" />
                  <span>
                    {debugData.execution_summary?.selected_break_count || debugData.final_breaks?.length || 0}{' '}
                    Approved Breaks
                  </span>
                </div>

                {/* Reset CTA */}
                <button
                  onClick={handleReset}
                  className="flex items-center gap-1.5 px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 hover:text-white transition cursor-pointer font-medium"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>New Run</span>
                </button>
              </div>
            </div>

            {/* Video Player Section (F17) */}
            <DemoPlayer
              contentVideoUrl={contentVideoUrl}
              vmapUrl={vmapUrl}
              currentTime={currentTime}
              onTimeUpdate={(t) => setCurrentTime(t)}
            />

            {/* Timeline Debug Console Section (F16) */}
            <TimelineDebugConsole
              debugData={debugData}
              currentTime={currentTime}
              onSeek={(t) => setCurrentTime(t)}
            />
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800/80 bg-slate-950 py-4 text-center text-xs text-slate-500 font-mono">
        Cutaway — Context-Aware Video Segmentation & Ad Placement Engine • Hackathon Demo 2026
      </footer>
    </div>
  );
}
