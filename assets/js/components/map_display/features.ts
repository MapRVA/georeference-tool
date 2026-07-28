import maplibregl from "maplibre-gl";
import { LAYER_IDS, SOURCE_IDS } from "./layer_ids";
import { TimeSliderControl } from "./time_slider_control";
import type { MapDisplayContext } from "./types";

// Watches for the images source's first load, then adds the time slider
// (when the features span multiple years) and performs the zoom-to-contents
// fit. Tile loading can race the sourcedata event, hence the retry.
export function watchInitialFeatures(ctx: MapDisplayContext): void {
  const { map, config } = ctx;

  let initialFeaturesLoaded = false;
  map.on("sourcedata", function (e) {
    if (
      e.sourceId === SOURCE_IDS.images &&
      e.isSourceLoaded &&
      !initialFeaturesLoaded
    ) {
      let features = map.querySourceFeatures(SOURCE_IDS.images, {
        sourceLayer: "image_points",
      });

      if (features.length === 0 && map.getLayer(LAYER_IDS.imageCircles)) {
        features = map.queryRenderedFeatures({
          layers: [LAYER_IDS.imageCircles],
        });
      }

      if (features.length > 0) {
        initialFeaturesLoaded = true;
        processFeatures(features);
      } else {
        setTimeout(() => {
          if (initialFeaturesLoaded) return;
          const retryFeatures = map.querySourceFeatures(SOURCE_IDS.images, {
            sourceLayer: "image_points",
          });

          if (retryFeatures.length > 0) {
            initialFeaturesLoaded = true;
            processFeatures(retryFeatures);
          }
        }, 1000);
      }
    }
  });

  function processFeatures(features: maplibregl.GeoJSONFeature[]) {
    // Calculate date range for time slider
    let minYear: number | null = null;
    let maxYear: number | null = null;
    features.forEach((feature) => {
      const props = feature.properties;
      if (props.fuzzy_start_decdate) {
        if (minYear === null || props.fuzzy_start_decdate < minYear) {
          minYear = props.fuzzy_start_decdate;
        }
      }
      const yearForMax = props.fuzzy_end_decdate || props.fuzzy_start_decdate;
      if (yearForMax) {
        if (maxYear === null || yearForMax > maxYear) {
          maxYear = yearForMax;
        }
      }
    });

    // Add time slider if valid date range and not single image view
    if (
      minYear !== null &&
      maxYear !== null &&
      minYear < maxYear &&
      !config.imageId
    ) {
      const timeSlider = new TimeSliderControl(minYear, maxYear, config.mapId);
      // Insert time slider after layer control but before other controls
      const layerControlElement = map
        .getContainer()
        .querySelector(".layer-control");
      if (layerControlElement && layerControlElement.parentNode) {
        const timeSliderElement = timeSlider.onAdd(map);
        layerControlElement.parentNode.insertBefore(
          timeSliderElement,
          layerControlElement.nextSibling,
        );
      } else {
        // Fallback to regular positioning
        map.addControl(timeSlider, "top-right");
      }
    }

    // Handle zoom to contents - fit map to all feature bounds
    if (config.zoomToContents && features.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      features.forEach(function (feature) {
        if (feature.geometry.type !== "Point") return;
        bounds.extend(feature.geometry.coordinates as [number, number]);
      });
      map.fitBounds(bounds, {
        padding: 50,
        maxZoom: 15,
      });
    }
  }
}
