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
  const loadingIndicator = document.getElementById("loadingIndicator");
  const searchResults = document.getElementById("searchResults");
  const semanticMode = document.getElementById("semanticMode");
  const textMode = document.getElementById("textMode");
  const semanticDescription = document.getElementById("semanticDescription");
  const textDescription = document.getElementById("textDescription");
  const subjectSearchWrapper = document.getElementById(
    "subject-search-wrapper",
  );
  const noSubjectsRadio = document.getElementById("noSubjects");

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
    const page = urlParams.has("page")
      ? parseInt(urlParams.get("page"), 10)
      : 1;

    if (urlParams.has("mode") && urlParams.get("mode") === "text") {
      textMode.checked = true;
      textMode.dispatchEvent(new Event("change"));
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
      performSearch(page);
    }
  }

  searchForm.addEventListener("submit", function (e) {
    e.preventDefault();
    performSearch(); // Defaults to page 1
  });

  searchResults.addEventListener("click", function (e) {
    if (e.target.matches("a.page-link")) {
      e.preventDefault();
      const page = e.target.dataset.page;
      if (page) {
        performSearch(parseInt(page, 10));
      }
    }
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
      searchQuery.placeholder = "Describe what you're looking for...";
    }
  });

  textMode.addEventListener("change", function () {
    if (this.checked) {
      semanticDescription.style.display = "none";
      textDescription.style.display = "block";
      searchQuery.placeholder = "Search for keywords...";
    }
  });

  function performSearch(page = 1) {
    const query = searchQuery.value.trim();
    const subjectOption = document.querySelector(
      'input[name="subjectOptions"]:checked',
    ).value;
    const hasSubjectFilter =
      subjectOption === "none" || selectedSubjects.length > 0;

    if (!query && !hasSubjectFilter) {
      return; // Do not search if there is no query and no subject filter
    }

    let searchMode = semanticMode.checked ? "semantic" : "text";
    // If query is empty, we must use the text search endpoint, as semantic search requires a query.
    if (!query) {
      searchMode = "text";
    }

    const apiEndpoint =
      searchMode === "semantic" ? "/api/v1/search/" : "/api/v1/search/text/";

    const params = new URLSearchParams();
    params.set("q", query);
    params.set("mode", searchMode);
    params.set("page", page);

    if (pagelimitSelect.value) {
      params.set("pagelimit", pagelimitSelect.value);
    }
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

    history.pushState(
      null,
      "",
      `${window.location.pathname}?${params.toString()}`,
    );

    loadingIndicator.style.display = "block";
    searchResults.innerHTML = "";

    fetch(`${apiEndpoint}?${params.toString()}`)
      .then((response) => response.json())
      .then((data) => {
        loadingIndicator.style.display = "none";
        if (data.success) {
          displayResults(data);
        } else {
          displayError(data.error);
        }
      })
      .catch((error) => {
        loadingIndicator.style.display = "none";
        displayError("Search failed: " + error.message);
      });
  }

  function renderPagination(data) {
    const { count, limit, page } = data;
    const totalPages = Math.ceil(count / limit);
    const currentPage = page;

    if (totalPages <= 1) {
      if (count > 0) {
        const startIndex = (currentPage - 1) * limit + 1;
        const endIndex = Math.min(currentPage * limit, count);
        return `<div class="text-center text-muted mt-4">Showing ${startIndex}-${endIndex} of ${count} results</div>`;
      }
      return "";
    }

    let html = `<nav aria-label="Search results pagination" class="mt-4"><ul class="pagination justify-content-center">`;

    // Previous link
    if (currentPage > 1) {
      html += `<li class="page-item">
                <a class="page-link" href="#" data-page="${currentPage - 1}">
                    <i class="fas fa-chevron-left"></i> Previous
                </a>
            </li>`;
    } else {
      html += `<li class="page-item disabled">
                <span class="page-link"><i class="fas fa-chevron-left"></i> Previous</span>
            </li>`;
    }

    // Page number links
    for (let num = 1; num <= totalPages; num++) {
      if (num === currentPage) {
        html += `<li class="page-item active" aria-current="page">
                    <span class="page-link">${num}</span>
                </li>`;
      } else if (num >= currentPage - 2 && num <= currentPage + 2) {
        html += `<li class="page-item">
                    <a class="page-link" href="#" data-page="${num}">${num}</a>
                </li>`;
      }
    }

    // Next link
    if (currentPage < totalPages) {
      html += `<li class="page-item">
                <a class="page-link" href="#" data-page="${currentPage + 1}">
                    Next <i class="fas fa-chevron-right"></i>
                </a>
            </li>`;
    } else {
      html += `<li class="page-item disabled">
                <span class="page-link">Next <i class="fas fa-chevron-right"></i></span>
            </li>`;
    }

    html += `</ul></nav>`;

    // "Showing X-Y of Z" text
    const startIndex = (currentPage - 1) * limit + 1;
    const endIndex = Math.min(currentPage * limit, count);
    html += `<div class="text-center text-muted mt-2">Showing ${startIndex}-${endIndex} of ${count} results</div>`;

    return html;
  }

  function displayResults(data) {
    if (data.results.length === 0) {
      let message = `No results found for "<strong>${escapeHtml(data.query)}</strong>".`;
      if (!data.query) {
        message = "No results found for the selected filters.";
      }
      searchResults.innerHTML = `
                <div class="alert alert-info">
                    <i class="fas fa-info-circle me-2"></i>
                    ${message}
                    Try a different search term or filter.
                </div>
            `;
      return;
    }

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

    // Get current search mode for display
    const currentSearchMode = semanticMode.checked ? "semantic" : "text";
    const searchModeLabel =
      data.search_type === "filter_only"
        ? "filters"
        : currentSearchMode === "semantic"
          ? "semantic search"
          : "text search";
    const forQuery = data.query
      ? ` for "<strong>${escapeHtml(data.query)}</strong>"`
      : "";

    let html = `
            <div class="search-stats mb-3">
                Found ${data.count} results${forQuery} using ${searchModeLabel}${filterSummary}
            </div>
            <div class="row">
        `;

    data.results.forEach((result) => {
      let similarityBadge = "";
      if (typeof result.similarity !== "undefined") {
        const similarity = Math.round(result.similarity * 100);
        const similarityClass =
          similarity > 80
            ? "bg-success"
            : similarity > 60
              ? "bg-warning"
              : "bg-secondary";
        similarityBadge = `<span class="badge ${similarityClass} position-absolute top-0 end-0 m-2" style="z-index: 10;">
                    ${similarity}% match
                </span>`;
      }

      html += `
                <div class="col-lg-3 col-md-4 col-sm-6 mb-4">
                    <div class="card h-100 shadow-sm image-card">
                        <div class="position-relative">
                            ${similarityBadge}

                            <!-- Georeferenced Status Badge -->
                            ${
                              result.georeferenced
                                ? `
                                <span class="badge bg-success position-absolute top-0 start-0 m-2" style="z-index: 10;" title="Georeferenced">
                                    <i class="fas fa-map-marker-alt"></i>
                                </span>
                            `
                                : result.will_not_georef
                                  ? `
                                <span class="badge bg-secondary position-absolute top-0 start-0 m-2" style="z-index: 10;" title="Will not georeference">
                                    <i class="fas fa-ban"></i>
                                </span>
                            `
                                  : ""
                            }

                            <!-- Image Thumbnail -->
                            <a href="${escapeHtml(result.detail_url)}" class="image-container d-block" style="height: 200px; overflow: hidden; text-decoration: none; color: inherit;">
                                <img src="${escapeHtml(result.permalink)}"
                                     alt="${escapeHtml(result.title)}"
                                     class="img-fluid w-100 h-100"
                                     style="object-fit: cover;"
                                     loading="lazy"
                                     onerror="this.onerror=null; this.style.display='none'; this.nextElementSibling.style.display='flex';">
                                <div class="image-placeholder bg-light d-flex align-items-center justify-content-center h-100" style="display: none;">
                                    <div class="text-center">
                                        <i class="fas fa-image fa-2x text-muted mb-2"></i>
                                        <p class="text-muted small mb-0">Image unavailable</p>
                                    </div>
                                </div>
                            </a>
                        </div>

                        <div class="card-body p-3">
                            <h6 class="card-title">
                                <a href="${escapeHtml(result.detail_url)}" class="text-dark text-decoration-none">
                                    ${
                                      escapeHtml(result.title).length > 50
                                        ? escapeHtml(result.title).substring(
                                            0,
                                            47,
                                          ) + "..."
                                        : escapeHtml(result.title)
                                    }
                                </a>
                            </h6>

                            <p class="card-text text-muted small mb-2">
                                <i class="fas fa-archive me-1"></i>${escapeHtml(result.source.name)} → ${escapeHtml(result.collection.name)}
                            </p>

                            ${
                              result.original_date
                                ? `
                                <p class="card-text small text-muted mb-2">
                                    <i class="fas fa-calendar me-1"></i>${escapeHtml(result.original_date)}
                                </p>
                            `
                                : ""
                            }
                        </div>

                        <div class="card-footer bg-white border-top-0 p-3">
                            <div class="d-flex justify-content-between">
                                <a href="${escapeHtml(result.permalink)}" target="_blank" class="btn btn-outline-secondary btn-sm">
                                    <i class="fas fa-external-link-alt me-1"></i>Original
                                </a>
                                <a href="${escapeHtml(result.detail_url)}" class="btn btn-primary btn-sm">
                                    <i class="fas fa-eye me-1"></i>View
                                </a>
                            </div>
                        </div>
                    </div>
                </div>
            `;
    });

    html += "</div>";
    html += renderPagination(data);
    searchResults.innerHTML = html;
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
