import { Brand, DebugData, DemoPreset, PipelineConfig } from '@/types/pipeline';

const API_BASE = 'http://localhost:8000';

export async function fetchPresets(): Promise<DemoPreset[]> {
  const res = await fetch(`${API_BASE}/api/presets`);
  if (!res.ok) {
    throw new Error(`Failed to fetch presets: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchBrands(): Promise<Brand[]> {
  const res = await fetch(`${API_BASE}/api/brands`);
  if (!res.ok) {
    throw new Error(`Failed to fetch brands: ${res.statusText}`);
  }
  return res.json();
}

export async function registerBrand(brand: Brand): Promise<Brand> {
  const res = await fetch(`${API_BASE}/api/brands`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(brand),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to register brand');
  }
  return res.json();
}

export async function uploadAdFile(file: File): Promise<{ filename: string; url: string }> {
  const formData = new FormData();
  formData.append('file', file);
  
  const res = await fetch(`${API_BASE}/api/ads/upload`, {
    method: 'POST',
    body: formData,
  });
  
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Failed to upload ad file');
  }
  
  return res.json();
}

export interface RunPipelineOptions {
  file?: File | null;
  presetId?: string;
  config: PipelineConfig;
  customBrands?: Brand[];
}

export interface RunPipelineResponse {
  session_id: string;
  sessionId: string;
  status: string;
  vmap_url: string;
  debug_url: string;
  scheduled_breaks_count: number;
  message?: string;
}

export async function startPipeline(options: RunPipelineOptions): Promise<RunPipelineResponse> {
  if (options.file) {
    const formData = new FormData();
    formData.append('file', options.file);
    if (options.config.safety_window_seconds !== undefined) {
      formData.append('safety_window_seconds', String(options.config.safety_window_seconds));
    }
    if (options.config.min_gap_seconds !== undefined) {
      formData.append('min_gap_seconds', String(options.config.min_gap_seconds));
    }
    if (options.config.max_breaks_per_hour !== undefined) {
      formData.append('max_breaks_per_hour', String(options.config.max_breaks_per_hour));
    }
    if (options.config.ad_load_pct !== undefined) {
      formData.append('ad_load_pct', String(options.config.ad_load_pct));
    }
    if (options.customBrands && options.customBrands.length > 0) {
      formData.append('custom_brands_json', JSON.stringify(options.customBrands));
    }

    const res = await fetch(`${API_BASE}/api/pipeline/run`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Pipeline run failed');
    }
    return res.json();
  } else {
    const payload: Record<string, any> = {
      preset_id: options.presetId || 'tech_review',
      safety_window_seconds: options.config.safety_window_seconds,
      min_gap_seconds: options.config.min_gap_seconds,
      max_breaks_per_hour: options.config.max_breaks_per_hour,
      ad_load_pct: options.config.ad_load_pct,
    };
    if (options.customBrands && options.customBrands.length > 0) {
      payload.custom_brands = options.customBrands;
    }

    const res = await fetch(`${API_BASE}/api/pipeline/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Pipeline run failed');
    }
    return res.json();
  }
}

export async function fetchPipelineStatus(sessionId: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/pipeline/status/${sessionId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch status: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchDebugData(sessionId: string): Promise<DebugData> {
  const res = await fetch(`${API_BASE}/api/debug/${sessionId}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch debug data: ${res.statusText}`);
  }
  return res.json();
}
