'use client';

import React, { useState, useEffect, useRef } from 'react';
import {
  CheckCircle2,
  Clock,
  AlertTriangle,
  Loader2,
  Terminal,
  Activity,
  Film,
  Sparkles,
  Volume2,
  ShieldCheck,
  FileCode,
} from 'lucide-react';
import { DebugData, PipelineEvent } from '@/types/pipeline';
import { fetchDebugData, fetchPipelineStatus } from '@/lib/api';

interface StageDefinition {
  id: string;
  name: string;
  description: string;
  icon: React.ElementType;
}

const STAGES: StageDefinition[] = [
  { id: 'ingest', name: 'Ingest & Probe Video', description: 'Probe video duration, resolution, frame rate', icon: Film },
  { id: 'audio_extraction', name: 'Audio Track Demuxing', description: 'Extract 16kHz mono PCM via ffmpeg', icon: Volume2 },
  { id: 'scene_detection', name: 'Coarse Scene Detection', description: 'Detect visual cut candidates with PySceneDetect', icon: Activity },
  { id: 'scene_refinement', name: 'Fine Boundary Refinement', description: 'Refine cuts to millisecond precision with TransNetV2', icon: Activity },
  { id: 'vad_speech_detection', name: 'Speech Activity Detection', description: 'Silero VAD speech interval analysis', icon: Volume2 },
  { id: 'silence_safety_gating', name: 'Silence Safety Window Gating', description: 'Enforce ±N-second speech safety margin (0 mid-speech cuts)', icon: ShieldCheck },
  { id: 'pacing_solver', name: 'Broadcast Pacing Solver', description: 'Enforce min-gap spacing and max breaks/hour', icon: Clock },
  { id: 'brand_matching', name: 'Gemini Scene & Brand Matching', description: 'Structured JSON, GARM safety tags & -∞ hard gating', icon: Sparkles },
  { id: 'manifest_generation', name: 'VMAP 1.0.1 & VAST Manifests', description: 'IAB standard XML manifests and debug.json output', icon: FileCode },
];

interface LiveRunConsoleProps {
  sessionId: string;
  onComplete: (debugData: DebugData, vmapUrl: string) => void;
  onError: (errorMsg: string) => void;
}

export const LiveRunConsole: React.FC<LiveRunConsoleProps> = ({
  sessionId,
  onComplete,
  onError,
}) => {
  const [currentStageId, setCurrentStageId] = useState<string>('ingest');
  const [completedStages, setCompletedStages] = useState<string[]>([]);
  const [failedStage, setFailedStage] = useState<string | null>(null);
  const [overallProgress, setOverallProgress] = useState<number>(0);
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const terminalRef = useRef<HTMLDivElement>(null);
  const isDoneRef = useRef(false);

  // Auto-scroll terminal log window
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [terminalLogs]);

  // Connect to SSE stream with polling fallback
  useEffect(() => {
    if (!sessionId) return;
    let eventSource: EventSource | null = null;
    let pollInterval: NodeJS.Timeout | null = null;

    const handleEventData = (event: PipelineEvent) => {
      setEvents((prev) => [...prev, event]);
      const timestamp = new Date(event.timestamp || Date.now()).toLocaleTimeString();
      const logMessage = `[${timestamp}] [${event.stage.toUpperCase()}] ${event.message}`;
      setTerminalLogs((prev) => [...prev, logMessage]);

      setCurrentStageId(event.stage);
      setOverallProgress(event.progress_percent || 0);

      if (event.status === 'COMPLETED' && !completedStages.includes(event.stage)) {
        setCompletedStages((prev) => Array.from(new Set([...prev, event.stage])));
      }

      if (event.status === 'FAILED') {
        setFailedStage(event.stage);
        onError(event.message || 'Pipeline failed at stage: ' + event.stage);
      }

      // Check if finished
      if (
        (event.stage === 'manifest_generation' && event.status === 'COMPLETED') ||
        event.progress_percent === 100
      ) {
        if (!isDoneRef.current) {
          isDoneRef.current = true;
          // Fetch final debug data and finish
          setTimeout(async () => {
            try {
              const debugData = await fetchDebugData(sessionId);
              onComplete(debugData, `http://localhost:8000/vmap/${sessionId}`);
            } catch (err: any) {
              console.error('Error fetching final debug.json:', err);
              onError(err.message || 'Failed to fetch debug data');
            }
          }, 600);
        }
      }
    };

    // Attempt Server-Sent Events
    try {
      eventSource = new EventSource(`http://localhost:8000/api/pipeline/stream/${sessionId}`);

      eventSource.onmessage = (e) => {
        try {
          const data: PipelineEvent = JSON.parse(e.data);
          handleEventData(data);
        } catch (err) {
          console.warn('Failed to parse SSE payload:', err);
        }
      };

      eventSource.onerror = () => {
        // SSE disconnected, fallback to polling
        if (eventSource) {
          eventSource.close();
          eventSource = null;
        }
        startPolling();
      };
    } catch {
      startPolling();
    }

    // Polling fallback
    function startPolling() {
      if (pollInterval || isDoneRef.current) return;
      pollInterval = setInterval(async () => {
        if (isDoneRef.current) {
          if (pollInterval) clearInterval(pollInterval);
          return;
        }
        try {
          const status = await fetchPipelineStatus(sessionId);
          if (status.current_stage) setCurrentStageId(status.current_stage);
          if (status.stages_completed) setCompletedStages(status.stages_completed);
          if (status.progress_percent !== undefined) setOverallProgress(status.progress_percent);

          if (status.status === 'COMPLETED') {
            if (!isDoneRef.current) {
              isDoneRef.current = true;
              if (pollInterval) clearInterval(pollInterval);
              const debugData = await fetchDebugData(sessionId);
              onComplete(debugData, `http://localhost:8000/vmap/${sessionId}`);
            }
          } else if (status.status === 'FAILED') {
            setFailedStage(status.current_stage);
            if (pollInterval) clearInterval(pollInterval);
            onError(status.error_message || 'Pipeline failed during execution');
          }
        } catch (e) {
          console.warn('Polling error:', e);
        }
      }, 800);
    }

    return () => {
      if (eventSource) eventSource.close();
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [sessionId, onComplete, onError, completedStages]);

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-8 animate-fade-in">
      {/* Top Status Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />
            <h2 className="text-xl font-bold text-white">Live Pipeline Execution</h2>
          </div>
          <p className="text-xs text-slate-400">
            Running 9-stage video segmentation, speech safety gating, and context-aware brand placement.
          </p>
        </div>

        <div className="w-full md:w-64 space-y-1.5">
          <div className="flex justify-between text-xs font-mono font-semibold">
            <span className="text-slate-400">Overall Progress</span>
            <span className="text-cyan-400">{overallProgress}%</span>
          </div>
          <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-cyan-500 to-indigo-500 transition-all duration-300"
              style={{ width: `${overallProgress}%` }}
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left: 9-Stage Stepper (5 cols) */}
        <div className="lg:col-span-5 bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400 pb-2 border-b border-slate-800">
            Pipeline Stages (9 Stages)
          </h3>

          <div className="space-y-3">
            {STAGES.map((st, idx) => {
              const isCompleted = completedStages.includes(st.id);
              const isRunning = currentStageId === st.id && !isCompleted && !failedStage;
              const isFailed = failedStage === st.id;
              const isPending = !isCompleted && !isRunning && !isFailed;
              const Icon = st.icon;

              return (
                <div
                  key={st.id}
                  className={`flex items-start gap-3 p-3 rounded-xl border transition-all ${
                    isRunning
                      ? 'bg-cyan-950/40 border-cyan-500 shadow-md shadow-cyan-950/50 ring-1 ring-cyan-500/30'
                      : isCompleted
                      ? 'bg-slate-950/40 border-slate-800 text-slate-300'
                      : isFailed
                      ? 'bg-rose-950/40 border-rose-500 text-rose-200'
                      : 'bg-slate-950/20 border-slate-800/60 opacity-60 text-slate-500'
                  }`}
                >
                  <div className="pt-0.5 shrink-0">
                    {isCompleted ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                    ) : isRunning ? (
                      <Loader2 className="w-5 h-5 text-cyan-400 animate-spin" />
                    ) : isFailed ? (
                      <AlertTriangle className="w-5 h-5 text-rose-400" />
                    ) : (
                      <div className="w-5 h-5 rounded-full border border-slate-700 flex items-center justify-center text-[10px] font-mono text-slate-500">
                        {idx + 1}
                      </div>
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className={`text-xs font-bold ${isRunning ? 'text-cyan-300' : isCompleted ? 'text-white' : 'text-slate-400'}`}>
                        {st.name}
                      </span>
                      <span className="text-[10px] font-mono">
                        {isCompleted && <span className="text-emerald-400 font-semibold">DONE</span>}
                        {isRunning && <span className="text-cyan-400 font-semibold animate-pulse">RUNNING</span>}
                        {isFailed && <span className="text-rose-400 font-semibold">FAILED</span>}
                        {isPending && <span className="text-slate-600">WAITING</span>}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400 truncate mt-0.5">
                      {st.description}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right: Live Log Terminal (7 cols) */}
        <div className="lg:col-span-7 bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col h-[580px]">
          <div className="flex items-center justify-between pb-3 border-b border-slate-800">
            <div className="flex items-center gap-2">
              <Terminal className="w-4 h-4 text-cyan-400" />
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300">
                Live Execution Logs & Telemetry
              </h3>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-500 font-mono">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
              <span>SSE Stream Active</span>
            </div>
          </div>

          <div
            ref={terminalRef}
            className="flex-1 bg-black/80 rounded-xl p-4 mt-3 font-mono text-xs overflow-y-auto space-y-2 border border-slate-800/80 text-slate-300"
          >
            {terminalLogs.length === 0 ? (
              <div className="text-slate-600 italic">Waiting for initial stage events from backend...</div>
            ) : (
              terminalLogs.map((log, index) => {
                const isError = log.includes('FAILED') || log.includes('error');
                const isComplete = log.includes('COMPLETED') || log.includes('finished');
                return (
                  <div
                    key={index}
                    className={`leading-relaxed break-all ${
                      isError
                        ? 'text-rose-400 font-semibold'
                        : isComplete
                        ? 'text-emerald-400'
                        : 'text-slate-300'
                    }`}
                  >
                    {log}
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
