// Standalone version of the OpenSeadragon branch of
// assets/js/components/image_viewer.ts. The demo runs as a native ES module
// with no bundler, so it cannot import the TypeScript component directly.
// Keep the viewer options and the "open" handler in sync with that file.
import OpenSeadragon from "openseadragon";
import { addViewerButtons } from "./osd_buttons.js";

export function initImageViewer() {
    const el = document.getElementById("osd-viewer");
    if (!el || !el.dataset.iiifUrl) {
        return;
    }

    const viewer = OpenSeadragon({
        element: el,
        showNavigationControl: false,
        visibilityRatio: 0.5,
        maxZoomPixelRatio: 4,
        minZoomImageRatio: 1,
        tileSources: [el.dataset.iiifUrl],
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
}
