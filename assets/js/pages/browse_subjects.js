import "../../styles/pages/browse-subjects.css";

/**
 * Alpine.js component for subject browsing with search, "Load More", and a
 * two-section autocomplete (Subjects + Categories powered by the Memgraph
 * Wikidata mirror).
 */
window.Alpine.data("subjectBrowser", function () {
  const config = window.subjectBrowserConfig || {};
  const perPage = config.perPage || 12;
  const autocompleteUrl = config.autocompleteUrl || null;

  return {
    query: new URLSearchParams(window.location.search).get("filter") || "",
    offset: perPage,
    hasMore: config.hasMore ?? false,
    loading: false,
    noResults: false,

    // Autocomplete dropdown state
    suggestions: { categories: [], subjects: [] },
    showDropdown: false,
    selectedCategory: config.selectedCategory || null,
    _autocompleteController: null,
    _searchController: null,

    _isLoadingMore: false,
    _pendingFetch: null,
    _loadingTimer: null,

    onInput() {
      // One Alpine listener, two side effects: refresh the suggestion
      // dropdown and re-run the grid search. Alpine's .debounce modifier
      // throttles us at the listener so neither side fires per keystroke.
      this._fetchSuggestions();
      this.search();
    },

    onFocus() {
      if (
        this.query.length >= 2 &&
        (this.suggestions.categories.length > 0 ||
          this.suggestions.subjects.length > 0)
      ) {
        this.showDropdown = true;
      }
    },

    async _fetchSuggestions() {
      if (!autocompleteUrl || this.query.length < 2) {
        this.suggestions = { categories: [], subjects: [] };
        this.showDropdown = false;
        return;
      }

      if (this._autocompleteController) {
        this._autocompleteController.abort();
      }
      this._autocompleteController = new AbortController();

      try {
        const url = new URL(autocompleteUrl, window.location.origin);
        url.searchParams.set("q", this.query);
        const response = await fetch(url.toString(), {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          signal: this._autocompleteController.signal,
        });
        if (!response.ok) return;
        const data = await response.json();
        this.suggestions = {
          categories: data.categories || [],
          subjects: data.subjects || [],
        };
        this.showDropdown =
          this.suggestions.categories.length > 0 ||
          this.suggestions.subjects.length > 0;
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error("Autocomplete error:", error);
        }
      }
    },

    selectCategory(category) {
      this.selectedCategory = { qid: category.qid, label: category.label };
      // The typed text was about finding the category, not narrowing
      // by title - reset it so the grid shows the whole category.
      // The user can type again to narrow within the category.
      this.query = "";
      this.suggestions = { categories: [], subjects: [] };
      this.showDropdown = false;
      this._syncUrl();
      this.search();
    },

    clearCategory() {
      this.selectedCategory = null;
      this._syncUrl();
      this.search();
    },

    _syncUrl() {
      const url = new URL(window.location.href);
      if (this.selectedCategory) {
        url.searchParams.set("category", this.selectedCategory.qid);
      } else {
        url.searchParams.delete("category");
      }
      if (this.query) {
        url.searchParams.set("filter", this.query);
      } else {
        url.searchParams.delete("filter");
      }
      url.searchParams.delete("offset");
      window.history.replaceState({}, "", url.toString());
    },

    async search() {
      // Cancel any in-flight earlier search. Without this, a slow typing
      // AJAX can return after a faster category-click AJAX and overwrite
      // the grid with stale results.
      if (this._searchController) {
        this._searchController.abort();
      }
      this._searchController = new AbortController();
      const signal = this._searchController.signal;

      this.offset = 0;
      this._isLoadingMore = true;
      this.loading = true;
      this._syncUrl();

      try {
        const html = await this._fetch(signal);
        if (signal.aborted) return;
        const grid = document.getElementById("subject-grid");
        grid.innerHTML = html;
        this._parseHasMore(html);
        this.noResults =
          grid.querySelectorAll(".subject-card-wrapper").length === 0;
        this.offset = perPage;
      } catch (error) {
        if (error.name !== "AbortError") {
          console.error("Error searching subjects:", error);
        }
      } finally {
        if (!signal.aborted) {
          clearTimeout(this._loadingTimer);
          this.loading = false;
          this._isLoadingMore = false;
        }
      }
    },

    prefetchMore() {
      if (this._isLoadingMore || !this.hasMore || this._pendingFetch) return;
      this._pendingFetch = this._fetch();
    },

    async loadMore() {
      if (this._isLoadingMore || !this.hasMore) return;
      this._isLoadingMore = true;

      this._loadingTimer = setTimeout(() => {
        this.loading = true;
      }, 200);

      try {
        let html;
        if (this._pendingFetch) {
          html = await this._pendingFetch;
          this._pendingFetch = null;
        } else {
          html = await this._fetch();
        }

        if (html.trim()) {
          const parser = new DOMParser();
          const doc = parser.parseFromString(html, "text/html");
          const newItems = doc.querySelectorAll(".subject-card-wrapper");

          if (newItems.length > 0) {
            const grid = document.getElementById("subject-grid");
            grid.insertAdjacentHTML("beforeend", html);
            const addedTemplate = grid.querySelector("[data-has-more]");
            if (addedTemplate) addedTemplate.remove();
            this.offset += newItems.length;
            this._parseHasMore(html);
          } else {
            this.hasMore = false;
          }
        } else {
          this.hasMore = false;
        }
      } catch (error) {
        console.error("Error loading more subjects:", error);
        this._pendingFetch = null;
      } finally {
        clearTimeout(this._loadingTimer);
        this.loading = false;
        this._isLoadingMore = false;
      }
    },

    async _fetch(signal) {
      const url = new URL(window.location.origin + window.location.pathname);
      url.searchParams.set("offset", this.offset);
      if (this.query) url.searchParams.set("filter", this.query);
      if (this.selectedCategory) {
        url.searchParams.set("category", this.selectedCategory.qid);
      }

      const response = await fetch(url.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        signal,
      });
      if (!response.ok) throw new Error(`HTTP error: ${response.status}`);
      return response.text();
    },

    _parseHasMore(html) {
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, "text/html");
      const el = doc.querySelector("[data-has-more]");
      this.hasMore = el ? el.dataset.hasMore === "true" : false;
    },
  };
});
