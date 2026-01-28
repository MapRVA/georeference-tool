// Map display module for shared map functionality
import maplibregl from "maplibre-gl";
import {
  OSM_STYLE_URL,
  DEFAULT_MAP_CENTER,
  DEFAULT_MAP_ZOOM,
} from "../constants/map.js";
import "maplibre-gl/dist/maplibre-gl.css";
import * as pmtiles from "pmtiles";
import MaplibreGeocoder from "@maplibre/maplibre-gl-geocoder";
import "@maplibre/maplibre-gl-geocoder/dist/maplibre-gl-geocoder.css";
import "../../styles/components/map-display.css";
import { LayerControl } from "./layer_control.js";
import { addResponsiveGeocoder } from "./responsive_geocoder.js";

// Get colors from Bootstrap's CSS custom properties
const primaryColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-primary")
    .trim() || "#286071";

const dangerColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-danger")
    .trim() || "#d52e1c";

// Make libraries globally available
window.maplibregl = maplibregl;
window.pmtiles = pmtiles;
window.MaplibreGeocoder = MaplibreGeocoder;

// Global PMTiles protocol setup
window.pmtilesProtocolSetup = false;

window.setupPMTilesProtocol = function () {
  if (window.pmtilesProtocolSetup) return true;

  if (typeof pmtiles !== "undefined") {
    try {
      console.log("Setting up PMTiles protocol...");
      let protocol = new pmtiles.Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
      console.log("PMTiles protocol setup complete");
      window.pmtilesProtocolSetup = true;
      return true;
    } catch (error) {
      console.error("Error setting up PMTiles protocol:", error);
      return false;
    }
  } else {
    console.log("PMTiles library not yet available");
    return false;
  }
};

// Time Slider Control Class
class TimeSliderControl {
  constructor(minYear, maxYear, mapId) {
    this._minYear = minYear;
    this._maxYear = maxYear;
    this._mapId = mapId;
  }

  onAdd(map) {
    this._map = map;
    this._outerContainer = document.createElement("div");
    this._outerContainer.className = "maplibregl-ctrl";

    const isSmallScreen = window.matchMedia("(max-width: 1000px)").matches;
    const collapseClass = isSmallScreen ? "collapse" : "collapse show";
    const ariaExpanded = isSmallScreen ? "false" : "true";

    this._outerContainer.innerHTML = `
            <div class="time-slider-control">
                <div class="time-slider-toolbar">
                    <div class="time-slider-header">
                        <span class="time-slider-label">Date Range</span>
                        <span id="time-slider-range-label-${this._mapId}" class="time-slider-range-label"></span>
                    </div>
                    <button type="button"
                            class="time-slider-toggle"
                            data-bs-toggle="collapse"
                            data-bs-target="#time-slider-body-${this._mapId}"
                            aria-expanded="${ariaExpanded}"
                            aria-controls="time-slider-body-${this._mapId}"
                            aria-label="Date filter">
                        <i class="fas fa-calendar-days"></i>
                    </button>
                    <button type="button"
                            class="time-slider-close"
                            data-bs-toggle="collapse"
                            data-bs-target="#time-slider-body-${this._mapId}"
                            aria-label="Close date filter">
                        <i class="fas fa-square-up-right"></i>
                    </button>
                </div>
                <div class="${collapseClass}" id="time-slider-body-${this._mapId}">
                    <div class="time-slider-container">
                        <div class="slider-track"></div>
                        <div class="slider-range" id="slider-range-${this._mapId}"></div>
                        <input type="range" id="start-slider-${this._mapId}" min="${this._minYear}" max="${this._maxYear}" value="${this._minYear}">
                        <input type="range" id="end-slider-${this._mapId}" min="${this._minYear}" max="${this._maxYear}" value="${this._maxYear}">
                    </div>
                </div>
            </div>
        `;

    this._sliderPanel = this._outerContainer.querySelector(
      ".time-slider-control",
    );
    this._startSlider = this._sliderPanel.querySelector(
      `#start-slider-${this._mapId}`,
    );
    this._endSlider = this._sliderPanel.querySelector(
      `#end-slider-${this._mapId}`,
    );
    this._rangeLabel = this._sliderPanel.querySelector(
      `#time-slider-range-label-${this._mapId}`,
    );
    this._sliderRange = this._sliderPanel.querySelector(
      `#slider-range-${this._mapId}`,
    );

    this.setupEventListeners();
    this.updateView();

    return this._outerContainer;
  }

  setupEventListeners() {
    this._startSlider.addEventListener("input", () => {
      if (parseInt(this._startSlider.value) > parseInt(this._endSlider.value)) {
        this._endSlider.value = this._startSlider.value;
      }
      this.updateView();
      this.applyFilter();
    });

    this._endSlider.addEventListener("input", () => {
      if (parseInt(this._endSlider.value) < parseInt(this._startSlider.value)) {
        this._startSlider.value = this._endSlider.value;
      }
      this.updateView();
      this.applyFilter();
    });
  }

  updateView() {
    this._rangeLabel.textContent = `${this._startSlider.value} - ${this._endSlider.value}`;

    const range = this._maxYear - this._minYear;
    if (range === 0) return;

    const startPercent =
      ((this._startSlider.value - this._minYear) / range) * 100;
    const endPercent = ((this._endSlider.value - this._minYear) / range) * 100;

    this._sliderRange.style.left = `${startPercent}%`;
    this._sliderRange.style.width = `${endPercent - startPercent}%`;
  }

  applyFilter() {
    const startYear = parseInt(this._startSlider.value);
    const endYear = parseInt(this._endSlider.value);

    const filter = [
      "all",
      ["<=", ["get", "fuzzy_start_decdate"], endYear],
      [">=", ["get", "fuzzy_end_decdate"], startYear],
    ];

    const directionFilter = ["all", ["has", "direction"], ...filter.slice(1)];

    // Heatmap style layers
    if (this._map.getLayer("image-heatmap")) {
      this._map.setFilter("image-heatmap", filter);
    }
    if (this._map.getLayer("image-circles")) {
      this._map.setFilter("image-circles", filter);
    }
    if (this._map.getLayer("image-directions")) {
      this._map.setFilter("image-directions", directionFilter);
    }

    // Simple style layers
    if (this._map.getLayer("image-circles-simple")) {
      this._map.setFilter("image-circles-simple", filter);
    }
    if (this._map.getLayer("image-directions-simple")) {
      this._map.setFilter("image-directions-simple", directionFilter);
    }
  }

  onRemove() {
    if (this._outerContainer && this._outerContainer.parentNode) {
      this._outerContainer.parentNode.removeChild(this._outerContainer);
    }
    this._map = undefined;
  }
}

// Export classes and setup function
export { LayerControl, TimeSliderControl };

// Main initialization function
export function initializeMap(config) {
  // Also expose to window for template usage
  window.initializeMap = initializeMap;
  const {
    mapId,
    styleUrl = OSM_STYLE_URL,
    center = DEFAULT_MAP_CENTER,
    zoom = DEFAULT_MAP_ZOOM,
    hash = false,
    vectorTilesUrl,
    singleImageUrl,
    allImagesUrl,
    showOtherImages = false,
    imageId = null,
    enableScaleVisibility = false,
    scaleVisibilityConfig = {},
    includeGeocoder = false,
    geolocate = false,
    aerialGeoreference = null,
    zoomToContents = false,
    directionImageUrl,
    onMapLoad = null,
    currentImageDirection = null,
  } = config;

  // Setup PMTiles protocol
  window.setupPMTilesProtocol();

  // Initialize the map
  const map = new maplibregl.Map({
    container: mapId,
    style: styleUrl,
    hash: hash,
    center: center,
    zoom: zoom,
  });

  // Setup toggle for other images if enabled
  if (showOtherImages && imageId) {
    let otherImagesLoaded = false;

    window.toggleOtherImages = function (showAll, onLoadCallback) {
      const visibility = showAll ? "visible" : "none";
      // Heatmap style layers
      if (map.getLayer("image-heatmap")) {
        map.setLayoutProperty("image-heatmap", "visibility", visibility);
      }
      if (map.getLayer("image-circles")) {
        map.setLayoutProperty("image-circles", "visibility", visibility);
      }
      if (map.getLayer("image-directions")) {
        map.setLayoutProperty("image-directions", "visibility", visibility);
      }
      // Simple style layers (keep hidden - they're controlled by LayerControl style toggle)
      if (map.getLayer("image-circles-simple")) {
        map.setLayoutProperty("image-circles-simple", "visibility", "none");
      }
      if (map.getLayer("image-directions-simple")) {
        map.setLayoutProperty("image-directions-simple", "visibility", "none");
      }

      // Handle loading callback
      if (showAll && onLoadCallback) {
        if (otherImagesLoaded) {
          // Already loaded, call immediately
          onLoadCallback();
        } else {
          // Wait for idle event (tiles finished loading)
          const onIdle = function () {
            otherImagesLoaded = true;
            onLoadCallback();
            map.off("idle", onIdle);
          };
          map.on("idle", onIdle);
        }
      }
    };
  }

  // Add controls
  const layerControl = new LayerControl({
    showImageLayerToggle: true,
    overlayLayerIds: [
      "image-heatmap",
      "image-circles",
      "image-directions",
      "image-circles-simple",
      "image-directions-simple",
    ],
    beforeLayerId: "image-heatmap",
  });
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

  // Build scale visibility helper functions
  const buildScaleHelpers = (enableScaleVisibility, scaleVisibilityConfig) => {
    if (!enableScaleVisibility) {
      return {
        isFullDetail: () => true,
        isPinpointVisible: () => true,
        buildDirectionOpacityExpression: () => 1,
        buildCircleRadiusExpression: () => 8,
        buildCircleStrokeWidthExpression: () => 2,
      };
    }

    const getScaleConfig = (scale) => {
      if (!scale || scale === 0 || scale === 6) {
        return { pinpointZoom: 0, fullDetailZoom: 0 };
      }
      return (
        scaleVisibilityConfig[scale] || { pinpointZoom: 99, fullDetailZoom: 99 }
      );
    };

    const isFullDetail = (scale, zoom) => {
      const config = getScaleConfig(scale);
      return zoom >= config.fullDetailZoom;
    };

    const isPinpointVisible = (scale, zoom) => {
      const config = getScaleConfig(scale);
      return zoom >= config.pinpointZoom;
    };

    const buildDirectionOpacityExpression = () => {
      const buildCaseForZoom = (atZoom) => {
        const caseExpr = ["case"];
        const scales = [5, 4, 3, 2, 1];
        scales.forEach((scale) => {
          const config = scaleVisibilityConfig[scale];
          if (!config) return;
          if (atZoom >= config.fullDetailZoom) {
            caseExpr.push(["==", ["coalesce", ["get", "scale"], 6], scale], 1);
          }
        });
        caseExpr.push(
          [
            "any",
            ["==", ["coalesce", ["get", "scale"], 6], 6],
            ["==", ["coalesce", ["get", "scale"], 6], 0],
            ["!", ["has", "scale"]],
          ],
          1,
        );
        caseExpr.push(0);
        return caseExpr;
      };

      const zoomThresholds = new Set();
      Object.values(scaleVisibilityConfig).forEach((config) => {
        zoomThresholds.add(config.fullDetailZoom);
      });
      const sortedZooms = Array.from(zoomThresholds).sort((a, b) => a - b);

      const expr = ["step", ["zoom"]];
      expr.push(buildCaseForZoom(0));
      sortedZooms.forEach((zoom) => {
        expr.push(zoom, buildCaseForZoom(zoom));
      });
      return expr;
    };

    const buildCircleRadiusExpression = () => {
      const buildCaseForZoom = (atZoom) => {
        const caseExpr = ["case"];
        const scales = [5, 4, 3, 2, 1];
        scales.forEach((scale) => {
          const config = scaleVisibilityConfig[scale];
          if (!config) return;
          if (atZoom >= config.fullDetailZoom) {
            caseExpr.push(["==", ["coalesce", ["get", "scale"], 6], scale], 8);
          } else if (atZoom >= config.pinpointZoom) {
            caseExpr.push(["==", ["coalesce", ["get", "scale"], 6], scale], 4);
          }
        });
        caseExpr.push(
          [
            "any",
            ["==", ["coalesce", ["get", "scale"], 6], 6],
            ["==", ["coalesce", ["get", "scale"], 6], 0],
            ["!", ["has", "scale"]],
          ],
          8,
        );
        caseExpr.push(0);
        return caseExpr;
      };

      const zoomThresholds = new Set();
      Object.values(scaleVisibilityConfig).forEach((config) => {
        zoomThresholds.add(config.pinpointZoom);
        zoomThresholds.add(config.fullDetailZoom);
      });
      const sortedZooms = Array.from(zoomThresholds).sort((a, b) => a - b);

      const expr = ["step", ["zoom"]];
      expr.push(buildCaseForZoom(0));
      sortedZooms.forEach((zoom) => {
        expr.push(zoom, buildCaseForZoom(zoom));
      });
      return expr;
    };

    const buildCircleStrokeWidthExpression = () => {
      const buildCaseForZoom = (atZoom) => {
        const caseExpr = ["case"];
        const scales = [5, 4, 3, 2, 1];
        scales.forEach((scale) => {
          const config = scaleVisibilityConfig[scale];
          if (!config) return;
          if (atZoom >= config.pinpointZoom) {
            caseExpr.push(["==", ["coalesce", ["get", "scale"], 6], scale], 2);
          }
        });
        caseExpr.push(
          [
            "any",
            ["==", ["coalesce", ["get", "scale"], 6], 6],
            ["==", ["coalesce", ["get", "scale"], 6], 0],
            ["!", ["has", "scale"]],
          ],
          2,
        );
        caseExpr.push(0);
        return caseExpr;
      };

      const zoomThresholds = new Set();
      Object.values(scaleVisibilityConfig).forEach((config) => {
        zoomThresholds.add(config.pinpointZoom);
        zoomThresholds.add(config.fullDetailZoom);
      });
      const sortedZooms = Array.from(zoomThresholds).sort((a, b) => a - b);

      const expr = ["step", ["zoom"]];
      expr.push(buildCaseForZoom(0));
      sortedZooms.forEach((zoom) => {
        expr.push(zoom, buildCaseForZoom(zoom));
      });
      return expr;
    };

    return {
      isFullDetail,
      isPinpointVisible,
      buildDirectionOpacityExpression,
      buildCircleRadiusExpression,
      buildCircleStrokeWidthExpression,
    };
  };

  const scaleHelpers = buildScaleHelpers(
    enableScaleVisibility,
    scaleVisibilityConfig,
  );

  // Map load handler
  map.on("load", async function () {
    // Add geocoder if requested
    if (includeGeocoder) {
      addResponsiveGeocoder(map);
    }

    // Load direction arrow image
    if (directionImageUrl) {
      try {
        const image = await map.loadImage(directionImageUrl);
        map.addImage("image-direction", image.data);
      } catch (error) {
        console.warn("Could not load direction arrow image:", error);
      }
    }

    // Add vector tiles source for other images
    const tilesUrl =
      showOtherImages && allImagesUrl ? allImagesUrl : vectorTilesUrl;
    if (tilesUrl) {
      map.addSource("images", {
        type: "vector",
        tiles: [tilesUrl],
        minzoom: 0,
        maxzoom: 18,
      });

      // Start hidden if in showOtherImages mode (toggle controls visibility)
      const initialVisibility = showOtherImages ? "none" : "visible";

      // Build filter to exclude current image if in showOtherImages mode
      // Convert imageId to number since vector tile properties are integers
      const excludeCurrentFilter =
        showOtherImages && imageId
          ? ["!=", ["get", "id"], parseInt(imageId, 10)]
          : null;

      // Add blurred background circles (heatmap effect, fades out at higher zoom)
      map.addLayer({
        id: "image-heatmap",
        type: "circle",
        source: "images",
        "source-layer": "image_points",
        filter: excludeCurrentFilter || ["literal", true],
        maxzoom: 17,
        layout: {
          visibility: initialVisibility,
        },
        paint: {
          "circle-blur": [
            "interpolate",
            ["linear"],
            ["zoom"],
            14.5,
            1.5,
            16,
            3,
          ],
          "circle-opacity": [
            "interpolate",
            ["exponential", 5],
            ["zoom"],
            14,
            1,
            17,
            0,
          ],
          "circle-radius": [
            "interpolate",
            ["exponential", 2],
            ["zoom"],
            10,
            25,
            20,
            100,
          ],
          "circle-color": primaryColor,
        },
      });

      // Add direction markers (fade in at higher zoom, rendered under circles)
      if (map.hasImage("image-direction")) {
        map.addLayer({
          id: "image-directions",
          type: "symbol",
          source: "images",
          "source-layer": "image_points",
          minzoom: 15,
          filter: excludeCurrentFilter
            ? ["all", ["has", "direction"], excludeCurrentFilter]
            : ["has", "direction"],
          layout: {
            "icon-image": "image-direction",
            "icon-overlap": "always",
            "icon-size": [
              "interpolate",
              ["exponential", 0.7],
              ["zoom"],
              15,
              0.3,
              20,
              1,
            ],
            "icon-rotate": ["to-number", ["get", "direction"]],
            "icon-rotation-alignment": "map",
            "icon-pitch-alignment": "map",
            visibility: initialVisibility,
          },
        });
      }

      // Add detail circles (blur transitions from blurry to sharp, on top of directions)
      map.addLayer({
        id: "image-circles",
        type: "circle",
        source: "images",
        "source-layer": "image_points",
        minzoom: 7,
        filter: excludeCurrentFilter || ["literal", true],
        layout: {
          visibility: initialVisibility,
        },
        paint: {
          "circle-blur": [
            "interpolate",
            ["exponential", 1.5],
            ["zoom"],
            9,
            5,
            13,
            1,
            15,
            0,
          ],
          "circle-opacity": [
            "interpolate",
            ["exponential", 1.5],
            ["zoom"],
            7,
            0,
            10,
            1,
          ],
          "circle-radius": [
            "interpolate",
            ["exponential", 0.6],
            ["zoom"],
            7,
            1,
            15,
            3,
            20,
            9,
          ],
          "circle-color": [
            "interpolate",
            ["linear"],
            ["zoom"],
            14,
            "#fff",
            15,
            primaryColor,
          ],
          "circle-stroke-color": "#fff",
          "circle-stroke-width": [
            "interpolate",
            ["linear"],
            ["zoom"],
            13.5,
            0,
            15,
            1,
            20,
            2,
          ],
        },
      });

      // === Simple style layers (hidden by default) ===

      // Add simple direction markers (rendered under simple circles)
      if (map.hasImage("image-direction")) {
        map.addLayer({
          id: "image-directions-simple",
          type: "symbol",
          source: "images",
          "source-layer": "image_points",
          filter: excludeCurrentFilter
            ? ["all", ["has", "direction"], excludeCurrentFilter]
            : ["has", "direction"],
          layout: {
            "icon-image": "image-direction",
            "icon-overlap": "always",
            "icon-size": 1,
            "icon-rotate": ["to-number", ["get", "direction"]],
            "icon-rotation-alignment": "map",
            "icon-pitch-alignment": "map",
            visibility: "none",
          },
        });
      }

      // Add simple circle layer (always visible at all zooms, on top of simple directions)
      map.addLayer({
        id: "image-circles-simple",
        type: "circle",
        source: "images",
        "source-layer": "image_points",
        filter: excludeCurrentFilter || ["literal", true],
        layout: {
          visibility: "none",
        },
        paint: {
          "circle-radius": 8,
          "circle-color": primaryColor,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
    }

    // Add current image as GeoJSON layer (always visible, distinct color, on top)
    if (showOtherImages && imageId && center) {
      map.addSource("current-image", {
        type: "geojson",
        data: {
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: center,
          },
          properties: {
            id: imageId,
            direction: currentImageDirection,
          },
        },
      });

      // Add direction marker for current image
      if (map.hasImage("image-direction") && currentImageDirection !== null) {
        map.addLayer({
          id: "current-image-direction",
          type: "symbol",
          source: "current-image",
          layout: {
            "icon-image": "image-direction",
            "icon-overlap": "always",
            "icon-size": 1,
            "icon-rotate": currentImageDirection,
            "icon-rotation-alignment": "map",
            "icon-pitch-alignment": "map",
          },
          paint: {
            "icon-opacity": 1,
          },
        });
      }

      // Add circle for current image
      map.addLayer({
        id: "current-image-circle",
        type: "circle",
        source: "current-image",
        paint: {
          "circle-radius": 8,
          "circle-color": dangerColor,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });
    }

    // Add aerial georeference if provided
    if (aerialGeoreference) {
      map.addSource("aerial-polygon", {
        type: "geojson",
        data: {
          type: "Feature",
          geometry: aerialGeoreference,
        },
      });

      map.addLayer({
        id: "aerial-polygon-fill",
        type: "fill",
        source: "aerial-polygon",
        paint: {
          "fill-color": primaryColor,
          "fill-opacity": 0.2,
        },
      });

      map.addLayer({
        id: "aerial-polygon-outline",
        type: "line",
        source: "aerial-polygon",
        paint: {
          "line-color": primaryColor,
          "line-width": 2.5,
        },
      });

      // Fit bounds to aerial polygon
      try {
        let coordinates = [];
        if (aerialGeoreference.type === "Polygon") {
          coordinates = aerialGeoreference.coordinates[0];
        } else if (aerialGeoreference.type === "MultiPolygon") {
          coordinates = aerialGeoreference.coordinates[0][0];
        }

        if (coordinates.length > 0) {
          const bounds = new maplibregl.LngLatBounds();
          coordinates.forEach(function (coord) {
            if (Array.isArray(coord) && coord.length === 2) {
              bounds.extend(coord);
            }
          });

          if (center && center.length === 2) {
            bounds.extend(center);
          }

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
    let initialFeaturesLoaded = false;
    map.on("sourcedata", function (e) {
      if (
        e.sourceId === "images" &&
        e.isSourceLoaded &&
        !initialFeaturesLoaded
      ) {
        let features = map.querySourceFeatures("images", {
          sourceLayer: "image_points",
        });

        if (features.length === 0 && map.getLayer("image-circles")) {
          features = map.queryRenderedFeatures({
            layers: ["image-circles"],
          });
        }

        if (features.length > 0) {
          initialFeaturesLoaded = true;
          processFeatures(features);
        } else {
          setTimeout(() => {
            if (initialFeaturesLoaded) return;
            const retryFeatures = map.querySourceFeatures("images", {
              sourceLayer: "image_points",
            });

            if (retryFeatures.length > 0) {
              initialFeaturesLoaded = true;
              processFeatures(retryFeatures);
            }
          }, 1000);
        }
      }
    });

    function processFeatures(features) {
      // Calculate date range for time slider
      let minYear = null;
      let maxYear = null;
      features.forEach((feature) => {
        const props = feature.properties;
        if (props.fuzzy_start_decdate) {
          if (minYear === null || props.fuzzy_start_decdate < minYear) {
            minYear = props.fuzzy_start_decdate;
          }
        }
        const yearForMax = props.fuzzy_end_decdate || props.fuzzy_start_decdate;
        if (yearForMax) {
          if (maxYear === null || yearForMax > maxYear) {
            maxYear = yearForMax;
          }
        }
      });

      // Add time slider if valid date range and not single image view
      if (
        minYear !== null &&
        maxYear !== null &&
        minYear < maxYear &&
        !imageId
      ) {
        const timeSlider = new TimeSliderControl(minYear, maxYear, mapId);
        // Insert time slider after layer control but before other controls
        const layerControlElement = map
          .getContainer()
          .querySelector(".layer-control");
        if (layerControlElement && layerControlElement.parentNode) {
          const timeSliderElement = timeSlider.onAdd(map);
          layerControlElement.parentNode.insertBefore(
            timeSliderElement,
            layerControlElement.nextSibling,
          );
        } else {
          // Fallback to regular positioning
          map.addControl(timeSlider, "top-right");
        }
      }

      // Handle zoom to contents - fit map to all feature bounds
      if (zoomToContents && features.length > 0) {
        const bounds = new maplibregl.LngLatBounds();
        features.forEach(function (feature) {
          bounds.extend(feature.geometry.coordinates);
        });
        map.fitBounds(bounds, {
          padding: 50,
          maxZoom: 15,
        });
      }
    }

    // Add click handlers for image markers
    if (!imageId || showOtherImages) {
      // Helper function to handle circle layer click
      const handleCircleClick = function (e, checkScaleVisibility) {
        if (!e.features.length) return;
        const properties = e.features[0].properties;

        if (checkScaleVisibility && enableScaleVisibility) {
          const scale =
            !properties.scale || properties.scale === 0 ? 6 : properties.scale;
          const zoom = map.getZoom();

          if (!scaleHelpers.isFullDetail(scale, zoom)) return;
        }

        const imgEntry = window.location.origin + "/" + properties.id + "/";

        const popupContent = `
                  <div>
                      <img src="${properties.thumbnail}"
                            style="border-radius: 0.5em; width: 30em; max-width: 100%; height: auto;">
                      ${properties.original_date ? `<p>Date: ${properties.original_date}</p>` : ""}
                      <a href="${imgEntry}" class="btn btn-primary btn-sm" style="margin-top: 8px;">
                          <i class="fas fa-eye me-1"></i>View Details
                      </a>
                  </div>
                `;

        new maplibregl.Popup()
          .setLngLat(e.features[0].geometry.coordinates)
          .setHTML(popupContent)
          .addTo(map);
      };

      // Helper function to handle circle layer mouseenter
      const handleCircleMouseenter = function (e, checkScaleVisibility) {
        if (checkScaleVisibility && enableScaleVisibility) {
          if (!e.features.length) return;
          const properties = e.features[0].properties;
          const scale =
            !properties.scale || properties.scale === 0 ? 6 : properties.scale;
          const zoom = map.getZoom();

          if (scaleHelpers.isFullDetail(scale, zoom)) {
            map.getCanvas().style.cursor = "pointer";
          } else {
            map.getCanvas().style.cursor = "";
          }
        } else {
          map.getCanvas().style.cursor = "pointer";
        }
      };

      // Heatmap style circle layer handlers
      map.on("click", "image-circles", (e) => handleCircleClick(e, true));
      map.on("mouseenter", "image-circles", (e) =>
        handleCircleMouseenter(e, true),
      );
      map.on("mouseleave", "image-circles", () => {
        map.getCanvas().style.cursor = "";
      });

      // Simple style circle layer handlers (no scale visibility checks)
      map.on("click", "image-circles-simple", (e) =>
        handleCircleClick(e, false),
      );
      map.on("mouseenter", "image-circles-simple", (e) =>
        handleCircleMouseenter(e, false),
      );
      map.on("mouseleave", "image-circles-simple", () => {
        map.getCanvas().style.cursor = "";
      });
    }

    // Call custom onMapLoad callback if provided
    if (onMapLoad && typeof onMapLoad === "function") {
      onMapLoad(map);
    }
  });

  return map;
}

// Expose initializeMap globally for template usage
window.initializeMap = initializeMap;
