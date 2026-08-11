// A vertical centerline overlay on the OpenSeadragon image viewer, shown
// alongside the map's bearing line so the user can line the two up.
import OpenSeadragon from "openseadragon";
import type { OsdViewerElement } from "../../components/image_viewer";
import type { GeoreferenceContext } from "./types";

export function initOsdCenterline(ctx: GeoreferenceContext): void {
  const { state } = ctx;
  const osdEl = document.getElementById("osd-viewer") as OsdViewerElement | null;
  const osdViewer = osdEl?.osdViewer;
  if (!osdViewer) return;

  osdViewer.addHandler("open", () => {
    const contentSize = osdViewer.world.getItemAt(0).getContentSize();

    const overlay = document.createElement("div");
    overlay.className = "image-centerline-overlay";
    overlay.style.visibility = "hidden";
    state.osdCenterlineOverlay = overlay;

    // The overlay is positioned in image pixels, so convert to viewport
    // coordinates first.
    const bounds = osdViewer.viewport.imageToViewportRectangle(
      new OpenSeadragon.Rect(contentSize.x / 2, 0, 0, contentSize.y),
    );
    osdViewer.addOverlay({
      element: overlay,
      location: bounds.getTopLeft(),
      width: bounds.width,
      height: bounds.height,
    });

    // Show immediately if bearing line is already enabled
    if (
      state.bearingLineEnabled &&
      state.pinPlaced &&
      state.currentDirection !== null
    ) {
      overlay.style.visibility = "visible";
    }
  });
}
