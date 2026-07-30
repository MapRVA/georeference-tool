// Shared map viewer component. Templates include
// templates/images/partials/map_display.html, which loads this bundle and
// calls window.initializeMap() with a MapDisplayConfig.
import maplibregl from "maplibre-gl";
import {
  OSM_STYLE_URL,
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_ZOOM,
} from "../../constants/map";
import "maplibre-gl/dist/maplibre-gl.css";
import "@maplibre/maplibre-gl-geocoder/dist/maplibre-gl-geocoder.css";
import "../../../styles/components/map-display.css";
import "./pmtiles_protocol";
import { LayerControl } from "../layer_control";
import { addResponsiveGeocoder } from "../responsive_geocoder";
import { boundsFromAerialGeometry } from "./bounds";
import { primaryColor, dangerColor } from "./colors";
import { setupMapDataLayers } from "./data_layers";
import { watchInitialFeatures } from "./features";
import { registerImageInteractions } from "./interactions";
import { LAYER_IDS, OVERLAY_LAYER_IDS } from "./layer_ids";
import { installToggleOtherImages } from "./other_images_toggle";
import { buildScaleHelpers } from "./scale_visibility";
import type {
  MapDisplayConfig,
  MapDisplayContext,
  ResolvedMapDisplayConfig,
} from "./types";

// Main initialization function
export function initializeMap(config: MapDisplayConfig): maplibregl.Map {
  const {
    mapId,
    center = DEFAULT_MAP_CENTER,
    zoom = DEFAULT_MAP_ZOOM,
    hash = false,
    vectorTilesUrl = null,
    allImagesUrl = null,
    showOtherImages = false,
    imageId = null,
    enableScaleVisibility = false,
    includeGeocoder = false,
    geolocate = false,
    aerialGeoreference = null,
    zoomToContents = false,
    directionImageUrl = null,
    currentImageDirection = null,
  } = config;

  const resolved: ResolvedMapDisplayConfig = {
    mapId,
    center,
    zoom,
    hash,
    vectorTilesUrl,
    allImagesUrl,
    showOtherImages,
    imageId,
    enableScaleVisibility,
    includeGeocoder,
    geolocate,
    aerialGeoreference,
    zoomToContents,
    directionImageUrl,
    currentImageDirection,
  };

  // Setup PMTiles protocol
  window.setupPMTilesProtocol();

  // Initialize the map
  const map = new maplibregl.Map({
    container: mapId,
    style: OSM_STYLE_URL,
    hash: hash,
    center: center,
    zoom: zoom,
  });

  // Setup toggle for other images if enabled
  if (showOtherImages && imageId) {
    installToggleOtherImages(map);
  }

  const ctx: MapDisplayContext = {
    map,
    config: resolved,
    colors: { primary: primaryColor, danger: dangerColor },
    scaleHelpers: buildScaleHelpers(enableScaleVisibility),
  };

  // Add controls
  const layerControl = new LayerControl({
    showImageLayerToggle: true,
    overlayLayerIds: OVERLAY_LAYER_IDS,
    beforeLayerId: LAYER_IDS.imageHeatmap,
    onStyleSwap: () => setupMapDataLayers(ctx),
  });
  ctx.layerControl = layerControl;
  const navControl = new maplibregl.NavigationControl();
  const fullscreenControl = new maplibregl.FullscreenControl();

  map.addControl(layerControl, "top-right");

  // Add navigation and fullscreen controls after time slider will be added
  // These will be positioned below the time slider
  map.addControl(navControl, "top-right");
  map.addControl(fullscreenControl, "top-right");

  if (geolocate) {
    const geolocateControl = new maplibregl.GeolocateControl({
      positionOptions: { enableHighAccuracy: true },
      trackUserLocation: true,
    });
    map.addControl(geolocateControl, "top-right");
  }

  // Map load handler
  map.on("load", async function () {
    // Add geocoder if requested
    if (includeGeocoder) {
      addResponsiveGeocoder(map);
    }

    await setupMapDataLayers(ctx);

    // Fit bounds to aerial polygon (only on initial load). Only include
    // `center` in the bounds when it marks the current image point
    // (point+polygon case). In the polygon-only case there is no
    // current-image marker and `center` is just the default map center, so
    // extending to it would drag the view off the polygon.
    if (aerialGeoreference) {
      try {
        const bounds = boundsFromAerialGeometry(
          aerialGeoreference,
          showOtherImages && imageId ? center : null,
        );
        if (bounds) {
          map.fitBounds(bounds, {
            padding: 50,
            maxZoom: 16,
          });
        }
      } catch (error) {
        console.error("Error fitting bounds to aerial polygon:", error);
      }
    }

    // Handle initial feature loading for time slider and zoom
    watchInitialFeatures(ctx);

    registerImageInteractions(ctx);
  });

  return map;
}

// Expose initializeMap globally for template usage
window.initializeMap = initializeMap;
