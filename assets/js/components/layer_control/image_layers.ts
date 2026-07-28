// Visibility and sizing of the georeferenced-image point layers added by
// map_display/data_layers.ts. The control owns their display state; the layers
// themselves may or may not exist, depending on the page.
import type { Map as MapLibreMap } from "maplibre-gl";
import { LAYER_IDS } from "../map_display/layer_ids";
import type { ImageDisplayStyle } from "./types";

export const SIMPLE_RADIUS_MIN = 2;
export const SIMPLE_RADIUS_MAX = 10;
export const DEFAULT_SIMPLE_RADIUS = 8;

const HEATMAP_LAYER_IDS = [
  LAYER_IDS.imageHeatmap,
  LAYER_IDS.imageCircles,
  LAYER_IDS.imageDirections,
];

const SIMPLE_LAYER_IDS = [
  LAYER_IDS.imageCirclesSimple,
  LAYER_IDS.imageDirectionsSimple,
];

// Interpolate a property linearly across the simple-mode radius range.
function scaleWithRadius(radius: number, atMin: number, atMax: number): number {
  const fraction =
    (radius - SIMPLE_RADIUS_MIN) / (SIMPLE_RADIUS_MAX - SIMPLE_RADIUS_MIN);
  return atMin + fraction * (atMax - atMin);
}

export function strokeWidthForRadius(radius: number): number {
  return scaleWithRadius(radius, 1, 2);
}

export function iconSizeForRadius(radius: number): number {
  return scaleWithRadius(radius, 0.4, 1.2);
}

function setLayersVisibility(
  map: MapLibreMap,
  layerIds: readonly string[],
  visible: boolean,
): void {
  for (const layerId of layerIds) {
    if (map.getLayer(layerId)) {
      map.setLayoutProperty(
        layerId,
        "visibility",
        visible ? "visible" : "none",
      );
    }
  }
}

export function updateImageLayerVisibility(
  map: MapLibreMap,
  visible: boolean,
  style: ImageDisplayStyle,
): void {
  setLayersVisibility(map, HEATMAP_LAYER_IDS, visible && style === "heatmap");
  setLayersVisibility(map, SIMPLE_LAYER_IDS, visible && style === "simple");
}

export function updateSimpleCircleRadius(
  map: MapLibreMap,
  radius: number,
): void {
  if (map.getLayer(LAYER_IDS.imageCirclesSimple)) {
    map.setPaintProperty(LAYER_IDS.imageCirclesSimple, "circle-radius", radius);
    map.setPaintProperty(
      LAYER_IDS.imageCirclesSimple,
      "circle-stroke-width",
      strokeWidthForRadius(radius),
    );
  }

  if (map.getLayer(LAYER_IDS.imageDirectionsSimple)) {
    map.setLayoutProperty(
      LAYER_IDS.imageDirectionsSimple,
      "icon-size",
      iconSizeForRadius(radius),
    );
  }
}
