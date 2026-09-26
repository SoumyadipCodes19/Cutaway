from __future__ import annotations

import math
from typing import List, Tuple, Optional
from backend.models.pipeline_models import CandidateBreak, PipelineConfig


def compute_break_quota(duration: float, config: PipelineConfig) -> int:
    """
    Computes the maximum allowable number of ad breaks based on:
    1. Maximum breaks per hour (broadcast frequency cap)
    2. Maximum ad load percentage (commercial runtime limit)
    3. Minimum video duration needed to accommodate start/end buffers
    """
    if duration <= 0:
        return 0

    available_runtime = duration - (config.min_start_buffer_seconds + config.min_end_buffer_seconds)
    if available_runtime <= 0:
        return 0

    # Rate-based quota (breaks / hour)
    rate_quota = max(1, int(math.floor((duration / 3600.0) * config.max_breaks_per_hour)))

    # Load-based quota (ad load %)
    if config.ad_duration_seconds > 0:
        max_commercial_seconds = (duration * config.ad_load_pct) / 100.0
        load_quota = max(1, int(math.floor(max_commercial_seconds / config.ad_duration_seconds)))
    else:
        load_quota = rate_quota

    # Overall quota is the stricter constraint
    quota = min(rate_quota, load_quota)

    # Maximum breaks that can physically fit with minimum gap
    max_fit = max(1, int(math.floor(available_runtime / max(1.0, config.min_gap_seconds))) + 1)
    quota = min(quota, max_fit)

    return max(0, quota)


def solve_pacing(
    candidate_breaks: List[CandidateBreak],
    video_duration: float,
    config: PipelineConfig,
) -> Tuple[List[CandidateBreak], List[CandidateBreak]]:
    """
    Evaluates candidate breaks against pacing rules:
    - min_start_buffer_seconds & min_end_buffer_seconds
    - min_gap_seconds between adjacent breaks
    - max_breaks_per_hour & ad_load_pct quota

    Returns:
        (updated_candidate_breaks, scheduled_breaks)
    """
    if not candidate_breaks:
        return [], []

    updated_candidates = [b.model_copy() for b in candidate_breaks]
    quota = compute_break_quota(video_duration, config)

    # 1. Edge buffer zone evaluation
    valid_window_start = config.min_start_buffer_seconds
    valid_window_end = max(0.0, video_duration - config.min_end_buffer_seconds)

    viable_indices: List[int] = []

    for idx, b in enumerate(updated_candidates):
        # If candidate already failed VAD, keep VAD rejection status
        if not b.vad_safe:
            b.pacing_valid = False
            b.status = "REJECTED_VAD"
            if not b.rejection_reason:
                b.rejection_reason = "REJECTED_SPEECH_OVERLAP"
            continue

        # Check edge buffer zones
        if b.cut_time < valid_window_start or b.cut_time > valid_window_end:
            b.pacing_valid = False
            b.status = "REJECTED_PACING"
            b.rejection_reason = (
                f"REJECTED_EDGE_BUFFER: Cut time {b.cut_time:.2f}s outside "
                f"[{valid_window_start:.2f}s, {valid_window_end:.2f}s]"
            )
            continue

        # If quota is 0 due to duration limits
        if quota <= 0:
            b.pacing_valid = False
            b.status = "REJECTED_PACING"
            b.rejection_reason = "REJECTED_PACING_MAX_BREAKS: Video duration cannot fit ad breaks"
            continue

        viable_indices.append(idx)

    if not viable_indices or quota <= 0:
        return updated_candidates, []

    # Sort viable candidates by timestamp
    viable_indices.sort(key=lambda i: updated_candidates[i].cut_time)

    # 2. Check if all viable candidates naturally satisfy min_gap and quota
    all_satisfy_gap = True
    for i in range(len(viable_indices) - 1):
        t1 = updated_candidates[viable_indices[i]].cut_time
        t2 = updated_candidates[viable_indices[i + 1]].cut_time
        if (t2 - t1) < config.min_gap_seconds:
            all_satisfy_gap = False
            break

    if len(viable_indices) <= quota and all_satisfy_gap:
        scheduled: List[CandidateBreak] = []
        for i in viable_indices:
            updated_candidates[i].pacing_valid = True
            updated_candidates[i].status = "CANDIDATE"
            updated_candidates[i].rejection_reason = None
            scheduled.append(updated_candidates[i])
        return updated_candidates, scheduled

    # 3. Dynamic Programming Selection with Spacing Regularization
    # Select k breaks (1 <= k <= min(quota, len(viable_indices))) that maximize
    # quality score + spacing uniformity while strictly satisfying min_gap_seconds.
    num_candidates = len(viable_indices)
    max_k = min(quota, num_candidates)

    times = [updated_candidates[i].cut_time for i in viable_indices]
    gaps = [updated_candidates[i].nearest_speech_gap for i in viable_indices]
    confidences = [updated_candidates[i].confidence or 1.0 for i in viable_indices]

    # Candidate intrinsic score
    scores = [
        confidences[i] + min(1.0, gaps[i] / max(1.0, config.safety_window_seconds * 2))
        for i in range(num_candidates)
    ]

    best_selection: List[int] = []
    best_overall_score = -float("inf")

    # Evaluate for target number of breaks m from max_k down to 1
    for m in range(max_k, 0, -1):
        # Ideal interval spacing
        ideal_spacing = (valid_window_end - valid_window_start) / (m + 1)
        ideal_targets = [valid_window_start + (step + 1) * ideal_spacing for step in range(m)]

        # dp[k][j]: best utility placing k breaks ending at candidate index j
        # parent[k][j]: previous candidate index
        dp = [[-float("inf")] * num_candidates for _ in range(m + 1)]
        parent = [[-1] * num_candidates for _ in range(m + 1)]

        # Base case k = 1 (1st break placed at candidate j)
        for j in range(num_candidates):
            spacing_dist = abs(times[j] - ideal_targets[0])
            spacing_penalty = 0.05 * (spacing_dist / max(1.0, ideal_spacing))
            dp[1][j] = scores[j] - spacing_penalty

        # Recurrence for k = 2 ... m
        for k in range(2, m + 1):
            target_t = ideal_targets[k - 1]
            for j in range(k - 1, num_candidates):
                spacing_dist = abs(times[j] - target_t)
                spacing_penalty = 0.05 * (spacing_dist / max(1.0, ideal_spacing))
                node_score = scores[j] - spacing_penalty

                # Find best valid predecessor p where times[j] - times[p] >= min_gap
                best_prev = -float("inf")
                best_p = -1
                for p in range(j):
                    if (times[j] - times[p]) >= (config.min_gap_seconds - 1e-4):
                        if dp[k - 1][p] > best_prev:
                            best_prev = dp[k - 1][p]
                            best_p = p

                if best_p != -1 and best_prev > -float("inf"):
                    dp[k][j] = best_prev + node_score
                    parent[k][j] = best_p

        # Find best end candidate for m breaks
        best_end_val = -float("inf")
        best_end_j = -1
        for j in range(m - 1, num_candidates):
            if dp[m][j] > best_end_val:
                best_end_val = dp[m][j]
                best_end_j = j

        if best_end_j != -1 and best_end_val > -float("inf"):
            # Bonus for placing more breaks (up to quota)
            overall_val = best_end_val + (m * 2.0)
            if overall_val > best_overall_score:
                best_overall_score = overall_val
                # Backtrack selection
                curr_j = best_end_j
                sel = []
                for k in range(m, 0, -1):
                    sel.append(curr_j)
                    curr_j = parent[k][curr_j]
                sel.reverse()
                best_selection = sel
                break  # Prefer higher m if valid solution found

    # Fallback to greedy if DP found no m-break configuration
    if not best_selection and viable_indices:
        last_t = -float("inf")
        for j in range(num_candidates):
            if (times[j] - last_t) >= config.min_gap_seconds:
                best_selection.append(j)
                last_t = times[j]
                if len(best_selection) >= quota:
                    break

    selected_viable_set = set(best_selection)
    scheduled_breaks: List[CandidateBreak] = []

    for local_idx, orig_idx in enumerate(viable_indices):
        cand = updated_candidates[orig_idx]
        if local_idx in selected_viable_set:
            cand.pacing_valid = True
            cand.status = "CANDIDATE"
            cand.rejection_reason = None
            scheduled_breaks.append(cand)
        else:
            cand.pacing_valid = False
            cand.status = "REJECTED_PACING"
            # Determine specific rejection reason: min gap violation vs max breaks quota
            violates_gap = False
            for sel_local_idx in selected_viable_set:
                sel_time = times[sel_local_idx]
                if abs(cand.cut_time - sel_time) < config.min_gap_seconds:
                    violates_gap = True
                    break

            if violates_gap:
                cand.rejection_reason = (
                    f"REJECTED_PACING_MIN_GAP: Within {config.min_gap_seconds:.1f}s of higher-priority break"
                )
            else:
                cand.rejection_reason = (
                    f"REJECTED_PACING_MAX_BREAKS: Break quota ({quota}) satisfied by higher-priority breaks"
                )

    return updated_candidates, scheduled_breaks
