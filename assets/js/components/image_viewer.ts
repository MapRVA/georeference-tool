import OpenSeadragon from "openseadragon";
import { addViewerButtons } from "./osd_buttons";

// #osd-viewer carries its live viewer, so other bundles (e.g. the point
// georeference interface's centerline overlay) can reach it.
export interface OsdViewerElement extends HTMLElement {
  osdViewer?: OpenSeadragon.Viewer;
}

export function initImageViewer(): void {
  const osdEl = document.getElementById(
    "osd-viewer",
  ) as OsdViewerElement | null;
  if (osdEl) {
    initOSDViewer(osdEl);
    return;
  }

  // Fallback: wire up broken-image handling for plain <img>
  const mainImage = document.getElementById("main-image");
  const imageFallback = document.getElementById("image-fallback");
  if (!(mainImage instanceof HTMLImageElement) || !imageFallback) return;

  const showImage = (): void => {
    imageFallback.style.setProperty("display", "none", "important");
    mainImage.style.display = "block";
    mainImage.style.visibility = "visible";
  };

  const showFallback = (): void => {
    mainImage.style.display = "none";
    imageFallback.style.setProperty("display", "flex", "important");
  };

  mainImage.onload = showImage;
  mainImage.onerror = showFallback;

  if (mainImage.complete) {
    if (mainImage.naturalHeight !== 0 && mainImage.naturalWidth !== 0) {
      showImage();
    } else {
      showFallback();
    }
  }
}

function initOSDViewer(el: OsdViewerElement): void {
  const iiifUrl = el.dataset.iiifUrl;
  if (!iiifUrl) return;

  const viewer = OpenSeadragon({
    element: el,
    showNavigationControl: false,
    visibilityRatio: 0.5,
    maxZoomPixelRatio: 4,
    minZoomImageRatio: 1,
    tileSources: [iiifUrl],
    drawer: "canvas",
  });

  viewer.addHandler("open", () => {
    const size = viewer.world.getItemAt(0).getContentSize();
    el.style.aspectRatio = `${size.x} / ${size.y}`;
    // The aspect-ratio change resizes the container; wait for layout, then
    // re-fit so the image meets the edges instead of leaving margin.
    requestAnimationFrame(() => {
      viewer.viewport.resize(
        new OpenSeadragon.Point(el.clientWidth, el.clientHeight),
        false,
      );
      viewer.viewport.goHome(true);
    });
  });

  addViewerButtons(viewer, el);

  // Expose viewer so other scripts (e.g. georeference interface) can access it
  el.osdViewer = viewer;
}
