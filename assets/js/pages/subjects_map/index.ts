// Entry point for the standalone subjects map (templates/subjects/subjects_map.html).
// Subject geometries come from the osm_elements vector tiles; hovering or
// tapping one reveals it in the info card handled by ./panel.
import "../../../styles/pages/subjects-map.css";
import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl from "maplibre-gl";
import { primaryColor } from "../../components/map_display/colors";
import { DEFAULT_MAP_CENTER } from "../../constants/map";
import { registerSubjectInteractions } from "./interactions";
import { addCustomLayers } from "./layers";
import { registerSubjectPanel } from "./panel";
import type { SubjectsMapUrls } from "./types";

const INITIAL_ZOOM = 13;

registerSubjectPanel();

function isDarkMode(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function getMapStyle(): string {
  const theme = isDarkMode() ? "dark" : "white";
  return `https://api.protomaps.com/styles/v5/${theme}/en.json?key=${window.PROTOMAPS_API_KEY}`;
}

// Django can only reverse a tile route with concrete coordinates, so the
// template renders tile 0/0/0 and we put MapLibre's placeholders back.
function toTileTemplate(path: string): string {
  return (
    window.location.origin + path.replace(/\/0\/0\/0(\.\w+)$/, "/{z}/{x}/{y}$1")
  );
}

document.addEventListener("DOMContentLoaded", () => {
  const wrapper = document.getElementById("subjects-map-wrapper");
  const container = document.getElementById("subjects-map");
  if (!wrapper || !container) return;

  const urls: SubjectsMapUrls = {
    imageTiles: toTileTemplate(wrapper.dataset.tilesUrl ?? ""),
    osmElementTiles: toTileTemplate(wrapper.dataset.osmElementsUrl ?? ""),
  };

  const map = new maplibregl.Map({
    container,
    style: getMapStyle(),
    center: DEFAULT_MAP_CENTER,
    zoom: INITIAL_ZOOM,
  });

  // Take the wrapper rather than the map container fullscreen so the info
  // card comes along; it lives outside #subjects-map.
  map.addControl(new maplibregl.FullscreenControl({ container: wrapper }));

  let interactions: ReturnType<typeof registerSubjectInteractions> | null = null;

  map.on("load", () => {
    addCustomLayers(map, urls, primaryColor);
    interactions = registerSubjectInteractions(map);
  });

  map.on("error", (e) => {
    console.error("Map error:", e);
  });

  // A theme change swaps the whole basemap style, which discards our sources
  // and layers — re-add them, then restore whatever was highlighted.
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      map.once("styledata", () => {
        addCustomLayers(map, urls, primaryColor);
        interactions?.reapplyHighlight();
      });
      map.setStyle(getMapStyle());
    });
});
