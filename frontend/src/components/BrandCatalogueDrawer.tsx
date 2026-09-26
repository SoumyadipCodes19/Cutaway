'use client';

import React, { useState, useEffect } from 'react';
import { X, ShieldAlert, Sparkles, Plus, CheckCircle2, AlertTriangle, Database } from 'lucide-react';
import { Brand } from '@/types/pipeline';
import { fetchBrands, registerBrand } from '@/lib/api';

const DEFAULT_9TH_BRAND: Brand = {
  id: 'cyber_shield_security',
  name: 'CyberShield Defense',
  category: 'Cybersecurity & IT Infrastructure',
  positive_contexts: [
    'cybersecurity',
    'tech',
    'computers',
    'coding',
    'data_center',
    'encryption',
    'privacy',
  ],
  negative_contexts: [
    'terrorism',
    'hate_speech',
    'adult_content',
    'death_injury',
    'military_conflict',
  ],
  creative_url: 'ads/cyber_shield.mp4',
  ad_creative_file: 'ads/cyber_shield.mp4',
  duration_seconds: 15,
  click_through_url: 'https://cybershield.example.com',
};

interface BrandCatalogueDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  onBrandInjected?: (brand: Brand) => void;
}

export const BrandCatalogueDrawer: React.FC<BrandCatalogueDrawerProps> = ({
  isOpen,
  onClose,
  onBrandInjected,
}) => {
  const [brands, setBrands] = useState<Brand[]>([]);
  const [loading, setLoading] = useState(false);
  const [injecting, setInjecting] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Custom brand form state
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [formId, setFormId] = useState('');
  const [formName, setFormName] = useState('');
  const [formCategory, setFormCategory] = useState('');
  const [formPositives, setFormPositives] = useState('');
  const [formNegatives, setFormNegatives] = useState('');

  const loadBrands = async () => {
    setLoading(true);
    try {
      const data = await fetchBrands();
      setBrands(data);
    } catch (e: any) {
      console.warn('Could not load brands from server, using fallback', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      loadBrands();
    }
  }, [isOpen]);

  const handleInject9thBrand = async () => {
    setInjecting(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    try {
      const injected = await registerBrand(DEFAULT_9TH_BRAND);
      setSuccessMsg(`Successfully registered 9th brand: "${injected.name}"! Zero code change required.`);
      await loadBrands();
      if (onBrandInjected) onBrandInjected(injected);
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to inject brand');
    } finally {
      setInjecting(false);
    }
  };

  const handleCreateCustomBrand = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formId.trim() || !formName.trim()) {
      setErrorMsg('Brand ID and Name are required');
      return;
    }

    setInjecting(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    const newBrand: Brand = {
      id: formId.trim().toLowerCase().replace(/\s+/g, '_'),
      name: formName.trim(),
      category: formCategory.trim() || 'General Commercial',
      positive_contexts: formPositives
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean),
      negative_contexts: formNegatives
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter(Boolean),
      creative_url: 'ads/apex_athletics.mp4',
      duration_seconds: 15,
    };

    try {
      const injected = await registerBrand(newBrand);
      setSuccessMsg(`Brand "${injected.name}" created successfully!`);
      setShowCustomForm(false);
      setFormId('');
      setFormName('');
      setFormCategory('');
      setFormPositives('');
      setFormNegatives('');
      await loadBrands();
      if (onBrandInjected) onBrandInjected(injected);
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to create brand');
    } finally {
      setInjecting(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-2xl bg-slate-900 border-l border-slate-800 h-full flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between bg-slate-900/90">
          <div className="flex items-center gap-2.5">
            <Database className="w-5 h-5 text-cyan-400" />
            <div>
              <h2 className="text-base font-bold text-white">Brand Catalogue & Safety Rules</h2>
              <p className="text-xs text-slate-400">
                {brands.length} Active Advertisers with Contextual & GARM Gating Rules
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

        {/* Action bar / Inject 9th brand */}
        <div className="p-4 bg-slate-950/60 border-b border-slate-800 flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
          <button
            onClick={handleInject9thBrand}
            disabled={injecting}
            className="flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white rounded-lg text-xs font-semibold shadow-lg shadow-cyan-900/30 transition disabled:opacity-50"
          >
            <Sparkles className="w-4 h-4 text-cyan-200" />
            <span>{injecting ? 'Injecting...' : 'Inject 9th Brand (CyberShield Defense)'}</span>
          </button>

          <button
            onClick={() => setShowCustomForm(!showCustomForm)}
            className="flex items-center justify-center gap-1.5 px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-medium transition"
          >
            <Plus className="w-4 h-4" />
            <span>{showCustomForm ? 'Cancel Custom Form' : 'Add Custom Brand'}</span>
          </button>
        </div>

        {/* Feedback Alerts */}
        {successMsg && (
          <div className="mx-6 mt-4 p-3 bg-emerald-950/60 border border-emerald-500/50 rounded-lg flex items-center gap-2 text-xs text-emerald-200">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successMsg}</span>
          </div>
        )}
        {errorMsg && (
          <div className="mx-6 mt-4 p-3 bg-rose-950/60 border border-rose-500/50 rounded-lg flex items-center gap-2 text-xs text-rose-200">
            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* Custom Brand Form */}
        {showCustomForm && (
          <form onSubmit={handleCreateCustomBrand} className="p-6 border-b border-slate-800 bg-slate-950/80 space-y-3">
            <h3 className="text-xs font-bold uppercase tracking-wider text-cyan-400">
              Inject Dynamic Brand (Zero-Code Test)
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] text-slate-400 block mb-1">Brand ID</label>
                <input
                  type="text"
                  placeholder="e.g. quantum_beverages"
                  value={formId}
                  onChange={(e) => setFormId(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-cyan-500"
                  required
                />
              </div>
              <div>
                <label className="text-[11px] text-slate-400 block mb-1">Brand Name</label>
                <input
                  type="text"
                  placeholder="e.g. Quantum Energy"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-cyan-500"
                  required
                />
              </div>
            </div>
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">Category</label>
              <input
                type="text"
                placeholder="e.g. Energy Drinks & Wellness"
                value={formCategory}
                onChange={(e) => setFormCategory(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">
                Positive Contexts (comma-separated tags)
              </label>
              <input
                type="text"
                placeholder="sports, fitness, energy, gaming, workout"
                value={formPositives}
                onChange={(e) => setFormPositives(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="text-[11px] text-slate-400 block mb-1">
                Negative Contexts (Hard Gate triggers, comma-separated)
              </label>
              <input
                type="text"
                placeholder="death_injury, crime_illegal, substance_abuse"
                value={formNegatives}
                onChange={(e) => setFormNegatives(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
            <button
              type="submit"
              disabled={injecting}
              className="w-full py-2 bg-cyan-600 hover:bg-cyan-500 text-white rounded text-xs font-semibold transition"
            >
              Register Brand to Server
            </button>
          </form>
        )}

        {/* Brand List */}
        <div className="flex-1 overflow-y-auto p-6 space-y-3.5">
          {loading ? (
            <div className="text-center py-12 text-slate-500 text-xs">Loading catalogue...</div>
          ) : brands.length === 0 ? (
            <div className="text-center py-12 text-slate-500 text-xs">No brands found.</div>
          ) : (
            brands.map((b) => (
              <div
                key={b.id}
                className={`p-4 rounded-xl border transition ${
                  b.id === 'cyber_shield_security'
                    ? 'bg-cyan-950/40 border-cyan-500/60 shadow-lg shadow-cyan-950/50'
                    : 'bg-slate-950/40 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm text-white">{b.name}</span>
                      {b.id === 'cyber_shield_security' && (
                        <span className="text-[9px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-full bg-cyan-900/80 text-cyan-300 border border-cyan-500/40">
                          Unseen 9th Brand
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-slate-400">{b.category}</span>
                  </div>
                  <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                    {b.id}
                  </span>
                </div>

                {/* Positive Contexts */}
                <div className="mb-2">
                  <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider block mb-1">
                    Positive Contexts (+Affinity)
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {b.positive_contexts.map((pc, i) => (
                      <span
                        key={i}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-800/60"
                      >
                        {pc}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Negative Contexts (Hard Gates) */}
                <div>
                  <span className="text-[10px] font-semibold text-rose-400 uppercase tracking-wider block mb-1 flex items-center gap-1">
                    <ShieldAlert className="w-3 h-3 text-rose-400" />
                    Negative Contexts (Hard Gate: -∞)
                  </span>
                  <div className="flex flex-wrap gap-1">
                    {b.negative_contexts.map((nc, i) => (
                      <span
                        key={i}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-rose-950/60 text-rose-300 border border-rose-800/60"
                      >
                        {nc}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
};
