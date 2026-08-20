import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "../components/map_display/pmtiles_protocol";
import { initialMapStyle } from "../components/layer_control";
import { initialMapView } from "../constants/map";

// Import image grid component (includes bulk selection and modal functionality)
import { imageGrid } from "../components/image_grid.js";

function aerialsPage() {
  return {
    // Map and data state
    map: null,
    allAerialData: null,
    config: null,

    // Filter state
    filterMarker: null,
    isFiltered: false,
    filterLat: null,
    filterLon: null,

    // UI state
    error: null,
    isFiltering: false,

    // Initialize the component
    async initMap() {
      try {
        // Get configuration from the HTML data attributes
        const mapContainer = document.getElementById("aerial-map");
        this.config = JSON.parse(mapContainer.dataset.config || "{}");

        if (!this.config.aerialGeojsonUrl) {
          this.error = "Aerial GeoJSON URL not provided in configuration";
          return;
        }

        // Initialize the map
        window.setupPMTilesProtocol();
        this.map = new maplibregl.Map({
          container: "aerial-map",
          style: initialMapStyle(),
          ...initialMapView(),
        });

        // Add controls
        const navControl = new maplibregl.NavigationControl();
        const fullscreenControl = new maplibregl.FullscreenControl();
        this.map.addControl(navControl);
        this.map.addControl(fullscreenControl);

        // Load data when map is ready
        this.map.on("load", () => {
          this.loadAerialData();

          // Show filter marker and apply filter if we're on a filtered page
          if (this.config.filterLat && this.config.filterLon) {
            this.isFiltered = true;
            this.filterLat = this.config.filterLat;
            this.filterLon = this.config.filterLon;
            this.addFilterMarker(this.config.filterLat, this.config.filterLon);
            this.loadFilteredMapData(
              this.config.filterLat,
              this.config.filterLon,
            );
          }
        });
      } catch (error) {
        console.error("Error initializing map:", error);
        this.error = "Failed to initialize map";
      }
    },

    // Load aerial georeferences data
    async loadAerialData() {
      try {
        const response = await fetch(this.config.aerialGeojsonUrl);
        const geojson = await response.json();

        console.log("Aerial GeoJSON:", geojson);
        this.allAerialData = geojson;

        if (!geojson.features || geojson.features.length === 0) {
          console.log("No aerial features found");
          return;
        }

        // Get Bootstrap CSS variable colors for polygon styling
        const styles = getComputedStyle(document.documentElement);
        const primaryColor = styles.getPropertyValue("--bs-primary").trim();

        // Add GeoJSON source to map
        this.map.addSource("aerial-georeferences", {
          type: "geojson",
          data: geojson,
        });

        // Add fill layer for polygons
        this.map.addLayer({
          id: "aerial-fill",
          type: "fill",
          source: "aerial-georeferences",
          paint: {
            "fill-color": primaryColor,
            "fill-opacity": 0.2,
          },
        });

        // Add outline layer for polygons
        this.map.addLayer({
          id: "aerial-outline",
          type: "line",
          source: "aerial-georeferences",
          paint: {
            "line-color": primaryColor,
            "line-width": 2,
          },
        });

        // Set up map event handlers
        this.setupMapEventHandlers();

        console.log("Map setup complete");
      } catch (error) {
        console.error("Error loading aerial georeferences:", error);
        this.error = "Error loading map data";
      }
    },

    // Fit map bounds to all features
    fitBoundsToFeatures(features) {
      if (features.length === 0) return;

      try {
        const bounds = new maplibregl.LngLatBounds();
        let hasBounds = false;

        features.forEach((feature) => {
          if (feature.geometry && feature.geometry.coordinates) {
            if (feature.geometry.type === "Polygon") {
              feature.geometry.coordinates[0].forEach((coord) => {
                if (Array.isArray(coord) && coord.length === 2) {
                  bounds.extend(coord);
                  hasBounds = true;
                }
              });
            } else if (feature.geometry.type === "MultiPolygon") {
              feature.geometry.coordinates.forEach((polygon) => {
                if (Array.isArray(polygon) && polygon.length > 0) {
                  polygon[0].forEach((coord) => {
                    if (Array.isArray(coord) && coord.length === 2) {
                      bounds.extend(coord);
                      hasBounds = true;
                    }
                  });
                }
              });
            }
          }
        });

        if (hasBounds) {
          this.map.fitBounds(bounds, {
            padding: 50,
            maxZoom: 15,
          });
        }
      } catch (boundsError) {
        console.error("Error fitting bounds:", boundsError);
      }
    },

    // Set up map event handlers
    setupMapEventHandlers() {
      // Handle map clicks for filtering
      this.map.on("click", (e) => {
        const lat = e.lngLat.lat;
        const lon = e.lngLat.lng;
        this.applyPointFilter(lat, lon);
      });

      // Add hover effects
      this.map.on("mouseenter", "aerial-fill", () => {
        this.map.getCanvas().style.cursor = "pointer";
      });

      this.map.on("mouseleave", "aerial-fill", () => {
        this.map.getCanvas().style.cursor = "";
      });
    },

    // Apply point filter - AJAX request to update content in-place
    async applyPointFilter(lat, lon) {
      try {
        this.isFiltering = true;

        // Set filter state
        this.isFiltered = true;
        this.filterLat = lat;
        this.filterLon = lon;

        // Add filter marker to show what was clicked
        this.addFilterMarker(lat, lon);

        // Update URL without page refresh
        const params = new URLSearchParams(window.location.search);
        params.set("lat", lat.toFixed(6));
        params.set("lon", lon.toFixed(6));
        params.delete("page"); // Reset to page 1 when filtering
        window.history.replaceState(
          {},
          "",
          `${window.location.pathname}?${params.toString()}`,
        );

        // Fetch filtered page content via AJAX
        const response = await fetch(
          `${window.location.pathname}?${params.toString()}`,
          {
            headers: {
              "X-Requested-With": "XMLHttpRequest",
            },
          },
        );

        if (!response.ok) {
          throw new Error("Failed to fetch filtered results");
        }

        const html = await response.text();
        this.updatePageContent(html);

        // Update map with filtered GeoJSON
        const filteredResponse = await fetch(
          `/api/v1/above/at-point/?lat=${lat}&lon=${lon}`,
        );
        const filteredData = await filteredResponse.json();

        console.log("Filtered data:", filteredData);
        console.log("Features count:", filteredData.features?.length || 0);

        if (this.map && this.map.getSource("aerial-georeferences")) {
          this.map.getSource("aerial-georeferences").setData(filteredData);
        }

        this.isFiltering = false;
      } catch (error) {
        console.error("Error filtering aerials:", error);
        this.error = "Error filtering aerials. Please try again.";
        this.isFiltering = false;
      }
    },

    // Clear filter and refresh content
    async clearFilter() {
      try {
        this.isFiltering = true;

        // Clear filter state immediately
        this.isFiltered = false;
        this.filterLat = null;
        this.filterLon = null;
        console.log("Filter state cleared:", { isFiltered: this.isFiltered });

        // Remove filter marker
        if (this.filterMarker) {
          this.filterMarker.remove();
          this.filterMarker = null;
        }

        // Update URL without page refresh
        window.history.replaceState({}, "", window.location.pathname);

        // Fetch unfiltered page content
        const response = await fetch(window.location.pathname, {
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
        });

        if (!response.ok) {
          throw new Error("Failed to fetch unfiltered results");
        }

        const html = await response.text();
        this.updatePageContent(html);

        // Restore all aerials to map
        if (
          this.allAerialData &&
          this.map &&
          this.map.getSource("aerial-georeferences")
        ) {
          this.map
            .getSource("aerial-georeferences")
            .setData(this.allAerialData);
        }

        this.isFiltering = false;
        console.log("Clear filter completed successfully");
      } catch (error) {
        console.error("Error clearing filter:", error);
        // Reset state even on error
        this.isFiltered = false;
        this.filterLat = null;
        this.filterLon = null;
        this.isFiltering = false;
        // Fallback: redirect to clear the filter
        window.location.href = window.location.pathname;
      }
    },

    // Add filter marker to map
    addFilterMarker(lat, lon) {
      // Remove existing marker
      if (this.filterMarker) {
        this.filterMarker.remove();
      }

      // Get Bootstrap primary color for the marker
      const styles = getComputedStyle(document.documentElement);
      const primaryColor =
        styles.getPropertyValue("--bs-primary").trim() || "#0d6efd";
      // Encode the color for use in SVG data URI
      const encodedColor = encodeURIComponent(primaryColor);

      // Create marker element
      const el = document.createElement("div");
      el.style.width = "20px";
      el.style.height = "20px";
      el.style.backgroundImage = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Ccircle cx='12' cy='12' r='10' fill='${encodedColor}' stroke='%23fff' stroke-width='2'/%3E%3C/svg%3E")`;
      el.style.backgroundSize = "contain";
      el.style.cursor = "pointer";

      this.filterMarker = new maplibregl.Marker({ element: el })
        .setLngLat([lon, lat])
        .addTo(this.map);
    },

    // Update page content from AJAX response
    updatePageContent(html) {
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, "text/html");

      // Find the main content wrapper
      const currentWrapper = document.querySelector(
        'div[class*="user-select-none"]',
      );
      const newWrapper = doc.querySelector('div[class*="user-select-none"]');

      if (newWrapper && currentWrapper) {
        // Replace the entire content wrapper
        currentWrapper.innerHTML = newWrapper.innerHTML;
        return;
      }

      // Fallback: Update individual components
      // Update the images grid OR the no results message
      const newImageGrid = doc.querySelector('.row[x-ref="imageGrid"]');
      const newNoResults = doc.querySelector("#no-results");
      const currentImageGrid = document.querySelector(
        '.row[x-ref="imageGrid"]',
      );
      const currentNoResults = document.querySelector("#no-results");

      if (newImageGrid && currentImageGrid) {
        // Replace grid content
        currentImageGrid.outerHTML = newImageGrid.outerHTML;
        // Remove no results if it exists
        const stillExistingNoResults = document.querySelector("#no-results");
        if (stillExistingNoResults) {
          stillExistingNoResults.remove();
        }
      } else if (newNoResults && currentImageGrid) {
        // Replace grid with no results
        currentImageGrid.outerHTML = newNoResults.outerHTML;
      } else if (newNoResults && currentNoResults) {
        // Update no results message
        currentNoResults.outerHTML = newNoResults.outerHTML;
      } else if (newImageGrid && currentNoResults) {
        // Replace no results with grid
        currentNoResults.outerHTML = newImageGrid.outerHTML;
      }

      // Update pagination
      const newPagination = doc.querySelector(
        'nav[aria-label="Images pagination"]',
      );
      const currentPagination = document.querySelector(
        'nav[aria-label="Images pagination"]',
      );
      if (newPagination && currentPagination) {
        currentPagination.outerHTML = newPagination.outerHTML;
      } else if (newPagination) {
        // Add pagination if it didn't exist before
        const currentContentGrid =
          document.querySelector('.row[x-ref="imageGrid"]') ||
          document.querySelector("#no-results");
        if (currentContentGrid && currentContentGrid.parentNode) {
          currentContentGrid.parentNode.appendChild(
            newPagination.cloneNode(true),
          );
        }
      } else if (currentPagination) {
        // Remove pagination if no longer needed
        currentPagination.remove();
      }

      // Update pagination text
      const newPaginationText = doc.querySelector(
        ".text-center.text-muted.mt-2",
      );
      const currentPaginationText = document.querySelector(
        ".text-center.text-muted.mt-2",
      );
      if (newPaginationText && currentPaginationText) {
        currentPaginationText.outerHTML = newPaginationText.outerHTML;
      } else if (newPaginationText) {
        // Add pagination text if it didn't exist before
        const currentContentGrid =
          document.querySelector('.row[x-ref="imageGrid"]') ||
          document.querySelector("#no-results");
        if (currentContentGrid && currentContentGrid.parentNode) {
          currentContentGrid.parentNode.appendChild(
            newPaginationText.cloneNode(true),
          );
        }
      } else if (currentPaginationText) {
        // Remove pagination text if no longer needed
        currentPaginationText.remove();
      }

      // Update filter status if it exists
      const newFilterStatus = doc.querySelector(
        ".card-header .d-flex.align-items-center.gap-2",
      );
      const currentFilterStatus = document.querySelector(
        ".card-header .d-flex.align-items-center.gap-2",
      );
      const headerContainer = document.querySelector(
        ".card-header .d-flex.justify-content-between.align-items-center",
      );

      if (newFilterStatus && !currentFilterStatus && headerContainer) {
        // Add filter status
        headerContainer.appendChild(newFilterStatus);
      } else if (newFilterStatus && currentFilterStatus) {
        // Update filter status
        currentFilterStatus.outerHTML = newFilterStatus.outerHTML;
      } else if (!newFilterStatus && currentFilterStatus) {
        // Remove filter status
        currentFilterStatus.remove();
      }
    },

    // Load filtered map data for direct URL navigation
    async loadFilteredMapData(lat, lon) {
      try {
        // Fetch filtered aerials from API
        const response = await fetch(
          `/api/v1/above/at-point/?lat=${lat}&lon=${lon}`,
        );
        const filteredData = await response.json();

        // Update map with filtered features
        if (this.map && this.map.getSource("aerial-georeferences")) {
          this.map.getSource("aerial-georeferences").setData(filteredData);
        }
      } catch (error) {
        console.error("Error loading filtered map data:", error);
      }
    },

    // Computed properties
  };
}

// Register components with Alpine (Alpine.start() is called by index.js on DOMContentLoaded)
window.Alpine.data("imageGrid", imageGrid);
window.Alpine.data("aerialsPage", aerialsPage);
