// Map configuration constants
// Uses global window values set by Django, with fallback defaults

export const OSM_STYLE_URL =
  window.OSM_STYLE_URL || "https://styles.maprva.org/openmaptiles-osm.json";

export const DEFAULT_MAP_CENTER: [number, number] =
  window.DEFAULT_MAP_CENTER || [-77.43916, 37.54376];

export const DEFAULT_MAP_ZOOM = window.DEFAULT_MAP_ZOOM || 10;
