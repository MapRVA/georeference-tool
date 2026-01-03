// Filter state management
class ImageFilterState {
  constructor() {
    this.georeference_status = [];
    this.start_year = null;
    this.end_year = null;
    this.with_subjects = [];
    this.without_subjects = [];
    this.no_subjects = false;
  }

  // Load state from URL parameters
  loadFromURL() {
    const urlParams = new URLSearchParams(window.location.search);

    // Georeference status
    if (urlParams.has("georeference_status")) {
      this.georeference_status = urlParams
        .get("georeference_status")
        .split(",");
    }

    // Year filters
    this.start_year = urlParams.get("start_year") || null;
    this.end_year = urlParams.get("end_year") || null;

    // Subject filters
    this.no_subjects = urlParams.get("no_subjects") === "true";
    if (urlParams.has("with_subjects")) {
      this.with_subjects = urlParams.get("with_subjects").split(",");
    }
    if (urlParams.has("without_subjects")) {
      this.without_subjects = urlParams.get("without_subjects").split(",");
    }
  }

  // Apply state to URL
  applyToURL(url) {
    // Georeference status
    if (this.georeference_status.length > 0) {
      url.searchParams.set(
        "georeference_status",
        this.georeference_status.join(","),
      );
    } else {
      url.searchParams.delete("georeference_status");
    }

    // Year filters
    if (this.start_year) {
      url.searchParams.set("start_year", this.start_year);
    } else {
      url.searchParams.delete("start_year");
    }

    if (this.end_year) {
      url.searchParams.set("end_year", this.end_year);
    } else {
      url.searchParams.delete("end_year");
    }

    // Subject filters
    if (this.no_subjects) {
      url.searchParams.set("no_subjects", "true");
      url.searchParams.delete("with_subjects");
      url.searchParams.delete("without_subjects");
    } else {
      if (this.with_subjects.length > 0) {
        url.searchParams.set("with_subjects", this.with_subjects.join(","));
        url.searchParams.delete("without_subjects");
      } else if (this.without_subjects.length > 0) {
        url.searchParams.set(
          "without_subjects",
          this.without_subjects.join(","),
        );
        url.searchParams.delete("with_subjects");
      } else {
        url.searchParams.delete("with_subjects");
        url.searchParams.delete("without_subjects");
      }
      url.searchParams.delete("no_subjects");
    }

    return url;
  }

  // Clear all filters
  clear() {
    this.georeference_status = [];
    this.start_year = null;
    this.end_year = null;
    this.with_subjects = [];
    this.without_subjects = [];
    this.no_subjects = false;
  }
}

// Subject management utilities
class SubjectManager {
  constructor() {
    this.allSubjects = [];
    this.subjectMap = new Map();
    this.selectedSubjects = [];
  }

  async fetchSubjects() {
    try {
      const response = await fetch("/api/v1/subjects/all/");
      if (response.ok) {
        this.allSubjects = await response.json();
        this.subjectMap = new Map(
          this.allSubjects.map((s) => [s.id.toString(), s.title]),
        );
        return true;
      } else {
        console.error("Failed to fetch subjects:", response.statusText);
        return false;
      }
    } catch (error) {
      console.error("Error fetching subjects:", error);
      return false;
    }
  }

  getSubjectTitle(id) {
    return this.subjectMap.get(id.toString()) || `ID: ${id}`;
  }

  addSubject(subject) {
    if (!this.selectedSubjects.some((s) => s.id === subject.id)) {
      this.selectedSubjects.push(subject);
      return true;
    }
    return false;
  }

  removeSubject(subjectId) {
    this.selectedSubjects = this.selectedSubjects.filter(
      (s) => s.id.toString() !== subjectId.toString(),
    );
  }

  clearSubjects() {
    this.selectedSubjects = [];
  }
}

// Card rendering utilities
class CardRenderer {
  static renderImageCard(image) {
    const hasGeoreference =
      image.has_georeference ||
      (image.georeferenced_count && image.georeferenced_count > 0);
    const isWillNotGeoref = image.will_not_georef;

    let statusBadge = "";
    if (hasGeoreference) {
      statusBadge =
        '<span class="badge bg-success"><i class="fas fa-map-marker-alt"></i> Georeferenced</span>';
    } else if (isWillNotGeoref) {
      statusBadge =
        '<span class="badge bg-secondary"><i class="fas fa-ban"></i> Will Not Reference</span>';
    } else {
      statusBadge =
        '<span class="badge bg-warning"><i class="fas fa-clock"></i> Pending</span>';
    }

    const yearDisplay =
      image.year_display || image.original_date || "Date unknown";

    return `
            <div class="col-md-6 col-lg-4 mb-4">
                <div class="card h-100 shadow-sm">
                    <a href="${image.detail_url || "#"}">
                        <img src="${image.permalink}"
                             class="card-img-top"
                             alt="${this.escapeHtml(image.title)}"
                             loading="lazy">
                    </a>
                    <div class="card-body d-flex flex-column">
                        <h5 class="card-title">
                            <a href="${image.detail_url || "#"}" class="text-decoration-none">
                                ${this.escapeHtml(image.title)}
                            </a>
                        </h5>
                        <p class="card-text small text-muted">
                            ${this.escapeHtml(yearDisplay)}
                        </p>
                        ${
                          image.description
                            ? `<p class="card-text small">${this.escapeHtml(this.truncateText(image.description, 100))}</p>`
                            : ""
                        }
                        <div class="mt-auto">
                            ${statusBadge}
                            ${
                              image.subjects && image.subjects.length > 0
                                ? `<div class="mt-2">
                                    ${image.subjects
                                      .slice(0, 3)
                                      .map(
                                        (s) =>
                                          `<span class="badge bg-info me-1">${this.escapeHtml(s.title)}</span>`,
                                      )
                                      .join("")}
                                    ${
                                      image.subjects.length > 3
                                        ? `<span class="badge bg-light text-dark">+${image.subjects.length - 3}</span>`
                                        : ""
                                    }
                                </div>`
                                : ""
                            }
                        </div>
                    </div>
                </div>
            </div>
        `;
  }

  static escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  static truncateText(text, maxLength) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + "...";
  }

  static renderNoResults() {
    return `
            <div class="col-12">
                <div class="alert alert-info">
                    <i class="fas fa-info-circle me-2"></i>
                    No images found matching your filters.
                </div>
            </div>
        `;
  }

  static renderLoadingState() {
    return `
            <div class="col-12 text-center">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <p class="mt-2">Loading images...</p>
            </div>
        `;
  }

  static renderErrorState(message = "An error occurred while loading images.") {
    return `
            <div class="col-12">
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-triangle me-2"></i>
                    ${this.escapeHtml(message)}
                </div>
            </div>
        `;
  }
}

// Pagination utilities
class PaginationRenderer {
  static render(currentPage, totalPages, baseUrl) {
    if (totalPages <= 1) return "";

    const url = new URL(baseUrl || window.location.href);
    let html =
      '<nav aria-label="Page navigation"><ul class="pagination justify-content-center">';

    // Previous button
    if (currentPage > 1) {
      url.searchParams.set("page", currentPage - 1);
      html += `
                <li class="page-item">
                    <a class="page-link" href="${url.toString()}" aria-label="Previous">
                        <span aria-hidden="true">&laquo;</span>
                    </a>
                </li>
            `;
    } else {
      html += `
                <li class="page-item disabled">
                    <span class="page-link">&laquo;</span>
                </li>
            `;
    }

    // Page numbers
    const maxVisible = 5;
    let startPage = Math.max(1, currentPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);

    if (endPage - startPage < maxVisible - 1) {
      startPage = Math.max(1, endPage - maxVisible + 1);
    }

    if (startPage > 1) {
      url.searchParams.set("page", 1);
      html += `
                <li class="page-item">
                    <a class="page-link" href="${url.toString()}">1</a>
                </li>
            `;
      if (startPage > 2) {
        html +=
          '<li class="page-item disabled"><span class="page-link">...</span></li>';
      }
    }

    for (let i = startPage; i <= endPage; i++) {
      if (i === currentPage) {
        html += `
                    <li class="page-item active">
                        <span class="page-link">${i}</span>
                    </li>
                `;
      } else {
        url.searchParams.set("page", i);
        html += `
                    <li class="page-item">
                        <a class="page-link" href="${url.toString()}">${i}</a>
                    </li>
                `;
      }
    }

    if (endPage < totalPages) {
      if (endPage < totalPages - 1) {
        html +=
          '<li class="page-item disabled"><span class="page-link">...</span></li>';
      }
      url.searchParams.set("page", totalPages);
      html += `
                <li class="page-item">
                    <a class="page-link" href="${url.toString()}">${totalPages}</a>
                </li>
            `;
    }

    // Next button
    if (currentPage < totalPages) {
      url.searchParams.set("page", currentPage + 1);
      html += `
                <li class="page-item">
                    <a class="page-link" href="${url.toString()}" aria-label="Next">
                        <span aria-hidden="true">&raquo;</span>
                    </a>
                </li>
            `;
    } else {
      html += `
                <li class="page-item disabled">
                    <span class="page-link">&raquo;</span>
                </li>
            `;
    }

    html += "</ul></nav>";
    return html;
  }
}

// Export utilities for use in other scripts
window.ImageFilterState = ImageFilterState;
window.SubjectManager = SubjectManager;
window.CardRenderer = CardRenderer;
window.PaginationRenderer = PaginationRenderer;
