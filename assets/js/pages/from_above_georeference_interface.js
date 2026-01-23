/**
 * From Above Georeference Interface
 * Handles polygon-based georeferencing for aerial/overhead images
 */

// CSS imports
import "../../styles/pages/from-above-georeference-interface.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "@geoman-io/maplibre-geoman-free/dist/maplibre-geoman.css";
import "../../styles/components/image-viewer.css";

// JS imports
import maplibregl from "maplibre-gl";
import * as pmtiles from "pmtiles";
import { Geoman } from "@geoman-io/maplibre-geoman-free";
import { OSM_STYLE_URL } from "../constants/map.js";
import { LayerControl } from "../components/layer_control.js";
import { initSubjectEditor } from "../components/subject_editor.js";
import { initImageViewer } from "../components/image_viewer.js";

function getBootstrapColor(difficulty) {
  const colors = { easy: "success", medium: "warning", hard: "danger" };
  return colors[difficulty] || "secondary";
}

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

document.addEventListener("DOMContentLoaded", function () {
  // Check if configuration is available
  if (!window.fromAboveConfig) {
    console.error("From Above configuration not found");
    return;
  }

  const config = window.fromAboveConfig;

  initImageViewer();

  const submitButton = document.getElementById("submitButton");
  const backButton = document.getElementById("backButton");
  const willNotGeorefButton = document.getElementById("willNotGeorefButton");
  const markDifficultyButtons = document.querySelectorAll(".mark-difficulty");
  const confidenceNotes = document.getElementById("confidence-notes");
  const isStaff = config.isStaff;
  const isAuthenticated = config.isAuthenticated;

  // Add PMTiles protocol
  if (pmtiles) {
    let protocol = new pmtiles.Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
  }

  var map = new maplibregl.Map({
    container: "mymap",
    style: OSM_STYLE_URL,
    center: [-77.44, 37.53],
    zoom: 11.5,
  });

  // Try to setup PMTiles protocol
  window.setupPMTilesProtocol();

  // Add LayerControl to map
  // Note: Geoman creates layers dynamically with "gm_" prefix. The LayerControl's isOverlayLayer()
  // already recognizes these. We don't set beforeLayerId since Geoman layers are created after
  // map load, so we rely on the fallback logic and moveLayer() to reposition overlays correctly.
  map.addControl(
    new LayerControl({
      mapLayersUrl: config.urls.mapLayers,
    }),
    "top-right",
  );
  map.addControl(new maplibregl.NavigationControl());
  map.addControl(new maplibregl.FullscreenControl());

  // Track polygon data
  var drawnPolygon = null;
  var gm = null;
  var currentPolygonId = null;

  // Initialize Geoman after map loads
  map.on("load", function () {
    // Configure Geoman options - only show polygon and erase tools
    var geomanOptions = {
      position: "top-left",
      controls: {
        draw: {
          polygon: {
            uiEnabled: true,
            title: "Draw Polygon (only one allowed)",
          },
          marker: {
            uiEnabled: false,
          },
          circle_marker: {
            uiEnabled: false,
          },
          text_marker: {
            uiEnabled: false,
          },
          circle: {
            uiEnabled: false,
          },
          ellipse: {
            uiEnabled: false,
          },
          line: {
            uiEnabled: false,
          },
          rectangle: {
            uiEnabled: false,
          },
        },
        edit: {
          delete: {
            uiEnabled: true,
          },
        },
        helper: {
          snapping: {
            uiEnabled: false,
          },
        },
      },
    };

    // Initialize Geoman with the map
    try {
      console.log("Attempting to initialize Geoman...");

      if (!Geoman) {
        throw new Error("Geoman library not loaded.");
      }

      // Create a new Geoman instance
      gm = new Geoman(map, geomanOptions);

      console.log("Geoman initialized successfully:", gm);

      // Listen for Geoman loaded event
      map.on("gm:loaded", function () {
        console.log("Geoman fully loaded");

        // Enforce one polygon limit
        map.on("gm:create", function (event) {
          if (event.shape === "polygon") {
            console.log("Polygon created:", event.feature.id);

            // If there's already a polygon, remove it
            if (
              currentPolygonId !== null &&
              currentPolygonId !== event.feature.id
            ) {
              console.log("Removing previous polygon:", currentPolygonId);

              try {
                gm.features.forEach(function (feature) {
                  if (feature.id === currentPolygonId) {
                    console.log(
                      "Found feature to remove, calling delete method",
                    );
                    if (typeof feature.delete === "function") {
                      feature.delete();
                    } else if (typeof feature.remove === "function") {
                      feature.remove();
                    }
                  }
                });
              } catch (e) {
                console.warn("Error removing polygon:", e);
              }
            }

            // Store the new polygon's ID
            currentPolygonId = event.feature.id;

            // Update polygon data
            updatePolygonData();
          }
        });

        // Track polygon removal
        map.on("gm:remove", function (event) {
          if (event.feature && event.feature.id === currentPolygonId) {
            console.log("Polygon removed by user");
            currentPolygonId = null;
            updatePolygonData();
          }
        });

        // Track polygon editing
        map.on("gm:editend", function (event) {
          if (event.feature && event.feature.id === currentPolygonId) {
            console.log("Polygon edited");
            updatePolygonData();
          }
        });

        updatePolygonData();
      });
    } catch (e) {
      console.error("Error initializing Geoman:", e);
      showAlert(
        "danger",
        "Failed to initialize polygon drawing tools: " + e.message,
      );
    }
  });

  function updatePolygonData() {
    try {
      if (!gm || !gm.features) {
        console.log("Geoman features not yet available");
        return;
      }

      // Get the current polygon if it exists
      drawnPolygon = null;

      gm.features.forEach(function (feature) {
        if (feature.shape === "polygon" && feature.id === currentPolygonId) {
          console.log("Found current polygon:", feature.id);
          drawnPolygon = feature.getGeoJson();
        }
      });

      // Update submit button state
      if (drawnPolygon) {
        submitButton.disabled = false;
        console.log("Polygon ready for submission:", drawnPolygon);
      } else {
        drawnPolygon = null;
        submitButton.disabled = true;
        console.log("No polygon to submit");
      }
    } catch (e) {
      console.warn("Error querying polygon data:", e);
    }
  }

  const confidenceRadios = document.querySelectorAll(
    'input[name="confidence"]',
  );
  const notesRequiredIndicator = document.getElementById(
    "notes-required-indicator",
  );
  const notesHelpText = document.getElementById("notes-help-text");

  // Handle confidence level changes
  if (confidenceRadios && confidenceRadios.length > 0) {
    confidenceRadios.forEach((radio) => {
      radio.addEventListener("change", function () {
        if (this.value === "low") {
          if (notesRequiredIndicator)
            notesRequiredIndicator.style.display = "inline";
          if (notesHelpText) notesHelpText.style.display = "block";
          if (confidenceNotes) confidenceNotes.required = true;
        } else {
          if (notesRequiredIndicator)
            notesRequiredIndicator.style.display = "none";
          if (notesHelpText) notesHelpText.style.display = "none";
          if (confidenceNotes) confidenceNotes.required = false;
        }
      });
    });
  }

  // Handle back button
  if (backButton) {
    backButton.addEventListener("click", function () {
      window.location.href = config.urls.imageDetail;
    });
  }

  // Handle submit button
  submitButton.addEventListener("click", function () {
    if (!drawnPolygon) {
      showAlert("warning", "Please draw a polygon on the map first");
      return;
    }

    const selectedConfidence = document.querySelector(
      'input[name="confidence"]:checked',
    );
    if (!selectedConfidence) {
      showAlert("warning", "Please select a confidence level");
      return;
    }

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

    performSubmission();
  });

  // Function to handle the actual submission
  function performSubmission() {
    if (!drawnPolygon || !drawnPolygon.geometry) {
      showAlert("danger", "Invalid polygon data");
      return;
    }

    const notes = confidenceNotes.value.trim();
    const selectedConfidence = document.querySelector(
      'input[name="confidence"]:checked',
    );
    const confidence = selectedConfidence ? selectedConfidence.value : "medium";

    const data = {
      polygon: drawnPolygon.geometry,
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
    submitButton.innerHTML =
      '<i class="fas fa-spinner fa-spin me-2"></i>Submitting...';

    fetch(config.urls.aerialGeoreferenceImage, {
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
          showAlert(
            "success",
            "Polygonal georeference submitted successfully!",
          );
          setTimeout(() => {
            window.location.href = config.urls.imageDetail;
          }, 1500);
        } else {
          showAlert("danger", "Error: " + data.error);
          submitButton.disabled = false;
          submitButton.innerHTML =
            '<i class="fas fa-check me-2"></i>Submit Aerial Georeference';
        }
      })
      .catch((error) => {
        showAlert("danger", "Network error occurred");
        submitButton.disabled = false;
        submitButton.innerHTML =
          '<i class="fas fa-check me-2"></i>Submit Aerial Georeference';
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
        button.className = `btn btn-sm btn-${getBootstrapColor(newDifficulty)}`;
        button.disabled = true;
        button.removeAttribute("data-difficulty");
      } else {
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

    if (difficultyBadge) {
      difficultyBadge.className = `badge bg-${getBootstrapColor(newDifficulty)}`;
      difficultyBadge.innerHTML =
        newDifficulty.charAt(0).toUpperCase() + newDifficulty.slice(1);
    } else {
      const badgeContainer = cardHeader.querySelector("h5");
      if (badgeContainer) {
        const newBadge = document.createElement("span");
        newBadge.className = `badge bg-${getBootstrapColor(newDifficulty)} ms-2`;
        newBadge.innerHTML =
          newDifficulty.charAt(0).toUpperCase() + newDifficulty.slice(1);
        badgeContainer.appendChild(newBadge);
      }
    }
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
            window.location.href = config.urls.imageDetail;
          }, 1000);
        }
      });
    });
  }

  // Helper function to show alerts
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

  // Initialize subject editor component
  initSubjectEditor();
});
