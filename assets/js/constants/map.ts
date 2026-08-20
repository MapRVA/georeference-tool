import type { MapOptions } from "maplibre-gl";

// Map configuration constants. Sitewide defaults remain distinct from the
// selected region so callers with explicit content can choose their own view.
export type MapBounds = [number, number, number, number];

export const DEFAULT_MAP_CENTER: [number, number] =
  window.DEFAULT_MAP_CENTER || [-77.43916, 37.54376];

export const DEFAULT_MAP_ZOOM = window.DEFAULT_MAP_ZOOM ?? 10;

export const REGION_MAP_CENTER = window.REGION_MAP_CENTER ?? null;
export const REGION_MAP_BOUNDS = window.REGION_MAP_BOUNDS ?? null;

export const EFFECTIVE_MAP_CENTER: [number, number] =
  REGION_MAP_CENTER ?? DEFAULT_MAP_CENTER;

export interface InitialMapViewOptions {
  center?: [number, number];
  zoom?: number;
  bounds?: MapBounds | null;
  padding?: number;
  maxZoom?: number;
}

type InitialMapView = Pick<
  MapOptions,
  "bounds" | "center" | "zoom" | "fitBoundsOptions"
>;

export function initialMapView(
  options: InitialMapViewOptions = {},
): Partial<InitialMapView> {
  const {
    center = EFFECTIVE_MAP_CENTER,
    zoom = DEFAULT_MAP_ZOOM,
    bounds = REGION_MAP_BOUNDS,
    padding = 48,
    maxZoom = 14,
  } = options;

  if (bounds) {
    const [west, south, east, north] = bounds;
    return {
      bounds: [
        [west, south],
        [east, north],
      ],
      fitBoundsOptions: { padding, maxZoom },
    };
  }
  return { center, zoom };
}
