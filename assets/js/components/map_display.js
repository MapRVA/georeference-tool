// Map display module for shared map functionality
import maplibregl from "maplibre-gl";
import { OSM_STYLE_URL } from "../constants/map.js";
import "maplibre-gl/dist/maplibre-gl.css";
import * as pmtiles from "pmtiles";
import MaplibreGeocoder from "@maplibre/maplibre-gl-geocoder";
import "@maplibre/maplibre-gl-geocoder/dist/maplibre-gl-geocoder.css";
import "../../styles/components/map-display.css";
import { LayerControl } from "./layer_control.js";
import { addResponsiveGeocoder } from "./responsive_geocoder.js";

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

    if (this._map.getLayer("image-circles")) {
      this._map.setFilter("image-circles", filter);
    }
    if (this._map.getLayer("image-directions")) {
      this._map.setFilter("image-directions", [
        "all",
        ["has", "direction"],
        ...filter.slice(1),
      ]);
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
    center = [-77.43916, 37.54376],
    zoom = 10,
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
    window.toggleOtherImages = function (showAll) {
      const newUrl = showAll ? allImagesUrl : singleImageUrl;
      const source = map.getSource("images");
      if (source) {
        source.setTiles([newUrl]);
      }
    };
  }

  // Add controls
  const layerControl = new LayerControl({
    showImageLayerToggle: true,
    overlayLayerIds: ["image-circles", "image-directions"],
    beforeLayerId: "image-directions",
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

    // Add vector tiles source
    if (vectorTilesUrl) {
      map.addSource("images", {
        type: "vector",
        tiles: [vectorTilesUrl],
        minzoom: 0,
        maxzoom: 18,
      });

      // Add direction markers
      if (map.hasImage("image-direction")) {
        map.addLayer({
          id: "image-directions",
          type: "symbol",
          source: "images",
          "source-layer": "image_points",
          filter: ["has", "direction"],
          layout: {
            "icon-image": "image-direction",
            "icon-overlap": "always",
            "icon-size": {
              stops: [
                [5, 0.3],
                [15, 1],
              ],
            },
            "icon-rotate": ["to-number", ["get", "direction"]],
            "icon-rotation-alignment": "map",
            "icon-pitch-alignment": "map",
          },
          paint: {
            "icon-opacity": scaleHelpers.buildDirectionOpacityExpression(),
          },
        });
      }

      // Add circle layer
      map.addLayer({
        id: "image-circles",
        type: "circle",
        source: "images",
        "source-layer": "image_points",
        paint: {
          "circle-radius": scaleHelpers.buildCircleRadiusExpression(),
          "circle-color": "green",
          "circle-stroke-color": "#fff",
          "circle-stroke-width":
            scaleHelpers.buildCircleStrokeWidthExpression(),
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
          "fill-color": "#0d6efd",
          "fill-opacity": 0.2,
        },
      });

      map.addLayer({
        id: "aerial-polygon-outline",
        type: "line",
        source: "aerial-polygon",
        paint: {
          "line-color": "#0d6efd",
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
            } else {
              if (!aerialGeoreference) {
                document.getElementById(mapId).innerHTML =
                  '<div class="d-flex align-items-center justify-content-center h-100 text-muted bg-light">' +
                  '<div class="text-center">' +
                  '<i class="fas fa-map-marker-alt fa-2x mb-2"></i><br>' +
                  "No georeferenced images found" +
                  "</div></div>";
              }
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

      // Handle zoom to contents
      if (zoomToContents) {
        if (center && center.length === 2 && zoom) {
          map.flyTo({ center: center, zoom: zoom });
        } else {
          if (features.length > 0) {
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
      }
    }

    // Add click handlers for image markers
    if (!imageId || showOtherImages) {
      map.on("click", "image-circles", function (e) {
        if (!e.features.length) return;
        const properties = e.features[0].properties;

        if (enableScaleVisibility) {
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
      });

      map.on("mouseenter", "image-circles", function (e) {
        if (enableScaleVisibility) {
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
      });

      map.on("mouseleave", "image-circles", function () {
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
