'use client';

import React, { useState, useRef } from 'react';
import {
  UploadCloud,
  Sliders,
  Sparkles,
  Database,
  ArrowRight,
  Clock,
  Volume2,
  Shield,
  Layers,
  FileVideo,
  Plus,
  Trash2,
} from 'lucide-react';
import { PipelineConfig, Brand } from '@/types/pipeline';
import { formatBytes } from '@/lib/formatters';
import { BrandCatalogueDrawer } from './BrandCatalogueDrawer';
import { uploadAdFile } from '@/lib/api';

interface CustomAd {
  id: string;
  brandName: string;
  category?: string;
  positiveContexts: string;
  negativeContexts: string;
  file: File | null;
  duration?: number;
  clickThroughUrl?: string;
}

interface IngestViewProps {
  onStart: (params: {
    file?: File | null;
    presetId?: string;
    config: PipelineConfig;
    customBrands?: Brand[];
  }) => void;
  isLoading: boolean;
}

export const IngestView: React.FC<IngestViewProps> = ({ onStart, isLoading }) => {
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Configuration Sliders
  const [safetyWindow, setSafetyWindow] = useState<number>(0.5);
  const [minGap, setMinGap] = useState<number>(60);
  const [maxBreaks, setMaxBreaks] = useState<number>(4);
  const [adLoadPct, setAdLoadPct] = useState<number>(10);

  // Brand Drawer
  const [brandDrawerOpen, setBrandDrawerOpen] = useState(false);

  // Custom Ads State
  const [customAds, setCustomAds] = useState<CustomAd[]>([]);
  const [isUploadingAds, setIsUploadingAds] = useState(false);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      const validExtensions = ['.mp4', '.mov', '.webm', '.mkv'];
      const ext = '.' + file.name.split('.').pop()?.toLowerCase();
      if (validExtensions.includes(ext)) {
        setUploadedFile(file);
      } else {
        alert('Please upload a video file (.mp4, .mov, .webm, or .mkv)');
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setUploadedFile(e.target.files[0]);
    }
  };

  const addCustomAd = () => {
    setCustomAds([
      ...customAds,
      {
        id: `brand_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
        brandName: '',
        positiveContexts: '',
        negativeContexts: '',
        file: null,
      },
    ]);
  };

  const removeCustomAd = (id: string) => {
    setCustomAds(customAds.filter((ad) => ad.id !== id));
  };

  const updateCustomAd = (id: string, field: keyof CustomAd, value: any) => {
    setCustomAds(
      customAds.map((ad) => (ad.id === id ? { ...ad, [field]: value } : ad))
    );
  };

  const loadDemoJson = () => {
    const demoJson = [
      {
        "brand_id": "brand_a",
        "display_name": "Brand A",
        "category": "food/spices/cooking",
        "target_contexts": ["cooking", "kitchen", "eating", "family meal", "recipe", "food preparation", "spices", "seasoning", "frying", "boiling", "homemade food", "lunch", "dinner", "festival food"],
        "negative_contexts": ["funeral", "hospital", "violence", "illness", "bathroom", "accident", "grief"],
        "creatives": [{ "id": "a_15s_bn", "duration_sec": 15, "language": "bn", "url": "ads/brand_a/a_15s_bn.mp4" }]
      },
      {
        "brand_id": "brand_b",
        "display_name": "Brand B",
        "category": "personal care/skincare",
        "target_contexts": ["face wash", "skincare", "bathroom", "morning routine", "hair care", "sweating", "heat", "shower", "washing face", "moisturizer", "cream", "personal hygiene", "self care", "getting ready"],
        "negative_contexts": ["funeral", "violence", "eating", "accident", "hospital", "grief"]
      },
      {
        "brand_id": "brand_c",
        "display_name": "Brand C",
        "category": "beauty/cosmetics",
        "target_contexts": ["make-up", "getting ready", "wedding", "party", "mirror", "fashion", "salon", "lipstick", "foundation", "eyeliner", "beauty", "dressing", "celebration", "special occasion"],
        "negative_contexts": ["funeral", "violence", "illness", "accident", "hospital", "grief"]
      },
      {
        "brand_id": "brand_d",
        "display_name": "Brand D",
        "category": "beverage/soft drinks",
        "target_contexts": ["drinking", "party", "celebration", "thirst", "summer", "friends", "meal", "refreshment", "sports", "outdoor", "picnic", "cafe", "restaurant"],
        "negative_contexts": ["funeral", "hospital", "violence", "illness", "accident", "grief", "sleeping"]
      },
      {
        "brand_id": "brand_e",
        "display_name": "Brand E",
        "category": "technology/gadgets",
        "target_contexts": ["smartphone", "laptop", "office", "working", "gaming", "music", "watching video", "technology", "online", "communication", "gadget", "headphones", "typing"],
        "negative_contexts": ["funeral", "violence", "illness", "accident", "hospital", "grief", "nature walk"]
      },
      {
        "brand_id": "brand_f",
        "display_name": "Brand F",
        "category": "home cleaning",
        "target_contexts": ["cleaning", "sweeping", "washing", "kitchen", "bathroom", "dirty", "stain", "dusting", "tidying", "household chores", "laundry", "floor", "mess"],
        "negative_contexts": ["funeral", "hospital", "violence", "eating", "accident", "grief", "party"]
      },
      {
        "brand_id": "brand_g",
        "display_name": "Brand G",
        "category": "travel/booking",
        "target_contexts": ["vacation", "airport", "beach", "mountains", "hotel", "luggage", "sightseeing", "tourist", "traveling", "road trip", "flight", "holiday", "train"],
        "negative_contexts": ["funeral", "hospital", "violence", "illness", "accident", "grief", "office"]
      },
      {
        "brand_id": "brand_h",
        "display_name": "Brand H",
        "category": "fitness/sports",
        "target_contexts": ["gym", "running", "yoga", "workout", "exercise", "sports", "sweating", "weights", "fitness", "training", "stretching", "athlete", "jogging", "healthy"],
        "negative_contexts": ["funeral", "hospital", "violence", "illness", "accident", "grief", "eating junk food"]
      }
    ];

    const mappedAds: CustomAd[] = demoJson.map(b => ({
      id: b.brand_id,
      brandName: b.display_name,
      category: b.category,
      positiveContexts: b.target_contexts.join(', '),
      negativeContexts: b.negative_contexts.join(', '),
      file: null,
      duration: (b as any).creatives?.[0]?.duration_sec || 15,
      clickThroughUrl: `https://www.${b.brand_id.replace('_', '')}.example.com`,
    }));

    setCustomAds(mappedAds);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const config: PipelineConfig = {
      safety_window_seconds: safetyWindow,
      min_gap_seconds: minGap,
      max_breaks_per_hour: maxBreaks,
      ad_load_pct: adLoadPct,
    };

    let customBrands: Brand[] | undefined = undefined;

    if (customAds.length > 0) {
      setIsUploadingAds(true);
      try {
        const brands: Brand[] = [];
        for (const ad of customAds) {
          if (!ad.brandName) continue; // skip empty
          let filename = '';
          if (ad.file) {
            const uploaded = await uploadAdFile(ad.file);
            filename = uploaded.filename;
          }
          brands.push({
            id: ad.id,
            name: ad.brandName,
            category: ad.category || 'Custom Brand',
            positive_contexts: ad.positiveContexts.split(',').map((s) => s.trim()).filter(Boolean),
            negative_contexts: ad.negativeContexts.split(',').map((s) => s.trim()).filter(Boolean),
            creative_url: '',
            ad_creative_file: filename || undefined,
            duration_seconds: ad.duration,
            click_through_url: ad.clickThroughUrl,
          });
        }
        if (brands.length > 0) {
          customBrands = brands;
        }
      } catch (err) {
        console.error("Failed to upload custom ads", err);
        alert("Failed to upload custom ads. Please try again.");
        setIsUploadingAds(false);
        return;
      }
      setIsUploadingAds(false);
    }

    onStart({ file: uploadedFile, config, customBrands });
  };

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-8 animate-fade-in">
      {/* Hero / Explainer Banner */}
      <div className="text-center max-w-3xl mx-auto space-y-3">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/60 border border-cyan-800 text-cyan-400 text-xs font-semibold uppercase tracking-wider">
          <Sparkles className="w-3.5 h-3.5 text-cyan-300" />
          <span>Zero Mid-Speech Cuts • 100% Brand Safety</span>
        </div>
        <h2 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white">
          Context-Aware Video Segmentation & Ad Placement
        </h2>
        <p className="text-sm sm:text-base text-slate-400">
          Ingest raw video, identify natural scene breaks with PySceneDetect & TransNetV2, gate mid-speech cuts with Silero VAD, and contextually match advertisers via Gemini with GARM safety hard-gating.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Column: Upload and Custom Ads */}
        <div className="lg:col-span-2 space-y-6">
          <div className="space-y-4">
            <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
              <UploadCloud className="w-4 h-4 text-cyan-400" />
              Custom Video Upload
            </h3>

            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed rounded-2xl p-8 sm:p-12 text-center cursor-pointer transition flex flex-col items-center justify-center gap-4 ${
                dragActive
                  ? 'border-cyan-400 bg-cyan-950/30'
                  : uploadedFile
                  ? 'border-emerald-500/70 bg-emerald-950/20'
                  : 'border-slate-800 bg-slate-900/40 hover:border-slate-700 hover:bg-slate-900/60'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="video/mp4,video/quicktime,video/webm,video/x-matroska"
                onChange={handleFileChange}
                className="hidden"
              />

              {uploadedFile ? (
                <div className="space-y-2">
                  <div className="w-14 h-14 rounded-2xl bg-emerald-950 border border-emerald-500/50 flex items-center justify-center text-emerald-400 mx-auto">
                    <FileVideo className="w-7 h-7" />
                  </div>
                  <div className="font-semibold text-white text-base">{uploadedFile.name}</div>
                  <div className="text-xs text-slate-400 font-mono">
                    {formatBytes(uploadedFile.size)} • Ready for ingestion
                  </div>
                  <p className="text-xs text-cyan-400 hover:underline pt-2">Click or drop to replace</p>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="w-14 h-14 rounded-2xl bg-slate-800/80 border border-slate-700 flex items-center justify-center text-cyan-400 mx-auto">
                    <UploadCloud className="w-7 h-7" />
                  </div>
                  <p className="font-semibold text-white text-sm">
                    Drag and drop your video here, or <span className="text-cyan-400">browse</span>
                  </p>
                  <p className="text-xs text-slate-400">
                    Supports MP4, MOV, WEBM, MKV (Arbitrary duration)
                  </p>
                </div>
              )}
            </div>
          </div>

          <div className="space-y-4 pt-4 border-t border-slate-800">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                <Database className="w-4 h-4 text-cyan-400" />
                Custom Ads
              </h3>
              <div className="flex gap-2">
                <button
                  onClick={loadDemoJson}
                  className="flex items-center gap-1.5 px-3 py-1 rounded bg-indigo-900/60 hover:bg-indigo-800 text-xs font-semibold text-indigo-300 transition"
                >
                  <Database className="w-3.5 h-3.5" /> Load Text-Only Demo JSON
                </button>
                <button
                  onClick={addCustomAd}
                  className="flex items-center gap-1.5 px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-cyan-400 transition"
                >
                  <Plus className="w-3.5 h-3.5" /> Add Brand
                </button>
              </div>
            </div>
            {customAds.length === 0 ? (
              <p className="text-xs text-slate-500 italic">
                No custom ads added. The system will fall back to using the default demo ads catalog.
              </p>
            ) : (
              <div className="space-y-4">
                {customAds.map((ad, idx) => (
                  <div key={ad.id} className="p-4 rounded-xl border border-slate-700 bg-slate-900/60 relative">
                    <button
                      onClick={() => removeCustomAd(ad.id)}
                      className="absolute top-4 right-4 text-slate-500 hover:text-rose-400 transition"
                      title="Remove Ad"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    <div className="space-y-3 mr-8">
                      <div>
                        <label className="block text-xs font-semibold text-slate-400 mb-1">Brand Name</label>
                        <input
                          type="text"
                          value={ad.brandName}
                          onChange={(e) => updateCustomAd(ad.id, 'brandName', e.target.value)}
                          placeholder="e.g., Zenith Motors"
                          className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold text-slate-400 mb-1">Positive Contexts (comma-separated)</label>
                        <input
                          type="text"
                          value={ad.positiveContexts}
                          onChange={(e) => updateCustomAd(ad.id, 'positiveContexts', e.target.value)}
                          placeholder="e.g., luxury, driving, electric, automotive"
                          className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold text-slate-400 mb-1">Negative Contexts (comma-separated)</label>
                        <input
                          type="text"
                          value={ad.negativeContexts}
                          onChange={(e) => updateCustomAd(ad.id, 'negativeContexts', e.target.value)}
                          placeholder="e.g., accident, crime, violence"
                          className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-sm text-white focus:outline-none focus:border-cyan-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-semibold text-slate-400 mb-1">Ad Creative (.mp4)</label>
                        <input
                          type="file"
                          accept="video/mp4"
                          onChange={(e) => updateCustomAd(ad.id, 'file', e.target.files ? e.target.files[0] : null)}
                          className="w-full text-sm text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-slate-800 file:text-cyan-400 hover:file:bg-slate-700 transition"
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Parameters & Brand Drawer Trigger */}
        <div className="space-y-6">
          <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-6 shadow-xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-xs font-bold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                <Sliders className="w-4 h-4 text-cyan-400" />
                Pipeline Tuning Controls
              </h3>
              <button
                type="button"
                onClick={() => setBrandDrawerOpen(true)}
                className="flex items-center gap-1.5 text-xs text-cyan-400 hover:text-cyan-300 font-semibold transition"
              >
                <Database className="w-3.5 h-3.5" />
                <span>Brand Rules</span>
              </button>
            </div>

            {/* Slider 1: Silence Safety Window (±N seconds) */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                  <Volume2 className="w-3.5 h-3.5 text-cyan-400" />
                  Silence Safety Window (±N s)
                </label>
                <span className="text-xs font-mono font-bold text-cyan-400 bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-800/60">
                  ±{safetyWindow.toFixed(2)}s
                </span>
              </div>
              <input
                type="range"
                min="0.1"
                max="5.0"
                step="0.05"
                value={safetyWindow}
                onChange={(e) => setSafetyWindow(parseFloat(e.target.value))}
                className="w-full accent-cyan-500 cursor-pointer h-1.5 bg-slate-800 rounded-lg"
              />
              <p className="text-[11px] text-slate-400 leading-tight">
                Rejects candidate cuts if speech is within ±{safetyWindow.toFixed(2)}s. Guarantees 0 mid-speech cuts.
              </p>
            </div>

            {/* Slider 2: Min Gap Between Breaks */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5 text-cyan-400" />
                  Min Gap Between Breaks
                </label>
                <span className="text-xs font-mono font-bold text-cyan-400 bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-800/60">
                  {minGap}s
                </span>
              </div>
              <input
                type="range"
                min="10"
                max="300"
                step="5"
                value={minGap}
                onChange={(e) => setMinGap(parseInt(e.target.value, 10))}
                className="w-full accent-cyan-500 cursor-pointer h-1.5 bg-slate-800 rounded-lg"
              />
              <p className="text-[11px] text-slate-400 leading-tight">
                Enforces minimum viewer comfort buffer between consecutive commercial breaks.
              </p>
            </div>

            {/* Slider 3: Max Breaks / Hour */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                  <Layers className="w-3.5 h-3.5 text-cyan-400" />
                  Max Breaks / Hour
                </label>
                <span className="text-xs font-mono font-bold text-cyan-400 bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-800/60">
                  {maxBreaks}
                </span>
              </div>
              <input
                type="range"
                min="1"
                max="20"
                step="1"
                value={maxBreaks}
                onChange={(e) => setMaxBreaks(parseInt(e.target.value, 10))}
                className="w-full accent-cyan-500 cursor-pointer h-1.5 bg-slate-800 rounded-lg"
              />
              <p className="text-[11px] text-slate-400 leading-tight">
                Broadcast frequency cap limiting total commercial breaks per hour.
              </p>
            </div>

            {/* Slider 4: Ad Load % */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5 text-cyan-400" />
                  Target Ad Load
                </label>
                <span className="text-xs font-mono font-bold text-cyan-400 bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-800/60">
                  {adLoadPct}%
                </span>
              </div>
              <input
                type="range"
                min="1"
                max="50"
                step="1"
                value={adLoadPct}
                onChange={(e) => setAdLoadPct(parseInt(e.target.value, 10))}
                className="w-full accent-cyan-500 cursor-pointer h-1.5 bg-slate-800 rounded-lg"
              />
              <p className="text-[11px] text-slate-400 leading-tight">
                Maximum commercial ad load percentage of total program runtime.
              </p>
            </div>

            {/* Start Pipeline Button */}
            <button
              type="button"
              onClick={handleSubmit}
              disabled={isLoading || isUploadingAds || !uploadedFile}
              className="w-full py-3.5 bg-gradient-to-r from-cyan-500 via-indigo-600 to-cyan-500 bg-size-200 hover:bg-pos-100 text-white font-bold rounded-xl text-sm shadow-xl shadow-cyan-900/30 flex items-center justify-center gap-2 transition-all disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
            >
              <span>{isUploadingAds ? 'Uploading Ads...' : isLoading ? 'Executing Pipeline...' : 'Run Cutaway Pipeline'}</span>
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Dynamic Brand Catalogue Drawer */}
      <BrandCatalogueDrawer
        isOpen={brandDrawerOpen}
        onClose={() => setBrandDrawerOpen(false)}
      />
    </div>
  );
};
