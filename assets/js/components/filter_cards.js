/**
 * Filter Cards Component
 * Provides filtering UI for image lists with bulk actions
 */
import autoComplete from "@tarekraafat/autocomplete.js";
import "../../styles/components/autocomplete.css";

// Global variables for filter state
let selectedSubjects = [];
let subjectMap = new Map();
let subjectAutocomplete = null;

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Render selected subjects as badges
 */
function renderSelectedSubjects() {
  const container = document.getElementById("selected-subjects");
  if (!container) return;

  container.innerHTML = selectedSubjects
    .map(
      (subject) => `
            <span class="badge bg-secondary">
                ${escapeHtml(subject.title)}
                <button type="button" class="btn-close btn-close-white ms-1"
                        aria-label="Remove" data-subject-id="${subject.id}"></button>
            </span>
        `,
    )
    .join("");
}

/**
 * Remove a subject from the selected list
 */
function removeSubject(subjectId) {
  selectedSubjects = selectedSubjects.filter(
    (s) => s.id.toString() !== subjectId.toString(),
  );
  renderSelectedSubjects();
}

/**
 * Update subject mode visibility
 */
function updateSubjectMode() {
  const noSubjectsRadio = document.getElementById("noSubjects");
  const wrapper = document.getElementById("subject-search-wrapper");
  if (noSubjectsRadio && wrapper) {
    wrapper.style.display = noSubjectsRadio.checked ? "none" : "block";
  }
}

/**
 * Update the dropdown button text based on selected checkboxes
 */
function updateGeoreferenceFilterText() {
  const georeferenced = document.getElementById("status_georeferenced");
  const pending = document.getElementById("status_pending");
  const willNotGeoref = document.getElementById("status_will_not_georef");
  const statusText = document.getElementById("georeferenceStatusText");

  if (!georeferenced || !pending || !willNotGeoref || !statusText) return;

  const selectedOptions = [];
  if (georeferenced.checked) selectedOptions.push("Georeferenced");
  if (pending.checked) selectedOptions.push("Pending");
  if (willNotGeoref.checked) selectedOptions.push("Will Not Georeference");

  if (selectedOptions.length === 3) {
    statusText.textContent = "All";
  } else if (selectedOptions.length === 0) {
    statusText.textContent = "None";
  } else if (selectedOptions.length === 1) {
    const shortNames = {
      Georeferenced: "Georef",
      Pending: "Pending",
      "Will Not Georeference": "Won't Georef",
    };
    statusText.textContent =
      shortNames[selectedOptions[0]] || selectedOptions[0];
  } else {
    statusText.textContent = `${selectedOptions.length} selected`;
  }
}

/**
 * Initialize subject autocomplete
 */
function initSubjectAutocomplete() {
  const input = document.getElementById("subjectSearchInput");
  if (!input) return;

  subjectAutocomplete = new autoComplete({
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
}

/**
 * Apply all filters and navigate
 */
function applyFilters() {
  const georeferenced = document.getElementById("status_georeferenced");
  const pending = document.getElementById("status_pending");
  const willNotGeoref = document.getElementById("status_will_not_georef");
  const startYear = document.getElementById("startYear");
  const endYear = document.getElementById("endYear");

  const url = new URL(window.location);

  // Build the georeference_status parameter
  const selectedStatuses = [];
  if (georeferenced?.checked) selectedStatuses.push("georeferenced");
  if (pending?.checked) selectedStatuses.push("pending");
  if (willNotGeoref?.checked) selectedStatuses.push("will_not_georef");

  if (selectedStatuses.length > 0 && selectedStatuses.length < 3) {
    url.searchParams.set("georeference_status", selectedStatuses.join(","));
  } else {
    url.searchParams.delete("georeference_status");
  }

  // Year filters
  if (startYear?.value) {
    url.searchParams.set("start_year", startYear.value);
  } else {
    url.searchParams.delete("start_year");
  }

  if (endYear?.value) {
    url.searchParams.set("end_year", endYear.value);
  } else {
    url.searchParams.delete("end_year");
  }

  // Subject filters
  const subjectModeRadio = document.querySelector(
    'input[name="subjectOptions"]:checked',
  );
  const subjectMode = subjectModeRadio?.value || "with";

  if (subjectMode === "none") {
    url.searchParams.set("no_subjects", "true");
    url.searchParams.delete("with_subjects");
    url.searchParams.delete("without_subjects");
  } else if (selectedSubjects.length > 0) {
    const subjectIds = selectedSubjects.map((s) => s.id).join(",");
    if (subjectMode === "with") {
      url.searchParams.set("with_subjects", subjectIds);
      url.searchParams.delete("without_subjects");
    } else {
      url.searchParams.set("without_subjects", subjectIds);
      url.searchParams.delete("with_subjects");
    }
    url.searchParams.delete("no_subjects");
  } else {
    url.searchParams.delete("with_subjects");
    url.searchParams.delete("without_subjects");
    url.searchParams.delete("no_subjects");
  }

  // Reset to page 1 when applying filter
  url.searchParams.delete("page");

  // Navigate to the new URL
  window.location.href = url.toString();
}

/**
 * Clear all filters
 */
function clearFilters() {
  const url = new URL(window.location);
  url.searchParams.delete("georeference_status");
  url.searchParams.delete("start_year");
  url.searchParams.delete("end_year");
  url.searchParams.delete("with_subjects");
  url.searchParams.delete("without_subjects");
  url.searchParams.delete("no_subjects");
  url.searchParams.delete("page");
  window.location.href = url.toString();
}

/**
 * Initialize the filter cards component
 */
export function initFilterCards() {
  // Check if filter elements exist on the page
  const filterPanel = document.getElementById("georeferenceFilterPanel");
  if (!filterPanel) return;

  // Fetch all subjects from the API for the subjectMap
  (async function () {
    try {
      const response = await fetch("/api/v1/subjects/all/");
      if (response.ok) {
        const allSubjects = await response.json();
        subjectMap = new Map(
          allSubjects.map((s) => [s.id.toString(), s.title]),
        );
      } else {
        console.error("Failed to fetch subjects:", response.statusText);
      }
    } catch (error) {
      console.error("Error fetching subjects:", error);
    }

    // Initialize selected subjects from URL
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has("with_subjects")) {
      const ids = urlParams.get("with_subjects").split(",");
      selectedSubjects = ids
        .map((id) => ({
          id: id,
          title: subjectMap.get(id) || `ID: ${id}`,
        }))
        .filter((s) => s.title);
    } else if (urlParams.has("without_subjects")) {
      const ids = urlParams.get("without_subjects").split(",");
      selectedSubjects = ids
        .map((id) => ({
          id: id,
          title: subjectMap.get(id) || `ID: ${id}`,
        }))
        .filter((s) => s.title);
    }

    renderSelectedSubjects();
    updateGeoreferenceFilterText();

    // Initialize autocomplete
    initSubjectAutocomplete();
  })();

  // Add event listeners for georeference status checkboxes
  const statusGeoreferenced = document.getElementById("status_georeferenced");
  const statusPending = document.getElementById("status_pending");
  const statusWillNotGeoref = document.getElementById("status_will_not_georef");

  if (statusGeoreferenced) {
    statusGeoreferenced.addEventListener(
      "change",
      updateGeoreferenceFilterText,
    );
  }
  if (statusPending) {
    statusPending.addEventListener("change", updateGeoreferenceFilterText);
  }
  if (statusWillNotGeoref) {
    statusWillNotGeoref.addEventListener(
      "change",
      updateGeoreferenceFilterText,
    );
  }

  // Handle subject removal from selected list
  document.addEventListener("click", function (e) {
    const closeBtn = e.target.closest(
      "#selected-subjects button.btn-close, #selected-subjects .btn-close",
    );
    if (closeBtn) {
      const subjectId = closeBtn.dataset.subjectId;
      if (subjectId) {
        removeSubject(subjectId);
      }
    }
  });

  // Expose functions globally for onclick handlers in HTML
  window.applyFilters = applyFilters;
  window.clearFilters = clearFilters;
  window.updateSubjectMode = updateSubjectMode;
}

// Auto-initialize when DOM is ready
document.addEventListener("DOMContentLoaded", function () {
  initFilterCards();
});
