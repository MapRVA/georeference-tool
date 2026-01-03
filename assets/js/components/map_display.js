// Map display module for shared map functionality
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import * as pmtiles from "pmtiles";
import MaplibreGeocoder from "@maplibre/maplibre-gl-geocoder";
import "@maplibre/maplibre-gl-geocoder/dist/maplibre-gl-geocoder.css";
import "../../styles/components/map_display.css";

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

// Layer Control Class
class LayerControl {
  constructor() {
    this.baseLayers = {
      osm: {
        name: "OpenStreetMap",
        isDefault: true,
        setupLayer: () => {},
        activate: () => this.showOSMLayers(),
        deactivate: () => this.hideOSMLayers(),
      },
      satellite: {
        name: "Satellite",
        setupLayer: () => this.setupSatelliteLayer(),
        activate: () => this.showSatelliteLayer(),
        deactivate: () => this.hideSatelliteLayer(),
      },
      usgs: {
        name: "USGS Topo",
        setupLayer: () => this.setupUSGSLayer(),
        activate: () => this.showUSGSLayer(),
        deactivate: () => this.hideUSGSLayer(),
      },
    };
    this.currentBaseLayer = "osm";
    this.currentOverlayLayer = null;
    this.imageLayersVisible = true;
    this.mapLayersLoaded = false;
    this.collectionsData = null;
  }

  onAdd(map) {
    this.map = map;
    this.mapId = map.getContainer().id;
    this.container = document.createElement("div");
    this.container.className =
      "maplibregl-ctrl maplibregl-ctrl-group layer-control";

    const baseLayerOptions = Object.entries(this.baseLayers)
      .map(([key, layer]) => {
        const activeClass = layer.isDefault ? " active" : "";
        return `<li><a class="dropdown-item layer-option${activeClass}" href="#" data-layer="${key}">${layer.name}</a></li>`;
      })
      .join("");

    this.container.innerHTML = `
            <div class="dropdown">
                <button class="dropdown-toggle" type="button" id="layerDropdown-${this.mapId}" data-bs-toggle="dropdown" aria-expanded="false" data-bs-container="body">
                    ${this.baseLayers[this.currentBaseLayer].name}
                </button>
                <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="layerDropdown-${this.mapId}">
                    ${baseLayerOptions}
                </ul>
            </div>
        `;

    this.layerDropdown = this.container.querySelector(".dropdown-toggle");
    this.setupEventListeners();

    if (this.map.loaded()) {
      this.setupMapLayers();
      this.loadMapLayers();
    } else {
      this.map.on("load", () => {
        this.setupMapLayers();
        this.loadMapLayers();
      });
    }

    return this.container;
  }

  onRemove() {
    this.container.parentNode.removeChild(this.container);
    this.map = undefined;
  }

  setupMapLayers() {
    Object.entries(this.baseLayers).forEach(([key, layer]) => {
      layer.setupLayer();
    });
  }

  setupSatelliteLayer() {
    if (!this.map.getSource("satellite")) {
      this.map.addSource("satellite", {
        type: "raster",
        tiles: [
          "https://vginmaps.vdem.virginia.gov/arcgis/rest/services/VBMP_Imagery/MostRecentImagery_WGS/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
        attribution: "Virginia Geographic Information Network (VGIN)",
      });
    }

    if (!this.map.getLayer("satellite-layer")) {
      this.map.addLayer({
        id: "satellite-layer",
        type: "raster",
        source: "satellite",
        layout: { visibility: "none" },
      });
    }
  }

  setupUSGSLayer() {
    if (!this.map.getSource("usgs")) {
      this.map.addSource("usgs", {
        type: "raster",
        tiles: [
          "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
        attribution: "USGS National Map",
      });
    }

    if (!this.map.getLayer("usgs-layer")) {
      this.map.addLayer({
        id: "usgs-layer",
        type: "raster",
        source: "usgs",
        layout: { visibility: "none" },
      });
    }
  }

  setupEventListeners() {
    this.container.querySelectorAll(".layer-option").forEach((item) => {
      item.addEventListener("click", (e) => {
        e.preventDefault();
        const layerKey = item.dataset.layer;
        if (layerKey === this.currentBaseLayer) return;
        this.switchToBaseLayer(layerKey);
      });
    });
  }

  switchToBaseLayer(newLayerKey) {
    if (!this.baseLayers[newLayerKey] || newLayerKey === this.currentBaseLayer)
      return;

    this.baseLayers[this.currentBaseLayer].deactivate();
    this.baseLayers[newLayerKey].activate();
    this.currentBaseLayer = newLayerKey;

    let currentLayerName;
    if (this.currentOverlayLayer) {
      const currentText = this.layerDropdown.textContent;
      const overlayTitle = currentText.split(" + ")[1];
      currentLayerName = `${this.baseLayers[newLayerKey].name} + ${overlayTitle}`;
    } else {
      currentLayerName = this.baseLayers[newLayerKey].name;
    }
    this.updateDropdownSelection(currentLayerName, newLayerKey);
  }

  showOSMLayers() {
    this.hideOtherBaseLayers(["satellite-layer", "usgs-layer"]);
    const layers = this.map.getStyle().layers;
    layers.forEach((layer) => {
      if (!this.isOverlayLayer(layer.id) && !this.isCustomBaseLayer(layer.id)) {
        this.map.setLayoutProperty(layer.id, "visibility", "visible");
      }
    });
  }

  hideOSMLayers() {
    const layers = this.map.getStyle().layers;
    layers.forEach((layer) => {
      if (!this.isOverlayLayer(layer.id) && !this.isCustomBaseLayer(layer.id)) {
        this.map.setLayoutProperty(layer.id, "visibility", "none");
      }
    });
  }

  showSatelliteLayer() {
    this.hideOSMLayers();
    this.hideOtherBaseLayers(["usgs-layer"]);
    if (this.map.getLayer("satellite-layer")) {
      this.map.setLayoutProperty("satellite-layer", "visibility", "visible");
    }
  }

  hideSatelliteLayer() {
    if (this.map.getLayer("satellite-layer")) {
      this.map.setLayoutProperty("satellite-layer", "visibility", "none");
    }
  }

  showUSGSLayer() {
    this.hideOSMLayers();
    this.hideOtherBaseLayers(["satellite-layer"]);
    if (this.map.getLayer("usgs-layer")) {
      this.map.setLayoutProperty("usgs-layer", "visibility", "visible");
    }
  }

  hideUSGSLayer() {
    if (this.map.getLayer("usgs-layer")) {
      this.map.setLayoutProperty("usgs-layer", "visibility", "none");
    }
  }

  isOverlayLayer(layerId) {
    return (
      layerId === "image-circles" ||
      layerId === "image-directions" ||
      layerId.startsWith("overlay-")
    );
  }

  isCustomBaseLayer(layerId) {
    return layerId === "satellite-layer" || layerId === "usgs-layer";
  }

  hideOtherBaseLayers(layersToHide) {
    layersToHide.forEach((layerId) => {
      if (this.map.getLayer(layerId)) {
        this.map.setLayoutProperty(layerId, "visibility", "none");
      }
    });
  }

  switchToOverlayLayer(layerId, tileUrl, title, tileType, attribution) {
    console.log(
      "Switching to overlay layer:",
      layerId,
      tileUrl,
      title,
      tileType,
      attribution,
    );

    if (tileType === "pmtiles") {
      console.log(
        "PMTiles protocol setup status:",
        window.pmtilesProtocolSetup,
      );
      console.log("PMTiles available:", typeof pmtiles !== "undefined");

      if (!window.pmtilesProtocolSetup) {
        console.error(
          "PMTiles protocol not available! Attempting to set up now...",
        );
        if (!window.setupPMTilesProtocol()) {
          alert(
            "PMTiles map overlay layers are not available - PMTiles protocol not loaded.",
          );
          return;
        }
        console.log("PMTiles protocol setup successful, continuing...");
      }
    }

    if (this.currentOverlayLayer === layerId) {
      console.log("Deactivating current overlay layer:", layerId);
      this.map.setLayoutProperty(layerId, "visibility", "none");
      this.currentOverlayLayer = null;
      const baseLayerName = this.baseLayers[this.currentBaseLayer].name;
      this.updateDropdownSelection(baseLayerName, this.currentBaseLayer);
      return;
    }

    const layers = this.map.getStyle().layers;
    layers.forEach((layer) => {
      if (layer.id.startsWith("overlay-") && layer.id !== layerId) {
        this.map.setLayoutProperty(layer.id, "visibility", "none");
      }
    });

    const sourceId = `${layerId}-source`;
    if (!this.map.getSource(sourceId)) {
      console.log(`Adding ${tileType} source:`, sourceId, tileUrl);
      try {
        if (tileType === "pmtiles") {
          this.map.addSource(sourceId, {
            type: "raster",
            url: `pmtiles://${tileUrl}`,
            tileSize: 256,
            attribution: attribution,
          });
        } else if (tileType === "xyz") {
          this.map.addSource(sourceId, {
            type: "raster",
            tiles: [tileUrl],
            tileSize: 256,
            attribution: attribution,
          });
        }
        console.log("Tile source added successfully");
      } catch (error) {
        console.error(`Error adding ${tileType} source:`, error);
        return;
      }
    } else {
      console.log("Tile source already exists:", sourceId);
    }

    if (!this.map.getLayer(layerId)) {
      console.log("Adding overlay layer:", layerId);
      try {
        const beforeId = this.map.getLayer("image-directions")
          ? "image-directions"
          : undefined;

        this.map.addLayer(
          {
            id: layerId,
            source: sourceId,
            type: "raster",
            paint: {
              "raster-opacity": 1.0,
              "raster-fade-duration": 300,
              "raster-resampling": "linear",
            },
            layout: { visibility: "visible" },
          },
          beforeId,
        );
        console.log("Overlay layer added successfully");
      } catch (error) {
        console.error("Error adding overlay layer:", error);
        return;
      }
    } else {
      console.log("Overlay layer already exists, showing it");
    }

    this.map.setLayoutProperty(layerId, "visibility", "visible");

    this.currentOverlayLayer = layerId;
    const combinedTitle = `${this.baseLayers[this.currentBaseLayer].name} + ${title}`;
    this.updateDropdownSelection(combinedTitle, layerId);
    console.log("Overlay layer switch complete");
  }

  updateDropdownSelection(buttonText, selectedLayer) {
    this.layerDropdown.textContent = buttonText;

    this.container
      .querySelectorAll(".layer-option, .overlay-layer")
      .forEach((item) => {
        item.classList.remove("active");
      });

    if (this.currentOverlayLayer) {
      const baseLayerItem = this.container.querySelector(
        `[data-layer="${this.currentBaseLayer}"]`,
      );
      if (baseLayerItem) baseLayerItem.classList.add("active");

      const overlayLayerItem = this.container.querySelector(
        `[data-layer="${this.currentOverlayLayer}"]`,
      );
      if (overlayLayerItem) overlayLayerItem.classList.add("active");
    } else {
      const selectedItem = this.container.querySelector(
        `[data-layer="${selectedLayer}"]`,
      );
      if (selectedItem) selectedItem.classList.add("active");
    }
  }

  async loadMapLayers() {
    if (this.mapLayersLoaded) return;

    try {
      console.log("Loading map layers...");
      const response = await fetch("/map-layers/");
      console.log("Map layers response:", response);

      if (!response.ok)
        throw new Error(`Failed to fetch map layers: ${response.status}`);

      const data = await response.json();
      console.log("Map layers data:", data);

      this.collectionsData = data.collections;
      this.populateCollectionSubmenus();
      this.mapLayersLoaded = true;
      console.log("Map layers loaded successfully");
    } catch (error) {
      console.error("Error loading map layers:", error);
      this.addErrorItem();
    }
  }

  populateCollectionSubmenus() {
    if (!this.collectionsData || this.collectionsData.length === 0) return;

    const dropdownMenu = this.container.querySelector(".dropdown-menu");
    let layerIndex = 0;

    this.collectionsData.forEach((collection, collectionIndex) => {
      if (collection.layers.length === 0) return;

      if (collectionIndex > 0 || dropdownMenu.children.length > 0) {
        const dividerItem = document.createElement("li");
        const divider = document.createElement("hr");
        divider.className = "dropdown-divider";
        dividerItem.appendChild(divider);
        dropdownMenu.appendChild(dividerItem);
      }

      const headerItem = document.createElement("li");
      const header = document.createElement("h6");
      header.className = "dropdown-header";
      header.textContent = collection.name;
      headerItem.appendChild(header);
      dropdownMenu.appendChild(headerItem);

      collection.layers.forEach((layer) => {
        const layerId = `overlay-${layerIndex}`;
        const listItem = document.createElement("li");
        const layerItem = document.createElement("a");
        layerItem.className = "dropdown-item overlay-layer";
        layerItem.href = "#";
        layerItem.dataset.layer = layerId;
        layerItem.dataset.tileUrl = layer.url;
        layerItem.dataset.tileType = layer.type || "pmtiles";
        layerItem.textContent = layer.name;

        layerItem.addEventListener("click", (e) => {
          e.preventDefault();
          this.switchToOverlayLayer(
            layerId,
            layer.url,
            layer.name,
            layer.type || "pmtiles",
            layer.attribution || "",
          );

          const dropdown = bootstrap.Dropdown.getInstance(this.layerDropdown);
          if (dropdown) dropdown.hide();
        });

        listItem.appendChild(layerItem);
        dropdownMenu.appendChild(listItem);
        layerIndex++;
      });
    });

    this.addImageLayerToggle();
  }

  addImageLayerToggle() {
    const dropdownMenu = this.container.querySelector(".dropdown-menu");

    const dividerItem = document.createElement("li");
    const divider = document.createElement("hr");
    divider.className = "dropdown-divider";
    dividerItem.appendChild(divider);
    dropdownMenu.appendChild(dividerItem);

    const headerItem = document.createElement("li");
    const header = document.createElement("h6");
    header.className = "dropdown-header";
    header.textContent = "Data Overlays";
    headerItem.appendChild(header);
    dropdownMenu.appendChild(headerItem);

    const listItem = document.createElement("li");
    const imageLayerItem = document.createElement("a");
    imageLayerItem.className = "dropdown-item overlay-layer active";
    imageLayerItem.href = "#";
    imageLayerItem.dataset.layer = "georeferenced-images";
    imageLayerItem.textContent = "Georeferenced Images";

    imageLayerItem.addEventListener("click", (e) => {
      e.preventDefault();
      this.toggleImageLayers();

      const dropdown = bootstrap.Dropdown.getInstance(this.layerDropdown);
      if (dropdown) dropdown.hide();
    });

    listItem.appendChild(imageLayerItem);
    dropdownMenu.appendChild(listItem);
  }

  toggleImageLayers() {
    this.imageLayersVisible = !this.imageLayersVisible;

    if (this.map.getLayer("image-circles")) {
      this.map.setLayoutProperty(
        "image-circles",
        "visibility",
        this.imageLayersVisible ? "visible" : "none",
      );
    }

    if (this.map.getLayer("image-directions")) {
      this.map.setLayoutProperty(
        "image-directions",
        "visibility",
        this.imageLayersVisible ? "visible" : "none",
      );
    }

    const imageLayerItem = this.container.querySelector(
      '[data-layer="georeferenced-images"]',
    );
    if (imageLayerItem) {
      if (this.imageLayersVisible) {
        imageLayerItem.classList.add("active");
      } else {
        imageLayerItem.classList.remove("active");
      }
    }
  }

  addErrorItem() {
    const dropdownMenu = this.container.querySelector(".dropdown-menu");

    const dividerItem = document.createElement("li");
    const divider = document.createElement("hr");
    divider.className = "dropdown-divider";
    dividerItem.appendChild(divider);
    dropdownMenu.appendChild(dividerItem);

    const errorItem = document.createElement("li");
    const errorLink = document.createElement("div");
    errorLink.className = "dropdown-item-text text-muted";
    errorLink.textContent = "Failed to load map layers";
    errorItem.appendChild(errorLink);
    dropdownMenu.appendChild(errorItem);
  }
}

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

    this._outerContainer.innerHTML = `
            <div class="time-slider-control">
                <div class="time-slider-values">
                    <span id="time-slider-label-${this._mapId}">Date Range</span>
                    <span id="time-slider-range-label-${this._mapId}"></span>
                </div>
                <div class="time-slider-container">
                    <div class="slider-track"></div>
                    <div class="slider-range" id="slider-range-${this._mapId}"></div>
                    <input type="range" id="start-slider-${this._mapId}" min="${this._minYear}" max="${this._maxYear}" value="${this._minYear}">
                    <input type="range" id="end-slider-${this._mapId}" min="${this._minYear}" max="${this._maxYear}" value="${this._maxYear}">
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
    styleUrl = "https://styles.trailsta.sh/openmaptiles-osm.json",
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
  const layerControl = new LayerControl();
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
      if (typeof MaplibreGeocoder === "undefined") {
        console.error("MaplibreGeocoder is not loaded.");
      } else {
        const geocoderApi = {
          forwardGeocode: async (config) => {
            const features = [];
            try {
              const request = `https://nominatim.openstreetmap.org/search?q=${config.query}&format=geojson&polygon_geojson=1&addressdetails=1&layer=address&viewbox=-77.61976,37.60954,-77.36673,37.44393&bounded=1`;
              const response = await fetch(request);
              const geojson = await response.json();
              for (const feature of geojson.features) {
                const center = [
                  feature.bbox[0] + (feature.bbox[2] - feature.bbox[0]) / 2,
                  feature.bbox[1] + (feature.bbox[3] - feature.bbox[1]) / 2,
                ];
                const point = {
                  type: "Feature",
                  geometry: { type: "Point", coordinates: center },
                  place_name: feature.properties.display_name,
                  properties: feature.properties,
                  text: feature.properties.display_name,
                  place_type: ["place"],
                  center,
                };
                features.push(point);
              }
            } catch (e) {
              console.error(`Failed to forwardGeocode with error: ${e}`);
            }
            return { features };
          },
        };
        const geocoder = new MaplibreGeocoder(geocoderApi, {
          maplibregl,
          placeholder: "Search places",
        });
        map.addControl(geocoder, "top-left");

        const geocoderInput = document
          .getElementById(mapId)
          .querySelector(".maplibregl-ctrl-geocoder--input");
        if (geocoderInput) {
          geocoderInput.type = "search";
        }
      }
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
