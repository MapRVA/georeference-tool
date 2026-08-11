// Map operations behind the base-layer options: raster (XYZ or PMTiles) base
// layers get their own source/layer, while the initial MapLibre style is shown
// and hidden in place.
import type { Map as MapLibreMap } from "maplibre-gl";
import type { BaseLayer, RasterBaseLayer } from "./types";

export function setupRasterBaseLayer(
  map: MapLibreMap,
  sourceId: string,
  layerId: string,
  url: string,
  attribution: string,
  tileType: RasterBaseLayer["type"],
): void {
  if (!map.getSource(sourceId)) {
    if (tileType === "pmtiles") {
      map.addSource(sourceId, {
        type: "raster",
        url: `pmtiles://${url}`,
        tileSize: 256,
        attribution: attribution,
      });
    } else {
      map.addSource(sourceId, {
        type: "raster",
        tiles: [url],
        tileSize: 256,
        attribution: attribution,
      });
    }
  }

  if (!map.getLayer(layerId)) {
    map.addLayer({
      id: layerId,
      type: "raster",
      source: sourceId,
      layout: { visibility: "none" },
    });
  }
}

export function setRasterBaseLayerVisibility(
  map: MapLibreMap,
  layerId: string,
  visible: boolean,
): void {
  if (map.getLayer(layerId)) {
    map.setLayoutProperty(layerId, "visibility", visible ? "visible" : "none");
  }
}

export function hideRasterBaseLayers(
  map: MapLibreMap,
  baseLayers: Record<string, BaseLayer>,
  exceptLayerId?: string,
): void {
  for (const baseLayer of Object.values(baseLayers)) {
    if (baseLayer.type !== "style" && baseLayer.layerId !== exceptLayerId) {
      setRasterBaseLayerVisibility(map, baseLayer.layerId, false);
    }
  }
}

/**
 * Show or hide every layer belonging to the map's own style, leaving overlays
 * and custom raster base layers untouched.
 */
export function setDefaultStyleLayersVisibility(
  map: MapLibreMap,
  visible: boolean,
  isDefaultStyleLayer: (layerId: string) => boolean,
): void {
  for (const layer of map.getStyle().layers) {
    if (isDefaultStyleLayer(layer.id)) {
      map.setLayoutProperty(
        layer.id,
        "visibility",
        visible ? "visible" : "none",
      );
    }
  }
}

/**
 * Move a base layer below all overlay layers so overlays remain visible.
 */
export function moveBaseLayerBelowOverlays(
  map: MapLibreMap,
  layerId: string,
  isOverlay: (layerId: string) => boolean,
): void {
  const firstOverlay = map
    .getStyle()
    .layers.find((layer) => isOverlay(layer.id));
  if (firstOverlay) {
    map.moveLayer(layerId, firstOverlay.id);
  }
}
