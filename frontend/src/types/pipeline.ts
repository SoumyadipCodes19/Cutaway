export interface SceneBoundary {
  scene_id: number;
  start_time: number;
  end_time: number;
  start_frame: number;
  end_frame: number;
  transition_type?: string;
  confidence?: number;
  dominant_activity?: string;
  setting?: string;
  sentiment?: string;
  garm_safety_tags?: string[];
  contextual_tags?: string[];
  key_objects?: string[];
}

export interface SpeechInterval {
  start_time: number;
  end_time: number;
  confidence?: number;
}

export type BreakStatus =
  | 'CANDIDATE'
  | 'SELECTED'
  | 'REJECTED_VAD'
  | 'REJECTED_PACING'
  | 'DROPPED_ALL_BRANDS_GATED';

export interface CandidateBreak {
  break_id: string;
  cut_time: number;
  lead_in_scene_id: number;
  lead_out_scene_id: number;
  vad_safe: boolean;
  nearest_speech_gap: number;
  pacing_valid: boolean;
  status: BreakStatus;
  rejection_reason?: string | null;
  time_offset?: string;
  timeOffset?: string;
  matched_brand?: Brand | null;
  brand_score?: number;
  winning_score?: number;
  all_brand_evaluations?: BrandEvaluation[];
}

export interface Brand {
  id: string;
  name: string;
  category: string;
  positive_contexts: string[];
  negative_contexts: string[];
  creative_url: string;
  ad_creative_file?: string;
  duration_seconds?: number;
  click_through_url?: string;
}

export interface BrandEvaluation {
  brand_id: string;
  brand_name?: string;
  score: number;
  is_gated: boolean;
  rejection_reason?: string | null;
  matched_positive_contexts?: string[];
  intersected_negative_contexts?: string[];
  context_score?: number;
  sentiment_score?: number;
  safety_score?: number;
}

export interface VideoMetadata {
  duration: number;
  fps: number;
  frame_count: number;
  total_frames?: number;
  width: number;
  height: number;
  has_audio: boolean;
  audio_sample_rate?: number;
}

export interface PipelineConfig {
  safety_window_seconds: number;
  min_start_buffer_seconds?: number;
  min_end_buffer_seconds?: number;
  min_gap_seconds?: number;
  max_breaks_per_hour: number;
  ad_load_pct: number;
  ad_duration_seconds?: number;
}

export interface ExecutionSummary {
  total_scenes: number;
  total_speech_intervals: number;
  candidate_break_count: number;
  selected_break_count: number;
  rejected_break_count: number;
  generated_at?: string;
}

export interface DebugData {
  session_id: string;
  video_metadata: VideoMetadata;
  scenes: SceneBoundary[];
  speech_intervals: SpeechInterval[];
  candidate_breaks: CandidateBreak[];
  final_breaks: CandidateBreak[];
  selected_breaks?: CandidateBreak[];
  brand_evaluations?: Record<string, BrandEvaluation[]>;
  pipeline_config?: PipelineConfig;
  execution_summary?: ExecutionSummary;
}

export interface PipelineEvent {
  session_id: string;
  stage: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  progress_percent: number;
  message: string;
  metrics?: Record<string, any>;
  timestamp: string;
}

export interface DemoPreset {
  id: string;
  name: string;
  category: string;
  description: string;
  duration: number;
  recommended_brands: string[];
  default_config: Partial<PipelineConfig>;
  video_url: string;
}
