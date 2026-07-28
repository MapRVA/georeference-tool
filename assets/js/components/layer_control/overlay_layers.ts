// Map operations behind the user-selected tile overlays (Sanborn maps and
// friends), served either as PMTiles archives or plain XYZ tiles.
import type { Map as MapLibreMap } from "maplibre-gl";
import type { MapLayerType } from "./types";

/**
 * PMTiles overlays need the protocol registered on maplibregl. Registration is
 * shared across bundles through window.setupPMTilesProtocol() — see
 * map_display/pmtiles_protocol.ts.
 */
export function ensurePMTilesProtocol(): boolean {
  if (window.pmtilesProtocolSetup) return true;

  console.error("PMTiles protocol not available! Attempting to set up now...");
  return window.setupPMTilesProtocol();
}

export function addOverlaySource(
  map: MapLibreMap,
  sourceId: string,
  tileUrl: string,
  tileType: MapLayerType,
  attribution: string,
): boolean {
  if (map.getSource(sourceId)) return true;

  try {
    if (tileType === "pmtiles") {
      map.addSource(sourceId, {
        type: "raster",
        url: `pmtiles://${tileUrl}`,
        tileSize: 256,
        attribution: attribution,
      });
    } else if (tileType === "xyz") {
      map.addSource(sourceId, {
        type: "raster",
        tiles: [tileUrl],
        tileSize: 256,
        attribution: attribution,
      });
    } else {
      console.error("Unsupported overlay tile type:", tileType);
      return false;
    }
  } catch (error) {
    console.error(`Error adding ${tileType} source:`, error);
    return false;
  }

  return true;
}

export function addOverlayLayer(
  map: MapLibreMap,
  layerId: string,
  sourceId: string,
  beforeId: string | undefined,
): boolean {
  try {
    map.addLayer(
      {
        id: layerId,
        source: sourceId,
        type: "raster",
        paint: {
          "raster-opacity": 1.0,
          "raster-fade-duration": 300,
          "raster-resampling": "linear",
        },
        layout: { visibility: "visible" },
      },
      beforeId,
    );
  } catch (error) {
    console.error("Error adding overlay layer:", error);
    return false;
  }

  return true;
}

/**
 * Only one tile overlay is shown at a time; hide any others left over from a
 * previous selection.
 */
export function hideOtherOverlayLayers(
  map: MapLibreMap,
  exceptLayerId: string,
): void {
  for (const layer of map.getStyle().layers) {
    if (layer.id.startsWith("overlay-") && layer.id !== exceptLayerId) {
      map.setLayoutProperty(layer.id, "visibility", "none");
    }
  }
}
