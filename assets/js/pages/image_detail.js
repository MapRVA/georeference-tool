// Import our custom styles
import "../../styles/main.css";
import "../../styles/components/rating-stars.css";
import "../../styles/components/timeline.css";
import "../../styles/pages/image-detail.css";
import "../../styles/components/markdown.css";
import "../../styles/components/image-viewer.css";

// Import components
import { initSubjectEditor } from "../components/subject_editor.js";
import { initImageViewer } from "../components/image_viewer.js";

// Utility function for difficulty badge colors
function getBootstrapColor(difficulty) {
  const colors = { easy: "success", medium: "warning", hard: "danger" };
  return colors[difficulty] || "secondary";
}

document.addEventListener("DOMContentLoaded", function () {
  // Get configuration from window object (set by Django template)
  const config = window.imageDetailConfig;

  if (!config) {
    console.error(
      "imageDetailConfig not found! Make sure the template script is loaded before this file.",
    );
    return;
  }

  // Extract config values for convenience
  const imageId = config.imageId;
  const isStaff = config.isStaff;
  const isAuthenticated = config.isAuthenticated;
  const isGeoreferenced = config.isGeoreferenced;
  const validationUrl = config.georeference?.validationUrl || null;
  let avgRating = config.avgRating;
  let userRating = config.userRating;
  window.ratingCount = config.ratingCount;

  // Rating modal state
  let ratingModal = null;
  let modalRating = null;
  let isDragging = false;
  let dragBounds = null; // Cache container bounds during drag

  // Extract and display domain from source link
  const sourceLink = document.getElementById("source-link");
  const sourceDomain = document.getElementById("source-domain");
  if (sourceLink && sourceDomain) {
    try {
      const url = new URL(sourceLink.href);
      sourceDomain.textContent = url.hostname;
    } catch (e) {
      sourceDomain.textContent = "Source";
    }
  }

  // Update MapSwap link for georeferenced images
  const mapswapLink = document.getElementById("mapswap-link");
  if (mapswapLink) {
    if (config.georeference) {
      // Use actual georeference coordinates
      const lat = config.georeference.lat;
      const lng = config.georeference.lng;
      const zoom = "18";
      mapswapLink.href = `https://mapswap.trailsta.sh/swap/#type=m&url=geo:${lat},${lng};z=${zoom}`;
    } else {
      // No georeferencing - set default link to Richmond, VA
      mapswapLink.href =
        "https://mapswap.trailsta.sh/swap/#type=m&url=geo:37.5407,-77.4360;z=12";
    }
  }

  initImageViewer();

  // Difficulty marking functionality (admin only)
  function handleDifficultyClick() {
    const difficulty = this.dataset.difficulty;
    const clickedButton = this;
    const csrfToken = document.querySelector(
      '[name="csrfmiddlewaretoken"]',
    )?.value;

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
    const labelText = buttonGroup.previousElementSibling;

    // Update label
    if (labelText && labelText.tagName === "SMALL") {
      labelText.textContent = "Difficulty Level:";
    }

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
      // Create new badge
      const badgeContainer = cardHeader.querySelector(".d-flex.gap-2");
      if (badgeContainer) {
        const newBadge = document.createElement("span");
        newBadge.className = `badge status-badge bg-${getBootstrapColor(newDifficulty)}`;
        newBadge.innerHTML = `<i class="fas fa-signal me-1"></i>${newDifficulty.charAt(0).toUpperCase() + newDifficulty.slice(1)}`;
        badgeContainer.insertBefore(newBadge, badgeContainer.firstChild);
      }
    }
  }

  function handleScaleClick() {
    const scale = this.dataset.scale;
    const clickedButton = this;
    const csrfToken = document.querySelector(
      '[name="csrfmiddlewaretoken"]',
    )?.value;

    const buttonGroup = document.getElementById("scale-button-group");
    if (buttonGroup) {
      buttonGroup
        .querySelectorAll("button")
        .forEach((btn) => (btn.disabled = true));
    }

    const originalText = clickedButton.innerHTML;
    clickedButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    const formData = new FormData();
    formData.append("scale", scale);
    formData.append("csrfmiddlewaretoken", csrfToken);

    fetch(config.urls.markScale, {
      method: "POST",
      body: formData,
    })
      .then((response) => {
        if (response.ok) {
          return response.json();
        }
        return response.json().then((err) => {
          throw new Error(err.error || "Network response was not ok");
        });
      })
      .then((data) => {
        if (data.success) {
          showAlert(
            "success",
            data.message || `Image scale marked as ${scale}`,
          );
          setTimeout(() => {
            updateScaleButtons(scale);
          }, 10);
        } else {
          throw new Error(data.error || "Error marking scale.");
        }
      })
      .catch((error) => {
        console.error("Error:", error);
        showAlert(
          "danger",
          error.message || "Error marking scale. Please try again.",
        );
        // Note: Can't access original scale from template anymore
        updateScaleButtons("");
      });
  }

  function updateScaleButtons(newScale) {
    const buttonGroup = document.getElementById("scale-button-group");
    if (!buttonGroup) return;

    const buttons = buttonGroup.querySelectorAll("button");

    buttons.forEach((button) => {
      const buttonValue = button.dataset.value;
      button.disabled = false;

      if (buttonValue === newScale) {
        button.disabled = true;
        button.className = "btn btn-sm btn-primary";
        button.removeAttribute("data-scale");
      } else {
        button.className = "btn btn-sm btn-outline-primary mark-scale";
        button.setAttribute("data-scale", buttonValue);

        if (!button.hasEventListener) {
          button.addEventListener("click", handleScaleClick);
          button.hasEventListener = true;
        }
      }
      button.innerHTML = buttonValue;
    });
  }

  function updateWillNotGeoreferenceStatus(willNotGeoref) {
    const cardHeader = document.querySelector(".card-header");
    if (!cardHeader) return;

    const badgeContainer = cardHeader.querySelector(".d-flex.gap-2");
    if (!badgeContainer) return;

    // Find the status badge (the one that shows georeferenced/available/will not georeference)
    let statusBadge = null;
    badgeContainer.querySelectorAll(".badge").forEach((badge) => {
      if (
        badge.innerHTML.includes("Georeferenced") ||
        badge.innerHTML.includes("Available") ||
        badge.innerHTML.includes("Will Not Georeference")
      ) {
        statusBadge = badge;
      }
    });

    if (statusBadge) {
      if (willNotGeoref) {
        statusBadge.className = "badge status-badge bg-secondary";
        statusBadge.innerHTML =
          '<i class="fas fa-ban me-1"></i>Will Not Georeference';
      } else {
        // Check if it's georeferenced or available
        if (isGeoreferenced) {
          statusBadge.className = "badge status-badge bg-success";
          statusBadge.innerHTML =
            '<i class="fas fa-map-marker-alt me-1"></i>Georeferenced';
        } else {
          statusBadge.className = "badge status-badge bg-warning text-dark";
          statusBadge.innerHTML = '<i class="fas fa-clock me-1"></i>Available';
        }
      }
    }
  }

  // Initialize difficulty buttons
  if (isStaff) {
    document.querySelectorAll(".mark-difficulty").forEach((button) => {
      button.addEventListener("click", handleDifficultyClick);
      button.hasEventListener = true;
    });

    document.querySelectorAll(".mark-scale").forEach((button) => {
      button.addEventListener("click", handleScaleClick);
      button.hasEventListener = true;
    });

    // Mark as Aerial toggle button handler
    const aerialBtn = document.querySelector(".toggle-aerial");
    if (aerialBtn) {
      aerialBtn.addEventListener("click", function () {
        const button = this;
        const currentState = button.dataset.aerial === "true";
        const newState = !currentState;
        const csrfToken = document.querySelector(
          '[name="csrfmiddlewaretoken"]',
        )?.value;

        button.disabled = true;
        const originalText = button.innerHTML;
        button.innerHTML =
          '<i class="fas fa-spinner fa-spin me-1"></i>Updating...';

        const formData = new FormData();
        formData.append("aerial", newState.toString());
        formData.append("csrfmiddlewaretoken", csrfToken);

        fetch(config.urls.markAerial, {
          method: "POST",
          body: formData,
        })
          .then((response) => {
            if (response.ok) {
              const message = newState
                ? "Image marked as aerial"
                : "Removed aerial marking";
              showAlert("success", message);

              // Reload page to refresh the UI
              setTimeout(() => location.reload(), 1000);
            } else {
              throw new Error("Network response was not ok");
            }
          })
          .catch((error) => {
            console.error("Error:", error);
            showAlert(
              "danger",
              "Error updating aerial status. Please try again.",
            );
            button.disabled = false;
            button.innerHTML = originalText;
          });
      });
    }

    // Will Not Georeference toggle button handler
    const willNotGeoreferenceBtn = document.querySelector(
      ".toggle-will-not-georeference",
    );
    if (willNotGeoreferenceBtn) {
      willNotGeoreferenceBtn.addEventListener("click", function () {
        const button = this;
        const currentState = button.dataset.willNotGeoref === "true";
        const newState = !currentState;
        const action = newState ? "mark" : "unmark";
        const csrfToken = document.querySelector(
          '[name="csrfmiddlewaretoken"]',
        )?.value;

        button.disabled = true;
        const originalText = button.innerHTML;
        button.innerHTML = `<i class="fas fa-spinner fa-spin me-1"></i>${action === "mark" ? "Marking" : "Removing"}...`;

        const formData = new FormData();
        formData.append("will_not_georef", newState.toString());
        formData.append("csrfmiddlewaretoken", csrfToken);

        fetch(config.urls.markWillNotGeoref, {
          method: "POST",
          body: formData,
        })
          .then((response) => {
            if (response.ok) {
              const message = newState
                ? 'Image marked as "Will Not Georeference"'
                : 'Removed "Will Not Georeference" flag';
              showAlert("success", message);

              // Update button state immediately
              button.dataset.willNotGeoref = newState.toString();

              if (newState) {
                button.className =
                  "btn btn-secondary btn-sm w-100 mb-2 toggle-will-not-georeference";
                button.innerHTML =
                  '<i class="fas fa-undo me-1"></i>Remove "Will Not Georeference"';
              } else {
                button.className =
                  "btn btn-outline-secondary btn-sm w-100 mb-2 toggle-will-not-georeference";
                button.innerHTML =
                  '<i class="fas fa-ban me-1"></i>Mark as "Will Not Georeference"';
              }

              button.disabled = false;

              // Update the status badge in the header
              updateWillNotGeoreferenceStatus(newState);
            } else {
              throw new Error("Network response was not ok");
            }
          })
          .catch((error) => {
            console.error("Error:", error);
            showAlert("danger", `Error ${action}ing image. Please try again.`);
            button.disabled = false;
            button.innerHTML = originalText;
          });
      });
    }
  }

  // Validation form handler
  const validateForm = document.getElementById("validateForm");
  if (validateForm && validationUrl) {
    validateForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const formData = new FormData(validateForm);
      const validation = formData.get("validation");

      if (!validation) {
        alert("Please select a validation option.");
        return;
      }

      const submitBtn = validateForm.querySelector('button[type="submit"]');
      const originalText = submitBtn.innerHTML;
      submitBtn.innerHTML =
        '<i class="fas fa-spinner fa-spin me-1"></i>Submitting...';
      submitBtn.disabled = true;

      fetch(validationUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": formData.get("csrfmiddlewaretoken"),
        },
        body: JSON.stringify({
          validation: validation,
          notes: formData.get("notes") || "",
        }),
      })
        .then((response) => response.json())
        .then((data) => {
          if (data.success) {
            location.reload();
          } else {
            alert("Error: " + data.error);
          }
        })
        .catch((error) => {
          console.error("Error:", error);
          alert("An error occurred while submitting the validation.");
        })
        .finally(() => {
          submitBtn.innerHTML = originalText;
          submitBtn.disabled = false;
        });
    });
  }

  // Comment form handler
  const commentForm = document.getElementById("commentForm");
  if (commentForm) {
    commentForm.addEventListener("submit", function (e) {
      e.preventDefault();
      const formData = new FormData(commentForm);
      const commentText = formData.get("text").trim();

      if (!commentText) {
        showAlert("warning", "Please enter a comment.");
        return;
      }

      const submitBtn = commentForm.querySelector('button[type="submit"]');
      const originalText = submitBtn.innerHTML;
      submitBtn.innerHTML =
        '<i class="fas fa-spinner fa-spin me-1"></i>Submitting...';
      submitBtn.disabled = true;

      const csrfToken = formData.get("csrfmiddlewaretoken");

      fetch(config.urls.addComment, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({
          text: commentText,
        }),
      })
        .then((response) => {
          // Check content-type to determine how to parse response
          const contentType = response.headers.get("content-type");
          if (contentType && contentType.includes("application/json")) {
            return response.json().then((data) => ({
              status: response.status,
              ok: response.ok,
              data: data,
            }));
          } else {
            return response.text().then((text) => {
              console.error("Non-JSON response:", text);
              throw new Error(
                "Server returned non-JSON response: " + text.substring(0, 100),
              );
            });
          }
        })
        .then((result) => {
          if (!result.ok) {
            throw new Error(
              result.data.error || `Server error: ${result.status}`,
            );
          }
          if (result.data.success) {
            showAlert("success", "Comment added successfully!");
            // Close modal and reload page
            const modal = bootstrap.Modal.getInstance(
              document.getElementById("commentModal"),
            );
            if (modal) modal.hide();
            setTimeout(() => location.reload(), 1000);
          } else {
            throw new Error(result.data.error || "Error adding comment");
          }
        })
        .catch((error) => {
          console.error("Error:", error);
          showAlert("danger", `Error: ${error.message}`);
        })
        .finally(() => {
          submitBtn.innerHTML = originalText;
          submitBtn.disabled = false;
        });
    });
  }

  // Force FontAwesome to use CSS mode instead of SVG
  if (window.FontAwesome) {
    window.FontAwesome.config = {
      autoReplaceSvg: false,
      searchPseudoElements: true,
    };
  }

  // Album dropdown functionality for image detail page
  if (isAuthenticated) {
    const createAlbumModal = document.getElementById("createAlbumModal");
    const newAlbumTitle = document.getElementById("newAlbumTitle");
    const newAlbumDescription = document.getElementById("newAlbumDescription");
    const newAlbumPublic = document.getElementById("newAlbumPublic");
    const createAlbumBtn = document.getElementById("createAlbumBtn");

    // Handle dropdown toggle - fetch albums when dropdown is shown
    const albumDropdownButton = document.getElementById(
      "imageAlbumDropdownBtn",
    );
    if (albumDropdownButton) {
      albumDropdownButton.addEventListener("click", function (e) {
        // Fetch albums after a brief delay to allow dropdown to open
        setTimeout(() => {
          const dropdown = this.closest(".dropdown");
          const dropdownMenu = dropdown.querySelector(".dropdown-menu");

          // Fetch user's albums and check which ones contain this image
          fetch(`${config.urls.userAlbumsApi}?image_id=${imageId}`)
            .then((response) => response.json())
            .then((data) => {
              let html = "";
              if (data.albums.length > 0) {
                data.albums.forEach((album) => {
                  const isInAlbum = album.has_image;
                  const icon = isInAlbum
                    ? '<i class="fas fa-check-circle me-2 text-success"></i>'
                    : '<i class="fas fa-plus me-2 text-muted"></i>';
                  const title = isInAlbum
                    ? `${album.title} <span class="text-muted small">(click to remove)</span>`
                    : album.title;
                  html += `<li><a class="dropdown-item album-option" href="#" data-album-id="${album.id}" data-image-id="${imageId}" data-in-album="${isInAlbum}">${icon}${title}</a></li>`;
                });
                html += '<li><hr class="dropdown-divider"></li>';
              }
              html += `<li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#createAlbumModal"><i class="fas fa-plus me-1"></i>Create New Album</a></li>`;
              dropdownMenu.innerHTML = html;

              // Add event listeners to album options
              dropdownMenu.querySelectorAll(".album-option").forEach((link) => {
                link.addEventListener("click", function (e) {
                  e.preventDefault();
                  const albumId = this.dataset.albumId;
                  const isInAlbum = this.dataset.inAlbum === "true";
                  if (isInAlbum) {
                    removeImageFromAlbum(imageId, albumId);
                  } else {
                    addImageToAlbum(imageId, albumId);
                  }
                });
              });

              // Handle create album link
              dropdownMenu
                .querySelector('[data-bs-target="#createAlbumModal"]')
                ?.addEventListener("click", function (e) {
                  e.preventDefault();
                  // Reset form
                  newAlbumTitle.value = "";
                  newAlbumDescription.value = "";
                  newAlbumPublic.checked = false;
                  const modal =
                    bootstrap.Modal.getOrCreateInstance(createAlbumModal);
                  modal.show();
                });
            })
            .catch((error) => {
              console.error("Error fetching albums:", error);
              dropdownMenu.innerHTML =
                '<li><span class="dropdown-item-text text-danger small">Error loading albums</span></li>';
            });
        }, 10);
      });
    }

    // Handle create album
    createAlbumBtn?.addEventListener("click", function () {
      if (!newAlbumTitle.value.trim()) {
        showAlert("warning", "Please enter an album title");
        return;
      }

      const data = {
        image_id: imageId,
        album_title: newAlbumTitle.value,
        album_description: newAlbumDescription.value,
        album_public: newAlbumPublic.checked,
      };

      const csrfToken = document.querySelector(
        "[name=csrfmiddlewaretoken]",
      )?.value;

      fetch(config.urls.createAlbum, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken || "",
        },
        body: JSON.stringify(data),
      })
        .then((response) => response.json())
        .then((result) => {
          if (result.success) {
            bootstrap.Modal.getInstance(createAlbumModal)?.hide();
            showAlert("success", "Album created and image added successfully!");
          } else {
            showAlert(
              "danger",
              "Error: " + (result.error || "Failed to create album"),
            );
          }
        })
        .catch((error) => {
          console.error("Error:", error);
          showAlert("danger", "An error occurred while creating the album");
        });
    });

    // Helper function to add image to existing album
    function addImageToAlbum(imgId, albumId) {
      const data = {
        image_id: imgId,
        album_id: albumId,
      };

      const csrfToken = document.querySelector(
        "[name=csrfmiddlewaretoken]",
      )?.value;

      fetch(config.urls.addToAlbum, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken || "",
        },
        body: JSON.stringify(data),
      })
        .then((response) => response.json())
        .then((result) => {
          if (result.success) {
            showAlert("success", "Image added to album successfully!");
          } else {
            showAlert(
              "danger",
              "Error: " + (result.error || "Failed to add image to album"),
            );
          }
        })
        .catch((error) => {
          console.error("Error:", error);
          showAlert(
            "danger",
            "An error occurred while adding the image to the album",
          );
        });
    }

    // Helper function to remove image from album
    function removeImageFromAlbum(imgId, albumId) {
      const data = {
        image_id: imgId,
        album_id: albumId,
      };

      const csrfToken = document.querySelector(
        "[name=csrfmiddlewaretoken]",
      )?.value;

      fetch(config.urls.removeFromAlbum, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken || "",
        },
        body: JSON.stringify(data),
      })
        .then((response) => response.json())
        .then((result) => {
          if (result.success) {
            showAlert("success", "Image removed from album successfully!");
          } else {
            showAlert(
              "danger",
              "Error: " + (result.error || "Failed to remove image from album"),
            );
          }
        })
        .catch((error) => {
          console.error("Error:", error);
          showAlert(
            "danger",
            "An error occurred while removing the image from the album",
          );
        });
    }
  }

  // Initialize subject editor component
  initSubjectEditor();

  // Rating functionality - Cleaner implementation
  let ratingEventsSetup = false;

  // Convert rating (1-10) to stars (0.5-5.0)
  function ratingToStars(rating) {
    return rating / 2;
  }

  // Render average rating stars with fractional support
  function renderAverageRatingStars() {
    const starsDiv = document.getElementById("avg-rating-stars");
    if (!starsDiv || !avgRating) return;

    const starCount = ratingToStars(avgRating);
    starsDiv.innerHTML = "";

    for (let i = 1; i <= 5; i++) {
      if (i <= Math.floor(starCount)) {
        // Full star
        const star = document.createElement("i");
        star.className = "fas fa-star avg-rating-star filled";
        starsDiv.appendChild(star);
      } else if (i === Math.ceil(starCount) && starCount % 1 !== 0) {
        // Fractional star
        const percentage = (starCount - Math.floor(starCount)) * 100;
        const starWrapper = document.createElement("div");
        starWrapper.className = "star-fractional";

        const bgStar = document.createElement("i");
        bgStar.className = "fas fa-star star-bg";

        const fillContainer = document.createElement("div");
        fillContainer.className = "star-fill-container";
        fillContainer.style.width = `${percentage}%`;

        const fillStar = document.createElement("i");
        fillStar.className = "fas fa-star star-fill";
        fillContainer.appendChild(fillStar);

        starWrapper.appendChild(bgStar);
        starWrapper.appendChild(fillContainer);
        starsDiv.appendChild(starWrapper);
      } else {
        // Empty star
        const star = document.createElement("i");
        star.className = "fas fa-star avg-rating-star empty";
        starsDiv.appendChild(star);
      }
    }
  }

  // Initialize user rating stars - keep static structure
  function initializeUserRatingStars() {
    if (!isAuthenticated) return;

    const starsDiv = document.getElementById("user-rating-stars");
    if (!starsDiv) return;

    // Clear and create fresh star structure
    starsDiv.innerHTML = "";

    for (let i = 1; i <= 5; i++) {
      const star = document.createElement("i");
      star.className = "fas fa-star rating-star";
      star.setAttribute("data-star", i);
      starsDiv.appendChild(star);
    }

    updateUserRatingDisplay();
    updateClearButtonVisibility();
  }

  // Update user rating display without rebuilding DOM
  function updateUserRatingDisplay() {
    if (!isAuthenticated) return;

    const starsDiv = document.getElementById("user-rating-stars");
    if (!starsDiv) return;

    const stars = starsDiv.querySelectorAll(".rating-star");

    if (userRating) {
      const starValue = ratingToStars(userRating);

      // Use exact same approach as average ratings
      starsDiv.innerHTML = "";

      for (let i = 1; i <= 5; i++) {
        if (i <= Math.floor(starValue)) {
          // Full star - same as average ratings
          const star = document.createElement("i");
          star.className = "fas fa-star user-rating-star filled";
          star.setAttribute("data-star", i);
          starsDiv.appendChild(star);
        } else if (i === Math.ceil(starValue) && starValue % 1 !== 0) {
          // Fractional star - identical to average ratings
          const percentage = (starValue - Math.floor(starValue)) * 100;
          const starWrapper = document.createElement("div");
          starWrapper.className = "star-fractional";
          starWrapper.setAttribute("data-star", i);

          const bgStar = document.createElement("i");
          bgStar.className = "fas fa-star star-bg";

          const fillContainer = document.createElement("div");
          fillContainer.className = "star-fill-container";
          fillContainer.style.width = `${percentage}%`;

          const fillStar = document.createElement("i");
          fillStar.className = "fas fa-star star-fill";
          fillContainer.appendChild(fillStar);

          starWrapper.appendChild(bgStar);
          starWrapper.appendChild(fillContainer);
          starsDiv.appendChild(starWrapper);
        } else {
          // Empty star - same as average ratings
          const star = document.createElement("i");
          star.className = "fas fa-star user-rating-star empty";
          star.setAttribute("data-star", i);
          starsDiv.appendChild(star);
        }
      }
    } else {
      // No rating - same approach as average ratings
      starsDiv.innerHTML = "";
      for (let i = 1; i <= 5; i++) {
        const star = document.createElement("i");
        star.className = "fas fa-star user-rating-star empty";
        star.setAttribute("data-star", i);
        starsDiv.appendChild(star);
      }
    }
  }

  // Setup inline stars as modal trigger (replaces old hover/click behavior)
  function setupRatingInput() {
    if (!isAuthenticated || ratingEventsSetup) return;

    const starsDiv = document.getElementById("user-rating-stars");
    if (!starsDiv) return;

    // Click opens modal
    starsDiv.addEventListener("click", (e) => {
      e.preventDefault();
      openRatingModal();
    });

    // Keyboard accessibility
    starsDiv.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openRatingModal();
      }
    });

    // Touch opens modal (prevent any default touch behaviors)
    starsDiv.addEventListener(
      "touchend",
      (e) => {
        e.preventDefault();
        openRatingModal();
      },
      { passive: false },
    );

    // Clear rating button handler (still works inline)
    const clearBtn = document.getElementById("clear-rating-btn");
    if (clearBtn) {
      clearBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        clearUserRating();
      });
    }

    ratingEventsSetup = true;
  }

  // Submit rating function
  function submitRating(rating) {
    const starsDiv = document.getElementById("user-rating-stars");
    if (starsDiv) {
      starsDiv.style.pointerEvents = "none";
      starsDiv.style.opacity = "0.6";
    }

    const csrfToken = document.querySelector(
      '[name="csrfmiddlewaretoken"]',
    )?.value;
    if (!csrfToken) {
      showAlert("danger", "Security token not found. Please refresh the page.");
      if (starsDiv) {
        starsDiv.style.pointerEvents = "auto";
        starsDiv.style.opacity = "1";
      }
      return;
    }

    fetch(config.urls.rate, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({ rating: rating }),
    })
      .then((response) => {
        if (!response.ok) {
          return response.text().then((text) => {
            try {
              const errorData = JSON.parse(text);
              throw new Error(
                errorData.error || `Server error: ${response.status}`,
              );
            } catch (parseError) {
              throw new Error(`Server error: ${response.status}`);
            }
          });
        }
        return response.json();
      })
      .then((data) => {
        if (data.success) {
          // Update user rating and average rating in memory
          userRating = data.user_rating;
          avgRating = data.avg_rating;
          window.ratingCount = data.rating_count;

          // Update the display
          updateRatingCountDisplay();
          renderAverageRatingStars();
          updateUserRatingDisplay();
          updateClearButtonVisibility();

          // Update the preview to show current rating
          const previewEl = document.getElementById("rating-preview");
          if (previewEl) {
            previewEl.textContent = "";
            previewEl.style.opacity = "0";
          }

          showAlert("success", "Rating submitted successfully!");
        } else {
          showAlert("danger", data.error || "Failed to submit rating");
        }
      })
      .catch((error) => {
        showAlert("danger", `Error: ${error.message}`);
      })
      .finally(() => {
        // Re-enable stars
        if (starsDiv) {
          starsDiv.style.pointerEvents = "auto";
          starsDiv.style.opacity = "1";
        }
      });
  }

  // Function to update the rating count display text
  function updateRatingCountDisplay() {
    const ratingCountEl = document.getElementById("rating-count");
    const noRatingsEl = document.getElementById("no-ratings-text");
    const avgStarsEl = document.getElementById("avg-rating-stars");

    if (window.ratingCount !== undefined && window.ratingCount > 0) {
      if (ratingCountEl) {
        ratingCountEl.textContent = `(${window.ratingCount} rating${window.ratingCount !== 1 ? "s" : ""})`;
        ratingCountEl.style.display = "inline";
      }
      if (avgStarsEl) {
        avgStarsEl.style.display = "block";
      }
      if (noRatingsEl) {
        noRatingsEl.style.display = "none";
      }
    } else {
      if (ratingCountEl) {
        ratingCountEl.textContent = "";
        ratingCountEl.style.display = "none";
      }
      if (avgStarsEl) {
        avgStarsEl.style.display = "none";
      }
      if (noRatingsEl) {
        noRatingsEl.style.display = "block";
      }
    }
  }

  // Update clear button visibility
  function updateClearButtonVisibility() {
    const clearBtn = document.getElementById("clear-rating-btn");
    if (clearBtn) {
      if (userRating) {
        clearBtn.style.display = "inline-block";
      } else {
        clearBtn.style.display = "none";
      }
    }
  }

  // Clear user rating
  function clearUserRating() {
    const clearBtn = document.getElementById("clear-rating-btn");
    if (clearBtn) {
      clearBtn.disabled = true;
      clearBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Clearing...';
    }

    const csrfToken = document.querySelector(
      '[name="csrfmiddlewaretoken"]',
    )?.value;
    if (!csrfToken) {
      showAlert("danger", "Security token not found. Please refresh the page.");
      return;
    }

    fetch(config.urls.rate, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
    })
      .then((response) => {
        if (!response.ok) {
          return response.text().then((text) => {
            try {
              const errorData = JSON.parse(text);
              throw new Error(
                errorData.error || `Server error: ${response.status}`,
              );
            } catch (parseError) {
              throw new Error(`Server error: ${response.status}`);
            }
          });
        }
        return response.json();
      })
      .then((data) => {
        if (data.success) {
          // Update user rating and average rating in memory
          userRating = null;
          avgRating = data.avg_rating;
          window.ratingCount = data.rating_count;

          // Update the display
          updateRatingCountDisplay();
          renderAverageRatingStars();
          updateUserRatingDisplay();
          updateClearButtonVisibility();

          showAlert("success", "Rating cleared successfully!");
        } else {
          showAlert("danger", data.error || "Failed to clear rating");
        }
      })
      .catch((error) => {
        showAlert("danger", `Error: ${error.message}`);
      })
      .finally(() => {
        // Re-enable button
        if (clearBtn) {
          clearBtn.disabled = false;
          clearBtn.innerHTML = '<i class="fas fa-times"></i> Clear';
        }
      });
  }

  // Handle "Show Other Images" toggle on map
  const showOtherImagesToggle = document.getElementById(
    "show-other-images-toggle",
  );
  const otherImagesLoading = document.getElementById("other-images-loading");
  if (showOtherImagesToggle && typeof window.toggleOtherImages === "function") {
    showOtherImagesToggle.addEventListener("change", function () {
      const showAll = this.checked;

      // Show loading spinner when enabling other images
      if (showAll && otherImagesLoading) {
        otherImagesLoading.classList.remove("d-none");
      }

      window.toggleOtherImages(showAll, function () {
        // Hide loading spinner when layer finishes loading
        if (otherImagesLoading) {
          otherImagesLoading.classList.add("d-none");
        }
      });
    });
  }

  // =============================================
  // Rating Modal Functions
  // =============================================

  function initRatingModal() {
    const modalEl = document.getElementById("ratingModal");
    if (!modalEl) return;

    ratingModal = new bootstrap.Modal(modalEl);

    renderModalStars();
    setupModalEvents();
    setupModalButtons();

    // Reset state when modal hidden
    modalEl.addEventListener("hidden.bs.modal", () => {
      modalRating = null;
      isDragging = false;
      updateModalStarsDisplay();
    });

    // Initialize with current rating when shown
    modalEl.addEventListener("shown.bs.modal", () => {
      modalRating = userRating;
      updateModalStarsDisplay();
      updateModalButtons();
    });
  }

  function openRatingModal() {
    if (!ratingModal) return;
    modalRating = userRating;
    ratingModal.show();
  }

  function renderModalStars() {
    const container = document.getElementById("modal-rating-stars");
    if (!container) return;

    container.innerHTML = "";

    for (let i = 1; i <= 5; i++) {
      const wrapper = document.createElement("div");
      wrapper.className = "modal-star-wrapper";
      wrapper.dataset.star = i;

      const star = document.createElement("i");
      star.className = "fas fa-star modal-rating-star empty";
      star.dataset.star = i;

      wrapper.appendChild(star);
      container.appendChild(wrapper);
    }
  }

  function updateModalStarsDisplay() {
    const container = document.getElementById("modal-rating-stars");
    if (!container) return;

    const starValue = modalRating ? modalRating / 2 : 0;

    // Rebuild stars each time (same approach as average rating display)
    container.innerHTML = "";

    for (let i = 1; i <= 5; i++) {
      const wrapper = document.createElement("div");
      wrapper.className = "modal-star-wrapper";
      wrapper.dataset.star = i;

      if (i <= Math.floor(starValue)) {
        // Full filled star
        const star = document.createElement("i");
        star.className = "fas fa-star modal-rating-star filled";
        star.dataset.star = i;
        wrapper.appendChild(star);
      } else if (i === Math.ceil(starValue) && starValue % 1 !== 0) {
        // Half star - use overlay approach like average ratings
        wrapper.classList.add("modal-star-fractional");

        const bgStar = document.createElement("i");
        bgStar.className = "fas fa-star modal-rating-star empty";
        bgStar.dataset.star = i;

        const fillContainer = document.createElement("div");
        fillContainer.className = "modal-star-fill-container";
        fillContainer.style.width = "50%";

        const fillStar = document.createElement("i");
        fillStar.className = "fas fa-star modal-rating-star filled";
        fillContainer.appendChild(fillStar);

        wrapper.appendChild(bgStar);
        wrapper.appendChild(fillContainer);
      } else {
        // Empty star
        const star = document.createElement("i");
        star.className = "fas fa-star modal-rating-star empty";
        star.dataset.star = i;
        wrapper.appendChild(star);
      }

      container.appendChild(wrapper);
    }
  }

  function updateModalButtons() {
    const submitBtn = document.getElementById("modal-submit-rating");
    const clearBtn = document.getElementById("modal-clear-rating");

    if (submitBtn) {
      submitBtn.disabled = !modalRating;
    }
    if (clearBtn) {
      clearBtn.style.display = userRating ? "inline-block" : "none";
    }
  }

  function setupModalEvents() {
    const container = document.getElementById("modal-rating-stars");
    if (!container) return;

    // Use pointer events for unified mouse/touch handling
    container.addEventListener("pointerdown", handleModalPointerDown);
  }

  // Cache star positions at the start of a drag
  function cacheDragBounds() {
    const container = document.getElementById("modal-rating-stars");
    if (!container) return;

    const wrappers = container.querySelectorAll(".modal-star-wrapper");
    dragBounds = Array.from(wrappers).map((wrapper) => {
      const rect = wrapper.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        center: rect.left + rect.width / 2,
        starNum: parseInt(wrapper.dataset.star),
      };
    });
  }

  // Pointer event handlers (unified mouse/touch)
  let activePointerId = null;

  function handleModalPointerDown(e) {
    e.preventDefault();
    isDragging = true;
    activePointerId = e.pointerId;
    cacheDragBounds();
    updateRatingFromPosition(e.clientX);

    // Attach move/end listeners to document to capture events anywhere on screen
    document.addEventListener("pointermove", handleModalPointerMove);
    document.addEventListener("pointerup", handleModalPointerUp);
    document.addEventListener("pointercancel", handleModalPointerUp);
  }

  function handleModalPointerMove(e) {
    if (!isDragging || e.pointerId !== activePointerId) return;
    e.preventDefault();
    updateRatingFromPosition(e.clientX);
  }

  function handleModalPointerUp(e) {
    if (e.pointerId !== activePointerId) return;

    isDragging = false;
    activePointerId = null;
    dragBounds = null;

    // Remove document listeners
    document.removeEventListener("pointermove", handleModalPointerMove);
    document.removeEventListener("pointerup", handleModalPointerUp);
    document.removeEventListener("pointercancel", handleModalPointerUp);
  }

  // Convert X position to rating (1-10) based on star positions
  function updateRatingFromPosition(clientX) {
    // Get star positions from cache or DOM
    let stars = dragBounds;
    if (!stars || stars.length === 0) {
      const container = document.getElementById("modal-rating-stars");
      if (!container) return;
      const wrappers = container.querySelectorAll(".modal-star-wrapper");
      stars = Array.from(wrappers).map((wrapper) => {
        const rect = wrapper.getBoundingClientRect();
        return {
          left: rect.left,
          right: rect.right,
          center: rect.left + rect.width / 2,
          starNum: parseInt(wrapper.dataset.star),
        };
      });
    }

    if (stars.length === 0) return;

    let rating;

    // Check if before first star
    if (clientX < stars[0].left) {
      rating = 1;
    }
    // Check if after last star
    else if (clientX > stars[stars.length - 1].right) {
      rating = 10;
    }
    // Find which star we're over or between
    else {
      for (const star of stars) {
        if (clientX >= star.left && clientX <= star.right) {
          // Inside a star - left half = .5, right half = full
          const isLeftHalf = clientX < star.center;
          rating = (star.starNum - 1) * 2 + (isLeftHalf ? 1 : 2);
          break;
        } else if (clientX < star.left) {
          // In gap before this star - use previous star's full rating
          // (but minimum of 1 for first star)
          rating = Math.max(1, (star.starNum - 1) * 2);
          break;
        }
      }
      // If we didn't find it, default to max
      if (rating === undefined || rating === null) {
        rating = 10;
      }
    }

    rating = Math.max(1, Math.min(10, rating)); // Clamp to valid range

    if (rating !== modalRating) {
      modalRating = rating;
      updateModalStarsDisplay();
      updateModalButtons();
    }
  }

  function setupModalButtons() {
    const submitBtn = document.getElementById("modal-submit-rating");
    const clearBtn = document.getElementById("modal-clear-rating");

    if (submitBtn) {
      submitBtn.addEventListener("click", () => {
        if (modalRating) {
          submitRating(modalRating);
          if (ratingModal) ratingModal.hide();
        }
      });
    }

    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        clearUserRating();
        if (ratingModal) ratingModal.hide();
      });
    }
  }

  // Initialize rating system
  setTimeout(function () {
    renderAverageRatingStars();
    initializeUserRatingStars();
    setupRatingInput();
    updateRatingCountDisplay();
    updateClearButtonVisibility();

    // Initialize rating modal
    initRatingModal();
  }, 100);
});
