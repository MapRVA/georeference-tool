/**
 * Georeference Interface JavaScript
 * Handles map interaction, georeferencing functionality, and UI interactions
 */

import "../../styles/pages/georeference-interface.css";
import "../../styles/components/map-display.css";
import "../../styles/components/image-viewer.css";
import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl from "maplibre-gl";
import * as pmtiles from "pmtiles";

import { initSubjectEditor } from "../components/subject_editor.js";
import { initImageViewer } from "../components/image_viewer.js";
import { OSM_STYLE_URL } from "../constants/map.js";
import { LayerControl } from "../components/layer_control.js";
import { addResponsiveGeocoder } from "../components/responsive_geocoder.js";

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

  // Initialize Image Viewer
  initImageViewer();

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

    // Determine initial map center and zoom based on location hint
    const locationHint = config.locationHint;
    let initialCenter = [-77.44, 37.53];
    let initialZoom = 11.5;

    if (locationHint) {
      initialCenter = [locationHint.lng, locationHint.lat];
      initialZoom = 17; // Zoom in closer when we have a hint
    }

    // Initialize map
    var map = new maplibregl.Map({
      container: "mymap",
      style: OSM_STYLE_URL,
      center: initialCenter,
      zoom: initialZoom,
    });

    // Try to setup PMTiles protocol
    window.setupPMTilesProtocol();

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

      // Add location hint marker if available
      if (locationHint) {
        const hintFeatures = [
          {
            type: "Feature",
            geometry: {
              type: "Point",
              coordinates: [locationHint.lng, locationHint.lat],
            },
            properties: {
              label: locationHint.label,
              type: locationHint.type,
              direction: locationHint.direction,
            },
          },
        ];

        map.addSource("location-hint", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: hintFeatures,
          },
        });

        // Add a pulsing circle for the hint (larger, semi-transparent)
        map.addLayer({
          id: "location-hint-pulse",
          type: "circle",
          source: "location-hint",
          paint: {
            "circle-radius": 25,
            "circle-color":
              locationHint.type === "georeference" ? "#ffc107" : "#17a2b8",
            "circle-opacity": 0.3,
            "circle-stroke-color":
              locationHint.type === "georeference" ? "#ffc107" : "#17a2b8",
            "circle-stroke-width": 2,
            "circle-stroke-opacity": 0.6,
          },
        });

        // Add label for the hint
        map.addLayer({
          id: "location-hint-label",
          type: "symbol",
          source: "location-hint",
          layout: {
            "text-field": ["get", "label"],
            "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
            "text-size": 12,
            "text-offset": [0, 2.5],
            "text-anchor": "top",
          },
          paint: {
            "text-color":
              locationHint.type === "georeference" ? "#856404" : "#0c5460",
            "text-halo-color": "#fff",
            "text-halo-width": 2,
          },
        });
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
    // Note: overlayLayerIds lists all layers that should stay on top of secondary tile layers
    // (like Sanborn maps). The LayerControl's fallback logic will automatically find the
    // bottommost overlay layer to insert secondary layers below. This ensures hints and pins
    // always render above secondary layers.
    map.addControl(
      new LayerControl({
        mapLayersUrl: config.urls.mapLayers,
        overlayLayerIds: [
          "location-hint-pulse",
          "location-hint-label",
          "pin-circle",
          "pin-symbol",
          "context-image-circles",
          "context-image-directions",
        ],
      }),
      "top-right",
    );
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

      // Remove current_image parameter if present to avoid redirecting back to the same image
      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.has("current_image")) {
        urlParams.delete("current_image");
        const newUrl =
          window.location.pathname +
          (urlParams.toString() ? "?" + urlParams.toString() : "");
        window.location.href = newUrl;
      } else {
        location.reload();
      }
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
            "#0d6efd",
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
      addResponsiveGeocoder(map);

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
