declare module "wavesurfer.js/dist/plugins/regions.esm.js" {
  export type Region = {
    id: string;
    start: number;
    end: number;
    element: HTMLElement | null;
    setOptions(options: Partial<{ color: string; start: number; end: number; drag: boolean; resize: boolean; content: string | HTMLElement; id: string }>): void;
    remove(): void;
  };

  export type RegionParams = {
    id?: string;
    start: number;
    end?: number;
    drag?: boolean;
    resize?: boolean;
    color?: string;
    content?: string | HTMLElement;
    minLength?: number;
  };

  export type RegionsPlugin = {
    getRegions(): Region[];
    addRegion(options: RegionParams): Region;
    clearRegions(): void;
    on(event: "region-clicked", listener: (region: Region, event: MouseEvent) => void): () => void;
    on(event: "region-updated", listener: (region: Region) => void): () => void;
  };

  const RegionsPlugin: {
    create(): RegionsPlugin;
  };

  export default RegionsPlugin;
}

declare module "wavesurfer.js/dist/plugins/timeline.esm.js" {
  type TimelinePluginOptions = {
    container?: HTMLElement | string;
    height?: number;
    formatTimeCallback?: (seconds: number) => string;
  };

  const TimelinePlugin: {
    create(options?: TimelinePluginOptions): unknown;
  };

  export default TimelinePlugin;
}
