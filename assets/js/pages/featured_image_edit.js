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

  // Keep the avatar in the field's prefix in sync with the selected user.
  const avatarImg = document.getElementById("featured-image-user-avatar");
  const avatarFallback = document.getElementById(
    "featured-image-user-avatar-fallback",
  );
  const setAvatar = (url, hasUser) => {
    if (!avatarImg || !avatarFallback) return;
    if (url) {
      avatarImg.src = url;
      avatarImg.style.display = "";
      avatarFallback.style.display = "none";
    } else {
      avatarImg.style.display = "none";
      // Only show the standin icon for a selected user with no picture; show
      // nothing when there's no assignment at all.
      // inline-flex (not "") so the span keeps centering the icon in its box.
      avatarFallback.style.display = hasUser ? "inline-flex" : "none";
    }
  };

  // The avatar prefix only makes sense at rest. While searching it's hidden and
  // the input's extra left padding (set in the template) is dropped, so the
  // field reads as a normal text box.
  const avatarWrap = avatarImg ? avatarImg.parentElement : null;
  // The padding that makes room for the avatar prefix. Kept as a constant
  // rather than read from the input, since the template omits it when no user
  // is selected (so there's nothing to read at load).
  const paddedLeft = "2.25rem";
  const showAvatarPrefix = (show) => {
    if (avatarWrap) {
      // The wrap uses d-flex (display: flex !important), so an inline
      // display:none can't hide it — toggle the Bootstrap classes instead.
      avatarWrap.classList.toggle("d-flex", show);
      avatarWrap.classList.toggle("d-none", !show);
    }
    searchInput.style.paddingLeft = show ? paddedLeft : "";
  };

  // The committed selection — what the field reverts to if the admin clicks in
  // to search but doesn't pick a new user. Seeded from the rendered values.
  let committed = {
    id: userIdInput.value || "",
    name: searchInput.value || "",
    picture:
      (avatarImg &&
        avatarImg.style.display !== "none" &&
        avatarImg.getAttribute("src")) ||
      "",
  };

  const applyCommitted = () => {
    searchInput.value = committed.name;
    userIdInput.value = committed.id;
    // No selection means no prefix at all, so the placeholder isn't indented.
    showAvatarPrefix(Boolean(committed.id));
    setAvatar(committed.picture || null, Boolean(committed.id));
  };

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
        item.style = "display: flex; align-items: center;";
        // Image and standin share one identical box, so the gap to the
        // username (me-2 on the box) is the same whether or not there's a pic.
        const avatarInner = data.value.picture
          ? `<img src="${data.value.picture}" alt="" class="rounded-circle" style="height: 100%; width: 100%; object-fit: cover;">`
          : `<i class="fas fa-user-circle text-muted" style="font-size: 1.5em;"></i>`;
        const avatar = `<span class="me-2 d-inline-flex align-items-center justify-content-center flex-shrink-0" style="width: 1.5em; height: 1.5em;">${avatarInner}</span>`;
        item.innerHTML = `
          ${avatar}
          <span>${data.match}</span>
          <small class="text-muted ms-2">${data.value.username}</small>`;
      },
    },
    threshold: 2,
    events: {
      input: {
        selection: (event) => {
          const selection = event.detail.selection.value;
          committed = {
            id: String(selection.id),
            name: selection.name,
            picture: selection.picture || "",
          };
          applyCommitted();
          searchInput.blur();
        },
      },
    },
  });

  // Clicking in clears the visible text so the admin can search from scratch,
  // and suppresses the avatar (they're either typing a search or have nothing
  // selected). The committed user id is left intact, so submitting mid-search
  // still saves the current assignment rather than wiping it.
  searchInput.addEventListener("focus", function () {
    searchInput.value = "";
    showAvatarPrefix(false);
  });

  // Leaving the field without picking a new user restores the committed one.
  // The short delay lets a result click commit its selection first (the blur
  // fires before the selection event when a result is clicked).
  searchInput.addEventListener("blur", function () {
    setTimeout(applyCommitted, 150);
  });

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      committed = { id: "", name: "", picture: "" };
      applyCommitted();
      searchInput.focus();
    });
  }
});
