/**
 * Activity Feed page JavaScript
 *
 * Handles the "Load More" infinite scroll functionality and filtering using Alpine.js.
 */
import "../../styles/pages/activity.css";

// Add x-cloak style to prevent flash of unstyled content
document.addEventListener("DOMContentLoaded", function () {
  const style = document.createElement("style");
  style.textContent = "[x-cloak] { display: none !important; }";
  document.head.appendChild(style);
});

/**
 * Alpine.js component for the activity type filter dropdown.
 *
 * @param {Object} initialFilters - Initial filter states {group, comment, milestone}
 */
window.activityFilter = function (initialFilters) {
  const allTypes = [
    "group",
    "comment",
    "milestone",
    "sitewide",
    "validation",
    "subject",
    "new_subject",
  ];
  const defaultTypes = [
    "group",
    "comment",
    "milestone",
    "sitewide",
    "new_subject",
  ];

  return {
    filters: {
      group: initialFilters?.group ?? true,
      comment: initialFilters?.comment ?? true,
      milestone: initialFilters?.milestone ?? true,
      sitewide: initialFilters?.sitewide ?? true,
      validation: initialFilters?.validation ?? false,
      subject: initialFilters?.subject ?? false,
      new_subject: initialFilters?.new_subject ?? true,
    },

    applyFilters() {
      const selected = Object.entries(this.filters)
        .filter(([, enabled]) => enabled)
        .map(([type]) => type);

      // Update URL without reloading
      const url = new URL(window.location.href);
      url.searchParams.delete("before");

      // Omit types param only when selection matches the server default
      const isDefault =
        selected.length === defaultTypes.length &&
        defaultTypes.every((t) => selected.includes(t));
      if (selected.length === 0 || isDefault) {
        url.searchParams.delete("types");
      } else {
        url.searchParams.set("types", selected.join(","));
      }

      history.replaceState(null, "", url.toString());

      // Dispatch event to reload the feed
      this.$dispatch("filter-changed", { types: selected });
    },
  };
};

/**
 * Alpine.js component for the activity feed with "Load More" functionality.
 *
 * @param {boolean} initialHasMore - Whether there are more items to load
 * @param {boolean} initialNoneSelected - Whether no filter types are selected
 */
window.activityFeed = function (initialHasMore, initialNoneSelected = false) {
  return {
    hasMore: initialHasMore,
    loading: false, // Controls spinner visibility (debounced)
    noneSelected: initialNoneSelected,

    // Pending fetch promise from prefetch (mousedown)
    _pendingFetch: null,
    // Timer for debounced loading indicator
    _loadingTimer: null,
    // Flag to prevent concurrent requests (separate from loading indicator)
    _isLoadingMore: false,

    get lastTimestamp() {
      const items = this.$refs.items?.querySelectorAll(".activity-item");
      if (items && items.length > 0) {
        return items[items.length - 1].dataset.timestamp;
      }
      return null;
    },

    async reloadFeed(event) {
      const types = event?.detail?.types ?? [];
      this.noneSelected = types.length === 0;

      if (this.noneSelected) {
        this.$refs.items.innerHTML = "";
        this.hasMore = false;
        return;
      }

      this.loading = true;

      try {
        const url = new URL(window.location.href);
        url.searchParams.delete("before");

        const response = await fetch(url.toString(), {
          headers: {
            "X-Requested-With": "XMLHttpRequest",
          },
        });

        if (!response.ok) {
          throw new Error(`HTTP error: ${response.status}`);
        }

        const html = await response.text();

        // Replace the feed content
        this.$refs.items.innerHTML = html;

        // Check if there are more items
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        const newItems = doc.querySelectorAll(".activity-item");
        this.hasMore = newItems.length >= 20;
      } catch (error) {
        console.error("Error reloading activities:", error);
      } finally {
        this.loading = false;
      }
    },

    /**
     * Prefetch next page on mousedown for faster perceived loading.
     * Called via @mousedown on the Load More button.
     */
    prefetchMore() {
      if (this._isLoadingMore || !this.hasMore || this._pendingFetch) return;

      const url = new URL(window.location.href);
      url.searchParams.set("before", this.lastTimestamp);

      this._pendingFetch = fetch(url.toString(), {
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
      });
    },

    /**
     * Load more activities via AJAX.
     * Uses prefetched response if available.
     */
    async loadMore() {
      if (this._isLoadingMore || !this.hasMore) return;
      this._isLoadingMore = true;

      // Debounce the loading indicator - only show after 200ms
      this._loadingTimer = setTimeout(() => {
        this.loading = true;
      }, 200);

      try {
        let response;

        if (this._pendingFetch) {
          // Use the prefetched request
          response = await this._pendingFetch;
          this._pendingFetch = null;
        } else {
          // No prefetch, make the request now
          const url = new URL(window.location.href);
          url.searchParams.set("before", this.lastTimestamp);

          response = await fetch(url.toString(), {
            headers: {
              "X-Requested-With": "XMLHttpRequest",
            },
          });
        }

        if (!response.ok) {
          throw new Error(`HTTP error: ${response.status}`);
        }

        const html = await response.text();

        if (html.trim()) {
          // Count how many items we received
          const parser = new DOMParser();
          const doc = parser.parseFromString(html, "text/html");
          const newItems = doc.querySelectorAll(".activity-item");

          if (newItems.length > 0) {
            // Append the new HTML to the feed
            this.$refs.items.insertAdjacentHTML("beforeend", html);

            // If we got fewer than 20 items, we've reached the end
            if (newItems.length < 20) {
              this.hasMore = false;
            }
          } else {
            this.hasMore = false;
          }
        } else {
          this.hasMore = false;
        }
      } catch (error) {
        console.error("Error loading more activities:", error);
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
