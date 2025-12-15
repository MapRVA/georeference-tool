// Utility function for difficulty badge colors
function getBootstrapColor(difficulty) {
  const colors = { easy: "success", medium: "warning", hard: "danger" };
  return colors[difficulty] || "secondary";
}

// PhotoSwipe setup
function setupPhotoSwipeData(img) {
  const link = img.parentElement;
  link.setAttribute("data-pswp-width", img.naturalWidth);
  link.setAttribute("data-pswp-height", img.naturalHeight);
}

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

  // Image loading handlers
  const mainImage = document.getElementById("main-image");
  const imageFallback = document.getElementById("image-fallback");

  if (mainImage && imageFallback) {
    mainImage.onload = function () {
      imageFallback.style.setProperty("display", "none", "important");
      mainImage.style.display = "block";
      mainImage.style.visibility = "visible";
      setupPhotoSwipeData(this);
    };

    mainImage.onerror = function () {
      mainImage.style.display = "none";
      imageFallback.style.setProperty("display", "flex", "important");
    };

    // Handle already loaded images
    if (mainImage.complete) {
      if (mainImage.naturalHeight !== 0 && mainImage.naturalWidth !== 0) {
        imageFallback.style.setProperty("display", "none", "important");
        mainImage.style.display = "block";
        mainImage.style.visibility = "visible";
        setupPhotoSwipeData(mainImage);
      } else {
        mainImage.style.display = "none";
        imageFallback.style.setProperty("display", "flex", "important");
      }
    }
  }

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

    // Find the status badge (the one that shows georeferenced/pending/will not georeference)
    let statusBadge = null;
    badgeContainer.querySelectorAll(".badge").forEach((badge) => {
      if (
        badge.innerHTML.includes("Georeferenced") ||
        badge.innerHTML.includes("Pending") ||
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
        // Check if it's georeferenced or pending
        if (isGeoreferenced) {
          statusBadge.className = "badge status-badge bg-success";
          statusBadge.innerHTML =
            '<i class="fas fa-map-marker-alt me-1"></i>Georeferenced';
        } else {
          statusBadge.className = "badge status-badge bg-warning text-dark";
          statusBadge.innerHTML = '<i class="fas fa-clock me-1"></i>Pending';
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

  // Subject management functionality (logged-in users only)
  console.log("User is authenticated:", isAuthenticated);

  if (isAuthenticated) {
    const addBtn = document.getElementById("add-subject-btn");
    const subjectInput = document.getElementById("subject-autocomplete");

    function addSubjectByWikidataId(wikidataId) {
      if (!wikidataId || !wikidataId.match(/^Q\d+$/)) {
        showAlert(
          "danger",
          "Invalid Wikidata ID format. Must be Q followed by numbers (e.g., Q123456)",
        );
        return;
      }

      addBtn.disabled = true;
      const originalText = addBtn.innerHTML;
      addBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Adding...';

      const csrfToken = document.querySelector(
        '[name="csrfmiddlewaretoken"]',
      )?.value;

      fetch(config.urls.addSubject, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ wikidata_id: wikidataId }),
      })
        .then((response) => {
          if (!response.ok) {
            return response.json().then((err) => {
              throw new Error(err.error || "Server error");
            });
          }
          return response.json();
        })
        .then((data) => {
          if (data.success) {
            showAlert("success", data.message);
            subjectInput.value = "";
            location.reload(); // Reload to see the new subject
          } else {
            showAlert("danger", data.error);
          }
        })
        .catch((error) => {
          showAlert("danger", `Error adding subject: ${error.message}`);
        })
        .finally(() => {
          addBtn.disabled = false;
          addBtn.innerHTML = originalText;
        });
    }

    if (addBtn) {
      addBtn.addEventListener("click", function (e) {
        e.preventDefault();
        const inputValue = subjectInput.value.trim();
        if (inputValue.match(/^Q\d+$/)) {
          addSubjectByWikidataId(inputValue);
        } else {
          showAlert(
            "info",
            "Please select a subject from the suggestions or enter a valid Wikidata ID.",
          );
        }
      });
    }

    // Init Autocomplete
    const subjectAutocomplete = new autoComplete({
      selector: "#subject-autocomplete",
      placeHolder: "Search for a subject by name...",
      data: {
        src: async (query) => {
          try {
            const source = await fetch(
              `${config.urls.subjectAutocomplete}?q=${query}`,
            );
            const data = await source.json();
            return data;
          } catch (error) {
            return error;
          }
        },
        keys: ["title"],
        cache: false,
      },
      resultItem: {
        highlight: true,
        element: (item, data) => {
          item.style =
            "display: flex; justify-content: space-between; align-items: center;";
          let description = data.value.description
            ? data.value.description.substring(0, 40) + "..."
            : "";
          item.innerHTML = `
                    <span style=\"text-overflow: ellipsis; white-space: nowrap; overflow: hidden;\">
                        ${data.match} <small class=\"text-muted ms-2\">${description}</small>
                    </span>
                    <span style=\"display: flex; align-items: center; font-size: 13px; font-weight: 100; text-transform: uppercase; color: rgba(0,0,0,.5);\">
                        ${data.value.wikidata_id || ""}
                    </span>`;
        },
      },
      threshold: 2,
      events: {
        input: {
          selection: (event) => {
            const selection = event.detail.selection.value;
            subjectAutocomplete.input.value = selection.title;
            if (selection.wikidata_id) {
              addSubjectByWikidataId(selection.wikidata_id);
            }
          },
        },
      },
    });

    document.addEventListener("click", function (e) {
      const removeButton = e.target.closest(".remove-subject");
      if (removeButton) {
        const subjectRelationId = removeButton.dataset.subjectRelationId;
        const cardWrapper = removeButton.closest(".subject-card-wrapper");

        if (!subjectRelationId) return;

        if (
          !confirm(
            "Are you sure you want to remove this subject from the image?",
          )
        ) {
          return;
        }

        removeButton.disabled = true;
        const originalIcon = removeButton.innerHTML;
        removeButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        const csrfToken = document.querySelector(
          '[name="csrfmiddlewaretoken"]',
        )?.value;
        const url = config.urls.removeSubjectPattern.replace(
          "/0/",
          `/${subjectRelationId}/`,
        );

        fetch(url, {
          method: "POST",
          headers: {
            "X-CSRFToken": csrfToken,
          },
        })
          .then((response) => {
            if (!response.ok) {
              return response
                .json()
                .catch(() => null)
                .then((errorData) => {
                  throw new Error(errorData?.error || response.statusText);
                });
            }
            return response.json();
          })
          .then((data) => {
            if (data.success) {
              showAlert("success", data.message);
              if (cardWrapper) {
                cardWrapper.style.transition =
                  "opacity 0.3s ease-out, transform 0.3s ease-out";
                cardWrapper.style.opacity = "0";
                cardWrapper.style.transform = "scale(0.9)";
                setTimeout(() => {
                  cardWrapper.remove();
                  const subjectRow =
                    document.getElementById("image-subjects-row");
                  if (subjectRow && subjectRow.children.length === 0) {
                    location.reload();
                  }
                }, 300);
              }
            } else {
              showAlert("danger", data.error || "An unknown error occurred.");
              removeButton.disabled = false;
              removeButton.innerHTML = originalIcon;
            }
          })
          .catch((error) => {
            console.error("Error:", error);
            showAlert("danger", `Error removing subject: ${error.message}`);
            removeButton.disabled = false;
            removeButton.innerHTML = originalIcon;
          });
      }
    });
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

  // Sortable subjects (logged-in users only)
  if (isAuthenticated) {
    const subjectRow = document.querySelector("#image-subjects-row");
    if (subjectRow) {
      const sortable = new Sortable(subjectRow, {
        animation: 150,
        handle: ".drag-handle",
        filter: ".remove-subject", // Clicks on remove button should not start a drag
        preventOnFilter: true,
        onEnd: function (evt) {
          const subjectCards = subjectRow.querySelectorAll(".subject-card");
          const newOrder = Array.from(subjectCards).map(
            (card) => card.dataset.subjectRelationId,
          );

          const csrfToken = document.querySelector(
            '[name="csrfmiddlewaretoken"]',
          ).value;

          fetch(config.urls.reorderSubjects, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": csrfToken,
            },
            body: JSON.stringify({ order: newOrder }),
          })
            .then((response) => response.json())
            .then((data) => {
              if (data.success) {
                showAlert("success", "Subject order updated.");
              } else {
                showAlert("danger", "Error updating order: " + data.error);
                // Revert the drag visually on failure
                sortable.sort(
                  newOrder
                    .map((id, index) => ({ id, index }))
                    .sort(
                      (a, b) => evt.oldDraggableIndex - evt.newDraggableIndex,
                    )
                    .map((item) => item.id),
                );
              }
            })
            .catch((error) => {
              showAlert(
                "danger",
                "An unexpected error occurred while reordering.",
              );
              console.error("Error:", error);
              // Revert the drag visually on failure
              sortable.sort(
                newOrder
                  .map((id, index) => ({ id, index }))
                  .sort((a, b) => evt.oldDraggableIndex - evt.newDraggableIndex)
                  .map((item) => item.id),
              );
            });
        },
      });
    }
  }

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

  // Clean hover preview using same structure as average ratings
  function showHoverPreview(hoveredStarNum, isLeftHalf) {
    const starsDiv = document.getElementById("user-rating-stars");
    if (!starsDiv) return;

    // Use identical approach as average ratings
    starsDiv.innerHTML = "";

    for (let i = 1; i <= 5; i++) {
      if (i < hoveredStarNum) {
        // Full active star - identical to average ratings
        const star = document.createElement("i");
        star.className = "fas fa-star user-rating-star hover-active";
        star.setAttribute("data-star", i);
        starsDiv.appendChild(star);
      } else if (i === hoveredStarNum) {
        if (isLeftHalf) {
          // Half star - exact same structure as average ratings
          const starWrapper = document.createElement("div");
          starWrapper.className = "star-fractional";
          starWrapper.setAttribute("data-star", i);

          const bgStar = document.createElement("i");
          bgStar.className = "fas fa-star star-bg";

          const fillContainer = document.createElement("div");
          fillContainer.className = "star-fill-container";
          fillContainer.style.width = "50%";

          const fillStar = document.createElement("i");
          fillStar.className = "fas fa-star star-fill";
          fillContainer.appendChild(fillStar);

          starWrapper.appendChild(bgStar);
          starWrapper.appendChild(fillContainer);
          starsDiv.appendChild(starWrapper);
        } else {
          // Full active star - identical to average ratings
          const star = document.createElement("i");
          star.className = "fas fa-star user-rating-star hover-active";
          star.setAttribute("data-star", i);
          starsDiv.appendChild(star);
        }
      } else {
        // Inactive star - identical to average ratings
        const star = document.createElement("i");
        star.className = "fas fa-star user-rating-star hover-inactive";
        star.setAttribute("data-star", i);
        starsDiv.appendChild(star);
      }
    }

    // Update preview text
    const previewRating = (hoveredStarNum - 1) * 2 + (isLeftHalf ? 1 : 2);
    const previewStars = previewRating / 2;

    const previewEl = document.getElementById("rating-preview");
    if (previewEl) {
      previewEl.textContent = "";
      previewEl.style.opacity = "0";
    }
  }

  // Clear hover preview and restore original state
  function clearHoverPreview() {
    // Simply restore the original user rating display
    updateUserRatingDisplay();

    const previewEl = document.getElementById("rating-preview");
    if (previewEl) {
      previewEl.textContent = "";
      previewEl.style.opacity = "0";
    }
  }

  // Setup rating interactions
  function setupRatingInput() {
    if (!isAuthenticated || ratingEventsSetup) return;

    const starsDiv = document.getElementById("user-rating-stars");
    if (!starsDiv) return;

    // Click handler (works for both regular stars and fractional stars)
    starsDiv.addEventListener("click", function (e) {
      const star = e.target.closest(".user-rating-star, .star-fractional");
      if (!star) return;

      e.preventDefault();
      e.stopPropagation();

      const starNum = parseInt(star.dataset.star);
      const rect = star.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const isLeftHalf = clickX < rect.width / 2;

      const ratingToSubmit = (starNum - 1) * 2 + (isLeftHalf ? 1 : 2);
      submitRating(ratingToSubmit);
    });

    // Hover handlers (works for both regular stars and fractional stars)
    starsDiv.addEventListener("mousemove", function (e) {
      const star = e.target.closest(".user-rating-star, .star-fractional");
      if (!star) return;

      const starNum = parseInt(star.dataset.star);
      const rect = star.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const isLeftHalf = mouseX < rect.width / 2;

      showHoverPreview(starNum, isLeftHalf);
    });

    starsDiv.addEventListener("mouseleave", function () {
      clearHoverPreview();
    });

    // Clear rating button handler
    const clearBtn = document.getElementById("clear-rating-btn");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
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
  if (showOtherImagesToggle && typeof window.toggleOtherImages === "function") {
    showOtherImagesToggle.addEventListener("change", function () {
      window.toggleOtherImages(this.checked);
    });
  }

  // Initialize rating system
  setTimeout(function () {
    renderAverageRatingStars();
    initializeUserRatingStars();
    setupRatingInput();
    updateRatingCountDisplay();
    updateClearButtonVisibility();
  }, 100);
});
