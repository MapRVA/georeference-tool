import type { Map as MapLibreMap } from "maplibre-gl";
import type { MapDisplayConfig } from "../js/components/map_display/types";

declare global {
  interface Window {
    // Django-provided configuration, set by inline scripts in templates/base.html
    OSM_STYLE_URL?: string;
    DEFAULT_MAP_CENTER?: [number, number];
    DEFAULT_MAP_ZOOM?: number;

    // PMTiles protocol registration, shared with still-JS modules (layer_control.js)
    pmtilesProtocolSetup: boolean;
    setupPMTilesProtocol: () => boolean;

    // Map viewer entry points called from Django templates and page bundles
    initializeMap: (config: MapDisplayConfig) => MapLibreMap;
    toggleOtherImages?: (showAll: boolean, onLoadCallback?: () => void) => void;
  }
}

export {};
