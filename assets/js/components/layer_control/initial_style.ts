import type { RasterSourceSpecification, StyleSpecification } from "maplibre-gl";
import type { MapLayersData, PrimaryLayerData } from "./types";

export const FALLBACK_MAP_STYLE_URL =
  "https://styles.maprva.org/openmaptiles-osm.json";

export function initialPrimaryLayer(
  data: MapLayersData | undefined = window.MAP_LAYERS_DATA,
): PrimaryLayerData | null {
  const primaryLayers = data?.primary_layers ?? [];
  return (
    primaryLayers.find((layer) => layer.is_default) ?? primaryLayers[0] ?? null
  );
}

export function rasterBaseLayerIds(slug: string): {
  sourceId: string;
  layerId: string;
} {
  return {
    sourceId: `base-${slug}`,
    layerId: `base-${slug}-layer`,
  };
}

export function initialMapStyle(
  data: MapLayersData | undefined = window.MAP_LAYERS_DATA,
): string | StyleSpecification {
  const layer = initialPrimaryLayer(data);
  if (!layer) return FALLBACK_MAP_STYLE_URL;
  if (layer.type === "style") return layer.url;

  const { sourceId, layerId } = rasterBaseLayerIds(layer.slug);
  const source: RasterSourceSpecification = {
    type: "raster",
    tileSize: 256,
    attribution: layer.attribution ?? "",
    ...(layer.type === "pmtiles"
      ? { url: `pmtiles://${layer.url}` }
      : { tiles: [layer.url] }),
  };

  return {
    version: 8,
    sources: { [sourceId]: source },
    layers: [{ id: layerId, type: "raster", source: sourceId }],
  };
}
