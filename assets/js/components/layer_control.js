/**
 * LayerControl - A shared MapLibre control for switching between base layers and overlays
 *
 * Base layers and overlay layers are loaded dynamically from the API.
 * Primary layers (no collection) become base layer options.
 * Secondary layers (in collections) become overlay options.
 *
 * Layer data is read from window.MAP_LAYERS_DATA (set by Django context processor).
 *
 * Usage:
 *   import { LayerControl } from './layer_control.js';
 *
 *   // Basic usage (for georeference interfaces)
 *   map.addControl(new LayerControl(), 'top-right');
 *
 *   // With image layer toggle (for map_display)
 *   map.addControl(new LayerControl({
 *     showImageLayerToggle: true,
 *     overlayLayerIds: ['image-circles', 'image-directions'],
 *     beforeLayerId: 'image-directions'
 *   }), 'top-right');
 */

import "../../styles/components/layer-control.css";

export class LayerControl {
  /**
   * @param {Object} options
   * @param {boolean} options.showImageLayerToggle - Whether to show the image layer toggle (default: false)
   * @param {string[]} options.overlayLayerIds - Layer IDs that should be considered overlay layers (for visibility checks)
   * @param {string} options.beforeLayerId - Insert overlay tile layers before this layer ID
   * @param {Function} options.onBaseLayerChange - Callback when base layer changes (receives layer key)
   * @param {Function} options.onStyleSwap - Callback after a style swap completes (receives map instance)
   */
  constructor(options = {}) {
    this.options = {
      showImageLayerToggle: false,
      overlayLayerIds: [],
      beforeLayerId: null,
      onBaseLayerChange: null,
      onStyleSwap: null,
      ...options,
    };

    this.baseLayers = {};
    this.currentBaseLayer = null;
    this.currentOverlayLayer = null;
    this.imageLayersVisible = true;
    this.imageDisplayStyle = "heatmap"; // "heatmap" or "simple"
    this.simpleCircleRadius = 8; // default radius for simple mode (2-10)
    this.collectionsData = null;
    this.offcanvas = null;
    this.offcanvasInstance = null;
    this.fullscreenChangeHandler = null;
  }

  onAdd(map) {
    this.map = map;
    this.mapId = map.getContainer().id;
    this.container = document.createElement("div");
    this.container.className =
      "maplibregl-ctrl maplibregl-ctrl-group layer-control";

    this.container.innerHTML = `
      <button type="button" class="layer-control-button" aria-label="Map layers">
        <i class="fas fa-layer-group"></i>
        <span class="layer-control-label"></span>
      </button>
    `;

    this.layerLabel = this.container.querySelector(".layer-control-label");

    this.triggerButton = this.container.querySelector(".layer-control-button");
    this.createOffcanvas();
    this.setupEventListeners();

    if (this.map.loaded()) {
      this.initializeLayers();
    } else {
      this.map.on("load", () => {
        this.initializeLayers();
      });
    }

    // Initialize the label with current layer
    this.updateLayerLabel(null);

    return this.container;
  }

  createOffcanvas() {
    const offcanvasId = `layerOffcanvas-${this.mapId}`;

    let existingOffcanvas = document.getElementById(offcanvasId);
    if (existingOffcanvas) {
      existingOffcanvas.remove();
    }

    this.offcanvas = document.createElement("div");
    this.offcanvas.className = "offcanvas offcanvas-end";
    this.offcanvas.setAttribute("tabindex", "-1");
    this.offcanvas.setAttribute("id", offcanvasId);
    this.offcanvas.setAttribute("aria-labelledby", `${offcanvasId}-label`);

    this.offcanvas.innerHTML = `
      <div class="offcanvas-header">
        <h5 class="offcanvas-title" id="${offcanvasId}-label">Map Layers</h5>
        <button type="button" class="btn-close" data-bs-dismiss="offcanvas" aria-label="Close"></button>
      </div>
      <div class="offcanvas-body">
        <h6 class="text-muted small text-uppercase mb-2">Base Layers</h6>
        <div class="list-group list-group-flush base-layers-list"></div>
        <hr class="my-3 border-2 opacity-50">
        <div class="overlay-layers-container"></div>
      </div>
    `;

    document.body.appendChild(this.offcanvas);
    this.offcanvasInstance = new bootstrap.Offcanvas(this.offcanvas);

    // Listen for fullscreen changes to move offcanvas appropriately
    this.fullscreenChangeHandler = () => this.handleFullscreenChange();
    document.addEventListener("fullscreenchange", this.fullscreenChangeHandler);
  }

  handleFullscreenChange() {
    const fullscreenElement = document.fullscreenElement;
    const mapContainer = this.map.getContainer();

    if (fullscreenElement === mapContainer) {
      // Map is now fullscreen - move offcanvas inside the map container
      mapContainer.appendChild(this.offcanvas);
    } else if (!fullscreenElement) {
      // Exited fullscreen - move offcanvas back to document.body
      document.body.appendChild(this.offcanvas);
    }
  }

  onRemove() {
    if (this.fullscreenChangeHandler) {
      document.removeEventListener(
        "fullscreenchange",
        this.fullscreenChangeHandler,
      );
    }
    if (this.offcanvas && this.offcanvas.parentNode) {
      if (this.offcanvasInstance) {
        this.offcanvasInstance.dispose();
      }
      this.offcanvas.parentNode.removeChild(this.offcanvas);
    }
    this.container.parentNode.removeChild(this.container);
    this.map = undefined;
  }

  initializeLayers() {
    const data = window.MAP_LAYERS_DATA;
    if (!data) {
      console.error("MAP_LAYERS_DATA not found on window");
      this.addErrorItem();
      return;
    }

    if (data.primary_layers && data.primary_layers.length > 0) {
      this.buildBaseLayers(data.primary_layers);
    }

    this.collectionsData = data.collections;
    this.populateBaseLayerButtons();
    this.populateCollectionSubmenus();
    this.updateLayerLabel(null);
  }

  /**
   * Build base layers from the API response's primary_layers array.
   * Style-type layers with is_default use show/hide of existing style layers.
   * XYZ-type layers use raster source/layer add/show/hide.
   */
  buildBaseLayers(primaryLayers) {
    primaryLayers.forEach((layer) => {
      const key = layer.slug;

      if (layer.type === "style" && layer.is_default) {
        this.baseLayers[key] = {
          name: layer.name,
          isDefault: true,
          type: "style",
          url: layer.url,
          setupLayer: () => {},
          activate: () => this.showDefaultStyleLayers(),
          deactivate: () => this.hideDefaultStyleLayers(),
        };
        this.currentBaseLayer = key;
        this.defaultStyleUrl = layer.url;
      } else if (layer.type === "style") {
        this.baseLayers[key] = {
          name: layer.name,
          isDefault: false,
          type: "style",
          url: layer.url,
          setupLayer: () => {},
          activate: () => this.activateStyle(layer.url),
          deactivate: () => {},
        };
      } else if (layer.type === "xyz") {
        const sourceId = `base-${key}`;
        const layerId = `base-${key}-layer`;
        this.baseLayers[key] = {
          name: layer.name,
          isDefault: false,
          type: "xyz",
          sourceId,
          layerId,
          setupLayer: () =>
            this.setupRasterBaseLayer(
              sourceId,
              layerId,
              layer.url,
              layer.attribution || "",
            ),
          activate: () => this.activateRasterBase(layerId),
          deactivate: () => this.deactivateRasterBase(layerId),
        };
      }
    });

    // Fallback: if no default was set, use the first layer
    if (!this.currentBaseLayer && primaryLayers.length > 0) {
      const firstKey = primaryLayers[0].slug;
      if (this.baseLayers[firstKey]) {
        this.baseLayers[firstKey].isDefault = true;
        this.currentBaseLayer = firstKey;
      }
    }

    // Run setup for all base layers
    Object.values(this.baseLayers).forEach((layer) => layer.setupLayer());
  }

  setupRasterBaseLayer(sourceId, layerId, url, attribution) {
    if (!this.map.getSource(sourceId)) {
      this.map.addSource(sourceId, {
        type: "raster",
        tiles: [url],
        tileSize: 256,
        attribution: attribution,
      });
    }

    if (!this.map.getLayer(layerId)) {
      this.map.addLayer({
        id: layerId,
        type: "raster",
        source: sourceId,
        layout: { visibility: "none" },
      });
    }
  }

  activateRasterBase(layerId) {
    if (this._nonDefaultStyleActive) {
      // Returning from a non-default style — restore default then show raster
      this._nonDefaultStyleActive = false;
      this._swapStyle(this.defaultStyleUrl, () => {
        this._showRasterBase(layerId);
      });
      return;
    }
    this._showRasterBase(layerId);
  }

  _showRasterBase(layerId) {
    this.hideDefaultStyleLayers();
    this.hideAllRasterBaseLayers(layerId);
    if (this.map.getLayer(layerId)) {
      this.moveBaseLayerBelowOverlays(layerId);
      this.map.setLayoutProperty(layerId, "visibility", "visible");
    }
  }

  deactivateRasterBase(layerId) {
    if (this.map.getLayer(layerId)) {
      this.map.setLayoutProperty(layerId, "visibility", "none");
    }
  }

  hideAllRasterBaseLayers(exceptLayerId) {
    Object.values(this.baseLayers).forEach((bl) => {
      if (bl.type === "xyz" && bl.layerId !== exceptLayerId) {
        if (this.map.getLayer(bl.layerId)) {
          this.map.setLayoutProperty(bl.layerId, "visibility", "none");
        }
      }
    });
  }

  setupEventListeners() {
    this.triggerButton.addEventListener("click", () => {
      this.offcanvasInstance.show();
    });
  }

  switchToBaseLayer(newLayerKey) {
    if (!this.baseLayers[newLayerKey] || newLayerKey === this.currentBaseLayer)
      return;

    this.baseLayers[this.currentBaseLayer].deactivate();
    this.baseLayers[newLayerKey].activate();
    this.currentBaseLayer = newLayerKey;

    this.updateSelection();

    if (this.options.onBaseLayerChange) {
      this.options.onBaseLayerChange(newLayerKey);
    }
  }

  showDefaultStyleLayers() {
    if (this._nonDefaultStyleActive) {
      // Returning from a non-default style — restore the default style
      this._nonDefaultStyleActive = false;
      this._swapStyle(this.defaultStyleUrl);
      return;
    }
    this.hideAllRasterBaseLayers();
    const layers = this.map.getStyle().layers;
    layers.forEach((layer) => {
      if (!this.isOverlayLayer(layer.id) && !this.isCustomBaseLayer(layer.id)) {
        this.map.setLayoutProperty(layer.id, "visibility", "visible");
      }
    });
  }

  hideDefaultStyleLayers() {
    const layers = this.map.getStyle().layers;
    layers.forEach((layer) => {
      if (!this.isOverlayLayer(layer.id) && !this.isCustomBaseLayer(layer.id)) {
        this.map.setLayoutProperty(layer.id, "visibility", "none");
      }
    });
  }

  activateStyle(styleUrl) {
    this._nonDefaultStyleActive = true;
    this._swapStyle(styleUrl);
  }

  /**
   * Swap the map style and restore overlay/raster base layers after load.
   * Captures active overlay state before the swap and restores it after.
   * @param {string} styleUrl - The style URL to swap to
   * @param {Function} [afterRestore] - Optional callback after layers are restored
   */
  _swapStyle(styleUrl, afterRestore) {
    // Capture state that will be lost during style swap
    const savedOverlay = this.currentOverlayLayer;
    const savedOverlayConfig = this._getActiveOverlayConfig();

    this.map.setStyle(styleUrl);

    this.map.once("style.load", () => {
      // Re-setup raster base layer sources/layers (destroyed by setStyle)
      Object.values(this.baseLayers).forEach((bl) => {
        if (bl.type === "xyz") bl.setupLayer();
      });

      // Restore overlay tile layer if one was active
      if (savedOverlay && savedOverlayConfig) {
        this.currentOverlayLayer = null; // Reset so switchToOverlayLayer doesn't toggle off
        this.switchToOverlayLayer(
          savedOverlayConfig.layerId,
          savedOverlayConfig.tileUrl,
          savedOverlayConfig.title,
          savedOverlayConfig.tileType,
          savedOverlayConfig.attribution,
        );
      }

      // Notify consumers to re-add their layers
      if (this.options.onStyleSwap) {
        this.options.onStyleSwap(this.map);
      }

      if (afterRestore) afterRestore();
    });
  }

  /**
   * Capture the config of the currently active overlay layer so it can be
   * re-added after a style swap.
   */
  _getActiveOverlayConfig() {
    if (!this.currentOverlayLayer) return null;

    const btn = this.offcanvas.querySelector(
      `.overlay-layer[data-layer="${this.currentOverlayLayer}"]`,
    );
    if (!btn) return null;

    return {
      layerId: this.currentOverlayLayer,
      tileUrl: btn.dataset.tileUrl,
      title: btn.textContent.trim(),
      tileType: btn.dataset.tileType || "pmtiles",
      attribution: btn.dataset.attribution || "",
    };
  }

  /**
   * Move a base layer below all overlay layers so overlays remain visible
   */
  moveBaseLayerBelowOverlays(layerId) {
    const styles = this.map.getStyle().layers;
    const overlayLayerIds = [];

    for (let layer of styles) {
      if (this.isOverlayLayer(layer.id)) {
        overlayLayerIds.push(layer.id);
      }
    }

    if (overlayLayerIds.length > 0) {
      this.map.moveLayer(layerId, overlayLayerIds[0]);
    }
  }

  isOverlayLayer(layerId) {
    // Check configured overlay layer IDs
    if (this.options.overlayLayerIds.includes(layerId)) {
      return true;
    }

    // Default overlay patterns
    return (
      layerId === "image-heatmap" ||
      layerId === "image-circles" ||
      layerId === "image-directions" ||
      layerId === "image-circles-simple" ||
      layerId === "image-directions-simple" ||
      layerId === "current-image-circle" ||
      layerId === "current-image-direction" ||
      layerId === "aerial-polygon-fill" ||
      layerId === "aerial-polygon-outline" ||
      layerId === "pin-circle" ||
      layerId === "pin-symbol" ||
      layerId === "context-image-circles" ||
      layerId === "context-image-directions" ||
      layerId === "polygon-fill" ||
      layerId === "polygon-outline" ||
      layerId.startsWith("overlay-") ||
      layerId.startsWith("gm_")
    );
  }

  isCustomBaseLayer(layerId) {
    return Object.values(this.baseLayers).some(
      (bl) => bl.type === "xyz" && bl.layerId === layerId,
    );
  }

  /**
   * Get the layer ID to insert overlay tile layers before.
   * This ensures user-selected overlays render below all image point layers.
   */
  getBeforeLayerId() {
    // Use configured beforeLayerId if specified
    if (this.options.beforeLayerId) {
      if (this.map.getLayer(this.options.beforeLayerId)) {
        return this.options.beforeLayerId;
      }
    }

    // Check for Geoman layers (dynamically created with "gm_" prefix)
    // These need to stay on top of secondary tile layers
    const layers = this.map.getStyle().layers;
    for (const layer of layers) {
      if (layer.id.startsWith("gm_")) {
        return layer.id;
      }
    }

    // Fall back to checking common overlay layers, in order from bottom to top.
    // We want to insert before the first (bottom-most) one that exists.
    // This order must match the actual layer stacking in the map:
    // 1. subject hints (bottom of overlays)
    // 2. location hints
    // 3. context images (other georeferenced images)
    // 4. pin layers (user's placement marker - always on top)
    const possibleBeforeLayers = [
      "subject-hints-pulse",
      "subject-hints-label",
      "location-hint-pulse",
      "location-hint-label",
      "context-image-circles",
      "context-image-directions",
      "pin-circle",
      "pin-symbol",
      "image-heatmap",
      "image-circles",
      "image-directions",
      "image-circles-simple",
      "image-directions-simple",
    ];

    for (const layerId of possibleBeforeLayers) {
      if (this.map.getLayer(layerId)) {
        return layerId;
      }
    }

    return undefined;
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
      this.updateSelection();
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
        const beforeId = this.getBeforeLayerId();

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
    this.updateSelection();
    console.log("Overlay layer switch complete");
  }

  updateSelection() {
    // Reset base layer and overlay selections, but not the independent image layer toggle
    this.offcanvas.querySelectorAll(".layer-option").forEach((item) => {
      item.classList.remove("active");
    });
    this.offcanvas
      .querySelectorAll(
        '.overlay-layer:not([data-layer="georeferenced-images"])',
      )
      .forEach((item) => {
        item.classList.remove("active");
      });

    const baseLayerItem = this.offcanvas.querySelector(
      `.layer-option[data-layer="${this.currentBaseLayer}"]`,
    );
    if (baseLayerItem) baseLayerItem.classList.add("active");

    let overlayLayerName = null;
    if (this.currentOverlayLayer) {
      const overlayLayerItem = this.offcanvas.querySelector(
        `.overlay-layer[data-layer="${this.currentOverlayLayer}"]`,
      );
      if (overlayLayerItem) {
        overlayLayerItem.classList.add("active");
        overlayLayerName = overlayLayerItem.textContent.trim();
      }
    }

    // Update the layer label
    this.updateLayerLabel(overlayLayerName);
  }

  updateLayerLabel(overlayLayerName) {
    if (!this.layerLabel) return;

    const baseLayerName = this.baseLayers[this.currentBaseLayer]?.name || "";

    if (overlayLayerName) {
      this.layerLabel.textContent = `${baseLayerName} + ${overlayLayerName}`;
    } else {
      this.layerLabel.textContent = baseLayerName;
    }
  }

  populateBaseLayerButtons() {
    const baseLayersList = this.offcanvas.querySelector(".base-layers-list");
    baseLayersList.innerHTML = "";

    Object.entries(this.baseLayers).forEach(([key, layer]) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className =
        "list-group-item list-group-item-action layer-option" +
        (key === this.currentBaseLayer ? " active" : "");
      btn.dataset.layer = key;
      btn.textContent = layer.name;

      btn.addEventListener("click", (e) => {
        e.preventDefault();
        if (key === this.currentBaseLayer) return;
        this.switchToBaseLayer(key);
        this.offcanvasInstance.hide();
      });

      baseLayersList.appendChild(btn);
    });
  }

  populateCollectionSubmenus() {
    if (!this.collectionsData || this.collectionsData.length === 0) return;

    const overlayContainer = this.offcanvas.querySelector(
      ".overlay-layers-container",
    );
    let layerIndex = 0;

    this.collectionsData.forEach((collection) => {
      if (collection.layers.length === 0) return;

      const header = document.createElement("h6");
      header.className = "text-muted small text-uppercase mb-2 mt-3";
      header.textContent = collection.name;
      overlayContainer.appendChild(header);

      const listGroup = document.createElement("div");
      listGroup.className = "list-group list-group-flush mb-2";

      collection.layers.forEach((layer) => {
        const layerId = `overlay-${layerIndex}`;
        const layerItem = document.createElement("button");
        layerItem.type = "button";
        layerItem.className =
          "list-group-item list-group-item-action overlay-layer";
        layerItem.dataset.layer = layerId;
        layerItem.dataset.tileUrl = layer.url;
        layerItem.dataset.tileType = layer.type || "pmtiles";
        layerItem.dataset.attribution = layer.attribution || "";
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
          this.offcanvasInstance.hide();
        });

        listGroup.appendChild(layerItem);
        layerIndex++;
      });

      overlayContainer.appendChild(listGroup);
    });

    if (this.options.showImageLayerToggle) {
      this.addImageLayerToggle();
    }
  }

  addImageLayerToggle() {
    const overlayContainer = this.offcanvas.querySelector(
      ".overlay-layers-container",
    );

    const divider = document.createElement("hr");
    divider.className = "my-3 border-2 opacity-50";
    overlayContainer.appendChild(divider);

    const header = document.createElement("h6");
    header.className = "text-muted small text-uppercase mb-2";
    header.textContent = "Data Overlays";
    overlayContainer.appendChild(header);

    const listGroup = document.createElement("div");
    listGroup.className = "list-group list-group-flush mb-2";

    const imageLayerItem = document.createElement("button");
    imageLayerItem.type = "button";
    imageLayerItem.className =
      "list-group-item list-group-item-action overlay-layer active";
    imageLayerItem.dataset.layer = "georeferenced-images";
    imageLayerItem.textContent = "Georeferenced Images";

    imageLayerItem.addEventListener("click", (e) => {
      e.preventDefault();
      this.toggleImageLayers();
      this.offcanvasInstance.hide();
    });

    listGroup.appendChild(imageLayerItem);
    overlayContainer.appendChild(listGroup);

    // Add display style toggle
    const styleHeader = document.createElement("h6");
    styleHeader.className = "text-muted small text-uppercase mb-2 mt-3";
    styleHeader.textContent = "Display Style";
    overlayContainer.appendChild(styleHeader);

    const styleGroup = document.createElement("div");
    styleGroup.className = "btn-group w-100";
    styleGroup.setAttribute("role", "group");
    styleGroup.setAttribute("aria-label", "Image display style");

    const heatmapBtn = document.createElement("button");
    heatmapBtn.type = "button";
    heatmapBtn.className = "btn btn-outline-primary active";
    heatmapBtn.dataset.style = "heatmap";
    heatmapBtn.textContent = "Heatmap";

    const simpleBtn = document.createElement("button");
    simpleBtn.type = "button";
    simpleBtn.className = "btn btn-outline-primary";
    simpleBtn.dataset.style = "simple";
    simpleBtn.textContent = "Simple";

    heatmapBtn.addEventListener("click", (e) => {
      e.preventDefault();
      this.setImageDisplayStyle("heatmap");
      heatmapBtn.classList.add("active");
      simpleBtn.classList.remove("active");
    });

    simpleBtn.addEventListener("click", (e) => {
      e.preventDefault();
      this.setImageDisplayStyle("simple");
      simpleBtn.classList.add("active");
      heatmapBtn.classList.remove("active");
    });

    styleGroup.appendChild(heatmapBtn);
    styleGroup.appendChild(simpleBtn);
    overlayContainer.appendChild(styleGroup);

    // Add radius slider for simple mode (hidden by default)
    const radiusContainer = document.createElement("div");
    radiusContainer.className = "mt-3";
    radiusContainer.style.display = "none";
    radiusContainer.id = `radius-slider-container-${this.mapId}`;

    const radiusLabel = document.createElement("label");
    radiusLabel.className = "form-label small text-muted";
    radiusLabel.textContent = "Point Size";

    const sliderWrapper = document.createElement("div");
    sliderWrapper.style.position = "relative";

    const radiusSlider = document.createElement("input");
    radiusSlider.type = "range";
    radiusSlider.className = "form-range";
    radiusSlider.min = "2";
    radiusSlider.max = "10";
    radiusSlider.value = this.simpleCircleRadius;
    radiusSlider.id = `radius-slider-${this.mapId}`;

    // Create tooltip with point preview
    const tooltip = document.createElement("div");
    tooltip.className = "radius-slider-tooltip";
    tooltip.style.cssText = `
      position: absolute;
      bottom: 100%;
      left: 50%;
      transform: translateX(-50%);
      background: #333;
      color: #fff;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      white-space: nowrap;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.15s;
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
    `;

    const tooltipCircle = document.createElement("span");
    tooltipCircle.style.cssText = `
      display: inline-block;
      width: ${this.simpleCircleRadius * 2}px;
      height: ${this.simpleCircleRadius * 2}px;
      background: #0d6efd;
      border: 2px solid #fff;
      border-radius: 50%;
      box-sizing: border-box;
    `;

    const tooltipText = document.createElement("span");
    tooltipText.textContent = this.simpleCircleRadius;

    tooltip.appendChild(tooltipCircle);
    tooltip.appendChild(tooltipText);

    const updateTooltipPosition = () => {
      const percent =
        (radiusSlider.value - radiusSlider.min) /
        (radiusSlider.max - radiusSlider.min);
      const sliderWidth = radiusSlider.offsetWidth;
      const thumbWidth = 16;
      const left = percent * (sliderWidth - thumbWidth) + thumbWidth / 2;
      tooltip.style.left = `${left}px`;
      tooltip.style.transform = "translateX(-50%)";
    };

    const updateTooltipContent = (value) => {
      tooltipCircle.style.width = `${value * 2}px`;
      tooltipCircle.style.height = `${value * 2}px`;
      // Interpolate stroke width: 1 at radius 2, 2 at radius 10
      const strokeWidth = 1 + ((value - 2) / (10 - 2)) * (2 - 1);
      tooltipCircle.style.borderWidth = `${strokeWidth}px`;
      tooltipText.textContent = value;
    };

    radiusSlider.addEventListener("input", (e) => {
      const value = parseInt(e.target.value, 10);
      this.setSimpleCircleRadius(value);
      updateTooltipContent(value);
      updateTooltipPosition();
    });

    radiusSlider.addEventListener("mouseenter", () => {
      tooltip.style.opacity = "1";
      updateTooltipPosition();
    });

    radiusSlider.addEventListener("mouseleave", () => {
      tooltip.style.opacity = "0";
    });

    radiusSlider.addEventListener("focus", () => {
      tooltip.style.opacity = "1";
      updateTooltipPosition();
    });

    radiusSlider.addEventListener("blur", () => {
      tooltip.style.opacity = "0";
    });

    sliderWrapper.appendChild(tooltip);
    sliderWrapper.appendChild(radiusSlider);
    radiusContainer.appendChild(radiusLabel);
    radiusContainer.appendChild(sliderWrapper);
    overlayContainer.appendChild(radiusContainer);

    // Store references for later updates
    this.styleButtons = { heatmap: heatmapBtn, simple: simpleBtn };
    this.radiusContainer = radiusContainer;
    this.radiusSlider = radiusSlider;
    this.styleGroup = styleGroup;
  }

  toggleImageLayers() {
    this.imageLayersVisible = !this.imageLayersVisible;
    this.applyImageLayerVisibility();
    this.updateStyleControlsState();

    const imageLayerItem = this.offcanvas.querySelector(
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

  updateStyleControlsState() {
    const disabled = !this.imageLayersVisible;

    // Disable/enable style toggle buttons
    if (this.styleButtons) {
      this.styleButtons.heatmap.disabled = disabled;
      this.styleButtons.simple.disabled = disabled;
    }

    // Disable/enable radius slider
    if (this.radiusSlider) {
      this.radiusSlider.disabled = disabled;
    }

    // Visually indicate disabled state
    if (this.styleGroup) {
      this.styleGroup.style.opacity = disabled ? "0.5" : "1";
      this.styleGroup.style.pointerEvents = disabled ? "none" : "auto";
    }
    if (this.radiusContainer) {
      this.radiusContainer.style.opacity = disabled ? "0.5" : "1";
      this.radiusContainer.style.pointerEvents = disabled ? "none" : "auto";
    }
  }

  setImageDisplayStyle(style) {
    if (style !== "heatmap" && style !== "simple") return;
    this.imageDisplayStyle = style;
    this.applyImageLayerVisibility();

    // Show/hide radius slider based on style
    if (this.radiusContainer) {
      this.radiusContainer.style.display =
        style === "simple" ? "block" : "none";
    }
  }

  setSimpleCircleRadius(radius) {
    this.simpleCircleRadius = radius;
    if (this.map.getLayer("image-circles-simple")) {
      this.map.setPaintProperty(
        "image-circles-simple",
        "circle-radius",
        radius,
      );
      // Interpolate stroke width: 1 at radius 2, 2 at radius 10
      const strokeWidth = 1 + ((radius - 2) / (10 - 2)) * (2 - 1);
      this.map.setPaintProperty(
        "image-circles-simple",
        "circle-stroke-width",
        strokeWidth,
      );
    }
    if (this.map.getLayer("image-directions-simple")) {
      // Interpolate icon size: 0.4 at radius 2, 1.2 at radius 10
      const iconSize = 0.4 + ((radius - 2) / (10 - 2)) * (1.2 - 0.4);
      this.map.setLayoutProperty(
        "image-directions-simple",
        "icon-size",
        iconSize,
      );
    }
  }

  applyImageLayerVisibility() {
    const showHeatmap =
      this.imageLayersVisible && this.imageDisplayStyle === "heatmap";
    const showSimple =
      this.imageLayersVisible && this.imageDisplayStyle === "simple";

    // Heatmap style layers
    if (this.map.getLayer("image-heatmap")) {
      this.map.setLayoutProperty(
        "image-heatmap",
        "visibility",
        showHeatmap ? "visible" : "none",
      );
    }
    if (this.map.getLayer("image-circles")) {
      this.map.setLayoutProperty(
        "image-circles",
        "visibility",
        showHeatmap ? "visible" : "none",
      );
    }
    if (this.map.getLayer("image-directions")) {
      this.map.setLayoutProperty(
        "image-directions",
        "visibility",
        showHeatmap ? "visible" : "none",
      );
    }

    // Simple style layers
    if (this.map.getLayer("image-circles-simple")) {
      this.map.setLayoutProperty(
        "image-circles-simple",
        "visibility",
        showSimple ? "visible" : "none",
      );
    }
    if (this.map.getLayer("image-directions-simple")) {
      this.map.setLayoutProperty(
        "image-directions-simple",
        "visibility",
        showSimple ? "visible" : "none",
      );
    }
  }

  addErrorItem() {
    const overlayContainer = this.offcanvas.querySelector(
      ".overlay-layers-container",
    );

    const errorText = document.createElement("p");
    errorText.className = "text-muted small mt-3";
    errorText.textContent = "Failed to load map layers";
    overlayContainer.appendChild(errorText);
  }
}
