/**
 * Image Grid Component
 *
 * Alpine.js component for managing image grid state, including bulk selection.
 * Cards register themselves via events, and selection state flows through the component.
 *
 * Usage:
 * 1. Import and register in page-specific JS:
 *    import { imageGrid } from '../components/image_grid.js';
 *    Alpine.data('imageGrid', imageGrid);
 *
 * 2. Use in template:
 *    <div x-data="imageGrid()">
 *        {% include 'images/partials/image_grid.html' %}
 *    </div>
 *
 * 3. Cards dispatch 'image-registered' events on init and the component tracks them.
 */

// Import autocomplete for subject search in modals
import autoComplete from "@tarekraafat/autocomplete.js";
import "../../styles/components/autocomplete.css";

// Import filter cards component (auto-initializes and exposes global functions)
import "./filter_cards.js";

// Import notifications for toast messages
import "./notifications.js";

// Import album dropdown component - it auto-initializes on DOMContentLoaded
// with hardcoded API URLs, so no configuration needed
import "./album_dropdown.js";

/**
 * Alpine.js component for image grid state management
 */
export function imageGrid() {
  return {
    selectionMode: false,
    selectedIds: new Set(),
    registeredIds: new Set(),

    // Modal-related state
    bulkSubjectAutocomplete: null,
    selectedBulkSubjects: [],
    userAlbums: [],
    selectedAlbum: null,
    albumMode: "existing",
    pendingBulkAction: null,

    /**
     * Initialize the component
     */
    init() {
      // Store global reference for modal access outside Alpine scope
      window.imageGridInstance = this;

      // Listen for card registration events (bubbled from child cards)
      this.$el.addEventListener("image-registered", (e) => {
        this.registerImage(e.detail.id);
      });

      // Listen for modal show events
      this.$el.addEventListener("show-add-subject-modal", () => {
        this.showAddSubjectModal();
      });

      this.$el.addEventListener("show-add-to-album-modal", () => {
        this.showAddToAlbumModal();
      });

      // Listen for staff-only bulk status events
      this.$el.addEventListener("bulk-mark-aerial", () => {
        this.bulkMarkAerial();
      });

      this.$el.addEventListener("bulk-mark-will-not-georef", () => {
        this.bulkMarkWillNotGeoref();
      });
    },

    /**
     * Register an image ID as available for selection
     */
    registerImage(id) {
      this.registeredIds.add(id);
    },

    /**
     * Toggle selection mode on/off
     */
    toggleSelectionMode() {
      this.selectionMode = !this.selectionMode;
      if (!this.selectionMode) {
        this.selectedIds = new Set();
      }
      // Sync Bootstrap collapse state with Alpine state
      this.syncToolbarCollapse();
    },

    /**
     * Ensure Bootstrap collapse state matches Alpine selectionMode state
     */
    syncToolbarCollapse() {
      const toolbar = document.getElementById("bulkActionsToolbar");
      if (!toolbar) return;

      const bsCollapse = bootstrap.Collapse.getOrCreateInstance(toolbar, {
        toggle: false,
      });

      if (this.selectionMode) {
        bsCollapse.show();
      } else {
        bsCollapse.hide();
      }
    },

    /**
     * Toggle selection state for a single image
     */
    toggleSelection(id) {
      if (this.selectedIds.has(id)) {
        this.selectedIds.delete(id);
      } else {
        this.selectedIds.add(id);
      }
      // Trigger reactivity by reassigning the Set
      this.selectedIds = new Set(this.selectedIds);
    },

    /**
     * Check if an image is selected
     */
    isSelected(id) {
      return this.selectedIds.has(id);
    },

    /**
     * Select all registered images
     */
    selectAll() {
      this.registeredIds.forEach((id) => this.selectedIds.add(id));
      this.selectedIds = new Set(this.selectedIds);
    },

    /**
     * Deselect all images
     */
    deselectAll() {
      this.selectedIds = new Set();
    },

    /**
     * Get array of selected image IDs (for API calls)
     */
    getSelectedIds() {
      return Array.from(this.selectedIds);
    },

    /**
     * Get count of selected images
     */
    get selectedCount() {
      return this.selectedIds.size;
    },

    /**
     * Clear registered IDs (useful when grid content changes)
     */
    clearRegisteredIds() {
      this.registeredIds = new Set();
    },

    // ==================== Modal Methods ====================

    /**
     * Show the add subject modal
     */
    showAddSubjectModal() {
      if (this.selectedIds.size === 0) return;

      // Reset subjects list when opening modal
      this.selectedBulkSubjects = [];
      this.renderBulkSelectedSubjects();
      const addBtn = document.getElementById("bulkAddSubjectBtn");
      if (addBtn) addBtn.disabled = true;

      const modalEl = document.getElementById("bulkAddSubjectModal");
      if (!modalEl) return;

      const modal = new bootstrap.Modal(modalEl);
      modal.show();

      // Initialize autocomplete if not already done
      if (!this.bulkSubjectAutocomplete) {
        const inputEl = document.getElementById("bulkSubjectSearchInput");
        if (!inputEl) return;

        this.bulkSubjectAutocomplete = new autoComplete({
          selector: "#bulkSubjectSearchInput",
          placeHolder: "Search by name or enter Wikidata ID (e.g., Q123456)...",
          data: {
            src: async (query) => {
              try {
                const source = await fetch(
                  `/api/v1/subjects/autocomplete/?q=${query}`,
                );
                if (!source.ok) {
                  window.showError(
                    "Failed to search subjects. Please try again.",
                  );
                  return [];
                }
                return await source.json();
              } catch (error) {
                window.showError(
                  "Unable to connect to subject search. Check your connection.",
                );
                return [];
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

        // Set up Wikidata ID button handler
        const wikidataBtn = document.getElementById("bulkAddWikidataBtn");
        if (wikidataBtn) {
          wikidataBtn.addEventListener("click", () => {
            this.addWikidataId(inputEl.value.trim());
          });
        }

        inputEl.addEventListener("keydown", (e) => {
          if (e.key === "Enter") {
            const value = inputEl.value.trim();
            if (value.match(/^Q\d+$/i)) {
              e.preventDefault();
              e.stopPropagation();
              this.addWikidataId(value);
            }
          }
        });
      }

      // Set up the Add button click handler
      const addSubjectBtn = document.getElementById("bulkAddSubjectBtn");
      if (addSubjectBtn && !addSubjectBtn._hasClickHandler) {
        addSubjectBtn.addEventListener("click", () => this.bulkAddSubject());
        addSubjectBtn._hasClickHandler = true;
      }
    },

    /**
     * Add a Wikidata ID directly to the selected subjects list
     */
    async addWikidataId(wikidataId) {
      wikidataId = wikidataId.toUpperCase();

      if (!wikidataId.match(/^Q\d+$/)) {
        this.showAlert(
          "danger",
          "Invalid Wikidata ID format. Must be Q followed by numbers.",
        );
        return;
      }

      if (this.selectedBulkSubjects.some((s) => s.wikidata_id === wikidataId)) {
        this.showAlert("info", `${wikidataId} is already in the list.`);
        return;
      }

      const searchInput = document.getElementById("bulkSubjectSearchInput");
      if (searchInput) searchInput.value = "";

      // Add loading placeholder
      const loadingId = `loading-${wikidataId}`;
      this.selectedBulkSubjects.push({
        id: loadingId,
        title: null,
        wikidata_id: wikidataId,
        loading: true,
      });
      this.renderBulkSelectedSubjects();

      try {
        const response = await fetch(
          `/api/v1/subjects/wikidata-lookup/?id=${wikidataId}`,
        );
        const data = await response.json();

        this.selectedBulkSubjects = this.selectedBulkSubjects.filter(
          (s) => s.id !== loadingId,
        );

        if (data.success && data.subject) {
          this.selectedBulkSubjects.push({
            id: data.subject.id,
            title: data.subject.title,
            description: data.subject.description,
            wikidata_id: data.subject.wikidata_id,
          });
          this.renderBulkSelectedSubjects();
          document.getElementById("bulkAddSubjectBtn").disabled = false;
        } else {
          this.renderBulkSelectedSubjects();
          this.showAlert(
            "danger",
            data.error || "Failed to look up Wikidata item.",
          );
        }
      } catch (error) {
        this.selectedBulkSubjects = this.selectedBulkSubjects.filter(
          (s) => s.id !== loadingId,
        );
        this.renderBulkSelectedSubjects();
        this.showAlert(
          "danger",
          `Error looking up Wikidata item: ${error.message}`,
        );
      }
    },

    /**
     * Render the list of selected subjects in the modal
     */
    renderBulkSelectedSubjects() {
      const container = document.getElementById("bulkSelectedSubjectsList");
      const emptyMessage = document.getElementById("emptySubjectsMessage");
      if (!container) return;

      if (this.selectedBulkSubjects.length === 0) {
        container.innerHTML = "";
        if (emptyMessage) emptyMessage.style.display = "block";
      } else {
        if (emptyMessage) emptyMessage.style.display = "none";
        container.innerHTML = this.selectedBulkSubjects
          .map((subject) => {
            const subjectKey = subject.wikidata_id || subject.id;
            if (subject.loading) {
              return `<span class="badge bg-secondary" data-subject-id="${subjectKey}">
                <span class="spinner-border spinner-border-sm me-1" role="status"></span>
                ${this.escapeHtml(subject.wikidata_id)}
              </span>`;
            }
            return `<span class="badge bg-primary" data-subject-id="${subjectKey}">
              ${this.escapeHtml(subject.title)}
              <button type="button" class="btn-close btn-close-white ms-1" style="font-size: 0.65rem;" data-subject-remove="${subjectKey}"></button>
            </span>`;
          })
          .join("");

        container.querySelectorAll("[data-subject-remove]").forEach((btn) => {
          btn.addEventListener("click", (e) => {
            this.removeBulkSubject(e.target.dataset.subjectRemove);
          });
        });
      }
    },

    /**
     * Remove a subject from the bulk selection list
     */
    removeBulkSubject(subjectKey) {
      this.selectedBulkSubjects = this.selectedBulkSubjects.filter((s) => {
        const key = s.wikidata_id || s.id;
        return key.toString() !== subjectKey.toString();
      });
      this.renderBulkSelectedSubjects();
      if (this.selectedBulkSubjects.length === 0) {
        document.getElementById("bulkAddSubjectBtn").disabled = true;
      }
    },

    /**
     * Perform bulk add subject operation
     */
    async bulkAddSubject() {
      if (this.selectedBulkSubjects.length === 0 || this.selectedIds.size === 0)
        return;

      const btn = document.getElementById("bulkAddSubjectBtn");
      btn.disabled = true;
      btn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-2"></span>Adding...';

      try {
        const results = [];
        for (const subject of this.selectedBulkSubjects) {
          const response = await fetch("/api/v1/subjects/bulk-add/", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": this.getCsrfToken(),
            },
            body: JSON.stringify({
              image_ids: this.getSelectedIds(),
              wikidata_id: subject.wikidata_id,
            }),
          });
          const result = await response.json();
          results.push({ subject, result });
        }

        const modal = bootstrap.Modal.getInstance(
          document.getElementById("bulkAddSubjectModal"),
        );
        if (modal) modal.hide();

        let successCount = results.filter((r) => r.result.success).length;
        if (successCount > 0) {
          const subjectNames = this.selectedBulkSubjects
            .map((s) => s.title)
            .join(", ");
          this.showAlert(
            "success",
            `Added ${successCount} subject(s) (${subjectNames}) to ${this.selectedIds.size} images.`,
          );
        } else {
          this.showAlert("danger", "Failed to add subjects. Please try again.");
        }

        this.toggleSelectionMode();
        this.selectedBulkSubjects = [];
        this.renderBulkSelectedSubjects();
      } catch (error) {
        console.error("Error adding subject:", error);
        this.showAlert("danger", "An error occurred while adding the subject.");
      } finally {
        btn.disabled = false;
        btn.innerHTML = "Add All Subjects";
      }
    },

    /**
     * Show the add to album modal
     */
    showAddToAlbumModal() {
      if (this.selectedIds.size === 0) return;

      this.selectedAlbum = null;
      this.albumMode = "existing";
      this.resetAlbumModal();
      this.loadUserAlbums();

      const countEl = document.getElementById("bulkAlbumSelectedCount");
      if (countEl) countEl.textContent = this.selectedIds.size;

      const modalEl = document.getElementById("bulkAddToAlbumModal");
      if (!modalEl) return;

      const modal = new bootstrap.Modal(modalEl);
      modal.show();

      this.setupAlbumModeToggle();

      // Set up the Add button click handler
      const addToAlbumBtn = document.getElementById("bulkAddToAlbumBtn");
      if (addToAlbumBtn && !addToAlbumBtn._hasClickHandler) {
        addToAlbumBtn.addEventListener("click", () => this.bulkAddToAlbum());
        addToAlbumBtn._hasClickHandler = true;
      }
    },

    /**
     * Reset album modal to initial state
     */
    resetAlbumModal() {
      const selectText = document.getElementById("bulkAlbumSelectText");
      if (selectText) selectText.textContent = "Choose an album...";

      const titleInput = document.getElementById("bulkNewAlbumTitle");
      if (titleInput) titleInput.value = "";

      const descInput = document.getElementById("bulkNewAlbumDescription");
      if (descInput) descInput.value = "";

      const publicCheck = document.getElementById("bulkNewAlbumPublic");
      if (publicCheck) publicCheck.checked = false;

      const existingRadio = document.getElementById("albumModeExisting");
      if (existingRadio) existingRadio.checked = true;

      const existingSection = document.getElementById("existingAlbumSection");
      if (existingSection) existingSection.style.display = "block";

      const newSection = document.getElementById("newAlbumSection");
      if (newSection) newSection.style.display = "none";

      const noAlbumsMsg = document.getElementById("noAlbumsMessage");
      if (noAlbumsMsg) noAlbumsMsg.style.display = "none";

      this.updateAddToAlbumButton();
    },

    /**
     * Set up album mode toggle listeners
     */
    setupAlbumModeToggle() {
      const existingRadio = document.getElementById("albumModeExisting");
      const newRadio = document.getElementById("albumModeNew");
      const titleInput = document.getElementById("bulkNewAlbumTitle");

      if (existingRadio && !existingRadio._hasChangeHandler) {
        existingRadio.addEventListener("change", () => {
          if (existingRadio.checked) {
            this.albumMode = "existing";
            document.getElementById("existingAlbumSection").style.display =
              "block";
            document.getElementById("newAlbumSection").style.display = "none";
            this.updateAddToAlbumButton();
          }
        });
        existingRadio._hasChangeHandler = true;
      }

      if (newRadio && !newRadio._hasChangeHandler) {
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
        newRadio._hasChangeHandler = true;
      }

      if (titleInput && !titleInput._hasInputHandler) {
        titleInput.addEventListener("input", () =>
          this.updateAddToAlbumButton(),
        );
        titleInput._hasInputHandler = true;
      }
    },

    /**
     * Load user albums from API
     */
    async loadUserAlbums() {
      try {
        const response = await fetch(
          window.filterConfig?.urls?.userAlbumsApi || "/api/v1/albums/user/",
        );
        if (response.ok) {
          const data = await response.json();
          this.userAlbums = data.albums || [];
          this.renderAlbumDropdown();
        } else {
          window.showError("Failed to load your albums. Please try again.");
        }
      } catch (error) {
        console.error("Error loading albums:", error);
        window.showError("Unable to load albums. Check your connection.");
      }
    },

    /**
     * Render album dropdown list
     */
    renderAlbumDropdown() {
      const dropdown = document.getElementById("bulkAlbumDropdown");
      const noAlbumsMessage = document.getElementById("noAlbumsMessage");
      if (!dropdown) return;

      dropdown.innerHTML = "";

      if (this.userAlbums.length === 0) {
        dropdown.innerHTML =
          '<li><span class="dropdown-item-text text-muted">No albums found</span></li>';
        if (noAlbumsMessage) noAlbumsMessage.style.display = "block";
        return;
      }

      if (noAlbumsMessage) noAlbumsMessage.style.display = "none";

      this.userAlbums.forEach((album) => {
        const li = document.createElement("li");
        const escapedTitle = this.escapeHtml(album.title);
        li.innerHTML = `
          <button class="dropdown-item d-flex justify-content-between align-items-center" type="button" data-album-id="${album.id}" data-album-title="${escapedTitle}">
            <span>${escapedTitle}</span>
            ${album.public ? '<i class="fas fa-globe text-muted ms-2" title="Public album"></i>' : '<i class="fas fa-lock text-muted ms-2" title="Private album"></i>'}
          </button>
        `;
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
      if (this.selectedIds.size === 0) return;

      const btn = document.getElementById("bulkAddToAlbumBtn");
      btn.disabled = true;
      btn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-2"></span>Adding...';

      try {
        let response;
        let albumTitle;

        if (this.albumMode === "new") {
          const newAlbumTitle = document
            .getElementById("bulkNewAlbumTitle")
            .value.trim();
          if (!newAlbumTitle) throw new Error("Please enter an album title");

          response = await fetch(
            window.filterConfig?.urls?.bulkCreateAndAddToAlbum ||
              "/api/v1/albums/bulk-create-and-add/",
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
                image_ids: this.getSelectedIds(),
              }),
            },
          );
          albumTitle = newAlbumTitle;
        } else if (this.selectedAlbum) {
          response = await fetch(
            window.filterConfig?.urls?.bulkAddToAlbum ||
              "/api/v1/albums/bulk-add/",
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-CSRFToken": this.getCsrfToken(),
              },
              body: JSON.stringify({
                album_id: this.selectedAlbum.id,
                image_ids: this.getSelectedIds(),
              }),
            },
          );
          albumTitle = this.selectedAlbum.title;
        } else {
          throw new Error("Please select an album");
        }

        if (response.ok) {
          const result = await response.json();
          if (result.success) {
            this.showAlert("success", result.message);
            bootstrap.Modal.getInstance(
              document.getElementById("bulkAddToAlbumModal"),
            ).hide();
            this.selectedAlbum = null;
            this.resetAlbumModal();
            this.toggleSelectionMode();
          } else {
            throw new Error(result.error || "Failed to add images to album");
          }
        } else {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || `HTTP ${response.status}`);
        }
      } catch (error) {
        console.error("Error adding to album:", error);
        this.showAlert(
          "danger",
          `Error adding images to album: ${error.message}`,
        );
      } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-plus me-1"></i>Add to Album';
      }
    },

    // ==================== Bulk Status Methods (staff) ====================

    /**
     * Mark all selected images as aerial ("from above")
     */
    bulkMarkAerial() {
      this.confirmBulkMarkFlag(
        "/api/v1/bulk/from-above/",
        "from above",
        (count) => `Marked ${count} image(s) as from above.`,
        "aerial",
      );
    },

    /**
     * Mark all selected images as "will not georeference"
     */
    bulkMarkWillNotGeoref() {
      this.confirmBulkMarkFlag(
        "/api/v1/bulk/will-not-georef/",
        "will not georeference",
        (count) => `Marked ${count} image(s) as will not georeference.`,
        "will_not_georef",
      );
    },

    /**
     * Show the Bootstrap confirmation modal for a bulk status flag action.
     * The action is stored as pending and performed if the user confirms.
     */
    confirmBulkMarkFlag(url, actionLabel, successMessage, flag) {
      if (this.selectedIds.size === 0) return;

      this.pendingBulkAction = { url, actionLabel, successMessage, flag };

      const messageEl = document.getElementById("bulkConfirmMessage");
      if (messageEl) {
        messageEl.textContent = `Mark ${this.selectedIds.size} selected image(s) as ${actionLabel}?`;
      }

      const modalEl = document.getElementById("bulkConfirmModal");
      if (!modalEl) return;

      const modal = new bootstrap.Modal(modalEl);
      modal.show();

      const confirmBtn = document.getElementById("bulkConfirmBtn");
      if (confirmBtn && !confirmBtn._hasClickHandler) {
        confirmBtn.addEventListener("click", () => this.executeBulkMarkFlag());
        confirmBtn._hasClickHandler = true;
      }
    },

    /**
     * Perform the pending bulk status flag action after confirmation.
     * POSTs the selected image IDs, then updates the affected cards in place
     * (no reload) so the user keeps their scroll position.
     */
    async executeBulkMarkFlag() {
      const action = this.pendingBulkAction;
      if (!action || this.selectedIds.size === 0) return;

      const modal = bootstrap.Modal.getInstance(
        document.getElementById("bulkConfirmModal"),
      );
      if (modal) modal.hide();

      try {
        const response = await fetch(action.url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": this.getCsrfToken(),
          },
          body: JSON.stringify({ image_ids: this.getSelectedIds() }),
        });
        const result = await response.json();

        if (response.ok && result.success) {
          // Capture the selection before toggleSelectionMode() clears it.
          const ids = this.getSelectedIds();
          this.showAlert(
            "success",
            action.successMessage(result.updated_count),
          );
          this.applyBulkFlagToCards(ids, action.flag);
          this.toggleSelectionMode();
        } else {
          this.showAlert(
            "danger",
            result.error || "Failed to update images. Please try again.",
          );
        }
      } catch (error) {
        console.error("Error updating images:", error);
        this.showAlert(
          "danger",
          "An error occurred while updating the images.",
        );
      } finally {
        this.pendingBulkAction = null;
      }
    },

    /**
     * Update the just-marked cards in the DOM so the page doesn't reload.
     * `flag` is "will_not_georef" or "aerial".
     *
     * The reproduced badge/footer markup below mirrors
     * templates/images/partials/image_card.html — keep them in sync.
     */
    applyBulkFlagToCards(ids, flag) {
      ids.forEach((id) => {
        const card = this.$el.querySelector(
          `.image-card-wrapper[data-image-id="${id}"]`,
        );
        // Scoped to .image-card-wrapper because data-image-id also sits on the
        // per-card album dropdown button. Cards paginated away are a safe no-op.
        if (!card) return;
        if (flag === "will_not_georef") {
          this.markCardWillNotGeorefInPlace(card);
        } else if (flag === "aerial") {
          this.markCardAerialInPlace(card, id);
        }
      });
    },

    /**
     * Return the DocumentFragment holding a card's status badges — the content of
     * the `<template x-if="!selectionMode">` block in image_card.html. We mutate
     * this source (not the rendered clone) so the change survives Alpine re-cloning
     * the template whenever selection mode is toggled again. This runs while
     * selection mode is still on, so the badges are not currently rendered.
     * Returns null when the card has no badges (e.g. badges=False grids).
     */
    cardBadgeContent(card) {
      for (const tpl of card.querySelectorAll("template")) {
        if (tpl.content && tpl.content.querySelector(".badge")) {
          return tpl.content;
        }
      }
      return null;
    },

    /**
     * Mark a card "will not georeference" in place (mirrors image_card.html).
     */
    markCardWillNotGeorefInPlace(card) {
      const badges = this.cardBadgeContent(card);
      if (badges) {
        const topRight = badges.querySelector(
          ".badge.position-absolute.top-0.end-0.m-2",
        );
        if (topRight && /match/i.test(topRight.textContent)) {
          // Search/similarity card: keep the "% match" badge, set the top-left
          // icon-only indicator (image_card.html lines 53-64).
          const group = badges.querySelector(
            ".position-absolute.top-0.start-0.m-2.d-flex.gap-1",
          );
          if (group) {
            group.innerHTML =
              '<span class="badge bg-secondary" title="Will not georeference"><i class="fas fa-ban"></i></span>';
          }
        } else if (topRight) {
          // Normal card: top-right status badge -> grey "Skip" (lines 29-32).
          topRight.className =
            "badge bg-secondary position-absolute top-0 end-0 m-2";
          topRight.innerHTML = '<i class="fas fa-ban"></i> Skip';
        }
      }
      // Footer: remove the action button; the album dropdown (a <button>) stays
      // (lines 153-154).
      card.querySelector(".card-footer a.btn")?.remove();
    },

    /**
     * Mark a card as aerial ("from above") in place (mirrors image_card.html).
     */
    markCardAerialInPlace(card, id) {
      const badges = this.cardBadgeContent(card);
      if (badges) {
        const topRight = badges.querySelector(
          ".badge.position-absolute.top-0.end-0.m-2",
        );
        const isSimilarity = topRight && /match/i.test(topRight.textContent);
        // The template only renders the plane badge in the non-similarity branch.
        if (!isSimilarity && !badges.querySelector('[title="Aerial image"]')) {
          const wrap = badges.querySelector("div") || badges;
          let group = wrap.querySelector(
            ".position-absolute.top-0.start-0.m-2.d-flex.gap-1",
          );
          if (!group) {
            // Group is absent when the card had no difficulty and wasn't aerial
            // (lines 67-68); create it to match the template.
            group = document.createElement("div");
            group.className =
              "position-absolute top-0 start-0 m-2 d-flex gap-1";
            wrap.appendChild(group);
          }
          // Plane badge goes first, before any difficulty badge (lines 69-78).
          group.insertAdjacentHTML(
            "afterbegin",
            '<span class="badge bg-success" title="Aerial image"><i class="fas fa-plane"></i></span>',
          );
        }
      }
      // Footer: repoint only a pending "Georeference" button (btn-success) to the
      // aerial interface; View buttons (btn-primary/outline) are left alone (line 170).
      card
        .querySelector(".card-footer a.btn-success")
        ?.setAttribute("href", `/polygonal-georeference/${id}/`);
    },

    // ==================== Utility Methods ====================

    /**
     * Get CSRF token for API requests
     */
    getCsrfToken() {
      const input = document.querySelector("[name=csrfmiddlewaretoken]");
      if (input) return input.value;

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

    /**
     * Show alert toast notification
     * Delegates to global showAlert from notifications.js
     */
    showAlert(type, message) {
      window.showAlert(type, message);
    },
  };
}

// Make available globally for pages that don't use ES modules
if (typeof window !== "undefined") {
  window.imageGrid = imageGrid;
}
