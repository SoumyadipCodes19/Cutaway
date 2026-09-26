'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize,
  Sparkles,
  Award,
  AlertCircle,
  Film,
} from 'lucide-react';
import { formatTimecode } from '@/lib/formatters';

interface DemoPlayerProps {
  contentVideoUrl: string;
  vmapUrl: string;
  currentTime: number;
  onTimeUpdate: (time: number) => void;
  onDurationChange?: (duration: number) => void;
}

export const DemoPlayer: React.FC<DemoPlayerProps> = ({
  contentVideoUrl,
  vmapUrl,
  currentTime,
  onTimeUpdate,
  onDurationChange,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const adContainerRef = useRef<HTMLDivElement>(null);
  const playerWrapperRef = useRef<HTMLDivElement>(null);

  // Player State
  const [isPlaying, setIsPlaying] = useState(false);
  const [isAdPlaying, setIsAdPlaying] = useState(false);
  const [currentAdTitle, setCurrentAdTitle] = useState<string>('Contextually Matched Ad');
  const [adDuration, setAdDuration] = useState<number>(15);
  const [adTimeRemaining, setAdTimeRemaining] = useState<number>(15);
  const [adClickUrl, setAdClickUrl] = useState<string>('');
  const [isMuted, setIsMuted] = useState(false);
  const [duration, setDuration] = useState<number>(38);
  const [imaInitialized, setImaInitialized] = useState(false);
  const [imaStatusText, setImaStatusText] = useState<string>('Ready to initialize IMA SDK');

  // Google IMA SDK references
  const adDisplayContainerRef = useRef<any>(null);
  const adsLoaderRef = useRef<any>(null);
  const adsManagerRef = useRef<any>(null);

  // Sync external seek requests from timeline
  useEffect(() => {
    if (videoRef.current && Math.abs(videoRef.current.currentTime - currentTime) > 0.5) {
      if (!isAdPlaying) {
        videoRef.current.currentTime = currentTime;
      }
    }
  }, [currentTime, isAdPlaying]);

  // Handle Video Time Update
  const handleTimeUpdate = () => {
    if (videoRef.current && !isAdPlaying) {
      onTimeUpdate(videoRef.current.currentTime);
    }
  };

  const handleLoadedMetadata = () => {
    if (videoRef.current) {
      const dur = videoRef.current.duration || 38;
      setDuration(dur);
      if (onDurationChange) onDurationChange(dur);
    }
  };

  // Google IMA SDK Setup & VMAP Request
  const initializeImaAndPlay = useCallback(async () => {
    if (typeof window === 'undefined' || !window.google?.ima) {
      console.warn('Google IMA SDK (window.google.ima) not yet loaded, starting direct playback.');
      setImaStatusText('IMA SDK unavailable, playing video directly');
      videoRef.current?.play();
      setIsPlaying(true);
      return;
    }

    if (!adContainerRef.current || !videoRef.current) return;

    try {
      setImaStatusText('Initializing Google IMA AdDisplayContainer...');

      // 1. Create AdDisplayContainer and initialize with user gesture
      if (!adDisplayContainerRef.current) {
        adDisplayContainerRef.current = new window.google.ima.AdDisplayContainer(
          adContainerRef.current,
          videoRef.current
        );
      }
      adDisplayContainerRef.current.initialize();

      // 2. Create AdsLoader
      if (!adsLoaderRef.current) {
        adsLoaderRef.current = new window.google.ima.AdsLoader(adDisplayContainerRef.current);

        // Listen for manager loaded
        adsLoaderRef.current.addEventListener(
          window.google.ima.AdsManagerLoadedEvent.Type.ADS_MANAGER_LOADED,
          (event: any) => {
            const adsRenderingSettings = new window.google!.ima.AdsRenderingSettings();
            adsRenderingSettings.restoreCustomPlaybackStateOnAdBreakComplete = true;

            const adsManager = event.getAdsManager(videoRef.current, adsRenderingSettings);
            adsManagerRef.current = adsManager;

            // Register Ad Event Listeners
            adsManager.addEventListener(
              window.google!.ima.AdEvent.Type.CONTENT_PAUSE_REQUESTED,
              () => {
                setImaStatusText('Ad Break Triggered! Pausing content video...');
                setIsAdPlaying(true);
                videoRef.current?.pause();
              }
            );

            adsManager.addEventListener(
              window.google!.ima.AdEvent.Type.CONTENT_RESUME_REQUESTED,
              () => {
                setImaStatusText('Ad Break Completed! Resuming main video...');
                setIsAdPlaying(false);
                videoRef.current?.play();
                setIsPlaying(true);
              }
            );

            adsManager.addEventListener(window.google!.ima.AdEvent.Type.STARTED, (adEvt: any) => {
              const ad = adEvt.getAd();
              if (ad) {
                const title = ad.getTitle() || 'Matched Brand Ad Creative';
                const dur = ad.getDuration() || 15;
                const desc = ad.getDescription() || 'https://example.com';
                setCurrentAdTitle(title);
                setAdDuration(dur);
                setAdTimeRemaining(dur);
                setAdClickUrl(desc);
                setImaStatusText(`Playing Ad: "${title}" (${dur}s)`);
              }
            });

            adsManager.addEventListener(window.google!.ima.AdEvent.Type.COMPLETE, () => {
              setIsAdPlaying(false);
            });

            adsManager.addEventListener(window.google!.ima.AdEvent.Type.ALL_ADS_COMPLETED, () => {
              setIsAdPlaying(false);
            });

            adsManager.addEventListener(
              window.google!.ima.AdErrorEvent.Type.AD_ERROR,
              (errEvt: any) => {
                console.warn('Google IMA Ad Error:', errEvt.getError());
                setImaStatusText(`Ad Error: ${errEvt.getError()?.getMessage() || 'Recovering content'}`);
                setIsAdPlaying(false);
                videoRef.current?.play();
                setIsPlaying(true);
              }
            );

            // Initialize adsManager
            const width = playerWrapperRef.current?.clientWidth || 1280;
            const height = playerWrapperRef.current?.clientHeight || 720;
            adsManager.init(width, height, window.google!.ima.ViewMode.NORMAL);
            adsManager.start();

            // Start main content video
            videoRef.current?.play();
            setIsPlaying(true);
            setImaStatusText('VMAP loaded. Playing content video with scheduled mid-rolls.');
          }
        );

        adsLoaderRef.current.addEventListener(
          window.google.ima.AdErrorEvent.Type.AD_ERROR,
          (adErrorEvt: any) => {
            console.warn('Google IMA AdsLoader Error:', adErrorEvt.getError());
            setImaStatusText('AdsLoader error, bypassing to direct content playback.');
            videoRef.current?.play();
            setIsPlaying(true);
          }
        );
      }

      // 3. Request VMAP manifest
      const adsRequest = new window.google.ima.AdsRequest();
      const finalVmapUrl = vmapUrl.startsWith('http')
        ? vmapUrl
        : `${window.location.origin}${vmapUrl}`;

      try {
        setImaStatusText('Fetching and inlining VMAP/VAST manifests...');
        const vmapResponse = await fetch(finalVmapUrl);
        let vmapXml = await vmapResponse.text();

        // Check for AdTagURI to inline VAST
        const adTagRegex = /<vmap:AdTagURI[^>]*>([\s\S]*?)<\/vmap:AdTagURI>/gi;
        let match;
        const matches: RegExpExecArray[] = [];
        while ((match = adTagRegex.exec(vmapXml)) !== null) {
          matches.push(match);
        }
        
        for (const match of matches) {
          let vastUrl = match[1].trim();
          // CDATA extraction if needed
          if (vastUrl.startsWith('<![CDATA[') && vastUrl.endsWith(']]>')) {
            vastUrl = vastUrl.substring(9, vastUrl.length - 3).trim();
          }
          
          try {
            const vastResponse = await fetch(vastUrl);
            let vastXml = await vastResponse.text();
            
            // Strip <?xml ... ?> from VAST
            vastXml = vastXml.replace(/<\?xml.*?\?>\s*/g, '');
            
            // Strip out <TrackingEvents>, <Impression>, and <Error> to avoid PNA/CORS blocks
            // Use robust regex that handles both `<Tag>...</Tag>` and self-closing `<Tag/>`
            vastXml = vastXml.replace(/<TrackingEvents[^>]*>(?:[\s\S]*?<\/TrackingEvents>|\s*\/>)/gi, '');
            vastXml = vastXml.replace(/<Impression[^>]*>(?:[\s\S]*?<\/Impression>|\s*\/>)/gi, '');
            vastXml = vastXml.replace(/<Error[^>]*>(?:[\s\S]*?<\/Error>|\s*\/>)/gi, '');
            
            // Extract MediaFile URL and inline as Base64 Data URI
            const mediaFileRegex = /<MediaFile[^>]*>\s*<!\[CDATA\[([\s\S]*?)\]\]>\s*<\/MediaFile>/i;
            const mediaMatch = vastXml.match(mediaFileRegex);
            
            if (mediaMatch && mediaMatch[1]) {
              const mediaUrl = mediaMatch[1].trim();
              try {
                const mediaResponse = await fetch(mediaUrl);
                const mediaBlob = await mediaResponse.blob();
                
                const base64DataUri = await new Promise<string>((resolve, reject) => {
                  const reader = new FileReader();
                  reader.onloadend = () => resolve(reader.result as string);
                  reader.onerror = reject;
                  reader.readAsDataURL(mediaBlob);
                });
                
                // Use a replacer function to avoid `$1`/`$&` evaluation bugs if base64 contains special patterns
                vastXml = vastXml.replace(mediaUrl, () => base64DataUri);
              } catch (err) {
                console.warn('Failed to fetch and inline media file:', err);
              }
            }
            
            // Replace <vmap:AdTagURI> with <vmap:VASTAdData>
            // Use a replacer function to avoid `$1`/`$&` evaluation bugs if vastXml contains special patterns
            vmapXml = vmapXml.replace(
              match[0],
              () => `<vmap:VASTAdData>\n${vastXml}\n</vmap:VASTAdData>`
            );
          } catch (e) {
            console.warn('Failed to fetch/inline VAST from:', vastUrl, e);
          }
        }
        
        (adsRequest as any).adsResponse = vmapXml;
      } catch (err) {
        console.warn('Failed to inline VMAP/VAST, falling back to adTagUrl:', err);
        adsRequest.adTagUrl = finalVmapUrl;
      }

      adsRequest.linearAdSlotWidth = playerWrapperRef.current?.clientWidth || 1280;
      adsRequest.linearAdSlotHeight = playerWrapperRef.current?.clientHeight || 720;

      adsLoaderRef.current.requestAds(adsRequest);
      setImaInitialized(true);
    } catch (err: any) {
      console.error('Error initializing Google IMA SDK:', err);
      setImaStatusText('Error loading IMA SDK, playing directly');
      videoRef.current?.play();
      setIsPlaying(true);
    }
  }, [vmapUrl]);

  // Clean up IMA on unmount
  useEffect(() => {
    return () => {
      try {
        if (adsManagerRef.current) {
          adsManagerRef.current.destroy();
        }
        if (adsLoaderRef.current) {
          adsLoaderRef.current.destroy();
        }
      } catch (e) {
        // ignore cleanup error
      }
    };
  }, []);

  const togglePlay = () => {
    if (!imaInitialized) {
      initializeImaAndPlay();
      return;
    }

    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
      setIsPlaying(false);
    } else {
      videoRef.current.play();
      setIsPlaying(true);
    }
  };

  const toggleMute = () => {
    if (videoRef.current) {
      videoRef.current.muted = !isMuted;
      setIsMuted(!isMuted);
    }
  };

  const toggleFullscreen = () => {
    if (playerWrapperRef.current) {
      if (document.fullscreenElement) {
        document.exitFullscreen();
      } else {
        playerWrapperRef.current.requestFullscreen();
      }
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
      {/* Player Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 pb-2">
        <div className="flex items-center gap-2">
          <Film className="w-5 h-5 text-cyan-400" />
          <h2 className="text-base font-bold text-white">
            Demo Player (Google IMA HTML5 SDK Integration)
          </h2>
        </div>
        <div className="flex items-center gap-2 text-xs font-mono">
          <span className="text-slate-400">VMAP Manifest:</span>
          <a
            href={vmapUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-cyan-400 hover:underline truncate max-w-[200px]"
          >
            {vmapUrl}
          </a>
        </div>
      </div>

      {/* Video & IMA Container */}
      <div
        ref={playerWrapperRef}
        className="relative w-full aspect-video bg-black rounded-xl overflow-hidden shadow-2xl border border-slate-800 group"
      >
        {/* Content Video Element */}
        <video
          ref={videoRef}
          src={contentVideoUrl}
          playsInline
          preload="auto"
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={handleLoadedMetadata}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
          className="w-full h-full object-contain"
        />

        {/* Google IMA Ad Display Container Overlay */}
        <div
          ref={adContainerRef}
          id="ad-container"
          className={`absolute inset-0 transition-opacity ${
            isAdPlaying
              ? 'pointer-events-auto opacity-100 z-20'
              : 'pointer-events-none opacity-0 z-10'
          }`}
        />

        {/* Ad Status HUD Overlay & Prominent Center Overlay */}
        {isAdPlaying && (
          <>
            <div className="absolute top-4 left-4 z-30 flex items-center gap-3 bg-black/85 backdrop-blur-md border border-amber-500/70 px-4 py-2.5 rounded-xl text-white shadow-2xl animate-fade-in">
              <div className="w-3 h-3 rounded-full bg-amber-400 animate-ping" />
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-amber-400">
                    Ad Break in Progress (Google IMA)
                  </span>
                  <span className="text-[10px] font-mono bg-amber-950/80 px-1.5 py-0.2 rounded border border-amber-500/40 text-amber-300">
                    {adDuration}s Commercial
                  </span>
                </div>
                <p className="text-xs font-semibold text-white truncate max-w-xs">
                  {currentAdTitle}
                </p>
              </div>
            </div>
            
            {/* Prominent text-only overlay covering the video center */}
            <div className="absolute inset-0 z-[9999] flex items-center justify-center pointer-events-auto bg-black animate-fade-in">
              <div className="bg-slate-900 border-2 border-cyan-500/50 p-8 rounded-3xl shadow-2xl text-center max-w-lg w-full transform transition-all">
                <div className="inline-flex items-center justify-center p-3 bg-cyan-950 rounded-full mb-4">
                  <Award className="w-8 h-8 text-cyan-400" />
                </div>
                <h2 className="text-3xl font-extrabold text-white mb-2 tracking-tight">
                  {currentAdTitle}
                </h2>
                <p className="text-slate-300 mb-6 font-medium">
                  This contextual placement brought to you by our sponsor.
                </p>
                <a
                  href={adClickUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center justify-center w-full py-3.5 px-6 rounded-xl bg-gradient-to-r from-cyan-600 to-indigo-600 text-white font-bold shadow-lg shadow-cyan-900/50 hover:brightness-110 transition cursor-pointer"
                >
                  Visit Sponsor Website
                </a>
              </div>
            </div>
          </>
        )}

        {/* Start / Gesture Play Splash Overlay (before first play) */}
        {!isPlaying && !isAdPlaying && !imaInitialized && (
          <div className="absolute inset-0 z-30 bg-black/60 backdrop-blur-sm flex flex-col items-center justify-center p-6 text-center space-y-4">
            <div className="w-16 h-16 rounded-full bg-cyan-600/90 text-white flex items-center justify-center shadow-xl shadow-cyan-900/60 ring-4 ring-cyan-500/30 group-hover:scale-105 transition">
              <Play className="w-8 h-8 ml-1" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-white">Start Demo Playback</h3>
              <p className="text-xs text-slate-300 max-w-md mt-1">
                Initializes Google IMA HTML5 SDK, loads generated IAB VMAP 1.0.1 manifest, and automatically triggers mid-roll brand ads.
              </p>
            </div>
            <button
              onClick={initializeImaAndPlay}
              className="px-6 py-2.5 bg-gradient-to-r from-cyan-500 to-indigo-600 text-white font-bold rounded-xl text-xs shadow-lg shadow-cyan-900/40 transition hover:brightness-110 cursor-pointer"
            >
              Play Video & Execute VMAP
            </button>
          </div>
        )}

        {/* Video Player Controls Bar */}
        <div className="absolute bottom-0 inset-x-0 z-20 bg-gradient-to-t from-black/90 via-black/50 to-transparent p-4 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-between text-white">
          <div className="flex items-center gap-3">
            <button
              onClick={togglePlay}
              className="p-1.5 rounded-lg hover:bg-white/20 transition cursor-pointer"
              title={isPlaying ? 'Pause' : 'Play'}
            >
              {isPlaying ? <Pause className="w-5 h-5" /> : <Play className="w-5 h-5" />}
            </button>

            <button
              onClick={toggleMute}
              className="p-1.5 rounded-lg hover:bg-white/20 transition cursor-pointer"
              title={isMuted ? 'Unmute' : 'Mute'}
            >
              {isMuted ? <VolumeX className="w-5 h-5" /> : <Volume2 className="w-5 h-5" />}
            </button>

            <div className="text-xs font-mono text-slate-300">
              <span>{formatTimecode(videoRef.current?.currentTime || currentTime)}</span>
              <span className="text-slate-500 mx-1">/</span>
              <span>{formatTimecode(duration)}</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="text-[11px] font-mono text-cyan-400 bg-black/60 px-2 py-0.5 rounded border border-slate-800">
              {imaStatusText}
            </div>

            <button
              onClick={toggleFullscreen}
              className="p-1.5 rounded-lg hover:bg-white/20 transition cursor-pointer"
              title="Toggle Fullscreen"
            >
              <Maximize className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
