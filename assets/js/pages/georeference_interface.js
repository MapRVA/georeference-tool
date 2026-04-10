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
import { deduplicateFeatures, buildPopupWrapper } from "../components/map_popup.js";

// Get colors from Bootstrap's CSS custom properties
const dangerColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-danger")
    .trim() || "#d52e1c";
const primaryColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-primary")
    .trim() || "#286071";
const secondaryColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-secondary")
    .trim() || "#6c757d";
const darkColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-dark")
    .trim() || "#212529";
const lightColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-light")
    .trim() || "#f8f9fa";

/**
 * Project a point along a bearing for a given distance.
 * Returns [lng, lat] for the destination point.
 */
function destinationPoint(lngLat, bearingDeg, distanceMeters) {
  const R = 6371000; // Earth radius in meters
  const toRad = (d) => (d * Math.PI) / 180;
  const toDeg = (r) => (r * 180) / Math.PI;
  const lat1 = toRad(lngLat[1]);
  const lng1 = toRad(lngLat[0]);
  const bearing = toRad(bearingDeg);
  const angularDist = distanceMeters / R;

  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(angularDist) +
      Math.cos(lat1) * Math.sin(angularDist) * Math.cos(bearing),
  );
  const lng2 =
    lng1 +
    Math.atan2(
      Math.sin(bearing) * Math.sin(angularDist) * Math.cos(lat1),
      Math.cos(angularDist) - Math.sin(lat1) * Math.sin(lat2),
    );

  return [toDeg(lng2), toDeg(lat2)];
}

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

    // Determine initial map position based on all hints
    const locationHint = config.locationHint;
    const subjectHints = config.subjectHints || [];

    // Collect all hint coordinates for bounds calculation
    const allHintCoords = [];
    if (locationHint) {
      allHintCoords.push([locationHint.lng, locationHint.lat]);
    }
    subjectHints.forEach((hint) => {
      allHintCoords.push([hint.lng, hint.lat]);
    });

    // Build map options based on number of hints
    const mapOptions = {
      container: "mymap",
      style: OSM_STYLE_URL,
    };

    if (allHintCoords.length > 1) {
      // Multiple hints: fit bounds to show them all
      const bounds = new maplibregl.LngLatBounds();
      allHintCoords.forEach((coord) => bounds.extend(coord));
      mapOptions.bounds = bounds;
      mapOptions.fitBoundsOptions = { padding: 100, maxZoom: 17 };
    } else if (allHintCoords.length === 1) {
      // Single hint: center on it
      mapOptions.center = allHintCoords[0];
      mapOptions.zoom = 17;
    } else {
      // No hints: default Richmond center
      mapOptions.center = [-117.37, 33.98];
      mapOptions.zoom = 11.5;
    }

    // Initialize map
    var map = new maplibregl.Map(mapOptions);

    // Try to setup PMTiles protocol
    window.setupPMTilesProtocol();

    // Function to add all map sources and layers
    async function addMapSourcesAndLayers() {
      if (!map.hasImage("surveillance-direction")) {
        try {
          const image = await map.loadImage(
            "https://maprva.org/img/surveillance-direction.png",
          );
          map.addImage("surveillance-direction", image.data);
        } catch (error) {
          console.warn("Could not load direction arrow image:", error);
        }
      }

      // Add subject hint markers if available (rendered first, so underneath other hints)
      const subjectHints = config.subjectHints || [];
      if (subjectHints.length > 0) {
        const subjectHintFeatures = subjectHints.map((hint) => ({
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: [hint.lng, hint.lat],
          },
          properties: {
            label: hint.label,
          },
        }));

        map.addSource("subject-hints", {
          type: "geojson",
          data: {
            type: "FeatureCollection",
            features: subjectHintFeatures,
          },
        });

        // Orange color to match browse subjects page
        const subjectHintColor = { circle: "#ff6b35", text: "#c44d1c" };

        // Add a pulsing circle for each subject hint
        map.addLayer({
          id: "subject-hints-pulse",
          type: "circle",
          source: "subject-hints",
          paint: {
            "circle-radius": 25,
            "circle-color": subjectHintColor.circle,
            "circle-opacity": 0.3,
            "circle-stroke-color": subjectHintColor.circle,
            "circle-stroke-width": 2,
            "circle-stroke-opacity": 0.6,
          },
        });

        // Add labels for subject hints
        map.addLayer({
          id: "subject-hints-label",
          type: "symbol",
          source: "subject-hints",
          layout: {
            "text-field": ["get", "label"],
            "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
            "text-size": 12,
            "text-offset": [0, 2.5],
            "text-anchor": "top",
          },
          paint: {
            "text-color": subjectHintColor.text,
            "text-halo-color": "#fff",
            "text-halo-width": 2,
          },
        });
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

        // Determine hint colors based on type
        // georeference = yellow, source = teal, detected = purple
        const hintColors = {
          georeference: { circle: "#ffc107", text: "#856404" },
          source: { circle: "#17a2b8", text: "#0c5460" },
          detected: { circle: "#9b59b6", text: "#6c3483" },
        };
        const hintColor = hintColors[locationHint.type] || hintColors.source;

        // Add a pulsing circle for the hint (larger, semi-transparent)
        map.addLayer({
          id: "location-hint-pulse",
          type: "circle",
          source: "location-hint",
          paint: {
            "circle-radius": 25,
            "circle-color": hintColor.circle,
            "circle-opacity": 0.3,
            "circle-stroke-color": hintColor.circle,
            "circle-stroke-width": 2,
            "circle-stroke-opacity": 0.6,
          },
        });

        // Add label for the hint (always visible, renders over subject hints)
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
            "text-allow-overlap": true,
          },
          paint: {
            "text-color": hintColor.text,
            "text-halo-color": "#fff",
            "text-halo-width": 2,
          },
        });
      }

      // Add all existing georeferenced images for context using vector tiles
      // These are added BEFORE the pin layers so the user's pin always renders on top
      try {
        // Build vector tiles URL (version is already included from template)
        const contextVectorTilesUrl =
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
            "circle-color": secondaryColor,
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

      // Add bearing line source and layer (rendered below pin but above context images)
      map.addSource("bearing-line", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: [],
        },
      });

      map.addLayer({
        id: "bearing-line-bg",
        type: "line",
        source: "bearing-line",
        paint: {
          "line-color": lightColor,
          "line-width": 2,
        },
        layout: {
          visibility: "none",
        },
      });

      map.addLayer({
        id: "bearing-line",
        type: "line",
        source: "bearing-line",
        paint: {
          "line-color": darkColor,
          "line-width": 2,
          "line-dasharray": [3, 3],
        },
        layout: {
          visibility: "none",
        },
      });

      // Add the user's pin source and layers LAST so they render above all else
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
          "circle-color": dangerColor,
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 2,
        },
      });

      if (map.hasImage("surveillance-direction")) {
        map.addLayer(
          {
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
          },
          "pin-circle",
        ); // Insert below pin-circle
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
        overlayLayerIds: [
          "subject-hints-pulse",
          "subject-hints-label",
          "location-hint-pulse",
          "location-hint-label",
          "bearing-line-bg",
          "bearing-line",
          "pin-circle",
          "pin-symbol",
          "context-image-circles",
          "context-image-directions",
        ],
        onStyleSwap: async () => {
          await addMapSourcesAndLayers();
          restoreOverlayState();
        },
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
    var bearingLineEnabled = false;
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

    function updateBearingLine() {
      if (!map.getSource("bearing-line")) return;

      var lat = parseFloat(latitudeInput.value);
      var lng = parseFloat(longitudeInput.value);

      var bearingLineVisible =
        bearingLineEnabled &&
        pinPlaced &&
        currentDirection !== null &&
        !isNaN(lat) &&
        !isNaN(lng);

      // Sync image centerline with map bearing line visibility
      var imageCenterline = document.querySelector(".image-centerline");
      if (imageCenterline) {
        imageCenterline.style.display = bearingLineVisible ? "block" : "none";
      }

      if (bearingLineVisible) {
        // Compute distance from map center to corner so the line always extends off-screen
        var bounds = map.getBounds();
        var center = map.getCenter();
        var cornerDist = center.distanceTo(bounds.getNorthEast());
        var totalDist = cornerDist * 2;

        // Interpolate points along the great circle so the line curves correctly
        // when zoomed out on a Mercator projection
        var numSegments = Math.max(2, Math.ceil(64 * (totalDist / 20000000)));
        var stepDist = totalDist / numSegments;
        var origin = [lng, lat];
        var coordinates = [origin];
        for (var i = 1; i <= numSegments; i++) {
          coordinates.push(
            destinationPoint(origin, currentDirection, stepDist * i),
          );
        }

        map.getSource("bearing-line").setData({
          type: "FeatureCollection",
          features: [
            {
              type: "Feature",
              geometry: {
                type: "LineString",
                coordinates: coordinates,
              },
            },
          ],
        });
      } else {
        map.getSource("bearing-line").setData({
          type: "FeatureCollection",
          features: [],
        });
      }
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

      // Update bearing centerline
      updateBearingLine();
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
      if (map.getSource("bearing-line")) {
        map.getSource("bearing-line").setData({
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
            secondaryColor,
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
            primaryColor,
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

            const features = deduplicateFeatures(e.features);
            if (features.length === 0) return;

            // Close any existing popup
            if (activePopup) {
              activePopup.remove();
            }

            // Create and track new popup
            activePopup = new maplibregl.Popup()
              .setLngLat(e.lngLat)
              .setDOMContent(buildPopupWrapper(features))
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

    // Restore overlay state after layers are (re-)created (used on initial load
    // and after style swaps, which destroy all sources/layers/images).
    function restoreOverlayState() {
      // Sync bearing line visibility from current toggle state
      if (bearingLineEnabled) {
        for (const layerId of ["bearing-line", "bearing-line-bg"]) {
          if (map.getLayer(layerId)) {
            map.setLayoutProperty(layerId, "visibility", "visible");
          }
        }
      }

      // Repopulate bearing line data (source is created empty)
      updateBearingLine();

      // Re-apply context image display mode and re-attach interaction handlers
      updateContextImagesDisplay();
    }

    // Map event handlers
    map.on("load", async () => {
      await addMapSourcesAndLayers();

      // Add address search control powered by Nominatim
      addResponsiveGeocoder(map);

      // Initialize MapSwap link and update on map move
      updateMapSwapLink();
      map.on("moveend", updateMapSwapLink);

      restoreOverlayState();

      // Recalculate bearing line on zoom/pan so it always extends off-screen
      map.on("moveend", updateBearingLine);
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
        difficultyBadge.className = `badge status-badge text-bg-${getBootstrapColor(newDifficulty)}`;
        difficultyBadge.innerHTML = `<i class="fas fa-signal me-1"></i>${newDifficulty.charAt(0).toUpperCase() + newDifficulty.slice(1)}`;
      } else if (!cardHeader.querySelector(".badge")) {
        // Create new badge as a sibling of the h5, not inside it
        const newBadge = document.createElement("span");
        newBadge.className = `badge status-badge text-bg-${getBootstrapColor(newDifficulty)} ms-2`;
        newBadge.innerHTML = `<i class="fas fa-signal me-1"></i>${newDifficulty.charAt(0).toUpperCase() + newDifficulty.slice(1)}`;
        cardHeader.appendChild(newBadge);
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

    // Handle bearing line toggle (checkbox is source of truth; browser restores state on reload)
    const bearingLineToggle = document.getElementById("bearing-line-toggle");
    if (bearingLineToggle) {
      // Read initial state from checkbox (browser may restore checked state on reload);
      // layer visibility is synced later in the map "load" handler once layers exist
      bearingLineEnabled = bearingLineToggle.checked;

      bearingLineToggle.addEventListener("change", function () {
        bearingLineEnabled = this.checked;
        const vis = bearingLineEnabled ? "visible" : "none";
        for (const layerId of ["bearing-line", "bearing-line-bg"]) {
          if (map.getLayer(layerId)) {
            map.setLayoutProperty(layerId, "visibility", vis);
          }
        }
        updateBearingLine();
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
