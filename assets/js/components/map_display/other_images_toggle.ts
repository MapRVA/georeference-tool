import type { Map as MapLibreMap } from "maplibre-gl";
import { LAYER_IDS } from "./layer_ids";

// Installs window.toggleOtherImages, the contract consumed by
// image_detail.js's "Show Other Images" checkbox handler.
export function installToggleOtherImages(map: MapLibreMap): void {
  let otherImagesLoaded = false;

  window.toggleOtherImages = function (showAll, onLoadCallback) {
    const visibility = showAll ? "visible" : "none";
    // Heatmap style layers
    if (map.getLayer(LAYER_IDS.imageHeatmap)) {
      map.setLayoutProperty(LAYER_IDS.imageHeatmap, "visibility", visibility);
    }
    if (map.getLayer(LAYER_IDS.imageCircles)) {
      map.setLayoutProperty(LAYER_IDS.imageCircles, "visibility", visibility);
    }
    if (map.getLayer(LAYER_IDS.imageDirections)) {
      map.setLayoutProperty(LAYER_IDS.imageDirections, "visibility", visibility);
    }
    // Simple style layers (keep hidden - they're controlled by LayerControl style toggle)
    if (map.getLayer(LAYER_IDS.imageCirclesSimple)) {
      map.setLayoutProperty(LAYER_IDS.imageCirclesSimple, "visibility", "none");
    }
    if (map.getLayer(LAYER_IDS.imageDirectionsSimple)) {
      map.setLayoutProperty(
        LAYER_IDS.imageDirectionsSimple,
        "visibility",
        "none",
      );
    }

    // Handle loading callback
    if (showAll && onLoadCallback) {
      if (otherImagesLoaded) {
        // Already loaded, call immediately
        onLoadCallback();
      } else {
        // Wait for idle event (tiles finished loading)
        const onIdle = function () {
          otherImagesLoaded = true;
          onLoadCallback();
          map.off("idle", onIdle);
        };
        map.on("idle", onIdle);
      }
    }
  };
}
