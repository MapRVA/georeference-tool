/**
 * Shared popup builder for map image features.
 * Used by map_display.js and georeference_interface.js.
 */

/**
 * Build DOM content for a single image feature popup.
 */
export function buildPopupContent(properties) {
  const imgEntry = window.location.origin + "/" + properties.id + "/";
  const container = document.createElement("div");

  const imgLink = document.createElement("a");
  imgLink.href = imgEntry;

  const img = document.createElement("img");
  img.src = properties.thumbnail;
  img.style.cssText =
    "border-radius: 0.5em; width: 30em; max-width: 100%; height: auto;";
  imgLink.appendChild(img);
  container.appendChild(imgLink);

  const footer = document.createElement("div");
  footer.className =
    "d-flex align-items-center justify-content-between mt-1";

  if (properties.original_date) {
    const dateSpan = document.createElement("span");
    dateSpan.className = "text-muted";
    dateSpan.innerHTML =
      '<i class="fas fa-calendar me-1"></i>' + properties.original_date;
    footer.appendChild(dateSpan);
  }

  const link = document.createElement("a");
  link.href = imgEntry;
  link.className = "btn btn-primary btn-sm";
  link.innerHTML = '<i class="fas fa-eye me-1"></i>View';
  footer.appendChild(link);

  container.appendChild(footer);

  return container;
}

/**
 * Deduplicate an array of map features by properties.id.
 */
export function deduplicateFeatures(features) {
  const seen = new Set();
  return features.filter((f) => {
    const id = f.properties.id;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

/**
 * Build a popup DOM wrapper with navigation for multiple features.
 * For a single feature, returns just the content with no nav row.
 */
export function buildPopupWrapper(features) {
  const wrapper = document.createElement("div");
  const contentSlot = document.createElement("div");

  let currentIndex = 0;

  let prevBtn = null;
  let nextBtn = null;
  let navLabel = null;

  if (features.length > 1) {
    const navRow = document.createElement("div");
    navRow.className =
      "popup-nav-row d-flex align-items-center gap-2 mb-1";

    prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.className = "btn btn-sm btn-outline-secondary py-0 px-1";
    prevBtn.innerHTML = '<i class="fas fa-chevron-left"></i>';

    nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.className = "btn btn-sm btn-outline-secondary py-0 px-1";
    nextBtn.innerHTML = '<i class="fas fa-chevron-right"></i>';

    navLabel = document.createElement("span");
    navLabel.className = "text-muted small";

    navRow.appendChild(prevBtn);
    navRow.appendChild(navLabel);
    navRow.appendChild(nextBtn);
    wrapper.appendChild(navRow);
  }

  wrapper.appendChild(contentSlot);

  const showFeature = (index) => {
    currentIndex = index;
    contentSlot.replaceChildren(
      buildPopupContent(features[index].properties),
    );
    if (navLabel) {
      navLabel.textContent = index + 1 + " of " + features.length;
    }
    if (prevBtn) {
      prevBtn.disabled = index === 0;
    }
    if (nextBtn) {
      nextBtn.disabled = index === features.length - 1;
    }
  };

  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      if (currentIndex > 0) showFeature(currentIndex - 1);
    });
  }
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      if (currentIndex < features.length - 1)
        showFeature(currentIndex + 1);
    });
  }

  showFeature(0);

  return wrapper;
}
