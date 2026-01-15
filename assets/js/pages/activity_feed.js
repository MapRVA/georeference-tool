/**
 * Activity Feed page JavaScript
 *
 * Handles the "Load More" infinite scroll functionality using Alpine.js.
 */

// Add x-cloak style to prevent flash of unstyled content
document.addEventListener("DOMContentLoaded", function () {
  const style = document.createElement("style");
  style.textContent = "[x-cloak] { display: none !important; }";
  document.head.appendChild(style);
});

/**
 * Alpine.js component for the activity feed with "Load More" functionality.
 *
 * @param {boolean} initialHasMore - Whether there are more items to load
 */
window.activityFeed = function (initialHasMore) {
  return {
    hasMore: initialHasMore,
    loading: false,

    get lastTimestamp() {
      const items = this.$refs.items?.querySelectorAll(".activity-item");
      if (items && items.length > 0) {
        return items[items.length - 1].dataset.timestamp;
      }
      return null;
    },

    async loadMore() {
      if (this.loading || !this.hasMore) return;

      this.loading = true;

      try {
        const url = new URL(window.location.href);
        url.searchParams.set("before", this.lastTimestamp);

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
        // Don't set hasMore to false on error - let user retry
      } finally {
        this.loading = false;
      }
    },
  };
};
