// Entry point for the map layer preview page (templates/maps/map_detail.html):
// a single MapLayer drawn over the Protomaps basemap, plus the two widgets in
// the header card (source domain, IIIF manifest copy button).
import "../../styles/pages/map-detail.css";
import "maplibre-gl/dist/maplibre-gl.css";

import maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, StyleSpecification } from "maplibre-gl";
import {
  onColorSchemeChange,
  protomapsStyleUrl,
} from "../components/map_display/basemap";
import "../components/map_display/pmtiles_protocol";
import { DEFAULT_MAP_CENTER } from "../constants/map";

const PREVIEW_ZOOM = 13;
const OVERLAY_ID = "overlay-layer";
const COPIED_REVERT_MS = 1500;

// The source link is labelled with the bare hostname rather than the full URL.
function showSourceDomain(): void {
  const sourceLink = document.querySelector<HTMLElement>("[data-source-url]");
  const domainSpan = sourceLink?.querySelector(".source-domain");
  if (!sourceLink || !domainSpan) return;

  const sourceUrl = sourceLink.dataset.sourceUrl ?? "";
  try {
    domainSpan.textContent = new URL(sourceUrl).hostname.replace(/^www\./, "");
  } catch (e) {
    console.error("Error parsing source URL:", e);
    domainSpan.textContent = sourceUrl;
  }
}

function setupIiifCopyButton(): void {
  const button = document.querySelector<HTMLElement>("[data-iiif-copy]");
  const manifestUrl = button?.dataset.iiifCopy;
  if (!button || !manifestUrl) return;

  const originalHtml = button.innerHTML;
  let revertTimer: ReturnType<typeof setTimeout> | undefined;

  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(manifestUrl);
      clearTimeout(revertTimer);
      button.innerHTML = '<i class="fas fa-check me-1"></i>Copied!';
      revertTimer = setTimeout(() => {
        button.innerHTML = originalHtml;
      }, COPIED_REVERT_MS);
    } catch (e) {
      console.error("Could not copy IIIF manifest URL:", e);
      window.showAlert("danger", "Could not copy the IIIF manifest URL.");
    }
  });
}

// Draw the previewed layer on top of the basemap. Only tile layers get here —
// a "style" layer is the map's whole style and is handled at construction.
function addOverlayLayer(map: MapLibreMap, layer: PreviewMapLayer): void {
  if (map.getSource(OVERLAY_ID)) return;

  const tiles =
    layer.type === "pmtiles"
      ? [`pmtiles://${layer.url}/{z}/{x}/{y}`]
      : [layer.url];

  map.addSource(OVERLAY_ID, {
    type: "raster",
    tiles,
    tileSize: 256,
    attribution: layer.attribution,
  });
  map.addLayer({ id: OVERLAY_ID, type: "raster", source: OVERLAY_ID });
}

// A colour-scheme flip means a different Protomaps style. setStyle() would
// discard the preview layer along with the old basemap, so fetch the new style
// and copy its paint properties onto the layers already on the map instead.
async function retintBaseMap(map: MapLibreMap): Promise<void> {
  try {
    const response = await fetch(protomapsStyleUrl());
    const style: StyleSpecification = await response.json();

    for (const layer of style.layers) {
      if (!map.getLayer(layer.id)) continue;
      const paint = ("paint" in layer ? layer.paint : undefined) as
        | Record<string, unknown>
        | undefined;
      if (!paint) continue;

      for (const [property, value] of Object.entries(paint)) {
        try {
          map.setPaintProperty(layer.id, property, value);
        } catch {
          // Not every paint property can be re-set on a live layer.
        }
      }
    }
  } catch (e) {
    console.warn("Could not update base map theme:", e);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  showSourceDomain();
  setupIiifCopyButton();

  const container = document.getElementById("layer-map");
  const layer = window.MAP_LAYER;
  if (!container || !layer) return;

  window.setupPMTilesProtocol();

  // A "style" layer is a basemap in its own right, so it replaces the
  // Protomaps style instead of being drawn over it — and there is then no
  // Protomaps layer left to retint when the colour scheme changes.
  const isStyleLayer = layer.type === "style";

  const map = new maplibregl.Map({
    container,
    style: isStyleLayer ? layer.url : protomapsStyleUrl(),
    center: DEFAULT_MAP_CENTER,
    zoom: PREVIEW_ZOOM,
  });

  map.addControl(new maplibregl.NavigationControl());
  map.addControl(new maplibregl.FullscreenControl());

  if (!isStyleLayer) {
    map.on("load", () => addOverlayLayer(map, layer));
    onColorSchemeChange(() => retintBaseMap(map));
  }
});
