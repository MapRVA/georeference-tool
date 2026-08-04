import autoComplete from "@tarekraafat/autocomplete.js";
import Sortable from "sortablejs";

import "../../styles/components/autocomplete.css";
import "../../styles/components/subject-cards.css";

/**
 * Initialize the subject editor component
 * Reads configuration from data attributes on #subject-editor element
 */
export function initSubjectEditor() {
  const editorElement = document.getElementById("subject-editor");
  if (!editorElement) {
    return;
  }

  // Prevent double initialization
  if (editorElement.dataset.initialized === "true") {
    return;
  }
  editorElement.dataset.initialized = "true";

  const isAuthenticated = editorElement.dataset.authenticated === "true";
  if (!isAuthenticated) {
    return;
  }

  const urls = {
    addSubject: editorElement.dataset.addSubjectUrl,
    subjectAutocomplete: editorElement.dataset.autocompleteUrl,
    removeSubjectPattern: editorElement.dataset.removeSubjectUrl,
    setRepresentativePattern: editorElement.dataset.setRepresentativeUrl,
    reorderSubjects: editorElement.dataset.reorderUrl,
  };

  const addBtn = document.getElementById("add-subject-btn");
  const subjectInput = document.getElementById("subject-autocomplete");
  let subjectRow = document.getElementById("image-subjects-row");
  let sortableInstance = null;

  // Create the remove subject confirmation modal
  let removeSubjectModal = document.getElementById("removeSubjectModal");
  if (!removeSubjectModal) {
    removeSubjectModal = document.createElement("div");
    removeSubjectModal.id = "removeSubjectModal";
    removeSubjectModal.className = "modal fade";
    removeSubjectModal.tabIndex = -1;
    removeSubjectModal.innerHTML = `
      <div class="modal-dialog">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">Remove Subject</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <p>Are you sure you want to remove this subject from the image?</p>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
            <button type="button" class="btn btn-danger" id="confirmRemoveSubjectBtn">
              <i class="fas fa-times me-1"></i>Remove
            </button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(removeSubjectModal);
  }

  const bsRemoveModal = new bootstrap.Modal(removeSubjectModal);
  let pendingRemoval = null;

  function addSubjectByWikidataId(wikidataId) {
    if (!wikidataId || !wikidataId.match(/^Q\d+$/)) {
      showAlert(
        "danger",
        "Invalid Wikidata ID format. Must be Q followed by numbers (e.g., Q123456)",
      );
      return;
    }

    addBtn.disabled = true;
    const originalText = addBtn.innerHTML;
    addBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Adding...';

    const csrfToken = document.querySelector(
      '[name="csrfmiddlewaretoken"]',
    )?.value;

    fetch(urls.addSubject, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      },
      body: JSON.stringify({ wikidata_id: wikidataId }),
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().then((err) => {
            throw new Error(err.error || "Server error");
          });
        }
        return response.json();
      })
      .then((data) => {
        if (data.success) {
          showAlert("success", data.message);
          subjectInput.value = "";

          // Insert the new subject card HTML
          insertSubjectCard(data.html);
        } else {
          showAlert("danger", data.error);
        }
      })
      .catch((error) => {
        showAlert("danger", `Error adding subject: ${error.message}`);
      })
      .finally(() => {
        addBtn.disabled = false;
        addBtn.innerHTML = originalText;
      });
  }

  function insertSubjectCard(html) {
    // If the subjects row doesn't exist, create it and remove empty message
    if (!subjectRow) {
      const noSubjectsMessage = document.getElementById("no-subjects-message");
      if (noSubjectsMessage) {
        noSubjectsMessage.remove();
      }

      // Create the subjects row
      subjectRow = document.createElement("div");
      subjectRow.className = "row g-3";
      subjectRow.id = "image-subjects-row";

      // Insert it into the card body
      const cardBody = editorElement.querySelector(".card-body");
      cardBody.appendChild(subjectRow);

      // Initialize sortable on the new row
      initSortable();
    }

    // Parse the HTML and get the new card element
    const temp = document.createElement("div");
    temp.innerHTML = html;
    const newCard = temp.firstElementChild;

    // Add initial styles for fade-in animation
    newCard.style.opacity = "0";
    newCard.style.transform = "scale(0.9)";

    // Append to the row
    subjectRow.appendChild(newCard);

    // Trigger the animation
    requestAnimationFrame(() => {
      newCard.style.transition =
        "opacity 0.3s ease-out, transform 0.3s ease-out";
      newCard.style.opacity = "1";
      newCard.style.transform = "scale(1)";
    });
  }

  function initSortable() {
    if (!subjectRow || sortableInstance) return;

    sortableInstance = new Sortable(subjectRow, {
      animation: 150,
      handle: ".drag-handle",
      filter: ".remove-subject, .set-representative",
      preventOnFilter: true,
      onEnd: function () {
        const subjectCards = subjectRow.querySelectorAll(".subject-card");
        const newOrder = Array.from(subjectCards).map(
          (card) => card.dataset.subjectRelationId,
        );

        const csrfToken = document.querySelector(
          '[name="csrfmiddlewaretoken"]',
        ).value;

        fetch(urls.reorderSubjects, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken,
          },
          body: JSON.stringify({ order: newOrder }),
        })
          .then((response) => response.json())
          .then((data) => {
            if (data.success) {
              showAlert("success", "Subject order updated.");
            } else {
              showAlert("danger", "Error updating order: " + data.error);
            }
          })
          .catch((error) => {
            showAlert(
              "danger",
              "An unexpected error occurred while reordering.",
            );
            console.error("Error:", error);
          });
      },
    });
  }

  // Add button click handler
  if (addBtn) {
    addBtn.addEventListener("click", function (e) {
      e.preventDefault();
      const inputValue = subjectInput.value.trim();
      if (inputValue.match(/^Q\d+$/)) {
        addSubjectByWikidataId(inputValue);
      } else {
        showAlert(
          "info",
          "Please select a subject from the suggestions or enter a valid Wikidata ID.",
        );
      }
    });
  }

  // Allow Enter key to submit Wikidata ID
  if (subjectInput) {
    subjectInput.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        const inputValue = subjectInput.value.trim();
        if (inputValue.match(/^Q\d+$/)) {
          addSubjectByWikidataId(inputValue);
        }
      }
    });
  }

  // Initialize autocomplete
  if (subjectInput) {
    const subjectAutocomplete = new autoComplete({
      selector: "#subject-autocomplete",
      placeHolder: "Search for a subject by name...",
      data: {
        src: async (query) => {
          try {
            const source = await fetch(
              `${urls.subjectAutocomplete}?q=${query}`,
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
            <span style="text-overflow: ellipsis; white-space: nowrap; overflow: hidden;">
                ${data.match} <small class="text-muted ms-2">${description}</small>
            </span>
            <span style="display: flex; align-items: center; font-size: 13px; font-weight: 100; text-transform: uppercase; color: rgba(0,0,0,.5);">
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
            subjectAutocomplete.input.value = selection.title;
            if (selection.wikidata_id) {
              addSubjectByWikidataId(selection.wikidata_id);
            }
          },
        },
      },
    });
  }

  // Remove subject - show modal
  document.addEventListener("click", function (e) {
    const removeButton = e.target.closest(".remove-subject");
    if (!removeButton) return;

    const subjectRelationId = removeButton.dataset.subjectRelationId;
    const cardWrapper = removeButton.closest(".subject-card-wrapper");

    if (!subjectRelationId) return;

    // Store pending removal info and show modal
    pendingRemoval = {
      subjectRelationId,
      cardWrapper,
      removeButton,
      originalIcon: removeButton.innerHTML,
    };
    bsRemoveModal.show();
  });

  // Confirm remove subject
  document
    .getElementById("confirmRemoveSubjectBtn")
    .addEventListener("click", function () {
      if (!pendingRemoval) return;

      const { subjectRelationId, cardWrapper, removeButton, originalIcon } =
        pendingRemoval;

      bsRemoveModal.hide();

      removeButton.disabled = true;
      removeButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

      const csrfToken = document.querySelector(
        '[name="csrfmiddlewaretoken"]',
      )?.value;
      const url = urls.removeSubjectPattern.replace(
        "/0/",
        `/${subjectRelationId}/`,
      );

      fetch(url, {
        method: "POST",
        headers: {
          "X-CSRFToken": csrfToken,
        },
      })
        .then((response) => {
          if (!response.ok) {
            return response
              .json()
              .catch(() => null)
              .then((errorData) => {
                throw new Error(errorData?.error || response.statusText);
              });
          }
          return response.json();
        })
        .then((data) => {
          if (data.success) {
            showAlert("success", data.message);
            if (cardWrapper) {
              cardWrapper.style.transition =
                "opacity 0.3s ease-out, transform 0.3s ease-out";
              cardWrapper.style.opacity = "0";
              cardWrapper.style.transform = "scale(0.9)";
              setTimeout(() => {
                cardWrapper.remove();
                // Check if we need to show the empty message
                subjectRow = document.getElementById("image-subjects-row");
                if (subjectRow && subjectRow.children.length === 0) {
                  subjectRow.remove();
                  subjectRow = null;
                  sortableInstance = null;

                  // Add the empty message back
                  const cardBody = editorElement.querySelector(".card-body");
                  const emptyMessage = document.createElement("div");
                  emptyMessage.className = "text-center py-4";
                  emptyMessage.id = "no-subjects-message";
                  emptyMessage.innerHTML =
                    '<p class="text-muted">No subjects have been assigned to this image yet.</p>';
                  cardBody.appendChild(emptyMessage);
                }
              }, 300);
            }
          } else {
            showAlert("danger", data.error || "An unknown error occurred.");
            removeButton.disabled = false;
            removeButton.innerHTML = originalIcon;
          }
        })
        .catch((error) => {
          console.error("Error:", error);
          showAlert("danger", `Error removing subject: ${error.message}`);
          removeButton.disabled = false;
          removeButton.innerHTML = originalIcon;
        })
        .finally(() => {
          pendingRemoval = null;
        });
    });

  // Clear pending removal when modal is hidden
  removeSubjectModal.addEventListener("hidden.bs.modal", function () {
    pendingRemoval = null;
  });

  // Set representative image
  document.addEventListener("click", function (e) {
    const starButton = e.target.closest(".set-representative");
    if (!starButton) return;

    const subjectId = starButton.dataset.subjectId;
    if (!subjectId) return;

    const csrfToken = document.querySelector(
      '[name="csrfmiddlewaretoken"]',
    )?.value;
    const url = urls.setRepresentativePattern.replace("/0/", `/${subjectId}/`);

    starButton.disabled = true;
    const originalIcon = starButton.innerHTML;
    starButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    fetch(url, {
      method: "POST",
      headers: {
        "X-CSRFToken": csrfToken,
      },
    })
      .then((response) => {
        if (!response.ok) {
          return response
            .json()
            .catch(() => null)
            .then((errorData) => {
              throw new Error(errorData?.error || response.statusText);
            });
        }
        return response.json();
      })
      .then((data) => {
        if (data.success) {
          showAlert("success", data.message);
          const card = starButton.closest(".subject-card");
          // Hide the "set representative" option now that this image is the representative
          starButton.closest("li")?.remove();

          // Swap thumbnail in the subject card
          if (data.thumbnail && card) {
            const existingImg = card.querySelector(".card-img-top");
            if (existingImg) {
              if (existingImg.tagName === "IMG") {
                existingImg.src = data.thumbnail;
              } else {
                // Replace placeholder div with an img inside a link
                const subjectUrl =
                  card.querySelector(".card-body a")?.href || "#";
                const link = document.createElement("a");
                link.href = subjectUrl;
                link.className = "d-block";
                link.innerHTML = `<img src="${data.thumbnail}" alt="" class="card-img-top" loading="lazy" style="height: 150px; object-fit: cover;">`;
                existingImg.replaceWith(link);
              }
            }
          }
        } else {
          showAlert("danger", data.error || "An unknown error occurred.");
        }
      })
      .catch((error) => {
        console.error("Error:", error);
        showAlert(
          "danger",
          `Error setting representative image: ${error.message}`,
        );
      })
      .finally(() => {
        starButton.disabled = false;
        starButton.innerHTML = originalIcon;
      });
  });

  // Initialize sortable for drag-and-drop reordering
  initSortable();
}
