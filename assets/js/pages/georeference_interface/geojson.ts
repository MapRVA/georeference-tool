import type { FeatureCollection, Point } from "geojson";

// Feature collection for the user's pin. The direction property is only
// present once a direction has been chosen, because the pin-symbol layer
// filters on ["has", "direction"].
export function pinFeatureCollection(
  lng: number,
  lat: number,
  direction: number | null,
): FeatureCollection<Point> {
  const properties: { direction?: number } = {};
  if (direction !== null) {
    properties.direction = direction;
  }
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [lng, lat] },
        properties,
      },
    ],
  };
}

export function emptyFeatureCollection(): FeatureCollection {
  return { type: "FeatureCollection", features: [] };
}
