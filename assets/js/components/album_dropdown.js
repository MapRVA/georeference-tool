/**
 * Album Dropdown Component
 *
 * Handles the album add/remove dropdown functionality for image cards.
 * Uses event delegation so it works with dynamically loaded content.
 */

/**
 * Initialize album dropdown handlers using event delegation.
 * Call this once on page load - it will handle all current and future dropdowns.
 *
 * @param {Object} config - Configuration object with URLs
 * @param {string} config.userAlbumsApi - URL to fetch user's albums
 * @param {string} config.addToAlbum - URL to add image to album
 * @param {string} config.removeFromAlbum - URL to remove image from album
 * @param {string} config.createAlbum - URL to create new album and add image
 * @param {string} [containerSelector='body'] - Selector for the container to attach delegation to
 */
export function initAlbumDropdowns(config, containerSelector = "body") {
  const container = document.querySelector(containerSelector);
  if (!container) return;

  // Use event delegation for dropdown toggles
  container.addEventListener("click", function (e) {
    // Check if click is on a dropdown toggle inside an image card
    const toggleButton = e.target.closest(
      ".image-card .dropdown-toggle[data-image-id]",
    );
    if (!toggleButton) return;

    const dropdown = toggleButton.closest(".dropdown");
    const dropdownMenu = dropdown?.querySelector(".album-dropdown");
    if (!dropdownMenu) return;

    const imageId = toggleButton.dataset.imageId;
    if (!imageId) return;

    // Fetch user's albums and populate dropdown
    fetchAndPopulateAlbums(dropdownMenu, imageId, config);
  });

  // Use event delegation for album option clicks
  container.addEventListener("click", function (e) {
    const albumOption = e.target.closest(".album-dropdown .album-option");
    if (!albumOption) return;

    e.preventDefault();
    const albumId = albumOption.dataset.albumId;
    const imageId = albumOption.dataset.imageId;
    const isInAlbum = albumOption.dataset.inAlbum === "true";

    if (isInAlbum) {
      removeImageFromAlbum(imageId, albumId, config);
    } else {
      addImageToAlbum(imageId, albumId, config);
    }
  });

  // Use event delegation for create album modal trigger
  container.addEventListener("click", function (e) {
    const createLink = e.target.closest(
      '.album-dropdown [data-bs-target="#createAlbumModal"]',
    );
    if (!createLink) return;

    e.preventDefault();
    const imageId = createLink.dataset.imageId;

    const modalImageId = document.getElementById("modalImageId");
    const newAlbumTitle = document.getElementById("newAlbumTitle");
    const newAlbumDescription = document.getElementById("newAlbumDescription");
    const newAlbumPublic = document.getElementById("newAlbumPublic");
    const createAlbumModal = document.getElementById("createAlbumModal");

    if (modalImageId) modalImageId.value = imageId;
    if (newAlbumTitle) newAlbumTitle.value = "";
    if (newAlbumDescription) newAlbumDescription.value = "";
    if (newAlbumPublic) newAlbumPublic.checked = false;

    if (createAlbumModal && window.bootstrap) {
      const modal = bootstrap.Modal.getOrCreateInstance(createAlbumModal);
      modal.show();
    }
  });
}

/**
 * Set up the create album button handler
 *
 * @param {Object} config - Configuration object with URLs
 */
export function initCreateAlbumButton(config) {
  const createAlbumBtn = document.getElementById("createAlbumBtn");
  if (!createAlbumBtn) return;

  createAlbumBtn.addEventListener("click", function () {
    const modalImageId = document.getElementById("modalImageId");
    const newAlbumTitle = document.getElementById("newAlbumTitle");
    const newAlbumDescription = document.getElementById("newAlbumDescription");
    const newAlbumPublic = document.getElementById("newAlbumPublic");
    const createAlbumModal = document.getElementById("createAlbumModal");

    const imageId = modalImageId?.value;
    const title = newAlbumTitle?.value?.trim();

    if (!title) {
      showAlert("warning", "Please enter an album title");
      return;
    }

    const data = {
      image_id: imageId,
      album_title: title,
      album_description: newAlbumDescription?.value || "",
      album_public: newAlbumPublic?.checked || false,
    };

    const csrfToken = getCsrfToken();

    fetch(config.createAlbum, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken || "",
      },
      body: JSON.stringify(data),
    })
      .then((response) => response.json())
      .then((result) => {
        if (result.success) {
          if (createAlbumModal && window.bootstrap) {
            bootstrap.Modal.getInstance(createAlbumModal)?.hide();
          }
          showAlert("success", "Album created and image added successfully!");
        } else {
          showAlert(
            "danger",
            "Error: " + (result.error || "Failed to create album"),
          );
        }
      })
      .catch((error) => {
        console.error("Error:", error);
        showAlert("danger", "An error occurred while creating the album");
      });
  });
}

/**
 * Fetch albums and populate the dropdown menu
 */
function fetchAndPopulateAlbums(dropdownMenu, imageId, config) {
  const apiUrl = config.userAlbumsApi || "/api/v1/albums/user/";

  fetch(`${apiUrl}?image_id=${imageId}`)
    .then((response) => response.json())
    .then((data) => {
      let html = "";

      if (data.albums && data.albums.length > 0) {
        data.albums.forEach((album) => {
          const isInAlbum = album.has_image;
          const icon = isInAlbum
            ? '<i class="fas fa-check-circle me-2 text-success"></i>'
            : '<i class="fas fa-plus me-2 text-muted"></i>';
          const title = isInAlbum
            ? `${escapeHtml(album.title)} <span class="text-muted small">(click to remove)</span>`
            : escapeHtml(album.title);
          html += `<li><a class="dropdown-item album-option" href="#" data-album-id="${album.id}" data-image-id="${imageId}" data-in-album="${isInAlbum}">${icon}${title}</a></li>`;
        });
        html += '<li><hr class="dropdown-divider"></li>';
      }

      html += `<li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#createAlbumModal" data-image-id="${imageId}"><i class="fas fa-plus me-1"></i>Create New Album</a></li>`;

      dropdownMenu.innerHTML = html;
    })
    .catch((error) => {
      console.error("Error fetching albums:", error);
      dropdownMenu.innerHTML =
        '<li><span class="dropdown-item-text text-danger small">Error loading albums</span></li>';
    });
}

/**
 * Add an image to an album
 */
function addImageToAlbum(imageId, albumId, config) {
  const apiUrl = config.addToAlbum || "/api/v1/albums/add/";
  const csrfToken = getCsrfToken();

  fetch(apiUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken || "",
    },
    body: JSON.stringify({ image_id: imageId, album_id: albumId }),
  })
    .then((response) => response.json())
    .then((result) => {
      if (result.success) {
        showAlert("success", "Image added to album successfully!");
      } else {
        showAlert(
          "danger",
          "Error: " + (result.error || "Failed to add image to album"),
        );
      }
    })
    .catch((error) => {
      console.error("Error:", error);
      showAlert(
        "danger",
        "An error occurred while adding the image to the album",
      );
    });
}

/**
 * Remove an image from an album
 */
function removeImageFromAlbum(imageId, albumId, config) {
  const apiUrl = config.removeFromAlbum || "/api/v1/albums/remove/";
  const csrfToken = getCsrfToken();

  fetch(apiUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken || "",
    },
    body: JSON.stringify({ image_id: imageId, album_id: albumId }),
  })
    .then((response) => response.json())
    .then((result) => {
      if (result.success) {
        showAlert("success", "Image removed from album successfully!");
      } else {
        showAlert(
          "danger",
          "Error: " + (result.error || "Failed to remove image from album"),
        );
      }
    })
    .catch((error) => {
      console.error("Error:", error);
      showAlert(
        "danger",
        "An error occurred while removing the image from the album",
      );
    });
}

/**
 * Get CSRF token from form input or cookie
 */
function getCsrfToken() {
  // First try to get from a form input
  const inputToken = document.querySelector(
    "[name=csrfmiddlewaretoken]",
  )?.value;
  if (inputToken) return inputToken;

  // Fall back to reading from cookie
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

/**
 * Show an alert message
 */
function showAlert(type, message) {
  // Use window.showAlert if available, otherwise create a simple alert
  if (typeof window.showAlert === "function") {
    window.showAlert(type, message);
  } else {
    // Fallback: create a Bootstrap alert
    const alertContainer =
      document.querySelector(".alert-container") || document.body;
    const alertDiv = document.createElement("div");
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    alertDiv.setAttribute("role", "alert");
    alertDiv.innerHTML = `
      ${message}
      <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
    `;
    alertContainer.prepend(alertDiv);

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
      alertDiv.remove();
    }, 5000);
  }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}
