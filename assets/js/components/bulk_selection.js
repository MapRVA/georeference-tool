/**
 * Bulk Selection Component
 *
 * This Alpine.js component provides bulk selection and action capabilities
 * for image grids across the application.
 *
 * Requirements:
 * - Alpine.js 3.x
 * - Bootstrap 5
 * - autoComplete.js (for subject search)
 * - window.filterConfig object with API URLs
 *
 * Usage:
 * 1. Include this script in your page
 * 2. Set up window.filterConfig with required URLs
 * 3. Include bulk_actions_ui.html partial
 * 4. Ensure image cards have data-image-id attribute
 */

// Import autocomplete
import autoComplete from "@tarekraafat/autocomplete.js";
import "../../styles/components/autocomplete.css";

// Import filter cards component (auto-initializes and exposes global functions)
// This is imported here because bulk_selection and filter_cards are always used together
import "./filter_cards.js";

/**
 * Alpine.js component for bulk selection
 * This is the main component that handles all bulk selection logic
 */
export function bulkSelection() {
  return {
    selectionMode: false,
    selectedImages: new Set(),
    bulkSubjectAutocomplete: null,
    selectedBulkSubjects: [],

    // Album-related properties
    userAlbums: [],
    selectedAlbum: null,
    albumMode: "existing",

    /**
     * Initialize the component
     */
    init() {
      // Store global reference for use outside Alpine scope (modals are outside x-data)
      window.bulkSelectionInstance = this;

      // Watch for selection mode changes
      this.$watch("selectionMode", (value) => {
        if (value) {
          this.enableSelectionMode();
        } else {
          this.disableSelectionMode();
        }
      });
    },

    /**
     * Toggle selection mode on/off
     */
    toggleSelectionMode() {
      this.selectionMode = !this.selectionMode;
    },

    /**
     * Enable selection mode - adds overlays to all image cards
     */
    enableSelectionMode() {
      // Add click handlers and overlays to image cards
      const cards = document.querySelectorAll("[data-image-id]");
      cards.forEach((cardWrapper) => {
        const imageId = cardWrapper.dataset.imageId;
        const card = cardWrapper.querySelector(".image-card");

        if (card && !card.querySelector(".image-selection-overlay")) {
          // Create selection overlay
          const overlay = document.createElement("div");
          overlay.className = "image-selection-overlay";
          overlay.innerHTML = `
                        <div class="image-selection-checkbox">
                            <i class="fas fa-check" style="display: none;"></i>
                        </div>
                    `;

          overlay.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.toggleImageSelection(imageId, overlay);
          });

          card.style.position = "relative";
          card.appendChild(overlay);
        }
      });
    },

    /**
     * Disable selection mode - removes overlays and clears selection
     */
    disableSelectionMode() {
      // Remove overlays and reset selection
      const overlays = document.querySelectorAll(".image-selection-overlay");
      overlays.forEach((overlay) => overlay.remove());

      const cards = document.querySelectorAll(".image-card");
      cards.forEach((card) => card.classList.remove("selected"));

      this.selectedImages.clear();
    },

    /**
     * Toggle selection state for a single image
     */
    toggleImageSelection(imageId, overlay) {
      const card = overlay.closest(".image-card");
      const checkbox = overlay.querySelector(".image-selection-checkbox");
      const checkIcon = checkbox
        ? checkbox.querySelector("svg") || checkbox.querySelector("i")
        : null;

      if (this.selectedImages.has(imageId)) {
        this.selectedImages.delete(imageId);
        card.classList.remove("selected");
        if (checkbox) checkbox.classList.remove("checked");
        if (checkIcon) checkIcon.style.display = "none";
      } else {
        this.selectedImages.add(imageId);
        card.classList.add("selected");
        if (checkbox) checkbox.classList.add("checked");
        if (checkIcon) checkIcon.style.display = "block";
      }
    },

    /**
     * Select all visible images
     */
    selectAll() {
      const cards = document.querySelectorAll("[data-image-id]");
      cards.forEach((cardWrapper) => {
        const imageId = cardWrapper.dataset.imageId;
        const card = cardWrapper.querySelector(".image-card");
        const overlay = card?.querySelector(".image-selection-overlay");

        if (overlay && !this.selectedImages.has(imageId)) {
          this.selectedImages.add(imageId);
          card.classList.add("selected");
          const checkbox = overlay.querySelector(".image-selection-checkbox");
          if (checkbox) {
            checkbox.classList.add("checked");
            const checkIcon =
              checkbox.querySelector("svg") || checkbox.querySelector("i");
            if (checkIcon) checkIcon.style.display = "block";
          }
        }
      });
    },

    /**
     * Deselect all images
     */
    deselectAll() {
      const cards = document.querySelectorAll(".image-card");
      cards.forEach((card) => {
        card.classList.remove("selected");
        const checkbox = card.querySelector(".image-selection-checkbox");
        if (checkbox) {
          checkbox.classList.remove("checked");
          const checkIcon =
            checkbox.querySelector("svg") || checkbox.querySelector("i");
          if (checkIcon) checkIcon.style.display = "none";
        }
      });
      this.selectedImages.clear();
    },

    /**
     * Show the add subject modal
     */
    showAddSubjectModal() {
      if (this.selectedImages.size === 0) return;

      // Reset subjects list when opening modal
      this.selectedBulkSubjects = [];
      this.renderBulkSelectedSubjects();
      document.getElementById("bulkAddSubjectBtn").disabled = true;

      const modal = new bootstrap.Modal(
        document.getElementById("bulkAddSubjectModal"),
      );
      modal.show();

      // Initialize autocomplete if not already done
      if (!this.bulkSubjectAutocomplete) {
        this.bulkSubjectAutocomplete = new autoComplete({
          selector: "#bulkSubjectSearchInput",
          placeHolder: "Search for a subject...",
          data: {
            src: async (query) => {
              try {
                const source = await fetch(
                  `/api/v1/subjects/autocomplete/?q=${query}`,
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
                                <span style="text-overflow: ellipsis; white-space: nowrap; overflow: hidden;">
                                    ${data.match} <small class="text-muted ms-2">${description}</small>
                                </span>
                                <span style="display: flex; align-items: center; font-size: 13px; font-weight: 100; text-transform: uppercase; color: rgba(0,0,0,.5);">
                                    ${data.value.wikidata_id || ""}
                                </span>`;
            },
          },
          threshold: 2,
          events: {
            input: {
              selection: (event) => {
                const subject = event.detail.selection.value;
                // Check if subject is already selected
                if (
                  !this.selectedBulkSubjects.some((s) => s.id === subject.id)
                ) {
                  this.selectedBulkSubjects.push(subject);
                  this.renderBulkSelectedSubjects();
                }
                document.getElementById("bulkAddSubjectBtn").disabled = false;
                this.bulkSubjectAutocomplete.input.value = "";
              },
            },
          },
        });
      }
    },

    /**
     * Render the list of selected subjects in the modal
     */
    renderBulkSelectedSubjects() {
      const container = document.getElementById("bulkSelectedSubjectsList");
      const emptyMessage = document.getElementById("emptySubjectsMessage");

      if (this.selectedBulkSubjects.length === 0) {
        container.innerHTML = "";
        emptyMessage.style.display = "block";
      } else {
        emptyMessage.style.display = "none";
        container.innerHTML = this.selectedBulkSubjects
          .map(
            (subject) => `
                        <span class="badge bg-primary" data-subject-id="${subject.id}">
                            ${this.escapeHtml(subject.title)}
                            <button type="button" class="btn-close btn-close-white ms-1"
                                    style="font-size: 0.65rem;"
                                    data-subject-remove="${subject.id}">
                            </button>
                        </span>
                    `,
          )
          .join("");

        // Add click handlers for remove buttons
        container.querySelectorAll("[data-subject-remove]").forEach((btn) => {
          btn.addEventListener("click", (e) => {
            const subjectId = e.target.dataset.subjectRemove;
            this.removeBulkSubject(subjectId);
          });
        });
      }
    },

    /**
     * Remove a subject from the bulk selection list
     */
    removeBulkSubject(subjectId) {
      this.selectedBulkSubjects = this.selectedBulkSubjects.filter(
        (s) => s.id.toString() !== subjectId.toString(),
      );
      this.renderBulkSelectedSubjects();
      if (this.selectedBulkSubjects.length === 0) {
        document.getElementById("bulkAddSubjectBtn").disabled = true;
      }
    },

    /**
     * Perform bulk add subject operation
     */
    async bulkAddSubject() {
      if (
        this.selectedBulkSubjects.length === 0 ||
        this.selectedImages.size === 0
      )
        return;

      const btn = document.getElementById("bulkAddSubjectBtn");
      btn.disabled = true;
      btn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-2"></span>Adding...';

      try {
        // Process each subject
        const results = [];
        for (const subject of this.selectedBulkSubjects) {
          const response = await fetch("/api/v1/subjects/bulk-add/", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": this.getCsrfToken(),
            },
            body: JSON.stringify({
              image_ids: Array.from(this.selectedImages),
              wikidata_id: subject.wikidata_id,
            }),
          });

          const result = await response.json();
          results.push({ subject: subject, result: result });
        }

        // Close modal and reset
        const modal = bootstrap.Modal.getInstance(
          document.getElementById("bulkAddSubjectModal"),
        );
        modal.hide();

        // Build success message
        let successCount = 0;
        let messages = [];
        for (const { subject, result } of results) {
          if (result.success) {
            successCount++;
            if (result.added_count > 0) {
              messages.push(`"${subject.title}": ${result.added_count} added`);
            }
            if (result.already_exists_count > 0) {
              messages.push(
                `"${subject.title}": ${result.already_exists_count} already had this subject`,
              );
            }
          } else {
            messages.push(`"${subject.title}": Error - ${result.error}`);
          }
        }

        // Show detailed message
        if (successCount > 0) {
          const subjectNames = this.selectedBulkSubjects
            .map((s) => s.title)
            .join(", ");
          showAlert(
            "success",
            `Successfully added ${successCount} subject(s) (${subjectNames}) to ${this.selectedImages.size} images.`,
          );
        } else {
          showAlert("danger", "Failed to add subjects. Please try again.");
        }

        // Reset selection
        this.toggleSelectionMode();

        // Reset modal state
        this.selectedBulkSubjects = [];
        this.renderBulkSelectedSubjects();
        document.getElementById("bulkAddSubjectBtn").disabled = true;
      } catch (error) {
        console.error("Error adding subject:", error);
        showAlert(
          "danger",
          "An error occurred while adding the subject. Please try again.",
        );
      } finally {
        btn.disabled = false;
        btn.innerHTML = "Add Subject";
      }
    },

    /**
     * Show the add to album modal
     */
    showAddToAlbumModal() {
      if (this.selectedImages.size === 0) return;

      this.selectedAlbum = null;
      this.albumMode = "existing";
      this.resetAlbumModal();
      this.loadUserAlbums();

      // Update the count display (since modal is outside x-data scope)
      document.getElementById("bulkAlbumSelectedCount").textContent =
        this.selectedImages.size;

      const modal = new bootstrap.Modal(
        document.getElementById("bulkAddToAlbumModal"),
      );
      modal.show();

      // Set up mode toggle listeners
      this.setupAlbumModeToggle();
    },

    /**
     * Reset album modal to initial state
     */
    resetAlbumModal() {
      document.getElementById("bulkAlbumSelectText").textContent =
        "Choose an album...";
      document.getElementById("bulkNewAlbumTitle").value = "";
      document.getElementById("bulkNewAlbumDescription").value = "";
      document.getElementById("bulkNewAlbumPublic").checked = false;
      document.getElementById("albumModeExisting").checked = true;
      document.getElementById("existingAlbumSection").style.display = "block";
      document.getElementById("newAlbumSection").style.display = "none";
      document.getElementById("noAlbumsMessage").style.display = "none";
      this.updateAddToAlbumButton();
    },

    /**
     * Set up album mode toggle listeners
     */
    setupAlbumModeToggle() {
      const existingRadio = document.getElementById("albumModeExisting");
      const newRadio = document.getElementById("albumModeNew");
      const newAlbumTitleInput = document.getElementById("bulkNewAlbumTitle");

      existingRadio.addEventListener("change", () => {
        if (existingRadio.checked) {
          this.albumMode = "existing";
          document.getElementById("existingAlbumSection").style.display =
            "block";
          document.getElementById("newAlbumSection").style.display = "none";
          this.updateAddToAlbumButton();
        }
      });

      newRadio.addEventListener("change", () => {
        if (newRadio.checked) {
          this.albumMode = "new";
          document.getElementById("existingAlbumSection").style.display =
            "none";
          document.getElementById("newAlbumSection").style.display = "block";
          this.selectedAlbum = null;
          document.getElementById("bulkAlbumSelectText").textContent =
            "Choose an album...";
          this.updateAddToAlbumButton();
        }
      });

      // Listen for input on the new album title field
      if (newAlbumTitleInput) {
        newAlbumTitleInput.addEventListener("input", () => {
          this.updateAddToAlbumButton();
        });
      }
    },

    /**
     * Load user albums from API
     */
    async loadUserAlbums() {
      try {
        const response = await fetch(window.filterConfig.urls.userAlbumsApi);
        if (response.ok) {
          const data = await response.json();
          this.userAlbums = data.albums || [];
          this.renderAlbumDropdown();
        } else {
          console.error("Failed to load albums:", response.statusText);
        }
      } catch (error) {
        console.error("Error loading albums:", error);
      }
    },

    /**
     * Render album dropdown list
     */
    renderAlbumDropdown() {
      const dropdown = document.getElementById("bulkAlbumDropdown");
      const noAlbumsMessage = document.getElementById("noAlbumsMessage");

      dropdown.innerHTML = "";

      if (this.userAlbums.length === 0) {
        dropdown.innerHTML =
          '<li><span class="dropdown-item-text text-muted">No albums found</span></li>';
        noAlbumsMessage.style.display = "block";
        return;
      }

      noAlbumsMessage.style.display = "none";

      this.userAlbums.forEach((album) => {
        const li = document.createElement("li");
        const escapedTitle = this.escapeHtml(album.title);
        li.innerHTML = `
                    <button class="dropdown-item d-flex justify-content-between align-items-center" type="button" data-album-id="${album.id}" data-album-title="${escapedTitle}">
                        <span>${escapedTitle}</span>
                        ${album.public ? '<i class="fas fa-globe text-muted ms-2" title="Public album"></i>' : '<i class="fas fa-lock text-muted ms-2" title="Private album"></i>'}
                    </button>
                `;

        // Add click handler
        li.querySelector("button").addEventListener("click", (e) => {
          const btn = e.currentTarget;
          this.selectAlbum(btn.dataset.albumId, btn.dataset.albumTitle);
        });

        dropdown.appendChild(li);
      });
    },

    /**
     * Select an album
     */
    selectAlbum(albumId, albumTitle) {
      this.selectedAlbum = { id: albumId, title: albumTitle };
      document.getElementById("bulkAlbumSelectText").textContent = albumTitle;
      this.updateAddToAlbumButton();
    },

    /**
     * Update add to album button state
     */
    updateAddToAlbumButton() {
      const btn = document.getElementById("bulkAddToAlbumBtn");
      if (!btn) return;

      let hasValidSelection = false;

      if (this.albumMode === "existing") {
        hasValidSelection = this.selectedAlbum !== null;
      } else {
        const titleInput = document.getElementById("bulkNewAlbumTitle");
        hasValidSelection = titleInput && titleInput.value.trim() !== "";
      }

      btn.disabled = !hasValidSelection;
    },

    /**
     * Perform bulk add to album operation
     */
    async bulkAddToAlbum() {
      if (this.selectedImages.size === 0) return;

      const btn = document.getElementById("bulkAddToAlbumBtn");
      btn.disabled = true;
      btn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-2"></span>Adding...';

      try {
        let response;
        let albumTitle;

        if (this.albumMode === "new") {
          // Create new album and add images
          const newAlbumTitle = document
            .getElementById("bulkNewAlbumTitle")
            .value.trim();
          if (!newAlbumTitle) {
            throw new Error("Please enter an album title");
          }

          response = await fetch(
            window.filterConfig.urls.bulkCreateAndAddToAlbum,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": this.getCsrfToken(),
              },
              body: JSON.stringify({
                title: newAlbumTitle,
                description: document
                  .getElementById("bulkNewAlbumDescription")
                  .value.trim(),
                is_public:
                  document.getElementById("bulkNewAlbumPublic").checked,
                image_ids: Array.from(this.selectedImages),
              }),
            },
          );

          albumTitle = newAlbumTitle;
        } else if (this.selectedAlbum) {
          // Add to existing album
          response = await fetch(window.filterConfig.urls.bulkAddToAlbum, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": this.getCsrfToken(),
            },
            body: JSON.stringify({
              album_id: this.selectedAlbum.id,
              image_ids: Array.from(this.selectedImages),
            }),
          });

          albumTitle = this.selectedAlbum.title;
        } else {
          throw new Error("Please select an album");
        }

        if (response.ok) {
          const result = await response.json();

          if (result.success) {
            // Show success message with detailed info
            let message = result.message;
            if (result.total_requested !== result.added_count) {
              message += ` (${result.added_count} of ${result.total_requested} images were new to the album)`;
            }

            showAlert("success", message);

            // Close modal and reset
            bootstrap.Modal.getInstance(
              document.getElementById("bulkAddToAlbumModal"),
            ).hide();
            this.selectedAlbum = null;
            this.resetAlbumModal();

            // Exit selection mode
            this.toggleSelectionMode();
          } else {
            throw new Error(result.error || "Failed to add images to album");
          }
        } else {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(
            errorData.error ||
              `HTTP ${response.status}: ${response.statusText}`,
          );
        }
      } catch (error) {
        console.error("Error adding to album:", error);
        showAlert("danger", `Error adding images to album: ${error.message}`);
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-plus me-1"></i>Add to Album';
      }
    },

    /**
     * Get CSRF token for API requests
     */
    getCsrfToken() {
      // Try to get from hidden input first
      const input = document.querySelector("[name=csrfmiddlewaretoken]");
      if (input) return input.value;

      // Fall back to cookie
      const name = "csrftoken";
      let cookieValue = null;
      if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let i = 0; i < cookies.length; i++) {
          const cookie = cookies[i].trim();
          if (cookie.substring(0, name.length + 1) === name + "=") {
            cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
            break;
          }
        }
      }
      return cookieValue;
    },

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
      const div = document.createElement("div");
      div.textContent = text;
      return div.innerHTML;
    },
  };
}

/**
 * Helper function to show alert toast notifications
 */
export function showAlert(type, message) {
  const alertDiv = document.createElement("div");
  alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
  alertDiv.style.cssText =
    "top: 20px; right: 20px; z-index: 9999; max-width: 400px;";
  alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;

  document.body.appendChild(alertDiv);

  // Auto-dismiss after 5 seconds
  setTimeout(() => {
    if (alertDiv.parentNode) {
      alertDiv.classList.remove("show");
      setTimeout(() => alertDiv.remove(), 150);
    }
  }, 5000);
}

// Make bulkSelection available globally for Alpine
if (typeof window !== "undefined") {
  window.bulkSelection = bulkSelection;
}
