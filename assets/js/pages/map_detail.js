import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";

document.addEventListener("DOMContentLoaded", async function () {
  const mapContainer = document.getElementById("layer-map");
  if (!mapContainer) return;

  // Register PMTiles protocol
  const protocol = new Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);

  // Function to detect if dark mode is enabled
  function isDarkMode() {
    return document.documentElement.getAttribute("data-bs-theme") === "dark";
  }

  // Function to get the appropriate map style URL
  function getMapStyle() {
    const theme = isDarkMode() ? "dark" : "white";
    return `https://api.protomaps.com/styles/v5/${theme}/en.json?key=${window.PROTOMAPS_API_KEY}`;
  }

  // Fetch and parse the Protomaps style to extract base layer IDs
  let baseLayerIds = [];
  async function fetchBaseLayerIds() {
    try {
      const response = await fetch(getMapStyle());
      const style = await response.json();
      baseLayerIds = style.layers.map((layer) => layer.id);
    } catch (e) {
      console.warn("Could not fetch base layer IDs:", e);
    }
  }

  // Function to update base map theme without removing overlay
  async function updateBaseMapTheme() {
    try {
      const response = await fetch(getMapStyle());
      const newStyle = await response.json();

      // Update each base layer's paint and layout properties
      for (const newLayer of newStyle.layers) {
        if (map.getLayer(newLayer.id)) {
          // Update paint properties
          if (newLayer.paint) {
            for (const [key, value] of Object.entries(newLayer.paint)) {
              try {
                map.setPaintProperty(newLayer.id, key, value);
              } catch (e) {
                // Some properties may not be updatable
              }
            }
          }
        }
      }
    } catch (e) {
      console.warn("Could not update base map theme:", e);
    }
  }

  // Function to add the map layer
  function addMapLayer() {
    const layerConfig = window.MAP_LAYER;
    if (!layerConfig) return;

    if (map.getSource("overlay-layer")) return; // Already added

    if (layerConfig.type === "pmtiles") {
      map.addSource("overlay-layer", {
        type: "raster",
        tiles: [`pmtiles://${layerConfig.url}/{z}/{x}/{y}`],
        tileSize: 256,
        attribution: layerConfig.attribution,
      });

      map.addLayer({
        id: "overlay-layer",
        type: "raster",
        source: "overlay-layer",
      });
    } else if (layerConfig.type === "xyz") {
      map.addSource("overlay-layer", {
        type: "raster",
        tiles: [layerConfig.url],
        tileSize: 256,
        attribution: layerConfig.attribution,
      });

      map.addLayer({
        id: "overlay-layer",
        type: "raster",
        source: "overlay-layer",
      });
    }
  }

  // Fetch base layer IDs before initializing
  await fetchBaseLayerIds();

  // Initialize MapLibre GL map with appropriate style
  const map = new maplibregl.Map({
    container: "layer-map",
    style: getMapStyle(),
    center: [-77.43916, 37.54376],
    zoom: 13,
  });

  // Add navigation controls
  map.addControl(new maplibregl.NavigationControl());

  // Add fullscreen control
  map.addControl(new maplibregl.FullscreenControl());

  // Add the overlay layer when the map loads
  map.on("load", function () {
    addMapLayer();
  });

  // Watch for theme changes and update only base map layers
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.attributeName === "data-bs-theme") {
        updateBaseMapTheme();
      }
    });
  });

  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-bs-theme"],
  });
});
