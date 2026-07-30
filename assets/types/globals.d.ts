import type { Map as MapLibreMap } from "maplibre-gl";
import type { MapLayersData } from "../js/components/layer_control/types";
import type { MapDisplayConfig } from "../js/components/map_display/types";

declare global {
  // Minimal shape of the Bootstrap bundle assets/index.js puts on window. The
  // npm package ships no type declarations, so only the pieces TypeScript
  // modules actually use are described here.
  interface BootstrapOffcanvas {
    show(): void;
    hide(): void;
    dispose(): void;
  }

  interface BootstrapNamespace {
    Offcanvas: new (
      element: Element,
      options?: Record<string, unknown>,
    ) => BootstrapOffcanvas;
  }

  interface Window {
    // Django-provided configuration, set by inline scripts in templates/base.html
    OSM_STYLE_URL?: string;
    DEFAULT_MAP_CENTER?: [number, number];
    DEFAULT_MAP_ZOOM?: number;

    // Geocoder configuration: the search bounding box is
    // [west, south, east, north]; ADMIN_EMAIL is sent to Nominatim as a
    // contact address and is null when unset.
    DEFAULT_SEARCH_BBOX?: [number, number, number, number];
    ADMIN_EMAIL?: string | null;

    MAP_LAYERS_DATA?: MapLayersData;

    // Protomaps basemap key, set by pages that build their own basemap style
    PROTOMAPS_API_KEY?: string;

    // Alpine.js, assigned globally in assets/index.js
    Alpine: typeof import("alpinejs").default;

    bootstrap: BootstrapNamespace;

    // PMTiles protocol registration, shared with still-JS page bundles
    pmtilesProtocolSetup: boolean;
    setupPMTilesProtocol: () => boolean;

    // Map viewer entry points called from Django templates and page bundles
    initializeMap: (config: MapDisplayConfig) => MapLibreMap;
    toggleOtherImages?: (showAll: boolean, onLoadCallback?: () => void) => void;
  }
}

export {};
