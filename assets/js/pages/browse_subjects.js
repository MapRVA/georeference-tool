import "../../styles/pages/browse-subjects.css";
import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl from "maplibre-gl";
import { DEFAULT_MAP_CENTER } from "../constants/map.js";

/**
 * Alpine.js component for subject browsing with search, "Load More", and a
 * two-section autocomplete (Subjects + Categories powered by the Oxigraph
 * SPARQL mirror).
 */
window.Alpine.data("subjectBrowser", function () {
  const config = window.subjectBrowserConfig || {};
  const perPage = config.perPage || 12;
  const autocompleteUrl = config.autocompleteUrl || null;

  return {
    query:
      new URLSearchParams(window.location.search).get("filter") || "",
    offset: perPage,
    hasMore: config.hasMore ?? false,
    loading: false,
    noResults: false,

    // Autocomplete dropdown state
    suggestions: { categories: [], subjects: [] },
    showDropdown: false,
    selectedCategory: config.selectedCategory || null,
    _autocompleteController: null,
    _searchController: null,

    _isLoadingMore: false,
    _pendingFetch: null,
    _loadingTimer: null,

    onInput() {
      // One Alpine listener, two side effects: refresh the suggestion
      // dropdown and re-run the grid search. Alpine's .debounce modifier
      // throttles us at the listener so neither side fires per keystroke.
      this._fetchSuggestions();
      this.search();
    },

    onFocus() {
      if (
        this.query.length >= 2 &&
        (this.suggestions.categories.length > 0 ||
          this.suggestions.subjects.length > 0)
      ) {
        this.showDropdown = true;
      }
    },

    async _fetchSuggestions() {
      if (!autocompleteUrl || this.query.length < 2) {
        this.suggestions = { categories: [], subjects: [] };
        this.showDropdown = false;
        return;
      }

      if (this._autocompleteController) {
        this._autocompleteController.abort();
      }
      this._autocompleteController = new AbortController();

      try {
        const url = new URL(autocompleteUrl, window.location.origin);
        url.searchParams.set("q", this.query);
        const response = await fetch(url.toString(), {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          signal: this._autocompleteController.signal,
        });
        if (!response.ok) return;
        const data = await response.json();
        this.suggestions = {
          categories: data.categories || [],
          subjects: data.subjects || [],
        };
        this.showDropdown =
          this.suggestions.categories.length > 0 ||
          this.suggestions.subjects.length > 0;
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error("Autocomplete error:", error);
        }
      }
    },

    selectCategory(category) {
      this.selectedCategory = { qid: category.qid, label: category.label };
      // The typed text was about finding the category, not narrowing
      // by title - reset it so the grid shows the whole category.
      // The user can type again to narrow within the category.
      this.query = "";
      this.suggestions = { categories: [], subjects: [] };
      this.showDropdown = false;
      this._syncUrl();
      this.search();
    },

    clearCategory() {
      this.selectedCategory = null;
      this._syncUrl();
      this.search();
    },

    _syncUrl() {
      const url = new URL(window.location.href);
      if (this.selectedCategory) {
        url.searchParams.set("category", this.selectedCategory.qid);
      } else {
        url.searchParams.delete("category");
      }
      if (this.query) {
        url.searchParams.set("filter", this.query);
      } else {
        url.searchParams.delete("filter");
      }
      url.searchParams.delete("offset");
      window.history.replaceState({}, "", url.toString());
    },

    async search() {
      // Cancel any in-flight earlier search. Without this, a slow typing
      // AJAX can return after a faster category-click AJAX and overwrite
      // the grid with stale results.
      if (this._searchController) {
        this._searchController.abort();
      }
      this._searchController = new AbortController();
      const signal = this._searchController.signal;

      this.offset = 0;
      this._isLoadingMore = true;
      this.loading = true;
      this._syncUrl();

      try {
        const html = await this._fetch(signal);
        if (signal.aborted) return;
        const grid = document.getElementById("subject-grid");
        grid.innerHTML = html;
        this._parseHasMore(html);
        this.noResults =
          grid.querySelectorAll(".subject-card-wrapper").length === 0;
        this.offset = perPage;
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error("Error searching subjects:", error);
        }
      } finally {
        if (!signal.aborted) {
          clearTimeout(this._loadingTimer);
          this.loading = false;
          this._isLoadingMore = false;
        }
      }
    },

    prefetchMore() {
      if (this._isLoadingMore || !this.hasMore || this._pendingFetch) return;
      this._pendingFetch = this._fetch();
    },

    async loadMore() {
      if (this._isLoadingMore || !this.hasMore) return;
      this._isLoadingMore = true;

      this._loadingTimer = setTimeout(() => {
        this.loading = true;
      }, 200);

      try {
        let html;
        if (this._pendingFetch) {
          html = await this._pendingFetch;
          this._pendingFetch = null;
        } else {
          html = await this._fetch();
        }

        if (html.trim()) {
          const parser = new DOMParser();
          const doc = parser.parseFromString(html, "text/html");
          const newItems = doc.querySelectorAll(".subject-card-wrapper");

          if (newItems.length > 0) {
            const grid = document.getElementById("subject-grid");
            grid.insertAdjacentHTML("beforeend", html);
            const addedTemplate = grid.querySelector("[data-has-more]");
            if (addedTemplate) addedTemplate.remove();
            this.offset += newItems.length;
            this._parseHasMore(html);
          } else {
            this.hasMore = false;
          }
        } else {
          this.hasMore = false;
        }
      } catch (error) {
        console.error("Error loading more subjects:", error);
        this._pendingFetch = null;
      } finally {
        clearTimeout(this._loadingTimer);
        this.loading = false;
        this._isLoadingMore = false;
      }
    },

    async _fetch(signal) {
      const url = new URL(window.location.origin + window.location.pathname);
      url.searchParams.set("offset", this.offset);
      if (this.query) url.searchParams.set("filter", this.query);
      if (this.selectedCategory) {
        url.searchParams.set("category", this.selectedCategory.qid);
      }

      const response = await fetch(url.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal,
      });
      if (!response.ok) throw new Error(`HTTP error: ${response.status}`);
      return response.text();
    },

    _parseHasMore(html) {
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, "text/html");
      const el = doc.querySelector("[data-has-more]");
      this.hasMore = el ? el.dataset.hasMore === "true" : false;
    },
  };
});

document.addEventListener("DOMContentLoaded", function () {
  const mapContainer = document.getElementById("subjects-map");
  if (!mapContainer) return; // Exit if no map on this page

  // Function to detect if dark mode is enabled
  function isDarkMode() {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }

  // Function to get the appropriate map style URL
  function getMapStyle() {
    const theme = isDarkMode() ? "dark" : "white";
    return `https://api.protomaps.com/styles/v5/${theme}/en.json?key=${window.PROTOMAPS_API_KEY}`;
  }

  // Initialize MapLibre GL map with appropriate style
  const map = new maplibregl.Map({
    container: "subjects-map",
    style: getMapStyle(),
    center: DEFAULT_MAP_CENTER,
    zoom: 13,
  });

  // Add fullscreen control
  map.addControl(new maplibregl.FullscreenControl());

  // Get Bootstrap's primary color from CSS variable
  const primaryColor =
    getComputedStyle(document.documentElement)
      .getPropertyValue("--bs-primary")
      .trim() || "#0d6efd";

  // Function to add all custom sources and layers
  function addCustomLayers() {
    console.log("Adding OSM elements source");
    map.addSource("osm-elements", {
      type: "vector",
      tiles: [
        window.location.origin + "/api/v1/osm_element_tiles/{z}/{x}/{y}.pbf",
      ],
      minzoom: 0,
      maxzoom: 14,
      scheme: "xyz",
      attribution: "Subject geometries © OpenStreetMap Contributors",
    });

    console.log("Source added, adding layers");

    // Add vector tiles source for regular image georeferences
    // URL with version is provided by the template via window.VECTOR_TILES_URL
    map.addSource("images", {
      type: "vector",
      tiles: [window.location.origin + window.VECTOR_TILES_URL],
      minzoom: 0,
      maxzoom: 14,
    });

    // Add circle layer for image georeferences
    map.addLayer({
      id: "image-circles",
      type: "circle",
      source: "images",
      "source-layer": "image_points",
      paint: {
        "circle-radius": 8,
        "circle-color": primaryColor,
        "circle-stroke-color": "#fff",
        "circle-stroke-width": 2,
        "circle-opacity": 0, // Hidden by default, will show on hover
        "circle-stroke-opacity": 0, // Hide stroke initially too
      },
    });

    // Load direction arrow image asynchronously
    (async () => {
      try {
        const image = await map.loadImage(
          "https://maprva.org/img/surveillance-direction.png",
        );
        map.addImage("image-direction", image.data);

        // Add direction markers for image georeferences (underneath circles)
        map.addLayer(
          {
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
              "icon-opacity": 0, // Hidden by default, will show on hover
            },
          },
          "image-circles",
        ); // Insert below image-circles
      } catch (error) {
        console.warn("Could not load direction arrow image:", error);
      }
    })();

    console.log("Image circles layer added");

    // Large polygons (background)
    map.addLayer({
      id: "osm-elements-polygons-large-fill",
      type: "fill",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: [
        "all",
        [
          "in",
          ["get", "geom_type"],
          ["literal", ["ST_Polygon", "ST_MultiPolygon"]],
        ],
        [">=", ["get", "geometry_area"], 3e-6],
      ],
      paint: {
        "fill-color": "#ff6b35",
        "fill-opacity": 0.3,
      },
    });

    map.addLayer({
      id: "osm-elements-polygons-large-stroke",
      type: "line",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: [
        "all",
        [
          "in",
          ["get", "geom_type"],
          ["literal", ["ST_Polygon", "ST_MultiPolygon"]],
        ],
        [">=", ["get", "geometry_area"], 3e-6],
      ],
      paint: {
        "line-color": "#ff6b35",
        "line-width": 2,
        "line-opacity": 0.5,
      },
    });

    // Small polygons (on top)
    map.addLayer({
      id: "osm-elements-polygons-small-fill",
      type: "fill",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: [
        "all",
        [
          "in",
          ["get", "geom_type"],
          ["literal", ["ST_Polygon", "ST_MultiPolygon"]],
        ],
        ["<", ["get", "geometry_area"], 3e-6],
      ],
      paint: {
        "fill-color": "#ff6b35",
        "fill-opacity": 0.6,
      },
    });

    map.addLayer({
      id: "osm-elements-polygons-small-stroke",
      type: "line",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: [
        "all",
        [
          "in",
          ["get", "geom_type"],
          ["literal", ["ST_Polygon", "ST_MultiPolygon"]],
        ],
        ["<", ["get", "geometry_area"], 3e-6],
      ],
      paint: {
        "line-color": "#ff6b35",
        "line-width": 2,
        "line-opacity": 0.8,
      },
    });

    // Lines (above polygons)
    map.addLayer({
      id: "osm-elements-lines",
      type: "line",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: [
        "in",
        ["get", "geom_type"],
        ["literal", ["ST_LineString", "ST_MultiLineString"]],
      ],
      paint: {
        "line-color": "#ff6b35",
        "line-width": 4,
        "line-opacity": 0.7,
      },
    });

    // Points (on top of everything)
    map.addLayer({
      id: "osm-elements-points",
      type: "circle",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: ["==", ["get", "geom_type"], "ST_Point"],
      paint: {
        "circle-radius": 6,
        "circle-color": "#ff6b35",
        "circle-opacity": 0.7,
        "circle-stroke-width": 2,
        "circle-stroke-color": "#fff",
      },
    });

    console.log("Layers added successfully");
  }

  // Add OSM elements tiles layer
  map.on("load", function () {
    addCustomLayers();

    // Add hover tooltip for subject names
    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
    });

    const layerIds = [
      "osm-elements-points",
      "osm-elements-lines",
      "osm-elements-polygons-large-fill",
      "osm-elements-polygons-large-stroke",
      "osm-elements-polygons-small-fill",
      "osm-elements-polygons-small-stroke",
    ];

    // Debounce timer for hover interactions
    let hoverTimeout;

    // Use a single mousemove handler that queries features and picks the topmost one
    map.on("mousemove", (e) => {
      const features = map.queryRenderedFeatures(e.point, {
        layers: layerIds,
      });

      if (features.length > 0) {
        // The first feature in the array is the topmost rendered feature
        const feature = features[0];
        map.getCanvas().style.cursor = "pointer";

        const subjectName =
          feature.properties.subject_name || "Unknown Subject";
        const imageIds = feature.properties.image_ids
          ? feature.properties.image_ids.split(",").filter((id) => id)
          : [];

        // Show the popup immediately
        popup
          .setLngLat(e.lngLat)
          .setHTML(
            `<div class="bg-body text-body" style="cursor: pointer; white-space: nowrap; line-height: 1; border-radius: 1em;"><strong>${subjectName}</strong></div>`,
          )
          .addTo(map);

        // Debounce only the expensive georeference operations
        clearTimeout(hoverTimeout);
        hoverTimeout = setTimeout(() => {
          // Filter and highlight image georeferences for this subject
          if (imageIds.length > 0) {
            const numIds = imageIds.map((id) => parseInt(id));
            const filter = ["in", ["get", "id"], ["literal", numIds]];

            // Set paint property to show only matching circles at full opacity
            map.setPaintProperty("image-circles", "circle-opacity", [
              "case",
              filter,
              1, // Matching images: full opacity
              0, // Non-matching images: hidden
            ]);

            // Keep circles green, hide stroke on non-matching
            map.setPaintProperty("image-circles", "circle-stroke-opacity", [
              "case",
              filter,
              1, // Matching images: visible stroke
              0, // Non-matching images: hidden stroke
            ]);

            if (map.getLayer("image-directions")) {
              map.setPaintProperty("image-directions", "icon-opacity", [
                "case",
                filter,
                1, // Matching: visible
                0, // Non-matching: hidden
              ]);
            }
          } else {
            // No images for this subject, hide all circles
            map.setPaintProperty("image-circles", "circle-opacity", 0);
            map.setPaintProperty("image-circles", "circle-stroke-opacity", 0);
            if (map.getLayer("image-directions")) {
              map.setPaintProperty("image-directions", "icon-opacity", 0);
            }
          }
        }, 10); // 10ms debounce delay for expensive operations only
      } else {
        // No features under cursor
        map.getCanvas().style.cursor = "";
        popup.remove();
        // Clear debounce timeout
        clearTimeout(hoverTimeout);
        // Reset to hidden state (no images visible)
        map.setPaintProperty("image-circles", "circle-opacity", 0);
        map.setPaintProperty("image-circles", "circle-stroke-opacity", 0);
        if (map.getLayer("image-directions")) {
          map.setPaintProperty("image-directions", "icon-opacity", 0);
        }
      }
    });

    // Click handler
    map.on("click", (e) => {
      const features = map.queryRenderedFeatures(e.point, {
        layers: layerIds,
      });

      if (features.length > 0) {
        const feature = features[0];
        const subjectSlug = feature.properties.subject_slug;
        if (subjectSlug) {
          window.location.href = `/subjects/${subjectSlug}/`;
        }
      }
    });
  });

  map.on("error", function (e) {
    console.error("Map error:", e);
  });

  // Watch for theme changes and update map style
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      // When style changes, we need to re-add custom layers after the new style loads
      map.once("styledata", () => {
        addCustomLayers();
      });
      map.setStyle(getMapStyle());
    });
});
