'use client';

import React, { useState, useRef, useMemo } from 'react';
import {
  Film,
  Volume2,
  Layers,
  Award,
  ShieldCheck,
  ShieldAlert,
  Clock,
  Sparkles,
  Info,
  Maximize2,
} from 'lucide-react';
import {
  DebugData,
  SceneBoundary,
  SpeechInterval,
  CandidateBreak,
  BrandEvaluation,
} from '@/types/pipeline';
import { formatTimecode, clamp } from '@/lib/formatters';
import { BreakDecisionModal } from './BreakDecisionModal';

interface TimelineDebugConsoleProps {
  debugData: DebugData;
  currentTime: number;
  onSeek: (timeInSeconds: number) => void;
}

export const TimelineDebugConsole: React.FC<TimelineDebugConsoleProps> = ({
  debugData,
  currentTime,
  onSeek,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [selectedBreak, setSelectedBreak] = useState<CandidateBreak | null>(null);
  const [hoveredScene, setHoveredScene] = useState<SceneBoundary | null>(null);
  const [hoverCoords, setHoverCoords] = useState<{ x: number; y: number } | null>(null);
  const [showOnlySelectedBreaks, setShowOnlySelectedBreaks] = useState(false);

  const duration = Math.max(1.0, debugData.video_metadata?.duration || 38.0);
  const safetyWindowN = debugData.pipeline_config?.safety_window_seconds || 0.5;

  const scenes = debugData.scenes || [];
  const speechIntervals = debugData.speech_intervals || [];
  const candidateBreaks = debugData.candidate_breaks || [];
  const brandEvaluations = debugData.brand_evaluations || {};

  const finalBreakMap = useMemo(() => {
    const map: Record<string, any> = {};
    const finals = debugData.final_breaks || (debugData as any).selected_breaks || [];
    finals.forEach((b: any) => {
      map[b.break_id] = b;
    });
    return map;
  }, [debugData]);

  // Scrubbing handling
  const handleTimelineClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const ratio = clamp(clickX / rect.width, 0, 1);
    const targetTime = ratio * duration;
    onSeek(targetTime);
  };

  const playheadPercent = clamp((currentTime / duration) * 100, 0, 100);

  // Time ruler tick generator
  const timeRulerTicks = useMemo(() => {
    const ticks: { time: number; label: string; percent: number }[] = [];
    const step = duration > 120 ? 30 : duration > 60 ? 15 : 5;
    for (let t = 0; t <= duration; t += step) {
      ticks.push({
        time: t,
        label: formatTimecode(t, false),
        percent: (t / duration) * 100,
      });
    }
    return ticks;
  }, [duration]);

  // Color helper for scene sentiment
  const getSceneSentimentStyle = (sentiment: string = 'neutral') => {
    const s = sentiment.toLowerCase();
    if (s.includes('pos') || s.includes('uplift')) {
      return 'bg-emerald-950/70 border-emerald-500/40 text-emerald-200 hover:border-emerald-400';
    }
    if (s.includes('neg') || s.includes('tense') || s.includes('sad')) {
      return 'bg-rose-950/70 border-rose-500/40 text-rose-200 hover:border-rose-400';
    }
    return 'bg-cyan-950/70 border-cyan-500/40 text-cyan-200 hover:border-cyan-400';
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
      {/* Header and Legend */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 pb-4 border-b border-slate-800">
        <div>
          <div className="flex items-center gap-2">
            <Layers className="w-5 h-5 text-cyan-400" />
            <h2 className="text-base font-bold text-white">
              Timeline Debug Console (Forensic Verification)
            </h2>
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Synchronized 3-track verification: Scenes, Silero VAD speech intervals, and candidate ad breaks.
          </p>
        </div>

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-3 text-[11px] font-medium text-slate-400 bg-slate-950/60 px-3 py-1.5 rounded-xl border border-slate-800">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
            <span>Selected Break</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
            <span>Rejected (VAD)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
            <span>Rejected (Pacing)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-purple-500" />
            <span>Gated Brand</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-orange-500" />
            <span>Speech (VAD)</span>
          </div>
        </div>
      </div>

      {/* Main Interactive Timeline Box */}
      <div
        ref={containerRef}
        onClick={handleTimelineClick}
        className="relative bg-slate-950/80 border border-slate-800 rounded-xl p-4 select-none cursor-pointer overflow-hidden space-y-4"
      >
        {/* Playhead Vertical Line */}
        <div
          className="absolute top-0 bottom-0 z-30 w-0.5 bg-cyan-400 shadow-[0_0_10px_#22d3ee] pointer-events-none transition-all duration-75"
          style={{ left: `${playheadPercent}%` }}
        >
          <div className="absolute -top-1 -translate-x-1/2 w-3 h-3 bg-cyan-400 rotate-45 rounded-sm" />
          <div className="absolute top-2 left-2 text-[10px] font-mono font-bold bg-cyan-950 text-cyan-300 px-1 rounded border border-cyan-500/50 whitespace-nowrap">
            {formatTimecode(currentTime)}
          </div>
        </div>

        {/* Top Time Ruler */}
        <div className="relative h-6 border-b border-slate-800/80 text-[10px] font-mono text-slate-500">
          {timeRulerTicks.map((tick, idx) => (
            <div
              key={idx}
              className="absolute -translate-x-1/2 flex flex-col items-center"
              style={{ left: `${tick.percent}%` }}
            >
              <span>{tick.label}</span>
              <div className="w-px h-1.5 bg-slate-700 mt-0.5" />
            </div>
          ))}
        </div>

        {/* Track 1: Scenes Track */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <span className="flex items-center gap-1.5">
              <Film className="w-3.5 h-3.5 text-cyan-400" />
              Track 1: Coarse-to-Fine Scenes ({scenes.length} Scenes)
            </span>
            <span className="text-[10px] text-slate-500">PySceneDetect + TransNetV2</span>
          </div>

          <div className="relative h-12 w-full bg-slate-900/80 rounded-lg overflow-hidden border border-slate-800 flex">
            {scenes.map((scene) => {
              const startPct = clamp((scene.start_time / duration) * 100, 0, 100);
              const endPct = clamp((scene.end_time / duration) * 100, 0, 100);
              const widthPct = Math.max(0.5, endPct - startPct);

              return (
                <div
                  key={scene.scene_id}
                  style={{ width: `${widthPct}%` }}
                  onMouseEnter={(e) => {
                    setHoveredScene(scene);
                    setHoverCoords({ x: e.clientX, y: e.clientY });
                  }}
                  onMouseLeave={() => setHoveredScene(null)}
                  className={`h-full border-r relative p-1.5 overflow-hidden transition-all group flex flex-col justify-between ${getSceneSentimentStyle(
                    scene.sentiment
                  )}`}
                >
                  <div className="flex items-center justify-between text-[9px] font-mono">
                    <span className="font-bold">#{scene.scene_id}</span>
                    <span className="truncate max-w-[70px] uppercase font-semibold">
                      {scene.sentiment || 'neutral'}
                    </span>
                  </div>
                  <p className="text-[10px] truncate text-slate-300 font-medium">
                    {scene.dominant_activity || `Scene ${scene.scene_id}`}
                  </p>
                </div>
              );
            })}
          </div>
        </div>

        {/* Track 2: Silero VAD Speech & Safety Zones */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <span className="flex items-center gap-1.5">
              <Volume2 className="w-3.5 h-3.5 text-orange-400" />
              Track 2: Voice Activity Detection (Silero VAD, ±{safetyWindowN}s Window)
            </span>
            <span className="text-[10px] text-slate-500">
              {speechIntervals.length} Speech Intervals
            </span>
          </div>

          <div className="relative h-8 w-full bg-slate-900/80 rounded-lg overflow-hidden border border-slate-800">
            {/* Background is silence (safe zone) */}
            <div className="absolute inset-0 bg-emerald-950/20" />

            {/* Speech interval blocks */}
            {speechIntervals.map((interval, i) => {
              const startPct = clamp((interval.start_time / duration) * 100, 0, 100);
              const endPct = clamp((interval.end_time / duration) * 100, 0, 100);
              const widthPct = Math.max(0.2, endPct - startPct);

              return (
                <div
                  key={i}
                  style={{ left: `${startPct}%`, width: `${widthPct}%` }}
                  title={`Speech: ${formatTimecode(interval.start_time)} - ${formatTimecode(interval.end_time)}`}
                  className="absolute top-0 bottom-0 bg-gradient-to-r from-orange-600 to-amber-600 border-x border-orange-400/60 shadow-sm flex items-center justify-center text-[9px] font-mono text-white font-bold opacity-90"
                >
                  {widthPct > 5 && 'SPEECH'}
                </div>
              );
            })}

            {/* Silence window safety margin markers around each candidate cut */}
            {candidateBreaks.map((b) => {
              const cutPct = clamp((b.cut_time / duration) * 100, 0, 100);
              const halfWinPct = ((safetyWindowN) / duration) * 100;
              const leftPct = Math.max(0, cutPct - halfWinPct);
              const widthPct = Math.min(100 - leftPct, halfWinPct * 2);

              return (
                <div
                  key={`vad-win-${b.break_id}`}
                  style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                  className={`absolute top-0 bottom-0 border border-dashed pointer-events-none ${
                    b.vad_safe
                      ? 'border-emerald-500/50 bg-emerald-500/10'
                      : 'border-rose-500/80 bg-rose-500/20'
                  }`}
                />
              );
            })}
          </div>
        </div>

        {/* Track 3: Candidate Ad Breaks */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-wider text-slate-400">
            <span className="flex items-center gap-1.5">
              <Award className="w-3.5 h-3.5 text-cyan-400" />
              Track 3: Candidate Ad Breaks ({candidateBreaks.length} Candidates)
            </span>
            <label className="text-[10px] text-slate-400 flex items-center gap-2 cursor-pointer hover:text-slate-300">
              <input 
                type="checkbox" 
                checked={showOnlySelectedBreaks}
                onChange={(e) => setShowOnlySelectedBreaks(e.target.checked)}
                className="w-3 h-3 rounded border-slate-700 bg-slate-800"
              />
              Show only added ads (SELECTED)
            </label>
          </div>

          <div className="relative h-14 w-full bg-slate-900/80 rounded-lg border border-slate-800 flex items-center">
            {candidateBreaks.length === 0 ? (
              <div className="w-full text-center text-xs text-slate-600 italic">
                No candidate breaks detected in video.
              </div>
            ) : (
              candidateBreaks
                .filter(b => !showOnlySelectedBreaks || b.status === 'SELECTED')
                .map((b) => {
                const isSelected = b.status === 'SELECTED';
                const isVadRejected = b.status === 'REJECTED_VAD';
                const isPacingRejected = b.status === 'REJECTED_PACING';
                const isDroppedGated = b.status === 'DROPPED_ALL_BRANDS_GATED';
                const cutPct = clamp((b.cut_time / duration) * 100, 0, 100);

                return (
                  <button
                    key={b.break_id}
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedBreak(b);
                      onSeek(b.cut_time);
                    }}
                    style={{ left: `${cutPct}%` }}
                    className={`absolute -translate-x-1/2 z-20 flex flex-col items-center group cursor-pointer transition-transform hover:scale-110 ${
                      isSelected
                        ? 'text-emerald-400'
                        : isVadRejected
                        ? 'text-rose-400'
                        : isPacingRejected
                        ? 'text-amber-400'
                        : 'text-purple-400'
                    }`}
                  >
                    {/* Badge Icon */}
                    <div
                      className={`w-6 h-6 rounded-full flex items-center justify-center border shadow-lg ${
                        isSelected
                          ? 'bg-emerald-950 border-emerald-400 ring-2 ring-emerald-500/40 text-emerald-300'
                          : isVadRejected
                          ? 'bg-rose-950 border-rose-500 text-rose-300'
                          : isPacingRejected
                          ? 'bg-amber-950 border-amber-500 text-amber-300'
                          : 'bg-purple-950 border-purple-500 text-purple-300'
                      }`}
                    >
                      {isSelected ? (
                        <Award className="w-3.5 h-3.5" />
                      ) : isVadRejected ? (
                        <Volume2 className="w-3.5 h-3.5" />
                      ) : isPacingRejected ? (
                        <Clock className="w-3.5 h-3.5" />
                      ) : (
                        <ShieldAlert className="w-3.5 h-3.5" />
                      )}
                    </div>

                    {/* Badge Label */}
                    <span className="text-[9px] font-bold font-mono tracking-tight mt-0.5 px-1.5 py-0.2 rounded bg-slate-950/90 border border-slate-700 whitespace-nowrap shadow">
                      {isSelected ? b.matched_brand?.name || 'Selected' : b.status.replace('REJECTED_', '')}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Hover Scene Tooltip Card */}
      {hoveredScene && hoverCoords && (
        <div
          className="fixed z-50 pointer-events-none p-3.5 bg-slate-900/95 border border-slate-700 rounded-xl shadow-2xl text-xs space-y-2 max-w-sm backdrop-blur-md animate-fade-in"
          style={{
            left: `${Math.min(window.innerWidth - 320, hoverCoords.x + 15)}px`,
            top: `${Math.min(window.innerHeight - 250, hoverCoords.y - 100)}px`,
          }}
        >
          <div className="flex items-center justify-between border-b border-slate-800 pb-1.5">
            <span className="font-bold text-white">Scene #{hoveredScene.scene_id}</span>
            <span className="font-mono text-cyan-400 text-[10px]">
              {formatTimecode(hoveredScene.start_time)} - {formatTimecode(hoveredScene.end_time)}
            </span>
          </div>
          <div>
            <span className="text-[10px] text-slate-400 block font-semibold uppercase">
              Dominant Activity
            </span>
            <p className="text-slate-200 font-medium">{hoveredScene.dominant_activity}</p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div>
              <span className="text-[10px] text-slate-400 block font-semibold uppercase">
                Setting
              </span>
              <p className="text-slate-300">{hoveredScene.setting || 'Unspecified'}</p>
            </div>
            <div>
              <span className="text-[10px] text-slate-400 block font-semibold uppercase">
                Sentiment
              </span>
              <p className="capitalize text-slate-300">{hoveredScene.sentiment || 'Neutral'}</p>
            </div>
          </div>
          <div>
            <span className="text-[10px] text-slate-400 block font-semibold uppercase mb-1">
              GARM Brand Safety Tags
            </span>
            <div className="flex flex-wrap gap-1">
              {(hoveredScene.garm_safety_tags || ['safe_all_audiences']).map((tag, idx) => (
                <span
                  key={idx}
                  className={`text-[9px] px-1.5 py-0.5 rounded font-medium border ${
                    tag === 'safe_all_audiences'
                      ? 'bg-emerald-950 text-emerald-300 border-emerald-800'
                      : 'bg-rose-950 text-rose-300 border-rose-800'
                  }`}
                >
                  {tag}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Break Decision Inspector Modal */}
      <BreakDecisionModal
        adBreak={
          selectedBreak 
            ? { ...selectedBreak, ...(finalBreakMap[selectedBreak.break_id] || {}) }
            : null
        }
        evaluations={
          selectedBreak ? brandEvaluations[selectedBreak.break_id] || [] : []
        }
        onClose={() => setSelectedBreak(null)}
      />
    </div>
  );
};
