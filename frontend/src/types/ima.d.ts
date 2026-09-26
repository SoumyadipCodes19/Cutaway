// src/types/ima.d.ts
// Ambient type declarations for Google Interactive Media Ads (IMA) HTML5 SDK

declare namespace google.ima {
  export class AdDisplayContainer {
    constructor(containerElement: HTMLElement, contentVideoElement?: HTMLMediaElement);
    initialize(): void;
    destroy(): void;
  }

  export class AdsLoader {
    constructor(adDisplayContainer: AdDisplayContainer);
    getSettings(): ImaSdkSettings;
    requestAds(adsRequest: AdsRequest): void;
    contentComplete(): void;
    destroy(): void;
    addEventListener(type: string, callback: (event: any) => void, useCapture?: boolean): void;
    removeEventListener(type: string, callback: (event: any) => void): void;
  }

  export class ImaSdkSettings {
    setAutoPlayAdBreaks(autoPlay: boolean): void;
    setVpaidMode(mode: any): void;
    setLocale(locale: string): void;
  }

  export class AdsRequest {
    adTagUrl: string;
    linearAdSlotWidth?: number;
    linearAdSlotHeight?: number;
    nonLinearAdSlotWidth?: number;
    nonLinearAdSlotHeight?: number;
  }

  export class AdsRenderingSettings {
    restoreCustomPlaybackStateOnAdBreakComplete?: boolean;
    useStyledLinearId?: boolean;
  }

  export class AdsManager {
    init(width: number, height: number, viewMode: ViewMode): void;
    start(): void;
    stop(): void;
    pause(): void;
    resume(): void;
    resize(width: number, height: number, viewMode: ViewMode): void;
    destroy(): void;
    addEventListener(type: string, callback: (event: any) => void): void;
    removeEventListener(type: string, callback: (event: any) => void): void;
    getCuePoints(): number[];
  }

  export enum ViewMode {
    NORMAL = 'normal',
    FULLSCREEN = 'fullscreen',
  }

  export class AdsManagerLoadedEvent {
    static readonly Type: {
      ADS_MANAGER_LOADED: string;
    };
    getAdsManager(contentPlayback: any, adsRenderingSettings?: AdsRenderingSettings): AdsManager;
  }

  export class AdEvent {
    static readonly Type: {
      CONTENT_PAUSE_REQUESTED: string;
      CONTENT_RESUME_REQUESTED: string;
      STARTED: string;
      COMPLETE: string;
      ALL_ADS_COMPLETED: string;
      FIRST_QUARTILE: string;
      MIDPOINT: string;
      THIRD_QUARTILE: string;
      CLICK: string;
      PAUSED: string;
      RESUMED: string;
      SKIPPED: string;
    };
    getAd(): Ad;
  }

  export class AdErrorEvent {
    static readonly Type: {
      AD_ERROR: string;
    };
    getError(): {
      getMessage(): string;
      getErrorCode(): number;
    };
  }

  export interface Ad {
    getTitle(): string;
    getDuration(): number;
    getAdId(): string;
    isLinear(): boolean;
  }
}

interface Window {
  google?: {
    ima?: typeof google.ima;
  };
}
