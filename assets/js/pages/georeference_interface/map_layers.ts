// Sources and layers for the georeference map: subject and location hints,
// context images from vector tiles, the bearing line, and the user's pin.
// Called on initial load and again after style swaps, which destroy all
// sources, layers, and images.
import type { GeoJSONSource } from "maplibre-gl";
import type { FeatureCollection, Point } from "geojson";
import {
  dangerColor,
  darkColor,
  lightColor,
} from "../../components/map_display/colors";
import { ensureDirectionSprite } from "../../components/map_display/direction_sprite";
import {
  detailCircleLayer,
  directionSymbolLayer,
} from "../../components/map_display/image_point_layers";
import { DIRECTION_SPRITE_ID } from "../../components/map_display/layer_ids";
import {
  CONTEXT_LAYER_IDS,
  CONTEXT_MIN_ZOOM,
  contextImageExtraFilter,
  contextModeAppearance,
} from "./context_images";
import { emptyFeatureCollection, pinFeatureCollection } from "./geojson";
import { updateBearingLine } from "./pin_direction";
import type { GeoreferenceContext, LocationHintType } from "./types";

// All layers that must stay on top of secondary tile layers (like Sanborn
// maps). The LayerControl's fallback logic finds the bottommost of these to
// insert secondary layers below, so hints and pins always render above them.
export const OVERLAY_LAYER_IDS: string[] = [
  "subject-hints-pulse",
  "subject-hints-label",
  "location-hint-pulse",
  "location-hint-label",
  "bearing-line-bg",
  "bearing-line",
  "pin-circle",
  "pin-symbol",
  CONTEXT_LAYER_IDS.directions,
  CONTEXT_LAYER_IDS.circles,
];

// Hint marker colors by type: georeference = yellow, source = teal,
// detected = purple.
const HINT_COLORS: Record<LocationHintType, { circle: string; text: string }> =
  {
    georeference: { circle: "#ffc107", text: "#856404" },
    source: { circle: "#17a2b8", text: "#0c5460" },
    detected: { circle: "#9b59b6", text: "#6c3483" },
  };

// Orange to match the browse subjects page
const SUBJECT_HINT_COLOR = { circle: "#ff6b35", text: "#c44d1c" };

export async function addMapSourcesAndLayers(
  ctx: GeoreferenceContext,
): Promise<void> {
  const { map, config, els, state } = ctx;

  await ensureDirectionSprite(map);

  // Add subject hint markers if available (rendered first, so underneath
  // other hints)
  const subjectHints = config.subjectHints || [];
  if (subjectHints.length > 0) {
    const subjectHintFeatures: FeatureCollection<Point, { label: string }> = {
      type: "FeatureCollection",
      features: subjectHints.map((hint) => ({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [hint.lng, hint.lat],
        },
        properties: {
          label: hint.label,
        },
      })),
    };

    map.addSource("subject-hints", {
      type: "geojson",
      data: subjectHintFeatures,
    });

    // Add a pulsing circle for each subject hint
    map.addLayer({
      id: "subject-hints-pulse",
      type: "circle",
      source: "subject-hints",
      paint: {
        "circle-radius": 25,
        "circle-color": SUBJECT_HINT_COLOR.circle,
        "circle-opacity": 0.3,
        "circle-stroke-color": SUBJECT_HINT_COLOR.circle,
        "circle-stroke-width": 2,
        "circle-stroke-opacity": 0.6,
      },
    });

    // Add labels for subject hints
    map.addLayer({
      id: "subject-hints-label",
      type: "symbol",
      source: "subject-hints",
      layout: {
        "text-field": ["get", "label"],
        "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
        "text-size": 12,
        "text-offset": [0, 2.5],
        "text-anchor": "top",
      },
      paint: {
        "text-color": SUBJECT_HINT_COLOR.text,
        "text-halo-color": "#fff",
        "text-halo-width": 2,
      },
    });
  }

  // Add location hint marker if available
  const locationHint = config.locationHint;
  if (locationHint) {
    const hintFeatures: FeatureCollection = {
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: [locationHint.lng, locationHint.lat],
          },
          properties: {
            label: locationHint.label,
            type: locationHint.type,
            direction: locationHint.direction,
          },
        },
      ],
    };

    map.addSource("location-hint", {
      type: "geojson",
      data: hintFeatures,
    });

    const hintColor = HINT_COLORS[locationHint.type] ?? HINT_COLORS.source;

    // Add a pulsing circle for the hint (larger, semi-transparent)
    map.addLayer({
      id: "location-hint-pulse",
      type: "circle",
      source: "location-hint",
      paint: {
        "circle-radius": 25,
        "circle-color": hintColor.circle,
        "circle-opacity": 0.3,
        "circle-stroke-color": hintColor.circle,
        "circle-stroke-width": 2,
        "circle-stroke-opacity": 0.6,
      },
    });

    // Add label for the hint (always visible, renders over subject hints)
    map.addLayer({
      id: "location-hint-label",
      type: "symbol",
      source: "location-hint",
      layout: {
        "text-field": ["get", "label"],
        "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
        "text-size": 12,
        "text-offset": [0, 2.5],
        "text-anchor": "top",
        "text-allow-overlap": true,
      },
      paint: {
        "text-color": hintColor.text,
        "text-halo-color": "#fff",
        "text-halo-width": 2,
      },
    });
  }

  // Add all existing georeferenced images for context using vector tiles,
  // rendered with the same zoom-graduated styling as the sitewide maps
  // (map_display/image_point_layers), but only from CONTEXT_MIN_ZOOM up.
  // These are added BEFORE the pin layers so the user's pin always renders on
  // top. Initial styling reflects the current display mode; restoreOverlayState
  // re-applies it afterwards.
  try {
    // Build vector tiles URL (version is already included from template)
    const contextVectorTilesUrl =
      window.location.origin +
      config.urls.vectorTiles.replace("/0/0/0.mvt", "/{z}/{x}/{y}.mvt");

    map.addSource("context-images", {
      type: "vector",
      tiles: [contextVectorTilesUrl],
      minzoom: 0,
      maxzoom: 14,
    });

    const appearance = contextModeAppearance(state.contextDisplayMode);
    const layerOptions = {
      source: "context-images",
      color: appearance.color,
      opacity: appearance.opacity,
      extraFilter: contextImageExtraFilter(ctx.image),
      visibility: appearance.visible ? ("visible" as const) : ("none" as const),
      minzoom: CONTEXT_MIN_ZOOM,
    };

    if (map.hasImage(DIRECTION_SPRITE_ID)) {
      map.addLayer(
        directionSymbolLayer(CONTEXT_LAYER_IDS.directions, layerOptions),
      );
    }

    map.addLayer(detailCircleLayer(CONTEXT_LAYER_IDS.circles, layerOptions));
  } catch (error) {
    console.warn("Could not load context images:", error);
  }

  // Add bearing line source and layers (rendered below pin but above
  // context images)
  map.addSource("bearing-line", {
    type: "geojson",
    data: emptyFeatureCollection(),
  });

  map.addLayer({
    id: "bearing-line-bg",
    type: "line",
    source: "bearing-line",
    paint: {
      "line-color": lightColor,
      "line-width": 2,
    },
    layout: {
      visibility: "none",
    },
  });

  map.addLayer({
    id: "bearing-line",
    type: "line",
    source: "bearing-line",
    paint: {
      "line-color": darkColor,
      "line-width": 2,
      "line-dasharray": [3, 3],
    },
    layout: {
      visibility: "none",
    },
  });

  // Add the user's pin source and layers LAST so they render above all else
  map.addSource("pin", {
    type: "geojson",
    data: emptyFeatureCollection(),
  });

  map.addLayer({
    id: "pin-circle",
    type: "circle",
    source: "pin",
    paint: {
      "circle-radius": 8,
      "circle-color": dangerColor,
      "circle-stroke-color": "#fff",
      "circle-stroke-width": 2,
    },
  });

  if (map.hasImage(DIRECTION_SPRITE_ID)) {
    map.addLayer(
      {
        id: "pin-symbol",
        type: "symbol",
        source: "pin",
        layout: {
          "icon-image": DIRECTION_SPRITE_ID,
          "icon-overlap": "always",
          "icon-size": ["interpolate", ["linear"], ["zoom"], 5, 0.3, 15, 1],
          "icon-rotate": ["to-number", ["get", "direction"]],
          "icon-rotation-alignment": "map",
          "icon-pitch-alignment": "map",
        },
        filter: ["has", "direction"],
      },
      "pin-circle", // Insert below pin-circle
    );
  }

  // Restore any existing pin if there was one
  if (state.pinPlaced) {
    const lat = parseFloat(els.latitudeInput.value);
    const lng = parseFloat(els.longitudeInput.value);
    if (!isNaN(lat) && !isNaN(lng)) {
      map
        .getSource<GeoJSONSource>("pin")
        ?.setData(pinFeatureCollection(lng, lat, state.currentDirection));
    }
  }
}

// Restore overlay state after layers are (re-)created (used on initial load
// and after style swaps, which destroy all sources/layers/images).
export function restoreOverlayState(ctx: GeoreferenceContext): void {
  const { map, state } = ctx;

  // Sync bearing line visibility from current toggle state
  if (state.bearingLineEnabled) {
    for (const layerId of ["bearing-line", "bearing-line-bg"]) {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", "visible");
      }
    }
  }

  // Repopulate bearing line data (source is created empty)
  updateBearingLine(ctx);

  // Re-apply context image display mode and re-attach interaction handlers
  ctx.contextImages?.updateDisplay();

  // Recreated layers come back with their base filters; re-apply the date
  // slider's range
  ctx.timeSlider?.applyFilter();
}
