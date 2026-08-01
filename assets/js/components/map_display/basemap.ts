// Protomaps basemap style, for the pages that build their own basemap instead
// of using OSM_STYLE_URL (the standalone subjects map and the map layer
// preview). The API key comes from window.PROTOMAPS_API_KEY, set by those
// templates.

const DARK_SCHEME_QUERY = "(prefers-color-scheme: dark)";

export function prefersDarkScheme(): boolean {
  return window.matchMedia(DARK_SCHEME_QUERY).matches;
}

// Protomaps publishes one style per theme, so a scheme flip means a new URL.
export function protomapsStyleUrl(): string {
  const theme = prefersDarkScheme() ? "dark" : "white";
  return `https://api.protomaps.com/styles/v5/${theme}/en.json?key=${window.PROTOMAPS_API_KEY}`;
}

export function onColorSchemeChange(listener: () => void): void {
  window
    .matchMedia(DARK_SCHEME_QUERY)
    .addEventListener("change", () => listener());
}
