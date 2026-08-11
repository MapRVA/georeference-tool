import maplibregl from "maplibre-gl";
import { LAYER_IDS, SOURCE_IDS } from "./layer_ids";
import { insertTimeSlider, TimeSliderControl } from "./time_slider_control";
import type { MapDisplayContext } from "./types";

export interface YearRange {
  minYear: number;
  maxYear: number;
}

// Min/max years across the features' fuzzy EDTF date properties; null when no
// feature carries a date.
export function computeYearRange(
  features: maplibregl.GeoJSONFeature[],
): YearRange | null {
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
  if (minYear === null || maxYear === null) return null;
  return { minYear, maxYear };
}

export interface SourceFeaturesWatch {
  sourceId: string;
  sourceLayer: string;
  // Layer to query rendered features from when the source query returns none
  fallbackLayerId?: string;
}

// Invokes onFeatures once, with the first non-empty batch of features from the
// source. Tile loading can race the sourcedata event, hence the retry.
export function watchFirstSourceFeatures(
  map: maplibregl.Map,
  watch: SourceFeaturesWatch,
  onFeatures: (features: maplibregl.GeoJSONFeature[]) => void,
): void {
  let loaded = false;
  map.on("sourcedata", (e) => {
    if (e.sourceId !== watch.sourceId || !e.isSourceLoaded || loaded) return;

    let features = map.querySourceFeatures(watch.sourceId, {
      sourceLayer: watch.sourceLayer,
    });

    if (
      features.length === 0 &&
      watch.fallbackLayerId &&
      map.getLayer(watch.fallbackLayerId)
    ) {
      features = map.queryRenderedFeatures({
        layers: [watch.fallbackLayerId],
      });
    }

    if (features.length > 0) {
      loaded = true;
      onFeatures(features);
    } else {
      setTimeout(() => {
        if (loaded) return;
        const retryFeatures = map.querySourceFeatures(watch.sourceId, {
          sourceLayer: watch.sourceLayer,
        });

        if (retryFeatures.length > 0) {
          loaded = true;
          onFeatures(retryFeatures);
        }
      }, 1000);
    }
  });
}

// Watches for the images source's first load, then adds the time slider
// (when the features span multiple years) and performs the zoom-to-contents
// fit.
export function watchInitialFeatures(ctx: MapDisplayContext): void {
  const { map, config } = ctx;

  watchFirstSourceFeatures(
    map,
    {
      sourceId: SOURCE_IDS.images,
      sourceLayer: "image_points",
      fallbackLayerId: LAYER_IDS.imageCircles,
    },
    (features) => {
      // Add time slider if valid date range and not single image view
      const range = computeYearRange(features);
      if (range && range.minYear < range.maxYear && !config.imageId) {
        const timeSlider = new TimeSliderControl(
          range.minYear,
          range.maxYear,
          config.mapId,
        );
        insertTimeSlider(map, timeSlider);
        ctx.timeSlider = timeSlider;
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
    },
  );
}
