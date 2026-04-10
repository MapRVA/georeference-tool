// Map configuration constants
// Uses global window values set by Django, with fallback defaults

export const OSM_STYLE_URL =
  window.OSM_STYLE_URL || "https://styles.maprva.org/openmaptiles-osm.json";

export const DEFAULT_MAP_CENTER = window.DEFAULT_MAP_CENTER || [
  -117.37, 33.98,
];

export const DEFAULT_MAP_ZOOM = window.DEFAULT_MAP_ZOOM || 10;
