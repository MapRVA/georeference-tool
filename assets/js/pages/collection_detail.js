import "../../styles/pages/collection-detail.css";

// Import image grid component (includes bulk selection and modal functionality)
import { imageGrid } from "../components/image_grid.js";

// Register the image grid component with Alpine and start Alpine.
// This runs synchronously before DOMContentLoaded, ensuring the component
// is registered before Alpine processes the DOM.
window.Alpine.data("imageGrid", imageGrid);
window.Alpine.start();
window.AlpineStarted = true;

document.addEventListener("DOMContentLoaded", function () {
  // Get configuration from window object (set by Django template)
  const config = window.collectionDetailConfig;

  if (!config) {
    console.error(
      "collectionDetailConfig not found! Make sure the template script is loaded before this file.",
    );
    return;
  }

  const createAlbumModal = document.getElementById("createAlbumModal");
  const newAlbumTitle = document.getElementById("newAlbumTitle");
  const newAlbumDescription = document.getElementById("newAlbumDescription");
  const newAlbumPublic = document.getElementById("newAlbumPublic");
  const createAlbumBtn = document.getElementById("createAlbumBtn");
  const modalImageId = document.getElementById("modalImageId");

  // Handle dropdown toggle - fetch albums when dropdown is shown
  // Only target album dropdowns in the image cards (not header dropdowns)
  document
    .querySelectorAll(".image-card .dropdown-toggle")
    .forEach((button) => {
      button.addEventListener("click", function (e) {
        const dropdown = this.closest(".dropdown");
        const dropdownMenu = dropdown.querySelector(".dropdown-menu");
        const imageId = this.dataset.imageId;

        // Fetch user's albums and check which ones contain this image
        fetch(`${config.urls.userAlbumsApi}?image_id=${imageId}`)
          .then((response) => response.json())
          .then((data) => {
            let html = "";

            if (data.albums.length > 0) {
              data.albums.forEach((album) => {
                const isInAlbum = album.has_image;
                const icon = isInAlbum
                  ? '<i class="fas fa-check-circle me-2 text-success"></i>'
                  : '<i class="fas fa-plus me-2 text-muted"></i>';
                const title = isInAlbum
                  ? `${album.title} <span class="text-muted small">(click to remove)</span>`
                  : album.title;
                html += `<li><a class="dropdown-item album-option" href="#" data-album-id="${album.id}" data-image-id="${imageId}" data-in-album="${isInAlbum}">${icon}${title}</a></li>`;
              });
              html += '<li><hr class="dropdown-divider"></li>';
            }

            html += `<li><a class="dropdown-item" href="#" data-bs-toggle="modal" data-bs-target="#createAlbumModal" data-image-id="${imageId}"><i class="fas fa-plus me-1"></i>Create New Album</a></li>`;

            dropdownMenu.innerHTML = html;

            // Add event listeners to album options
            dropdownMenu.querySelectorAll(".album-option").forEach((link) => {
              link.addEventListener("click", function (e) {
                e.preventDefault();
                const albumId = this.dataset.albumId;
                const imageId = this.dataset.imageId;
                const isInAlbum = this.dataset.inAlbum === "true";

                if (isInAlbum) {
                  removeImageFromAlbum(imageId, albumId);
                } else {
                  addImageToAlbum(imageId, albumId);
                }
              });
            });

            // Handle create album link
            dropdownMenu
              .querySelector('[data-bs-target="#createAlbumModal"]')
              .addEventListener("click", function (e) {
                e.preventDefault();
                modalImageId.value = this.dataset.imageId;
                // Reset form
                newAlbumTitle.value = "";
                newAlbumDescription.value = "";
                newAlbumPublic.checked = false;
                const modal =
                  bootstrap.Modal.getOrCreateInstance(createAlbumModal);
                modal.show();
              });
          })
          .catch((error) => {
            console.error("Error fetching albums:", error);
            dropdownMenu.innerHTML =
              '<li><span class="dropdown-item-text text-danger small">Error loading albums</span></li>';
          });
      });
    });

  // Handle create album
  createAlbumBtn.addEventListener("click", function () {
    const imageId = modalImageId.value;

    if (!newAlbumTitle.value.trim()) {
      showAlert("warning", "Please enter an album title");
      return;
    }

    const data = {
      image_id: imageId,
      album_title: newAlbumTitle.value,
      album_description: newAlbumDescription.value,
      album_public: newAlbumPublic.checked,
    };

    const csrfToken = document.querySelector(
      "[name=csrfmiddlewaretoken]",
    )?.value;

    fetch(config.urls.createAlbum, {
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
          bootstrap.Modal.getInstance(createAlbumModal).hide();
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

  // Helper function to add image to existing album
  function addImageToAlbum(imageId, albumId) {
    const data = {
      image_id: imageId,
      album_id: albumId,
    };

    const csrfToken = document.querySelector(
      "[name=csrfmiddlewaretoken]",
    )?.value;

    fetch(config.urls.addToAlbum, {
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

  // Helper function to remove image from album
  function removeImageFromAlbum(imageId, albumId) {
    const data = {
      image_id: imageId,
      album_id: albumId,
    };

    const csrfToken = document.querySelector(
      "[name=csrfmiddlewaretoken]",
    )?.value;

    fetch(config.urls.removeFromAlbum, {
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
});
