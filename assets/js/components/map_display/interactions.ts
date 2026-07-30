import maplibregl from "maplibre-gl";
import { deduplicateFeatures, buildPopupWrapper } from "../map_popup";
import { LAYER_IDS } from "./layer_ids";
import type { MapDisplayContext } from "./types";

// Registers popup click handlers and hover cursor changes for the image
// circle layers. No-op on single-image maps without other images shown.
export function registerImageInteractions(ctx: MapDisplayContext): void {
  const { map, config, scaleHelpers } = ctx;
  const { imageId, showOtherImages, enableScaleVisibility } = config;

  // Add click handlers for image markers
  if (imageId && !showOtherImages) return;

  // Helper function to handle circle layer click
  const handleCircleClick = function (
    e: maplibregl.MapLayerMouseEvent,
    checkScaleVisibility: boolean,
  ) {
    if (!e.features?.length) return;

    // Filter features by scale visibility if needed
    let features = e.features;
    if (checkScaleVisibility && enableScaleVisibility) {
      const zoom = map.getZoom();
      features = features.filter((f) => {
        const scale =
          !f.properties.scale || f.properties.scale === 0
            ? 6
            : f.properties.scale;
        return scaleHelpers.isFullDetail(scale, zoom);
      });
      if (features.length === 0) return;
    }

    features = deduplicateFeatures(features);

    new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setDOMContent(buildPopupWrapper(features))
      .addTo(map);
  };

  // Helper function to handle circle layer mouseenter
  const handleCircleMouseenter = function (
    e: maplibregl.MapLayerMouseEvent,
    checkScaleVisibility: boolean,
  ) {
    if (checkScaleVisibility && enableScaleVisibility) {
      const firstFeature = e.features?.[0];
      if (!firstFeature) return;
      const properties = firstFeature.properties;
      const scale =
        !properties.scale || properties.scale === 0 ? 6 : properties.scale;
      const zoom = map.getZoom();

      if (scaleHelpers.isFullDetail(scale, zoom)) {
        map.getCanvas().style.cursor = "pointer";
      } else {
        map.getCanvas().style.cursor = "";
      }
    } else {
      map.getCanvas().style.cursor = "pointer";
    }
  };

  // Heatmap style circle layer handlers
  map.on("click", LAYER_IDS.imageCircles, (e) => handleCircleClick(e, true));
  map.on("mouseenter", LAYER_IDS.imageCircles, (e) =>
    handleCircleMouseenter(e, true),
  );
  map.on("mouseleave", LAYER_IDS.imageCircles, () => {
    map.getCanvas().style.cursor = "";
  });

  // Simple style circle layer handlers (no scale visibility checks)
  map.on("click", LAYER_IDS.imageCirclesSimple, (e) =>
    handleCircleClick(e, false),
  );
  map.on("mouseenter", LAYER_IDS.imageCirclesSimple, (e) =>
    handleCircleMouseenter(e, false),
  );
  map.on("mouseleave", LAYER_IDS.imageCirclesSimple, () => {
    map.getCanvas().style.cursor = "";
  });
}
