/**
 * Similar Images page JavaScript
 *
 * Extends the image grid component with "Load More" infinite scroll functionality.
 */

import { imageGrid } from "../components/image_grid.js";

// Add x-cloak style to prevent flash of unstyled content
document.addEventListener("DOMContentLoaded", function () {
  const style = document.createElement("style");
  style.textContent = "[x-cloak] { display: none !important; }";
  document.head.appendChild(style);
});

/**
 * Alpine.js component for similar images grid with "Load More" functionality.
 *
 * Extends the base imageGrid component with:
 * - hasMore: Whether there are more images to load
 * - loading: Whether a load operation is in progress
 * - offset: Current offset for pagination
 * - loadMore(): Function to load the next batch of images
 */
window.similarImagesGrid = function () {
  // Get base imageGrid functionality
  const base = imageGrid();

  // Get configuration from window.filterConfig
  const config = window.filterConfig?.similarImages || {};
  const perPage = config.perPage || 24;
  const initialHasMore = config.hasMore ?? true;

  return {
    // Include all base imageGrid properties and methods
    ...base,

    // Re-declare getter since spread doesn't preserve getters
    get selectedCount() {
      return this.selectedIds.size;
    },

    // Load More specific state
    hasMore: initialHasMore,
    loading: false,
    offset: perPage, // Start at perPage since first batch is already loaded

    /**
     * Initialize the component
     */
    init() {
      // Call base init
      base.init.call(this);
    },

    /**
     * Load more similar images via AJAX
     */
    async loadMore() {
      if (this.loading || !this.hasMore) return;

      this.loading = true;

      try {
        // Build URL with current offset and any filter parameters
        const url = new URL(window.location.href);
        url.searchParams.set("offset", this.offset);

        const response = await fetch(url.toString(), {
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
        });

        if (!response.ok) {
          throw new Error(`HTTP error: ${response.status}`);
        }

        const html = await response.text();

        if (html.trim()) {
          // Parse the response to count new items and check hasMore flag
          const parser = new DOMParser();
          const doc = parser.parseFromString(html, "text/html");
          const newItems = doc.querySelectorAll("[data-image-id]");
          const hasMoreEl = doc.querySelector("[data-has-more]");

          if (newItems.length > 0) {
            // Append the new HTML to the grid (excluding the template element)
            this.$refs.imageGrid.insertAdjacentHTML("beforeend", html);

            // Remove the template element we just added
            const addedTemplate =
              this.$refs.imageGrid.querySelector("[data-has-more]");
            if (addedTemplate) addedTemplate.remove();

            // Update offset for next load
            this.offset += newItems.length;

            // Use server's hasMore flag if available, otherwise fall back to count check
            if (hasMoreEl) {
              this.hasMore = hasMoreEl.dataset.hasMore === "true";
            } else if (newItems.length < perPage) {
              this.hasMore = false;
            }
          } else {
            this.hasMore = false;
          }
        } else {
          this.hasMore = false;
        }
      } catch (error) {
        console.error("Error loading more images:", error);
        // Don't set hasMore to false on error - let user retry
      } finally {
        this.loading = false;
      }
    },
  };
};

// Also register the base imageGrid for backwards compatibility
window.Alpine.data("imageGrid", imageGrid);
