import OpenSeadragon from "openseadragon";
import { addViewerButtons } from "./osd_buttons";

export function initImageViewer() {
  const osdEl = document.getElementById("osd-viewer");
  if (osdEl) {
    initOSDViewer(osdEl);
    return;
  }

  // Fallback: wire up broken-image handling for plain <img>
  const mainImage = document.getElementById("main-image");
  const imageFallback = document.getElementById("image-fallback");

  if (mainImage && imageFallback) {
    mainImage.onload = function () {
      imageFallback.style.setProperty("display", "none", "important");
      mainImage.style.display = "block";
      mainImage.style.visibility = "visible";
    };

    mainImage.onerror = function () {
      mainImage.style.display = "none";
      imageFallback.style.setProperty("display", "flex", "important");
    };

    if (mainImage.complete) {
      if (mainImage.naturalHeight !== 0 && mainImage.naturalWidth !== 0) {
        imageFallback.style.setProperty("display", "none", "important");
        mainImage.style.display = "block";
        mainImage.style.visibility = "visible";
      } else {
        mainImage.style.display = "none";
        imageFallback.style.setProperty("display", "flex", "important");
      }
    }
  }
}

function initOSDViewer(el) {
  const iiifUrl = el.dataset.iiifUrl;
  if (!iiifUrl) return;

  const viewer = OpenSeadragon({
    element: el,
    showNavigationControl: false,
    visibilityRatio: 0.5,
    maxZoomPixelRatio: 4,
    minZoomLevel: 0.5,
    defaultZoomLevel: 1,
    tileSources: [iiifUrl],
    drawer: "canvas",
  });

  viewer.addHandler("open", function () {
    const size = viewer.world.getItemAt(0).getContentSize();
    el.style.aspectRatio = `${size.x} / ${size.y}`;
  });

  addViewerButtons(viewer, el);

  // Expose viewer so other scripts (e.g. georeference interface) can access it
  el.osdViewer = viewer;
}
