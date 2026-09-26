'use client';

import React from 'react';
import {
  X,
  ShieldCheck,
  ShieldAlert,
  Clock,
  Volume2,
  CheckCircle2,
  XCircle,
  Award,
  Layers,
} from 'lucide-react';
import { CandidateBreak, BrandEvaluation } from '@/types/pipeline';
import { formatTimecode } from '@/lib/formatters';

interface BreakDecisionModalProps {
  adBreak: CandidateBreak | null;
  evaluations?: BrandEvaluation[];
  onClose: () => void;
}

export const BreakDecisionModal: React.FC<BreakDecisionModalProps> = ({
  adBreak,
  evaluations = [],
  onClose,
}) => {
  if (!adBreak) return null;

  const isSelected = adBreak.status === 'SELECTED';
  const isVadRejected = adBreak.status === 'REJECTED_VAD';
  const isPacingRejected = adBreak.status === 'REJECTED_PACING';
  const isDroppedGated = adBreak.status === 'DROPPED_ALL_BRANDS_GATED';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-3xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
          <div className="flex items-center gap-3">
            <div
              className={`w-9 h-9 rounded-xl flex items-center justify-center ${
                isSelected
                  ? 'bg-emerald-950 text-emerald-400 border border-emerald-500/50'
                  : isVadRejected
                  ? 'bg-rose-950 text-rose-400 border border-rose-500/50'
                  : isPacingRejected
                  ? 'bg-amber-950 text-amber-400 border border-amber-500/50'
                  : 'bg-purple-950 text-purple-400 border border-purple-500/50'
              }`}
            >
              {isSelected && <Award className="w-5 h-5" />}
              {isVadRejected && <Volume2 className="w-5 h-5" />}
              {isPacingRejected && <Clock className="w-5 h-5" />}
              {isDroppedGated && <ShieldAlert className="w-5 h-5" />}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-white">
                  Commercial Break Decision Inspector
                </h3>
                <span
                  className={`text-[10px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full border ${
                    isSelected
                      ? 'bg-emerald-950 text-emerald-300 border-emerald-500/60'
                      : isVadRejected
                      ? 'bg-rose-950 text-rose-300 border-rose-500/60'
                      : isPacingRejected
                      ? 'bg-amber-950 text-amber-300 border-amber-500/60'
                      : 'bg-purple-950 text-purple-300 border-purple-500/60'
                  }`}
                >
                  {adBreak.status}
                </span>
              </div>
              <p className="text-xs text-slate-400 font-mono">
                Break ID: {adBreak.break_id} • Cut Time: {formatTimecode(adBreak.cut_time)} ({adBreak.cut_time.toFixed(3)}s)
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-6">
          {/* Top Verification Stats Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {/* VAD Silence Safety */}
            <div className="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-1">
              <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider flex items-center gap-1.5">
                <Volume2 className="w-3.5 h-3.5 text-cyan-400" />
                VAD Speech Gating
              </span>
              <div className="flex items-center gap-2">
                {adBreak.vad_safe ? (
                  <>
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span className="text-xs font-semibold text-emerald-400">0 Mid-Speech Cut</span>
                  </>
                ) : (
                  <>
                    <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
                    <span className="text-xs font-semibold text-rose-400">Mid-Speech Conflict</span>
                  </>
                )}
              </div>
              <p className="text-[11px] text-slate-500">
                Nearest speech gap: {adBreak.nearest_speech_gap !== undefined ? `${adBreak.nearest_speech_gap.toFixed(2)}s` : 'N/A'}
              </p>
            </div>

            {/* Broadcast Pacing */}
            <div className="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-1">
              <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-cyan-400" />
                Broadcast Pacing
              </span>
              <div className="flex items-center gap-2">
                {adBreak.pacing_valid ? (
                  <>
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span className="text-xs font-semibold text-emerald-400">Spacing Valid</span>
                  </>
                ) : (
                  <>
                    <XCircle className="w-4 h-4 text-amber-400 shrink-0" />
                    <span className="text-xs font-semibold text-amber-400">Min Gap Violated</span>
                  </>
                )}
              </div>
              <p className="text-[11px] text-slate-500">
                Lead-in: Scene #{adBreak.lead_in_scene_id} → Lead-out: Scene #{adBreak.lead_out_scene_id}
              </p>
            </div>

            {/* Placement Brand */}
            <div className="p-3.5 bg-slate-950/60 border border-slate-800 rounded-xl space-y-1">
              <span className="text-[10px] uppercase font-bold text-slate-400 tracking-wider flex items-center gap-1.5">
                <Award className="w-3.5 h-3.5 text-cyan-400" />
                Matched Brand
              </span>
              <div className="text-xs font-semibold text-white truncate">
                {adBreak.matched_brand?.name || 'No Brand Placed'}
              </div>
              <p className="text-[11px] text-cyan-400 font-mono">
                {adBreak.brand_score !== undefined
                  ? `Affinity Score: ${adBreak.brand_score.toFixed(1)} pts`
                  : 'N/A'}
              </p>
            </div>
          </div>

          {/* Rejection / Drop Explanation if not selected */}
          {adBreak.rejection_reason && (
            <div className="p-3.5 bg-rose-950/40 border border-rose-500/50 rounded-xl text-xs text-rose-200 flex items-start gap-2.5">
              <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
              <div>
                <span className="font-bold text-rose-300">Algorithmic Rejection Reason:</span>{' '}
                {adBreak.rejection_reason}
              </div>
            </div>
          )}

          {/* Brand Safety & Affinity Evaluation Matrix */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                <Layers className="w-4 h-4 text-cyan-400" />
                Brand Safety & Affinity Evaluation Matrix (R2 / AC-What)
              </h4>
              <span className="text-[11px] text-slate-500 font-mono">
                {evaluations.length} Advertisers Scored
              </span>
            </div>

            {evaluations.length === 0 ? (
              <div className="text-center py-8 text-xs text-slate-500 border border-slate-800 rounded-xl">
                No individual brand evaluations recorded for this candidate break.
              </div>
            ) : (
              <div className="border border-slate-800 rounded-xl overflow-hidden bg-slate-950/40">
                <table className="w-full text-left text-xs">
                  <thead className="bg-slate-900/90 text-slate-400 uppercase text-[10px] font-bold border-b border-slate-800">
                    <tr>
                      <th className="py-2.5 px-3">Brand Name</th>
                      <th className="py-2.5 px-3">Score</th>
                      <th className="py-2.5 px-3">Status</th>
                      <th className="py-2.5 px-3">Context Reasoning & Safety Gating</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/80">
                    {evaluations.map((ev, idx) => {
                      const isWinning =
                        adBreak.matched_brand?.id === ev.brand_id && isSelected;
                      return (
                        <tr
                          key={idx}
                          className={`hover:bg-slate-900/40 transition ${
                            isWinning ? 'bg-emerald-950/30' : ev.is_gated ? 'bg-rose-950/15' : ''
                          }`}
                        >
                          <td className="py-2.5 px-3 font-medium text-white whitespace-nowrap">
                            <div className="flex items-center gap-1.5">
                              {isWinning && <Award className="w-3.5 h-3.5 text-emerald-400" />}
                              <span>{ev.brand_name || ev.brand_id}</span>
                            </div>
                          </td>
                          <td className="py-2.5 px-3 font-mono font-bold whitespace-nowrap">
                            {ev.is_gated ? (
                              <span className="text-rose-400">-∞</span>
                            ) : (
                              <span className="text-cyan-400">{ev.score.toFixed(1)}</span>
                            )}
                          </td>
                          <td className="py-2.5 px-3 whitespace-nowrap">
                            {isWinning ? (
                              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-500/50">
                                SELECTED
                              </span>
                            ) : ev.is_gated ? (
                              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-500/50">
                                HARD GATED
                              </span>
                            ) : (
                              <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                                Eligible
                              </span>
                            )}
                          </td>
                          <td className="py-2.5 px-3 text-slate-300">
                            {ev.is_gated ? (
                              <span className="text-rose-300 text-[11px] leading-tight flex items-center gap-1">
                                <ShieldAlert className="w-3.5 h-3.5 text-rose-400 shrink-0" />
                                {ev.rejection_reason || 'Scene tags intersected brand negative contexts'}
                              </span>
                            ) : ev.matched_positive_contexts && ev.matched_positive_contexts.length > 0 ? (
                              <span className="text-emerald-300 text-[11px]">
                                Matched positive tags: {ev.matched_positive_contexts.join(', ')}
                              </span>
                            ) : (
                              <span className="text-slate-500 text-[11px]">
                                Base neutral fit (0 positive intersections)
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
