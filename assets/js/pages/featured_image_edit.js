import autoComplete from "@tarekraafat/autocomplete.js";
import "../../styles/components/autocomplete.css";

document.addEventListener("DOMContentLoaded", function () {
  // A date only matters while locked: unlocking frees the image from a
  // specific day, so disable the date field whenever the lock is off.
  const lockSwitch = document.getElementById("featured-image-locked");
  const dayInput = document.getElementById("featured-image-day");
  if (lockSwitch && dayInput) {
    const syncDayState = () => {
      dayInput.disabled = !lockSwitch.checked;
    };
    syncDayState();
    lockSwitch.addEventListener("change", syncDayState);
  }

  const searchInput = document.getElementById("featured-image-user-search");
  const userIdInput = document.getElementById("featured-image-user-id");
  const clearBtn = document.getElementById("featured-image-user-clear");
  if (!searchInput || !userIdInput) return;

  const autocompleteUrl = searchInput.dataset.autocompleteUrl;

  const userAutocomplete = new autoComplete({
    selector: "#featured-image-user-search",
    placeHolder: "Search by name or username...",
    data: {
      src: async (query) => {
        try {
          const response = await fetch(
            `${autocompleteUrl}?q=${encodeURIComponent(query)}`,
          );
          return await response.json();
        } catch (error) {
          return [];
        }
      },
      keys: ["name"],
      cache: false,
    },
    resultItem: {
      highlight: true,
      element: (item, data) => {
        item.style =
          "display: flex; justify-content: space-between; align-items: center;";
        item.innerHTML = `
          <span>${data.match}</span>
          <small class="text-muted ms-2">${data.value.username}</small>`;
      },
    },
    threshold: 2,
    events: {
      input: {
        selection: (event) => {
          const selection = event.detail.selection.value;
          userAutocomplete.input.value = selection.name;
          userIdInput.value = selection.id;
        },
      },
    },
  });

  // Typing by hand invalidates any prior selection until a new one is picked,
  // so we never submit a stale user id that doesn't match the visible text.
  searchInput.addEventListener("input", function () {
    userIdInput.value = "";
  });

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      searchInput.value = "";
      userIdInput.value = "";
      searchInput.focus();
    });
  }
});
