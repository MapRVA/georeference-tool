/**
 * Georeference Interface JavaScript
 * Handles map interaction, georeferencing functionality, and UI interactions
 */

import "../../styles/pages/georeference-interface.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "@maplibre/maplibre-gl-geocoder/dist/maplibre-gl-geocoder.css";
import "photoswipe/dist/photoswipe.css";

import maplibregl from "maplibre-gl";
import * as pmtiles from "pmtiles";
import MaplibreGeocoder from "@maplibre/maplibre-gl-geocoder";
import PhotoSwipe from "photoswipe";
import PhotoSwipeLightbox from "photoswipe/lightbox";

import { initSubjectEditor } from "../components/subject_editor.js";

document.addEventListener("DOMContentLoaded", function () {
  // Check if configuration is available
  if (!window.georeferenceConfig) {
    console.error("Georeference configuration not found");
    return;
  }

  const config = window.georeferenceConfig;

  // Initialize difficulty filter toggles if they exist in the DOM
  // (shown when not viewing a specific image via URL parameter)
  const difficultyFilterGroup = document.getElementById(
    "difficulty-filter-group",
  );
  if (difficultyFilterGroup) {
    initializeDifficultyToggles();
  }

  // Initialize PhotoSwipe lightbox
  initializePhotoSwipe();

  // Initialize main functionality if we have a current image
  if (config.currentImage) {
    initializeGeoreferenceInterface();
  }

  // Initialize subject editor component
  initSubjectEditor();

  /**
   * Initialize difficulty filter toggles for the main interface
   */
  function initializeDifficultyToggles() {
    const difficultyToggles = document.querySelectorAll(".difficulty-toggle");
    const currentFilters = config.difficultyFilters || [];

    difficultyToggles.forEach((button) => {
      const difficulty = button.dataset.difficulty;

      // Set initial state based on current filters
      if (currentFilters.includes(difficulty)) {
        updateDifficultyButtonState(button, true);
      } else {
        updateDifficultyButtonState(button, false);
      }

      // Add click handler
      button.addEventListener("click", function () {
        const isActive =
          button.classList.contains("btn-success") ||
          button.classList.contains("btn-warning") ||
          button.classList.contains("btn-danger") ||
          button.classList.contains("btn-secondary");

        // Toggle the state
        updateDifficultyButtonState(button, !isActive);

        // Update URL with new filter selection
        updateDifficultyFilter();
      });
    });
  }

  function updateDifficultyButtonState(button, isActive) {
    const difficulty = button.dataset.difficulty;

    if (isActive) {
      // Active state - solid color
      button.className = `btn btn-sm btn-${getDifficultyColor(difficulty)} difficulty-toggle`;
    } else {
      // Inactive state - outline
      button.className = `btn btn-sm btn-outline-${getDifficultyColor(difficulty)} difficulty-toggle`;
    }
  }

  function getDifficultyColor(difficulty) {
    const colors = {
      easy: "success",
      medium: "warning",
      hard: "danger",
      unlabeled: "secondary",
    };
    return colors[difficulty] || "secondary";
  }

  function updateDifficultyFilter() {
    const urlParams = new URLSearchParams(window.location.search);
    const difficultyToggles = document.querySelectorAll(".difficulty-toggle");

    // Remove existing difficulty parameter
    urlParams.delete("difficulty");

    // Collect active difficulties
    const activeDifficulties = [];
    difficultyToggles.forEach((button) => {
      const isActive =
        button.classList.contains("btn-success") ||
        button.classList.contains("btn-warning") ||
        button.classList.contains("btn-danger") ||
        button.classList.contains("btn-secondary");

      if (isActive) {
        activeDifficulties.push(button.dataset.difficulty);
      }
    });

    // Add single plus-separated difficulty parameter if any are active
    if (activeDifficulties.length > 0) {
      urlParams.set("difficulty", activeDifficulties.join("+"));
    }

    // Update URL
    const newUrl = window.location.pathname + "?" + urlParams.toString();
    window.location.href = newUrl;
  }

  /**
   * Initialize PhotoSwipe lightbox for image gallery
   */
  function initializePhotoSwipe() {
    // Function to setup PhotoSwipe data for images
    function setupPhotoSwipeData(img) {
      const link = img.parentElement;
      link.setAttribute("data-pswp-width", img.naturalWidth);
      link.setAttribute("data-pswp-height", img.naturalHeight);
    }

    // Initialize PhotoSwipe lightbox
    if (PhotoSwipeLightbox) {
      const lightbox = new PhotoSwipeLightbox({
        gallery: "#pswp-gallery",
        children: "a",
        showHideAnimationType: "fade",
        zoomAnimationDuration: 300,
        maxZoomLevel: 8,
        wheelToZoom: true,
        pswpModule: PhotoSwipe,
      });

      lightbox.init();

      // Setup data for main image when it loads
      const mainImage = document.getElementById("main-image");
      if (mainImage) {
        mainImage.onload = function () {
          setupPhotoSwipeData(this);
        };

        if (mainImage.complete && mainImage.naturalHeight !== 0) {
          setupPhotoSwipeData(mainImage);
        }
      }
    }
  }

  /**
   * Initialize the main georeference interface
   */
  function initializeGeoreferenceInterface() {
    // Global PMTiles setup
    window.pmtilesProtocolSetup = false;

    window.setupPMTilesProtocol = function () {
      if (window.pmtilesProtocolSetup) return true;

      if (pmtiles) {
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

    // Get DOM elements
    const skipButton = document.getElementById("skipButton");
    const submitButton = document.getElementById("submitButton");
    const willNotGeorefButton = document.getElementById("willNotGeorefButton");
    const markDifficultyButtons = document.querySelectorAll(".mark-difficulty");
    const confidenceNotes = document.getElementById("confidence-notes");
    const isStaff = config.isStaff;
    const isImageGeoreferenced = config.currentImage.isGeoreferenced;

    // Add PMTiles protocol
    if (pmtiles) {
      let protocol = new pmtiles.Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
    }

    // Initialize map
    var map = new maplibregl.Map({
      container: "mymap",
      style: "https://styles.trailsta.sh/openmaptiles-osm.json",
      center: [-77.44, 37.53],
      zoom: 11.5,
    });

    // Try to setup PMTiles protocol
    window.setupPMTilesProtocol();

    // Initialize Layer Control
    class LayerControl {
      constructor() {
        this.baseLayers = {
          osm: {
            name: "OpenStreetMap",
            isDefault: true,
            setupLayer: () => {
              // OSM is the default style, no additional setup needed
            },
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
        this.mapLayersLoaded = false;
        this.collectionsData = null;
      }

      onAdd(map) {
        this.map = map;
        this.container = document.createElement("div");
        this.container.className =
          "maplibregl-ctrl maplibregl-ctrl-group layer-control";

        // Generate base layer options dynamically
        const baseLayerOptions = Object.entries(this.baseLayers)
          .map(([key, layer]) => {
            const activeClass = layer.isDefault ? " active" : "";
            return `<li><a class="dropdown-item layer-option${activeClass}" href="#" data-layer="${key}">${layer.name}</a></li>`;
          })
          .join("");

        this.container.innerHTML = `
                    <div class="dropdown">
                        <button class="dropdown-toggle" type="button" id="layerDropdown-georef" data-bs-toggle="dropdown" aria-expanded="false" data-bs-container="body">
                            ${this.baseLayers[this.currentBaseLayer].name}
                        </button>
                        <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="layerDropdown-georef">
                            ${baseLayerOptions}
                        </ul>
                    </div>
                `;

        this.layerDropdown = this.container.querySelector(".dropdown-toggle");
        this.setupEventListeners();

        // Defer layer setup until map is loaded
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
        // Setup all base layers
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
            layout: {
              visibility: "none",
            },
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
            layout: {
              visibility: "none",
            },
          });
        }
      }

      setupEventListeners() {
        // Add event listeners for base layer options
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
        if (
          !this.baseLayers[newLayerKey] ||
          newLayerKey === this.currentBaseLayer
        )
          return;

        // Deactivate current base layer
        this.baseLayers[this.currentBaseLayer].deactivate();

        // Activate new base layer
        this.baseLayers[newLayerKey].activate();

        // Update current layer
        this.currentBaseLayer = newLayerKey;

        // Update dropdown display
        let currentLayerName;
        if (this.currentOverlayLayer) {
          // Get the overlay layer title from the current button text
          const currentText = this.layerDropdown.textContent;
          const overlayTitle = currentText.split(" + ")[1]; // Extract overlay name after " + "
          currentLayerName = `${this.baseLayers[newLayerKey].name} + ${overlayTitle}`;
        } else {
          currentLayerName = this.baseLayers[newLayerKey].name;
        }
        this.updateDropdownSelection(currentLayerName, newLayerKey);
      }

      showOSMLayers() {
        // Hide other base layers
        this.hideOtherBaseLayers(["satellite-layer", "usgs-layer"]);

        // Show OSM layers (all layers except our custom base layers and overlays)
        const layers = this.map.getStyle().layers;
        layers.forEach((layer) => {
          if (
            !this.isOverlayLayer(layer.id) &&
            !this.isCustomBaseLayer(layer.id)
          ) {
            this.map.setLayoutProperty(layer.id, "visibility", "visible");
          }
        });
      }

      hideOSMLayers() {
        const layers = this.map.getStyle().layers;
        layers.forEach((layer) => {
          if (
            !this.isOverlayLayer(layer.id) &&
            !this.isCustomBaseLayer(layer.id)
          ) {
            this.map.setLayoutProperty(layer.id, "visibility", "none");
          }
        });
      }

      showSatelliteLayer() {
        this.hideOSMLayers();
        this.hideOtherBaseLayers(["usgs-layer"]);
        if (this.map.getLayer("satellite-layer")) {
          this.map.setLayoutProperty(
            "satellite-layer",
            "visibility",
            "visible",
          );
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
          layerId === "pin-circle" ||
          layerId === "pin-symbol" ||
          layerId === "context-image-circles" ||
          layerId === "context-image-directions" ||
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

        // For PMTiles, check if protocol is set up
        if (tileType === "pmtiles") {
          console.log(
            "PMTiles protocol setup status:",
            window.pmtilesProtocolSetup,
          );
          console.log("PMTiles available:", !!pmtiles);

          // Check if PMTiles protocol has been set up
          if (!window.pmtilesProtocolSetup) {
            console.error(
              "PMTiles protocol not available! Attempting to set up now...",
            );
            // Try to set it up now
            if (!window.setupPMTilesProtocol()) {
              alert(
                "PMTiles map overlay layers are not available - PMTiles protocol not loaded.",
              );
              return;
            }
            console.log("PMTiles protocol setup successful, continuing...");
          }
        }

        // If clicking the same layer, deactivate it
        if (this.currentOverlayLayer === layerId) {
          console.log("Deactivating current overlay layer:", layerId);
          this.map.setLayoutProperty(layerId, "visibility", "none");
          this.currentOverlayLayer = null;
          const baseLayerName = this.baseLayers[this.currentBaseLayer].name;
          this.updateDropdownSelection(baseLayerName, this.currentBaseLayer);
          return;
        }

        // Hide other overlay layers
        const layers = this.map.getStyle().layers;
        layers.forEach((layer) => {
          if (layer.id.startsWith("overlay-") && layer.id !== layerId) {
            this.map.setLayoutProperty(layer.id, "visibility", "none");
          }
        });

        // Add source if it doesn't exist
        const sourceId = `${layerId}-source`;
        if (!this.map.getSource(sourceId)) {
          console.log(`Adding ${tileType} source:`, sourceId, tileUrl);
          try {
            // Different source configuration based on tile type
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

        // Add layer if it doesn't exist
        if (!this.map.getLayer(layerId)) {
          console.log("Adding overlay layer:", layerId);
          try {
            // Add before pin layers so pin/direction indicators appear on top
            const beforeId = this.map.getLayer("pin-circle")
              ? "pin-circle"
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
                layout: {
                  visibility: "visible",
                },
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

        // Show the selected overlay layer
        this.map.setLayoutProperty(layerId, "visibility", "visible");

        this.currentOverlayLayer = layerId;
        // Combine base layer name with overlay layer title
        const combinedTitle = `${this.baseLayers[this.currentBaseLayer].name} + ${title}`;
        this.updateDropdownSelection(combinedTitle, layerId);
        console.log("Overlay layer switch complete");
      }

      updateDropdownSelection(buttonText, selectedLayer) {
        this.layerDropdown.textContent = buttonText;

        // Clear all active states
        this.container
          .querySelectorAll(".layer-option, .overlay-layer")
          .forEach((item) => {
            item.classList.remove("active");
          });

        // Highlight active layers
        if (this.currentOverlayLayer) {
          // Highlight both base layer and overlay layer
          const baseLayerItem = this.container.querySelector(
            `[data-layer="${this.currentBaseLayer}"]`,
          );
          if (baseLayerItem) baseLayerItem.classList.add("active");

          const overlayLayerItem = this.container.querySelector(
            `[data-layer="${this.currentOverlayLayer}"]`,
          );
          if (overlayLayerItem) overlayLayerItem.classList.add("active");
        } else {
          // Only highlight base layer
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
          const response = await fetch(config.urls.mapLayers);
          console.log("Map layers response:", response);

          if (!response.ok)
            throw new Error(`Failed to fetch map layers: ${response.status}`);

          const data = await response.json();
          console.log("Map layers data:", data);

          // Store collections data with proper structure
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

          // Add divider before each collection (except if it's the first)
          if (collectionIndex > 0 || dropdownMenu.children.length > 0) {
            const dividerItem = document.createElement("li");
            const divider = document.createElement("hr");
            divider.className = "dropdown-divider";
            dividerItem.appendChild(divider);
            dropdownMenu.appendChild(dividerItem);
          }

          // Add collection header
          const headerItem = document.createElement("li");
          const header = document.createElement("h6");
          header.className = "dropdown-header";
          header.textContent = collection.name;
          headerItem.appendChild(header);
          dropdownMenu.appendChild(headerItem);

          // Add layers for this collection
          collection.layers.forEach((layer) => {
            const layerId = `overlay-${layerIndex}`;
            const listItem = document.createElement("li");
            const layerItem = document.createElement("a");
            layerItem.className = "dropdown-item overlay-layer";
            layerItem.href = "#";
            layerItem.dataset.layer = layerId;
            layerItem.dataset.tileUrl = layer.url;
            layerItem.dataset.tileType = layer.type || "pmtiles"; // Default to pmtiles for backward compatibility
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

              // Close dropdown
              const dropdown = bootstrap.Dropdown.getInstance(
                this.layerDropdown,
              );
              if (dropdown) dropdown.hide();
            });

            listItem.appendChild(layerItem);
            dropdownMenu.appendChild(listItem);
            layerIndex++;
          });
        });
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

    // Function to add all map sources and layers
    async function addMapSourcesAndLayers() {
      try {
        const image = await map.loadImage(
          "https://maprva.org/img/surveillance-direction.png",
        );
        map.addImage("surveillance-direction", image.data);
      } catch (error) {
        console.warn("Could not load direction arrow image:", error);
      }

      map.addSource("pin", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: [],
        },
      });

      map.addLayer({
        id: "pin-circle",
        type: "circle",
        source: "pin",
        paint: {
          "circle-radius": 8,
          "circle-color": "#dc3545",
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });

      if (map.hasImage("surveillance-direction")) {
        map.addLayer({
          id: "pin-symbol",
          type: "symbol",
          source: "pin",
          layout: {
            "icon-image": "surveillance-direction",
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
          filter: ["has", "direction"],
        });
      }

      // Add all existing georeferenced images for context using vector tiles
      try {
        // Build vector tiles URL for all context images
        let contextVectorTilesUrl =
          window.location.origin +
          config.urls.vectorTiles.replace("/0/0/0.mvt", "/{z}/{x}/{y}.mvt");

        // Add vector tiles source for existing georeferenced images in this collection
        map.addSource("context-images", {
          type: "vector",
          tiles: [contextVectorTilesUrl],
          minzoom: 16,
        });

        // Add circles for existing images (styling depends on mode)
        map.addLayer({
          id: "context-image-circles",
          type: "circle",
          source: "context-images",
          "source-layer": "image_points",
          paint: {
            "circle-radius": 6,
            "circle-color": "#6c757d",
            "circle-opacity": 0.6,
            "circle-stroke-color": "#fff",
            "circle-stroke-width": 1,
            "circle-stroke-opacity": 0.8,
          },
          layout: {
            visibility: "visible",
          },
        });

        // Add de-emphasized direction markers for existing images
        if (map.hasImage("surveillance-direction")) {
          map.addLayer({
            id: "context-image-directions",
            type: "symbol",
            source: "context-images",
            "source-layer": "image_points",
            layout: {
              "icon-image": "surveillance-direction",
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
            filter: ["has", "direction"],
          });
        }

        // Update context images display based on initial mode
        updateContextImagesDisplay();
      } catch (error) {
        console.warn("Could not load context images:", error);
      }

      // Restore any existing pin if there was one
      if (pinPlaced) {
        const lat = parseFloat(latitudeInput.value);
        const lng = parseFloat(longitudeInput.value);
        if (!isNaN(lat) && !isNaN(lng)) {
          const properties = {};
          if (currentDirection !== null) {
            properties.direction = currentDirection;
          }

          map.getSource("pin").setData({
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: {
                  type: "Point",
                  coordinates: [lng, lat],
                },
                properties: properties,
              },
            ],
          });
        }
      }
    }

    // Add LayerControl to map
    map.addControl(new LayerControl(), "top-right");
    map.addControl(new maplibregl.NavigationControl());
    map.addControl(new maplibregl.FullscreenControl());

    // Get DOM elements for controls
    var latitudeInput = document.getElementById("latitude-input");
    var longitudeInput = document.getElementById("longitude-input");
    var directionInput = document.getElementById("direction-input");
    var joystickContainer = document.getElementById("joystick-container");
    var joystickHandle = document.getElementById("joystick-handle");

    // State variables
    var pinPlaced = false;
    var currentDirection = null;
    var isJoystickDragging = false;
    var contextDisplayMode = "ghost"; // Default to ghost mode
    var isHoveringContextImage = false; // Track when hovering over context images
    var activePopup = null; // Track active popup

    map.getCanvas().style.cursor = "crosshair";

    const confidenceRadios = document.querySelectorAll(
      'input[name="confidence"]',
    );
    const notesRequiredIndicator = document.getElementById(
      "notes-required-indicator",
    );
    const notesHelpText = document.getElementById("notes-help-text");
    const confidenceHighRadio = document.getElementById("confidence-high");

    if (
      !confidenceNotes ||
      !notesRequiredIndicator ||
      !notesHelpText ||
      !confidenceHighRadio
    ) {
      console.error("Confidence elements not found in DOM");
    }

    // Handle image loading and fallback
    const mainImage = document.getElementById("main-image");
    const imageFallback = document.getElementById("image-fallback");

    if (mainImage && imageFallback) {
      mainImage.onload = function () {
        imageFallback.style.setProperty("display", "none", "important");
        mainImage.style.display = "block";
        mainImage.style.visibility = "visible";
        if (typeof setupPhotoSwipeData === "function") {
          setupPhotoSwipeData(this);
        }
      };

      mainImage.onerror = function () {
        mainImage.style.display = "none";
        imageFallback.style.setProperty("display", "flex", "important");
      };

      if (mainImage.complete) {
        if (mainImage.naturalHeight !== 0 && mainImage.naturalWidth !== 0) {
          imageFallback.style.setProperty("display", "none", "important");
          mainImage.style.display = "block";
          mainImage.style.visibility = "visible";
          if (typeof setupPhotoSwipeData === "function") {
            setupPhotoSwipeData(mainImage);
          }
        } else {
          mainImage.style.display = "none";
          imageFallback.style.setProperty("display", "flex", "important");
        }
      }
    }

    // Helper functions
    function updateCoordinates(lng, lat) {
      latitudeInput.value = lat.toFixed(6);
      longitudeInput.value = lng.toFixed(6);
      submitButton.disabled = false;
    }

    function updateDirection(direction) {
      currentDirection = direction;

      if (direction !== null) {
        directionInput.value = Math.round(direction) + "°";
        directionInput.classList.remove("inactive");
      } else {
        directionInput.value = "";
        directionInput.classList.add("inactive");
        updateJoystickHandle(0, 0);
      }

      // Update pin direction
      if (pinPlaced) {
        var lat = parseFloat(latitudeInput.value);
        var lng = parseFloat(longitudeInput.value);
        if (!isNaN(lat) && !isNaN(lng)) {
          var properties = {};
          if (direction !== null) {
            properties.direction = direction;
          }
          map.getSource("pin").setData({
            type: "FeatureCollection",
            features: [
              {
                type: "Feature",
                geometry: {
                  type: "Point",
                  coordinates: [lng, lat],
                },
                properties: properties,
              },
            ],
          });
        }
      }

      // Update confidence validation based on new direction
      updateConfidenceValidation();
    }

    function getJoystickMaxRadius() {
      var containerRect = joystickContainer.getBoundingClientRect();
      var handleRect = joystickHandle.getBoundingClientRect();
      var handleMargin = handleRect.width / 2; // Half the handle size as margin
      return containerRect.width / 2 - handleMargin;
    }

    function updateJoystickHandle(x, y) {
      var maxRadius = getJoystickMaxRadius();
      var distance = Math.sqrt(x * x + y * y);

      if (distance > maxRadius) {
        var ratio = maxRadius / distance;
        x *= ratio;
        y *= ratio;
      }

      joystickHandle.style.transform =
        "translate(calc(-50% + " + x + "px), calc(-50% + " + y + "px))";
    }

    function updatePinLocation(lng, lat, direction) {
      if (!map.getSource("pin")) return;

      var properties = {};
      if (direction !== null) {
        properties.direction = direction;
      }

      map.getSource("pin").setData({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: {
              type: "Point",
              coordinates: [lng, lat],
            },
            properties: properties,
          },
        ],
      });

      map.setCenter([lng, lat]);
    }

    function handleJoystickMove(clientX, clientY) {
      if (!pinPlaced) return;

      var rect = joystickContainer.getBoundingClientRect();
      var centerX = rect.left + rect.width / 2;
      var centerY = rect.top + rect.height / 2;
      var x = clientX - centerX;
      var y = clientY - centerY;

      // Calculate direction (0° is north)
      var angle = (Math.atan2(y, x) * 180) / Math.PI;
      var direction = (angle + 90) % 360;
      if (direction < 0) direction += 360;

      updateDirection(direction);
      updateJoystickHandle(x, y);
    }

    function updateMapSwapLink() {
      const mapswapLink = document.getElementById("mapswap-link");
      if (mapswapLink && map) {
        const center = map.getCenter();
        const zoom = map.getZoom().toFixed(2);
        const lat = center.lat.toFixed(6);
        const lng = center.lng.toFixed(6);
        const url = `https://mapswap.trailsta.sh/swap/#type=m&url=geo:${lat},${lng};z=${zoom}`;
        mapswapLink.href = url;
      }
    }

    function updateConfidenceValidation() {
      if (!confidenceHighRadio) return; // Guard against missing element

      if (currentDirection === null) {
        // Disable high confidence when no direction is set
        confidenceHighRadio.disabled = true;
        // If high confidence was selected, switch to medium
        if (confidenceHighRadio.checked) {
          const mediumRadio = document.getElementById("confidence-medium");
          if (mediumRadio) {
            mediumRadio.checked = true;
            // Trigger change event to update UI
            mediumRadio.dispatchEvent(new Event("change"));
          }
        }
      } else {
        // Enable high confidence when direction is set
        confidenceHighRadio.disabled = false;
      }
    }

    function showAlert(type, message) {
      const alertDiv = document.createElement("div");
      alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
      alertDiv.style.cssText =
        "top: 20px; right: 20px; z-index: 9999; min-width: 300px;";
      alertDiv.innerHTML = `
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;

      document.body.appendChild(alertDiv);

      setTimeout(() => {
        alertDiv.remove();
      }, 5000);
    }

    function performSubmission() {
      const lat = parseFloat(latitudeInput.value);
      const lng = parseFloat(longitudeInput.value);
      const dir =
        currentDirection !== null ? Math.round(currentDirection) : null;
      const notes = confidenceNotes.value.trim();
      const selectedConfidence = document.querySelector(
        'input[name="confidence"]:checked',
      );
      let confidence = selectedConfidence ? selectedConfidence.value : "medium";

      // Check for the override from the modal
      const forceHighConfidenceCheckbox = document.getElementById(
        "force-high-confidence-checkbox",
      );
      if (forceHighConfidenceCheckbox && forceHighConfidenceCheckbox.checked) {
        confidence = "high";
      }

      const data = {
        latitude: lat,
        longitude: lng,
        direction: dir,
        notes: notes,
        confidence: confidence,
      };

      // Get CSRF token
      const csrfToken =
        document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
        document
          .querySelector('meta[name="csrf-token"]')
          ?.getAttribute("content") ||
        config.csrfToken;

      submitButton.disabled = true;
      if (isImageGeoreferenced) {
        submitButton.innerHTML =
          '<i class="fas fa-spinner fa-spin me-2"></i>Submitting Correction...';
      } else {
        submitButton.innerHTML =
          '<i class="fas fa-spinner fa-spin me-2"></i>Submitting...';
      }

      fetch(config.urls.georeferenceImage, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify(data),
      })
        .then((response) => response.json())
        .then((data) => {
          if (data.success) {
            if (isImageGeoreferenced) {
              showAlert("success", "Correction submitted successfully!");
            } else {
              showAlert("success", "Image georeferenced successfully!");
            }
            // Clear the form and reset for next image
            setTimeout(() => {
              // Check if we came from a specific image
              const urlParams = new URLSearchParams(window.location.search);
              const specificImageRequested = urlParams.has("image");

              if (specificImageRequested) {
                // Redirect back to the image detail page
                window.location.href = config.urls.imageDetail;
              } else {
                clearFormAndGetNext();
              }
            }, 1500);
          } else {
            showAlert("danger", "Error: " + data.error);
            submitButton.disabled = false;
            if (isImageGeoreferenced) {
              submitButton.innerHTML =
                '<i class="fas fa-edit me-2"></i>Submit Correction';
            } else {
              submitButton.innerHTML =
                '<i class="fas fa-check me-2"></i>Submit Georeference';
            }
          }
        })
        .catch((error) => {
          showAlert("danger", "Network error occurred");
          submitButton.disabled = false;
          if (isImageGeoreferenced) {
            submitButton.innerHTML =
              '<i class="fas fa-edit me-2"></i>Submit Correction';
          } else {
            submitButton.innerHTML =
              '<i class="fas fa-check me-2"></i>Submit Georeference';
          }
        });
    }

    function clearFormAndGetNext() {
      // Clear coordinate inputs
      latitudeInput.value = "";
      longitudeInput.value = "";
      directionInput.value = "";
      directionInput.classList.add("inactive");
      confidenceNotes.value = "";

      // Clear confidence selection
      if (confidenceRadios && confidenceRadios.length > 0) {
        confidenceRadios.forEach((radio) => (radio.checked = false));
      }
      if (notesRequiredIndicator) notesRequiredIndicator.style.display = "none";
      if (notesHelpText) notesHelpText.style.display = "none";
      if (confidenceNotes) confidenceNotes.required = false;

      // Clear map
      if (map.getSource("pin")) {
        map.getSource("pin").setData({
          type: "FeatureCollection",
          features: [],
        });
      }

      // Reset state
      pinPlaced = false;
      currentDirection = null;
      submitButton.disabled = true;
      updateJoystickHandle(0, 0);

      // Reset confidence validation
      if (confidenceHighRadio) confidenceHighRadio.disabled = false;

      // Scroll to top and reload to get next image
      window.scrollTo(0, 0);
      location.reload();
    }

    function updateContextImagesDisplay() {
      if (!map.getLayer("context-image-circles")) return;

      switch (contextDisplayMode) {
        case "hidden":
          map.setLayoutProperty("context-image-circles", "visibility", "none");
          if (map.getLayer("context-image-directions")) {
            map.setLayoutProperty(
              "context-image-directions",
              "visibility",
              "none",
            );
          }
          // Close any existing popup
          if (activePopup) {
            activePopup.remove();
            activePopup = null;
          }
          // Remove click handlers
          map.off("click", "context-image-circles");
          map.off("mouseenter", "context-image-circles");
          map.off("mouseleave", "context-image-circles");
          // Reset hover state and cursor
          isHoveringContextImage = false;
          map.getCanvas().style.cursor = "crosshair";
          break;

        case "ghost":
          map.setLayoutProperty(
            "context-image-circles",
            "visibility",
            "visible",
          );
          if (map.getLayer("context-image-directions")) {
            map.setLayoutProperty(
              "context-image-directions",
              "visibility",
              "visible",
            );
          }
          // Set ghost styling
          map.setPaintProperty(
            "context-image-circles",
            "circle-color",
            "#6c757d",
          );
          map.setPaintProperty("context-image-circles", "circle-opacity", 0.6);
          map.setPaintProperty(
            "context-image-circles",
            "circle-stroke-opacity",
            0.8,
          );
          // Close any existing popup
          if (activePopup) {
            activePopup.remove();
            activePopup = null;
          }
          // Remove ALL handlers to make completely non-interactive
          map.off("click", "context-image-circles");
          map.off("mouseenter", "context-image-circles");
          map.off("mouseleave", "context-image-circles");
          // Reset hover state and cursor
          isHoveringContextImage = false;
          map.getCanvas().style.cursor = "crosshair";
          break;

        case "clickable":
          map.setLayoutProperty(
            "context-image-circles",
            "visibility",
            "visible",
          );
          if (map.getLayer("context-image-directions")) {
            map.setLayoutProperty(
              "context-image-directions",
              "visibility",
              "visible",
            );
          }
          // Set active styling
          map.setPaintProperty(
            "context-image-circles",
            "circle-color",
            "green",
          );
          map.setPaintProperty("context-image-circles", "circle-opacity", 1.0);
          map.setPaintProperty(
            "context-image-circles",
            "circle-stroke-opacity",
            1.0,
          );

          // Add click handlers like in map_display.html
          map.off("click", "context-image-circles"); // Remove existing handlers first
          map.on("click", "context-image-circles", function (e) {
            // Only show popup if in clickable mode
            if (contextDisplayMode !== "clickable") {
              return;
            }

            // Prevent the map click handler from firing when clicking on context images
            e.originalEvent.stopPropagation();

            const properties = e.features[0].properties;

            // Build absolute URL for image entry
            const imgEntry = window.location.origin + "/" + properties.id + "/";

            // Create popup content
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

            // Close any existing popup
            if (activePopup) {
              activePopup.remove();
            }

            // Create and track new popup
            activePopup = new maplibregl.Popup()
              .setLngLat(e.features[0].geometry.coordinates)
              .setHTML(popupContent)
              .addTo(map);

            // Clear the popup reference when it's closed
            activePopup.on("close", function () {
              activePopup = null;
              // Reset cursor to crosshairs when popup closes
              if (!isHoveringContextImage) {
                map.getCanvas().style.cursor = "crosshair";
              }
            });
          });

          // Add hover handlers
          map.off("mouseenter", "context-image-circles");
          map.off("mouseleave", "context-image-circles");
          map.on("mouseenter", "context-image-circles", function () {
            // Only change cursor if in clickable mode
            if (contextDisplayMode === "clickable") {
              map.getCanvas().style.cursor = "pointer";
              isHoveringContextImage = true;
            }
          });
          map.on("mouseleave", "context-image-circles", function () {
            // Only reset cursor if in clickable mode
            if (contextDisplayMode === "clickable") {
              map.getCanvas().style.cursor = "";
              isHoveringContextImage = false;
            }
          });
          break;
      }
    }

    // Map event handlers
    map.on("load", async () => {
      await addMapSourcesAndLayers();

      // Add address search control powered by Nominatim
      const geocoderApi = {
        forwardGeocode: async (config) => {
          const features = [];
          try {
            const request = `https://nominatim.openstreetmap.org/search?q=${
              config.query
            }&format=geojson&polygon_geojson=1&addressdetails=1&layer=address&viewbox=-77.61976,37.60954,-77.36673,37.44393&bounded=1`;
            const response = await fetch(request);
            const geojson = await response.json();
            for (const feature of geojson.features) {
              const center = [
                feature.bbox[0] + (feature.bbox[2] - feature.bbox[0]) / 2,
                feature.bbox[1] + (feature.bbox[3] - feature.bbox[1]) / 2,
              ];
              const point = {
                type: "Feature",
                geometry: {
                  type: "Point",
                  coordinates: center,
                },
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

          return {
            features,
          };
        },
      };

      if (MaplibreGeocoder) {
        const geocoder = new MaplibreGeocoder(geocoderApi, {
          maplibregl,
          placeholder: "Search places",
        });

        map.addControl(geocoder, "top-left");

        // fix geocoder search on mobile chrome
        const geocoderInput = document.getElementsByClassName(
          "maplibregl-ctrl-geocoder--input",
        )[0];
        if (geocoderInput) {
          geocoderInput.type = "search";
        }
      }

      // Initialize MapSwap link and update on map move
      updateMapSwapLink();
      map.on("moveend", updateMapSwapLink);
    });

    map.on("click", function (e) {
      // If there's an open popup, close it and don't place pin
      if (activePopup) {
        activePopup.remove();
        activePopup = null;
        return;
      }

      // Don't place pin if clicking on a context image
      if (isHoveringContextImage) {
        return;
      }

      var lng = e.lngLat.lng;
      var lat = e.lngLat.lat;

      map.getSource("pin").setData({
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            geometry: {
              type: "Point",
              coordinates: [lng, lat],
            },
            properties: {},
          },
        ],
      });

      pinPlaced = true;
      updateCoordinates(lng, lat);

      // Maintain current direction when placing new pin
      if (currentDirection !== null) {
        updateDirection(currentDirection);
        var radians = ((currentDirection - 90) * Math.PI) / 180;
        var radius = getJoystickMaxRadius();
        var x = Math.cos(radians) * radius;
        var y = Math.sin(radians) * radius;
        updateJoystickHandle(x, y);
      }
    });

    // Mouse events for joystick
    joystickContainer.addEventListener("mousedown", function (e) {
      e.preventDefault();
      isJoystickDragging = true;
      handleJoystickMove(e.clientX, e.clientY);
    });

    document.addEventListener("mousemove", function (e) {
      if (isJoystickDragging) {
        handleJoystickMove(e.clientX, e.clientY);
      }
    });

    document.addEventListener("mouseup", function () {
      isJoystickDragging = false;
    });

    // Touch events for joystick
    joystickContainer.addEventListener("touchstart", function (e) {
      e.preventDefault();
      isJoystickDragging = true;
      handleJoystickMove(e.touches[0].clientX, e.touches[0].clientY);
    });

    document.addEventListener("touchmove", function (e) {
      if (isJoystickDragging) {
        e.preventDefault();
        handleJoystickMove(e.touches[0].clientX, e.touches[0].clientY);
      }
    });

    document.addEventListener("touchend", function () {
      isJoystickDragging = false;
    });

    // Input handlers
    latitudeInput.addEventListener("change", function () {
      var lat = parseFloat(this.value);
      var lng = parseFloat(longitudeInput.value);
      if (!isNaN(lat) && !isNaN(lng) && lat >= -90 && lat <= 90) {
        updatePinLocation(lng, lat, currentDirection);
        pinPlaced = true;
        submitButton.disabled = false;
      }
    });

    longitudeInput.addEventListener("change", function () {
      var lng = parseFloat(this.value);
      var lat = parseFloat(latitudeInput.value);
      if (!isNaN(lng) && !isNaN(lat) && lng >= -180 && lng <= 180) {
        updatePinLocation(lng, lat, currentDirection);
        pinPlaced = true;
        submitButton.disabled = false;
      }
    });

    directionInput.addEventListener("change", function () {
      if (!pinPlaced) return;

      var directionText = this.value.replace("°", "");
      var direction = parseFloat(directionText);

      if (!isNaN(direction)) {
        direction = direction % 360;
        if (direction < 0) direction += 360;

        updateDirection(direction);

        var radians = ((direction - 90) * Math.PI) / 180;
        var radius = getJoystickMaxRadius();
        var x = Math.cos(radians) * radius;
        var y = Math.sin(radians) * radius;
        updateJoystickHandle(x, y);
      }
    });

    document
      .getElementById("reset-direction")
      .addEventListener("click", function () {
        if (!pinPlaced) return;
        updateDirection(null);
      });

    // Handle confidence level changes
    if (confidenceRadios && confidenceRadios.length > 0) {
      confidenceRadios.forEach((radio) => {
        radio.addEventListener("change", function () {
          if (this.value === "low") {
            // Show required indicator and help text for low confidence
            if (notesRequiredIndicator)
              notesRequiredIndicator.style.display = "inline";
            if (notesHelpText) notesHelpText.style.display = "block";
            if (confidenceNotes) confidenceNotes.required = true;
          } else {
            // Hide required indicator and help text for medium/high confidence
            if (notesRequiredIndicator)
              notesRequiredIndicator.style.display = "none";
            if (notesHelpText) notesHelpText.style.display = "none";
            if (confidenceNotes) confidenceNotes.required = false;
          }

          // Disable high confidence if no direction is specified
          updateConfidenceValidation();
        });
      });
    }

    // Handle submit button
    submitButton.addEventListener("click", function () {
      if (!pinPlaced) {
        showAlert("warning", "Please select a location on the map first");
        return;
      }

      // Check if confidence level is selected
      const selectedConfidence = document.querySelector(
        'input[name="confidence"]:checked',
      );
      if (!selectedConfidence) {
        showAlert("warning", "Please select a confidence level");
        return;
      }

      // Check if notes are required for low confidence
      if (
        selectedConfidence.value === "low" &&
        confidenceNotes.value.trim() === ""
      ) {
        showAlert(
          "warning",
          "Low confidence georeferences must include a descriptive note",
        );
        confidenceNotes.focus();
        return;
      }

      // Check if direction is missing and show confirmation modal
      if (currentDirection === null) {
        const forceHighConfidenceContainer = document.getElementById(
          "force-high-confidence-container",
        );
        const forceHighConfidenceCheckbox = document.getElementById(
          "force-high-confidence-checkbox",
        );

        if (selectedConfidence.value === "medium") {
          forceHighConfidenceContainer.style.display = "block";
        } else {
          forceHighConfidenceContainer.style.display = "none";
        }
        if (forceHighConfidenceCheckbox) {
          forceHighConfidenceCheckbox.checked = false; // Always reset checkbox
        }

        const directionModal = new bootstrap.Modal(
          document.getElementById("directionConfirmModal"),
        );
        directionModal.show();
        return; // Don't proceed with submission yet
      }

      // Proceed with submission
      performSubmission();
    });

    // Handle confirmation button in modal
    document
      .getElementById("confirmSubmitWithoutDirection")
      .addEventListener("click", function () {
        const directionModal = bootstrap.Modal.getInstance(
          document.getElementById("directionConfirmModal"),
        );
        directionModal.hide();
        performSubmission();
      });

    // Handle skip button (available to everyone)
    if (skipButton) {
      skipButton.addEventListener("click", function () {
        const csrfToken =
          document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
          document
            .querySelector('meta[name="csrf-token"]')
            ?.getAttribute("content") ||
          config.csrfToken;

        // Check if we came from a specific image (image parameter in URL)
        const urlParams = new URLSearchParams(window.location.search);
        const specificImageRequested = urlParams.has("image");

        fetch(config.urls.skipImage, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: JSON.stringify({ reason: "Skipped during georeferencing" }),
        })
          .then((response) => response.json())
          .then((data) => {
            if (data.success) {
              showAlert("info", "Image skipped");
              setTimeout(() => {
                if (specificImageRequested) {
                  // Redirect back to the image detail page
                  window.location.href = config.urls.imageDetail;
                } else {
                  clearFormAndGetNext();
                }
              }, 1000);
            } else {
              showAlert("danger", "Error: " + data.error);
            }
          });
      });
    }

    // Difficulty marking functionality (admin only)
    function handleDifficultyClick() {
      const difficulty = this.dataset.difficulty;
      const clickedButton = this;
      const csrfToken =
        document.querySelector('[name="csrfmiddlewaretoken"]')?.value ||
        config.csrfToken;

      clickedButton.disabled = true;
      const originalText = clickedButton.innerHTML;
      clickedButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

      const formData = new FormData();
      formData.append("difficulty", difficulty);
      formData.append("csrfmiddlewaretoken", csrfToken);

      fetch(config.urls.markDifficulty, {
        method: "POST",
        body: formData,
      })
        .then((response) => {
          if (response.ok) {
            showAlert("success", `Image marked as ${difficulty}`);
            clickedButton.innerHTML =
              difficulty.charAt(0).toUpperCase() + difficulty.slice(1);
            clickedButton.disabled = false;

            // Force reflow and update UI
            clickedButton.offsetHeight;
            setTimeout(() => {
              updateDifficultyButtons(difficulty);
              updateDifficultyBadge(difficulty);
            }, 10);
          } else {
            throw new Error("Network response was not ok");
          }
        })
        .catch((error) => {
          console.error("Error:", error);
          showAlert("danger", "Error marking difficulty. Please try again.");
          clickedButton.disabled = false;
          clickedButton.innerHTML = originalText;
        });
    }

    function updateDifficultyButtons(newDifficulty) {
      // Find the difficulty button group
      let buttonGroup = null;
      document.querySelectorAll(".btn-group").forEach((group) => {
        const buttons = group.querySelectorAll("button");
        buttons.forEach((btn) => {
          const text = btn.textContent.toLowerCase().trim();
          if (
            btn.hasAttribute("data-difficulty") ||
            btn.classList.contains("mark-difficulty") ||
            ["easy", "medium", "hard"].some((d) => text.includes(d))
          ) {
            buttonGroup = group;
          }
        });
      });

      if (!buttonGroup) return;

      const buttons = buttonGroup.querySelectorAll("button");

      buttons.forEach((button) => {
        const buttonText = button.textContent.toLowerCase().trim();
        let buttonDifficulty = ["easy", "medium", "hard"].find((d) =>
          buttonText.includes(d),
        );

        if (buttonDifficulty === newDifficulty) {
          // Selected difficulty: highlight and disable
          button.className = `btn btn-sm btn-${getBootstrapColor(newDifficulty)}`;
          button.disabled = true;
          button.removeAttribute("data-difficulty");
        } else {
          // Other difficulties: make clickable
          button.className = `btn btn-sm btn-outline-${getBootstrapColor(buttonDifficulty)} mark-difficulty`;
          button.disabled = false;
          button.setAttribute("data-difficulty", buttonDifficulty);

          if (!button.hasEventListener) {
            button.addEventListener("click", handleDifficultyClick);
            button.hasEventListener = true;
          }
        }
        button.innerHTML =
          buttonDifficulty.charAt(0).toUpperCase() + buttonDifficulty.slice(1);
      });
    }

    function updateDifficultyBadge(newDifficulty) {
      const cardHeader = document.querySelector(".card-header");
      if (!cardHeader) return;

      let difficultyBadge = cardHeader.querySelector(".badge");

      if (difficultyBadge && difficultyBadge.innerHTML.includes("fa-signal")) {
        // Update existing badge
        difficultyBadge.className = `badge status-badge bg-${getBootstrapColor(newDifficulty)}`;
        difficultyBadge.innerHTML = `<i class="fas fa-signal me-1"></i>${newDifficulty.charAt(0).toUpperCase() + newDifficulty.slice(1)}`;
      } else {
        // Create new badge if it doesn't exist yet
        const badgeContainer = cardHeader.querySelector("h5");
        if (badgeContainer && !cardHeader.querySelector(".badge")) {
          const newBadge = document.createElement("span");
          newBadge.className = `badge status-badge bg-${getBootstrapColor(newDifficulty)} ms-2`;
          newBadge.innerHTML = `<i class="fas fa-signal me-1"></i>${newDifficulty.charAt(0).toUpperCase() + newDifficulty.slice(1)}`;
          badgeContainer.appendChild(newBadge);
        }
      }
    }

    function getBootstrapColor(difficulty) {
      const colors = { easy: "success", medium: "warning", hard: "danger" };
      return colors[difficulty] || "secondary";
    }

    // Initialize difficulty buttons
    if (isStaff) {
      markDifficultyButtons.forEach((button) => {
        button.addEventListener("click", handleDifficultyClick);
        button.hasEventListener = true;
      });
    }

    // Handle will not georeference (only for staff users)
    if (willNotGeorefButton && isStaff) {
      willNotGeorefButton.addEventListener("click", function () {
        const csrfToken =
          document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
          document
            .querySelector('meta[name="csrf-token"]')
            ?.getAttribute("content") ||
          config.csrfToken;
        const formData = new FormData();
        formData.append("csrfmiddlewaretoken", csrfToken);

        fetch(config.urls.markWillNotGeoref, {
          method: "POST",
          body: formData,
        }).then((response) => {
          if (response.ok) {
            showAlert("info", 'Image marked as "will not georeference"');
            setTimeout(() => {
              // Check if we came from a specific image
              const urlParams = new URLSearchParams(window.location.search);
              const specificImageRequested = urlParams.has("image");

              if (specificImageRequested) {
                // Redirect back to the image detail page
                window.location.href = config.urls.imageDetail;
              } else {
                clearFormAndGetNext();
              }
            }, 1000);
          }
        });
      });
    }

    // Handle context display mode changes
    const contextDisplayRadios = document.querySelectorAll(
      'input[name="contextDisplay"]',
    );

    // Set initial mode from checked radio button
    const checkedRadio = document.querySelector(
      'input[name="contextDisplay"]:checked',
    );
    if (checkedRadio) {
      contextDisplayMode = checkedRadio.value;
    }

    contextDisplayRadios.forEach((radio) => {
      radio.addEventListener("change", function () {
        if (this.checked) {
          contextDisplayMode = this.value;
          updateContextImagesDisplay();
        }
      });
    });

    // Add CSRF token to the page if not already present
    if (!document.querySelector('input[name="csrfmiddlewaretoken"]')) {
      const csrfInput = document.createElement("input");
      csrfInput.type = "hidden";
      csrfInput.name = "csrfmiddlewaretoken";
      csrfInput.value = config.csrfToken;
      document.body.appendChild(csrfInput);
    }
  }
});
