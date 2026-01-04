// Map configuration constants
// Uses the global window.OSM_STYLE_URL set by Django, with a fallback default

export const OSM_STYLE_URL =
  window.OSM_STYLE_URL || "https://styles.maprva.org/openmaptiles-osm.json";
