import OpenSeadragon from "openseadragon";
import { addViewerButtons } from "../components/osd_buttons";
import "../../styles/components/timeline.css";

const el = document.getElementById("osd-viewer");
if (el) {
  const iiifInfoUrl = el.dataset.iiifInfo;
  const entry = JSON.parse(el.dataset.entry || "{}");

  const viewer = OpenSeadragon({
    element: el,
    showNavigationControl: false,
    visibilityRatio: 1,
    minZoomLevel: 0.5,
    defaultZoomLevel: 0,
    gestureSettingsMouse: { scrollToZoom: true },
    tileSources: [iiifInfoUrl],
    drawer: "canvas",
  });

  addViewerButtons(viewer, el);

  viewer.addHandler("open", () => {
    if (entry.x == null) return;

    // Draw overlay on the entry's bounding box
    const rect = viewer.viewport.imageToViewportRectangle(
      entry.x, entry.y, entry.w, entry.h,
    );
    const overlay = document.createElement("div");
    overlay.className = "annotation-overlay active";
    viewer.addOverlay({ element: overlay, location: rect });

    // Zoom to the entry with padding
    viewer.viewport.fitBounds(
      new OpenSeadragon.Rect(
        rect.x - rect.width * 0.3,
        rect.y - rect.height * 0.3,
        rect.width * 1.6,
        rect.height * 1.6,
      ),
    );
  });
}
