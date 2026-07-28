import maplibregl from "maplibre-gl";
import type { MultiPolygon, Polygon, Position } from "geojson";

// Bounds of the outer ring of a Polygon/MultiPolygon, optionally extended
// with an extra point. Returns null when the geometry has no coordinates.
export function boundsFromAerialGeometry(
  geometry: Polygon | MultiPolygon,
  extraPoint?: [number, number] | null,
): maplibregl.LngLatBounds | null {
  let coordinates: Position[] = [];
  if (geometry.type === "Polygon") {
    coordinates = geometry.coordinates[0] ?? [];
  } else if (geometry.type === "MultiPolygon") {
    coordinates = geometry.coordinates[0]?.[0] ?? [];
  }

  if (coordinates.length === 0) return null;

  const bounds = new maplibregl.LngLatBounds();
  coordinates.forEach(function (coord) {
    if (Array.isArray(coord) && coord.length === 2) {
      bounds.extend(coord as [number, number]);
    }
  });

  if (extraPoint) {
    bounds.extend(extraPoint);
  }

  return bounds;
}
