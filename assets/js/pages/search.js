import autoComplete from "@tarekraafat/autocomplete.js";
import "../../styles/components/autocomplete.css";

// Import image grid component (includes bulk selection and modal functionality)
import { imageGrid } from "../components/image_grid.js";

// Add x-cloak style to prevent flash of unstyled content
const style = document.createElement("style");
style.textContent = "[x-cloak] { display: none !important; }";
document.head.appendChild(style);

// Store for current search state (used by searchGrid for load more)
window.searchState = {
  query: "",
  mode: "semantic", // "semantic", "text", or "reverse"
  params: new URLSearchParams(),
  uploadedImageFile: null,
  hasMore: false,
  offset: 0,
  limit: 20,
  totalCount: 0,
};

/**
 * Alpine.js component for search results grid with "Load More" functionality.
 * Extends the base imageGrid component.
 */
window.searchGrid = function () {
  const base = imageGrid();

  return {
    ...base,

    // Re-declare getter since spread doesn't preserve getters
    get selectedCount() {
      return this.selectedIds.size;
    },

    // Load More specific state - must be reactive Alpine state
    hasMore: false,
    loading: false, // Controls spinner visibility (debounced)

    // Pending fetch promise from prefetch (mousedown)
    _pendingFetch: null,
    // Timer for debounced loading indicator
    _loadingTimer: null,
    // Flag to prevent concurrent requests (separate from loading indicator)
    _isLoadingMore: false,

    init() {
      base.init.call(this);

      // Listen for search state updates from displayHtmlResults
      document.addEventListener("searchStateUpdated", (e) => {
        this.hasMore = e.detail.hasMore;
        // Clear any pending fetch when new search results arrive
        this._pendingFetch = null;
      });
    },

    /**
     * Build fetch request for loading more results.
     * Used by both prefetchMore and loadMore.
     */
    _buildLoadMoreFetch() {
      const state = window.searchState;
      const nextPage = Math.floor(state.offset / state.limit) + 1;

      if (state.mode === "reverse" && state.uploadedImageFile) {
        // Reverse image search uses POST with FormData
        const formData = new FormData();
        formData.append("image", state.uploadedImageFile);
        formData.append("page", nextPage);
        formData.append("pagelimit", state.limit);

        // Copy filter params to formData
        for (const [key, value] of state.params.entries()) {
          if (
            !["q", "mode", "page", "format", "pagelimit"].includes(key) &&
            value
          ) {
            formData.append(key, value);
          }
        }

        return fetch("/api/v1/search/reverse/?format=html", {
          method: "POST",
          body: formData,
          headers: {
            "X-CSRFToken": getCsrfToken(),
          },
        });
      } else {
        // Semantic and text search use GET
        const apiEndpoint =
          state.mode === "semantic"
            ? "/api/v1/search/"
            : "/api/v1/search/text/";
        const params = new URLSearchParams(state.params);
        params.set("page", nextPage);
        params.set("format", "html");

        return fetch(`${apiEndpoint}?${params.toString()}`);
      }
    },

    /**
     * Prefetch next page on mousedown for faster perceived loading.
     * Called via @mousedown on the Load More button.
     */
    prefetchMore() {
      if (this._isLoadingMore || !this.hasMore || this._pendingFetch) return;
      this._pendingFetch = this._buildLoadMoreFetch();
    },

    /**
     * Load more search results via AJAX.
     * Uses prefetched response if available.
     */
    async loadMore() {
      if (this._isLoadingMore || !this.hasMore) return;
      this._isLoadingMore = true;

      // Debounce the loading indicator - only show after 200ms
      this._loadingTimer = setTimeout(() => {
        this.loading = true;
      }, 200);

      const state = window.searchState;

      try {
        let response;

        if (this._pendingFetch) {
          // Use the prefetched request
          response = await this._pendingFetch;
          this._pendingFetch = null;
        } else {
          // No prefetch, make the request now
          response = await this._buildLoadMoreFetch();
        }

        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.error || "Failed to load more results");
        }

        const html = await response.text();

        if (html.trim()) {
          const parser = new DOMParser();
          const doc = parser.parseFromString(html, "text/html");
          const newItems = doc.querySelectorAll(".image-card-wrapper");
          const metaEl = doc.querySelector("template[data-has-more]");

          if (newItems.length > 0) {
            // Remove the template element from HTML before inserting
            const cleanHtml = html.replace(
              /<template[^>]*data-has-more[^>]*>.*?<\/template>/gi,
              "",
            );

            // Append to the grid
            const gridEl = document.querySelector("#searchResults .row");
            if (gridEl) {
              gridEl.insertAdjacentHTML("beforeend", cleanHtml);

              // Re-initialize Alpine on new content
              if (window.Alpine) {
                // Only init the newly added elements
                newItems.forEach((item) => {
                  const addedItem = gridEl.querySelector(
                    `[data-image-id="${item.dataset.imageId}"]`,
                  );
                  if (addedItem) {
                    window.Alpine.initTree(addedItem);
                  }
                });
              }
            }

            // Update state
            state.offset += newItems.length;

            if (metaEl) {
              this.hasMore = metaEl.dataset.hasMore === "true";
            } else {
              this.hasMore = newItems.length >= state.limit;
            }
          } else {
            this.hasMore = false;
          }
        } else {
          this.hasMore = false;
        }
      } catch (error) {
        console.error("Error loading more results:", error);
        this._pendingFetch = null;
        // Don't set hasMore to false on error - let user retry
      } finally {
        clearTimeout(this._loadingTimer);
        this.loading = false;
        this._isLoadingMore = false;
      }
    },
  };
};

// Register the search grid component with Alpine
window.Alpine.data("searchGrid", window.searchGrid);

// Also register the base imageGrid for backwards compatibility
window.Alpine.data("imageGrid", imageGrid);

// Helper function to get CSRF token (defined here for use by searchGrid)
function getCsrfToken() {
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
}

document.addEventListener("DOMContentLoaded", async function () {
  // Fetch all subjects from the API
  let allSubjects = [];
  let subjectMap = new Map();

  try {
    const response = await fetch("/api/v1/subjects/all/");
    if (response.ok) {
      allSubjects = await response.json();
      subjectMap = new Map(allSubjects.map((s) => [s.id.toString(), s.title]));
    } else {
      console.error("Failed to fetch subjects:", response.statusText);
    }
  } catch (error) {
    console.error("Error fetching subjects:", error);
  }

  let selectedSubjects = [];

  const searchForm = document.getElementById("searchForm");
  const searchQuery = document.getElementById("searchQuery");
  const pagelimitSelect = document.getElementById("pagelimitSelect");
  const startYear = document.getElementById("startYear");
  const endYear = document.getElementById("endYear");
  const searchResults = document.getElementById("searchResults");
  const semanticMode = document.getElementById("semanticMode");
  const textMode = document.getElementById("textMode");
  const reverseMode = document.getElementById("reverseMode");
  const semanticDescription = document.getElementById("semanticDescription");
  const textDescription = document.getElementById("textDescription");
  const reverseDescription = document.getElementById("reverseDescription");
  const textSearchContainer = document.getElementById("textSearchContainer");
  const reverseSearchContainer = document.getElementById(
    "reverseSearchContainer",
  );
  const imageDropZone = document.getElementById("imageDropZone");
  const imageFileInput = document.getElementById("imageFileInput");
  const selectFileBtn = document.getElementById("selectFileBtn");
  const dropZoneContent = document.getElementById("dropZoneContent");
  const imagePreviewContainer = document.getElementById(
    "imagePreviewContainer",
  );
  const imagePreview = document.getElementById("imagePreview");
  const imageActionsContainer = document.getElementById(
    "imageActionsContainer",
  );
  const changeImageBtn = document.getElementById("changeImageBtn");
  const subjectSearchWrapper = document.getElementById(
    "subject-search-wrapper",
  );
  const noSubjectsRadio = document.getElementById("noSubjects");

  let uploadedImageFile = null;

  function renderSelectedSubjects() {
    const container = document.getElementById("selected-subjects");
    container.innerHTML = selectedSubjects
      .map(
        (subject) => `
            <span class="badge bg-primary d-flex align-items-center">
                ${escapeHtml(subject.title)}
                <button type="button" class="btn-close btn-close-white ms-2" aria-label="Remove" data-id="${subject.id}"></button>
            </span>
        `,
      )
      .join("");
  }

  function initializeFromURL() {
    const urlParams = new URLSearchParams(window.location.search);

    if (urlParams.has("mode") && urlParams.get("mode") === "text") {
      textMode.checked = true;
      textMode.dispatchEvent(new Event("change"));
    } else if (urlParams.has("mode") && urlParams.get("mode") === "reverse") {
      reverseMode.checked = true;
      reverseMode.dispatchEvent(new Event("change"));
    } else {
      semanticMode.checked = true;
      semanticMode.dispatchEvent(new Event("change"));
    }

    if (urlParams.has("q")) {
      searchQuery.value = urlParams.get("q");
    }
    if (urlParams.has("pagelimit")) {
      pagelimitSelect.value = urlParams.get("pagelimit");
    }
    if (urlParams.has("start_year")) {
      startYear.value = urlParams.get("start_year");
    }
    if (urlParams.has("end_year")) {
      endYear.value = urlParams.get("end_year");
    }
    if (urlParams.get("georeferenced_only") === "true") {
      document.getElementById("georeferencedOnly").checked = true;
    } else if (urlParams.get("non_georeferenced_only") === "true") {
      document.getElementById("notGeoreferencedOnly").checked = true;
    } else {
      document.getElementById("allImages").checked = true;
    }

    // Handle subject params
    if (urlParams.get("no_subjects") === "true") {
      document.getElementById("noSubjects").checked = true;
    } else if (urlParams.has("with_subjects")) {
      document.getElementById("withSubjects").checked = true;
      const ids = urlParams.get("with_subjects").split(",");
      selectedSubjects = ids
        .map((id) => ({ id: id, title: subjectMap.get(id) || `ID: ${id}` }))
        .filter((s) => s.title);
    } else if (urlParams.has("without_subjects")) {
      document.getElementById("withoutSubjects").checked = true;
      const ids = urlParams.get("without_subjects").split(",");
      selectedSubjects = ids
        .map((id) => ({ id: id, title: subjectMap.get(id) || `ID: ${id}` }))
        .filter((s) => s.title);
    }
    renderSelectedSubjects();
    // Trigger change to hide/show subject input
    document
      .querySelector('input[name="subjectOptions"]:checked')
      .dispatchEvent(new Event("change"));

    const subjectOption = document.querySelector(
      'input[name="subjectOptions"]:checked',
    ).value;
    const hasSubjectFilter =
      subjectOption === "none" || selectedSubjects.length > 0;

    if (urlParams.has("q") || hasSubjectFilter) {
      const hasAdvanced =
        urlParams.has("start_year") ||
        urlParams.has("end_year") ||
        urlParams.has("georeferenced_only") ||
        selectedSubjects.length > 0 ||
        urlParams.has("no_subjects");
      if (hasAdvanced) {
        const advancedOptions = document.getElementById("advancedOptions");
        new bootstrap.Collapse(advancedOptions, { toggle: false }).show();
      }
      performSearch();
    }
  }

  searchForm.addEventListener("submit", function (e) {
    e.preventDefault();
    performSearch();
  });

  document
    .getElementById("selected-subjects")
    .addEventListener("click", function (e) {
      if (e.target.matches("button.btn-close")) {
        const subjectId = e.target.dataset.id;
        selectedSubjects = selectedSubjects.filter(
          (s) => s.id.toString() !== subjectId,
        );
        renderSelectedSubjects();
      }
    });

  document.querySelectorAll('input[name="subjectOptions"]').forEach((radio) => {
    radio.addEventListener("change", function () {
      subjectSearchWrapper.style.display =
        this.value === "none" ? "none" : "block";
    });
  });

  // Handle search mode toggle
  semanticMode.addEventListener("change", function () {
    if (this.checked) {
      semanticDescription.style.display = "block";
      textDescription.style.display = "none";
      reverseDescription.style.display = "none";
      textSearchContainer.style.display = "flex";
      reverseSearchContainer.style.display = "none";
      searchQuery.placeholder = "Describe what you're looking for...";
    }
  });

  textMode.addEventListener("change", function () {
    if (this.checked) {
      semanticDescription.style.display = "none";
      textDescription.style.display = "block";
      reverseDescription.style.display = "none";
      textSearchContainer.style.display = "flex";
      reverseSearchContainer.style.display = "none";
      searchQuery.placeholder = "Search for keywords...";
    }
  });

  reverseMode.addEventListener("change", function () {
    if (this.checked) {
      semanticDescription.style.display = "none";
      textDescription.style.display = "none";
      reverseDescription.style.display = "block";
      textSearchContainer.style.display = "none";
      reverseSearchContainer.style.display = "block";
      searchQuery.placeholder = "Upload an image to search...";
    }
  });

  // Reverse image search functionality
  function handleImageFile(file) {
    if (!file || !file.type.startsWith("image/")) {
      alert("Please select a valid image file");
      return;
    }

    uploadedImageFile = file;
    const reader = new FileReader();
    reader.onload = function (e) {
      imagePreview.src = e.target.result;
      dropZoneContent.style.display = "none";
      imagePreviewContainer.style.display = "block";
      if (imageActionsContainer) {
        imageActionsContainer.style.display = "block";
      }
    };
    reader.readAsDataURL(file);
  }

  // Click to select file
  if (selectFileBtn) {
    selectFileBtn.addEventListener("click", function (e) {
      e.preventDefault();
      imageFileInput.click();
    });
  }

  // Drop zone click
  if (imageDropZone) {
    imageDropZone.addEventListener("click", function (e) {
      // Allow clicking anywhere in the drop zone to trigger file selection
      imageFileInput.click();
    });
  }

  // File input change
  if (imageFileInput) {
    imageFileInput.addEventListener("change", function (e) {
      if (e.target.files && e.target.files[0]) {
        handleImageFile(e.target.files[0]);
      }
    });
  }

  // Drag and drop
  if (imageDropZone) {
    imageDropZone.addEventListener("dragover", function (e) {
      e.preventDefault();
      e.stopPropagation();
      this.classList.add("border-primary", "bg-primary-subtle");
    });

    imageDropZone.addEventListener("dragleave", function (e) {
      e.preventDefault();
      e.stopPropagation();
      this.classList.remove("border-primary", "bg-primary-subtle");
    });

    imageDropZone.addEventListener("drop", function (e) {
      e.preventDefault();
      e.stopPropagation();
      this.classList.remove("border-primary", "bg-primary-subtle");

      const files = e.dataTransfer.files;
      if (files && files[0]) {
        handleImageFile(files[0]);
      }
    });
  }

  // Paste image
  document.addEventListener("paste", function (e) {
    if (reverseMode && reverseMode.checked) {
      const items = e.clipboardData.items;
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf("image") !== -1) {
          const blob = items[i].getAsFile();
          handleImageFile(blob);
          e.preventDefault();
          break;
        }
      }
    }
  });

  // Change image button
  if (changeImageBtn) {
    changeImageBtn.addEventListener("click", function (e) {
      e.preventDefault();
      uploadedImageFile = null;
      imagePreview.src = "";
      dropZoneContent.style.display = "block";
      imagePreviewContainer.style.display = "none";
      if (imageActionsContainer) {
        imageActionsContainer.style.display = "none";
      }
      imageFileInput.value = "";
    });
  }

  function performReverseImageSearch() {
    if (!uploadedImageFile) {
      alert("Please upload an image first");
      return;
    }

    const limit = parseInt(pagelimitSelect.value, 10) || 20;

    const apiEndpoint = "/api/v1/search/reverse/?format=html";
    const formData = new FormData();
    formData.append("image", uploadedImageFile);
    formData.append("page", 1);
    formData.append("pagelimit", limit);

    // Build params for state storage
    const stateParams = new URLSearchParams();
    stateParams.set("pagelimit", limit);

    if (startYear.value) {
      formData.append("start_year", startYear.value);
      stateParams.set("start_year", startYear.value);
    }
    if (endYear.value) {
      formData.append("end_year", endYear.value);
      stateParams.set("end_year", endYear.value);
    }

    const georeferencedOption = document.querySelector(
      'input[name="georeferencedOptions"]:checked',
    ).value;
    if (georeferencedOption === "georeferenced") {
      formData.append("georeferenced_only", "true");
      stateParams.set("georeferenced_only", "true");
    } else if (georeferencedOption === "not_georeferenced") {
      formData.append("non_georeferenced_only", "true");
      stateParams.set("non_georeferenced_only", "true");
    }

    // Add subject params
    const subjectOption = document.querySelector(
      'input[name="subjectOptions"]:checked',
    ).value;
    const subjectIds = selectedSubjects.map((s) => s.id).join(",");

    if (subjectOption === "none") {
      formData.append("no_subjects", "true");
      stateParams.set("no_subjects", "true");
    } else if (subjectIds) {
      if (subjectOption === "with") {
        formData.append("with_subjects", subjectIds);
        stateParams.set("with_subjects", subjectIds);
      } else if (subjectOption === "without") {
        formData.append("without_subjects", subjectIds);
        stateParams.set("without_subjects", subjectIds);
      }
    }

    // Update search state for load more
    window.searchState.mode = "reverse";
    window.searchState.query = "";
    window.searchState.params = stateParams;
    window.searchState.uploadedImageFile = uploadedImageFile;
    window.searchState.limit = limit;
    window.searchState.offset = 0;
    window.searchState.hasMore = false;

    searchResults.innerHTML = renderLoadingPlaceholder();

    fetch(apiEndpoint, {
      method: "POST",
      body: formData,
      headers: {
        "X-CSRFToken": getCsrfToken(),
      },
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().then((data) => {
            throw new Error(data.error || "Search failed");
          });
        }
        return response.text();
      })
      .then((html) => {
        displayHtmlResults(html, null, "reverse image search");
      })
      .catch((error) => {
        displayError("Search failed: " + error.message);
      });
  }

  function renderLoadingPlaceholder() {
    return `
      <div class="text-center py-5">
        <div class="spinner-border text-primary" role="status">
          <span class="visually-hidden">Searching...</span>
        </div>
        <p class="mt-2 text-muted">Searching images...</p>
      </div>
    `;
  }

  function performSearch() {
    const query = searchQuery.value.trim();
    const subjectOption = document.querySelector(
      'input[name="subjectOptions"]:checked',
    ).value;
    const hasSubjectFilter =
      subjectOption === "none" || selectedSubjects.length > 0;

    // Handle reverse image search differently
    if (reverseMode && reverseMode.checked) {
      if (!uploadedImageFile) {
        alert("Please upload an image first");
        return;
      }
      performReverseImageSearch();
      return;
    }

    if (!query && !hasSubjectFilter) {
      return; // Do not search if there is no query and no subject filter
    }

    let searchMode = semanticMode.checked ? "semantic" : "text";
    // If query is empty, we must use the text search endpoint, as semantic search requires a query.
    if (!query) {
      searchMode = "text";
    }

    const limit = parseInt(pagelimitSelect.value, 10) || 20;

    const apiEndpoint =
      searchMode === "semantic" ? "/api/v1/search/" : "/api/v1/search/text/";

    const params = new URLSearchParams();
    params.set("q", query);
    params.set("mode", searchMode);
    params.set("page", 1);
    params.set("pagelimit", limit);
    params.set("format", "html"); // Request HTML format

    if (startYear.value) {
      params.set("start_year", startYear.value);
    }
    if (endYear.value) {
      params.set("end_year", endYear.value);
    }

    const georeferencedOption = document.querySelector(
      'input[name="georeferencedOptions"]:checked',
    ).value;
    if (georeferencedOption === "georeferenced") {
      params.set("georeferenced_only", "true");
    } else if (georeferencedOption === "not_georeferenced") {
      params.set("non_georeferenced_only", "true");
    }

    // Add subject params
    const subjectIds = selectedSubjects.map((s) => s.id).join(",");

    if (subjectOption === "none") {
      params.set("no_subjects", "true");
    } else if (subjectIds) {
      if (subjectOption === "with") {
        params.set("with_subjects", subjectIds);
      } else if (subjectOption === "without") {
        params.set("without_subjects", subjectIds);
      }
    }

    // Update search state for load more
    window.searchState.mode = searchMode;
    window.searchState.query = query;
    window.searchState.params = new URLSearchParams(params);
    window.searchState.uploadedImageFile = null;
    window.searchState.limit = limit;
    window.searchState.offset = 0;
    window.searchState.hasMore = false;

    // Update URL without the format param (for cleaner URLs)
    const urlParams = new URLSearchParams(params);
    urlParams.delete("format");
    urlParams.delete("page");
    history.pushState(
      null,
      "",
      `${window.location.pathname}?${urlParams.toString()}`,
    );

    searchResults.innerHTML = renderLoadingPlaceholder();

    const searchModeLabel =
      searchMode === "semantic" ? "semantic search" : "text search";

    fetch(`${apiEndpoint}?${params.toString()}`)
      .then((response) => {
        if (!response.ok) {
          return response.json().then((data) => {
            throw new Error(data.error || "Search failed");
          });
        }
        return response.text();
      })
      .then((html) => {
        displayHtmlResults(html, query, searchModeLabel);
      })
      .catch((error) => {
        displayError("Search failed: " + error.message);
      });
  }

  function displayHtmlResults(html, query, searchModeLabel) {
    // Set when a region is selected in the navbar; the search endpoints scope
    // results to it server-side via the region cookie.
    const regionName = window.filterConfig?.regionName;

    // Parse the HTML to extract metadata from the template element
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, "text/html");
    const metaEl = doc.querySelector("template[data-has-more]");
    const imageCards = doc.querySelectorAll(".image-card-wrapper");

    // Check if there are no results
    if (imageCards.length === 0) {
      let message = query
        ? `No results found for "<strong>${escapeHtml(query)}</strong>".`
        : "No results found for the selected filters.";
      const regionHint = regionName
        ? ` You're searching within <strong>${escapeHtml(regionName)}</strong> \u2014 switch to Global in the region selector to search everywhere.`
        : "";
      searchResults.innerHTML = `
        <div class="alert alert-info">
          <i class="fas fa-info-circle me-2"></i>
          ${message}
          Try a different search term or filter.${regionHint}
        </div>
      `;
      // Hide bulk actions when no results
      const bulkActionsContainer = document.getElementById(
        "bulkActionsContainer",
      );
      if (bulkActionsContainer) {
        bulkActionsContainer.style.display = "none";
      }
      // Reset search state
      window.searchState.hasMore = false;
      window.searchState.offset = 0;
      window.searchState.totalCount = 0;
      // Dispatch event to notify Alpine component
      document.dispatchEvent(
        new CustomEvent("searchStateUpdated", { detail: { hasMore: false } }),
      );
      return;
    }

    // Show bulk actions when there are results
    const bulkActionsContainer = document.getElementById(
      "bulkActionsContainer",
    );
    if (bulkActionsContainer) {
      bulkActionsContainer.style.display = "block";
    }

    // Extract pagination data from the template element
    const hasMore = metaEl ? metaEl.dataset.hasMore === "true" : false;
    const totalCount = metaEl ? parseInt(metaEl.dataset.totalCount, 10) : 0;
    const limit = window.searchState.limit || 20;

    // Update search state for load more functionality
    window.searchState.hasMore = hasMore;
    window.searchState.offset = imageCards.length;
    window.searchState.totalCount = totalCount;

    // Dispatch event to notify Alpine component of state change
    document.dispatchEvent(
      new CustomEvent("searchStateUpdated", { detail: { hasMore } }),
    );

    // Build filter summary
    let filterSummary = "";
    const startYearVal = startYear.value;
    const endYearVal = endYear.value;
    const georeferencedOption = document.querySelector(
      'input[name="georeferencedOptions"]:checked',
    ).value;

    if (startYearVal || endYearVal || georeferencedOption !== "all") {
      let filters = [];
      if (startYearVal && endYearVal) {
        filters.push(`${startYearVal}-${endYearVal}`);
      } else if (startYearVal) {
        filters.push(`from ${startYearVal}`);
      } else if (endYearVal) {
        filters.push(`until ${endYearVal}`);
      }
      if (georeferencedOption === "georeferenced") {
        filters.push("georeferenced only");
      } else if (georeferencedOption === "not_georeferenced") {
        filters.push("not georeferenced only");
      }
      filterSummary = ` (filtered: ${filters.join(", ")})`;
    }

    const forQuery = query
      ? ` for "<strong>${escapeHtml(query)}</strong>"`
      : "";

    // For semantic/reverse image search, don't show count (all images are returned ranked by similarity)
    const isSemanticOrReverse =
      searchModeLabel === "semantic search" ||
      searchModeLabel === "reverse image search";
    const inRegion = regionName ? ` in ${escapeHtml(regionName)}` : "";
    const statsMessage = isSemanticOrReverse
      ? `Showing results${forQuery}${inRegion} using ${searchModeLabel}${filterSummary}`
      : `Found ${totalCount} results${forQuery}${inRegion} using ${searchModeLabel}${filterSummary}`;

    // Clear previously registered IDs since we're loading new results
    if (window.imageGridInstance) {
      window.imageGridInstance.clearRegisteredIds();
    }

    // Remove the template element from the HTML before inserting
    const cleanHtml = html.replace(
      /<template[^>]*data-has-more[^>]*>.*?<\/template>/gi,
      "",
    );

    // Build the full results HTML with Load More button instead of pagination
    let resultsHtml = `
      <div class="search-stats mb-3">
        ${statsMessage}
      </div>
      <div class="row">
        ${cleanHtml}
      </div>
    `;

    searchResults.innerHTML = resultsHtml;

    // Re-initialize Alpine on the new content
    if (window.Alpine) {
      window.Alpine.initTree(searchResults);
    }
  }

  function displayError(error) {
    searchResults.innerHTML = `
            <div class="alert alert-danger">
                <i class="fas fa-exclamation-triangle me-2"></i>
                <strong>Search Error:</strong> ${escapeHtml(error)}
            </div>
        `;
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // Init Autocomplete
  const subjectAutocomplete = new autoComplete({
    selector: "#subjectSearchInput",
    placeHolder: "Search for a subject by name...",
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
    // The server does the (fuzzy) filtering and ranking; never drop or
    // reorder results client-side. <mark> literal substring hits;
    // typo-only hits render as plain text.
    searchEngine: (query, record) => {
      const idx = record.toLowerCase().indexOf(query.toLowerCase());
      if (idx === -1) return record;
      return (
        record.slice(0, idx) +
        "<mark>" +
        record.slice(idx, idx + query.length) +
        "</mark>" +
        record.slice(idx + query.length)
      );
    },
    events: {
      input: {
        selection: (event) => {
          const selection = event.detail.selection.value;
          if (!selectedSubjects.some((s) => s.id === selection.id)) {
            selectedSubjects.push(selection);
            renderSelectedSubjects();
          }
          subjectAutocomplete.input.value = "";
        },
      },
    },
  });

  initializeFromURL();
});
