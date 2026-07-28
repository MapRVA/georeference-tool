import type { ExpressionSpecification } from "maplibre-gl";
import { DIRECTION_SPRITE_ID, LAYER_IDS, SOURCE_IDS } from "./layer_ids";
import type { MapDisplayContext } from "./types";

// Reusable function to add all image/overlay sources and layers to the map.
// Called on initial load and after style swaps to restore layers.
export async function setupMapDataLayers(ctx: MapDisplayContext): Promise<void> {
  const { map, config, colors } = ctx;
  const {
    showOtherImages,
    imageId,
    vectorTilesUrl,
    allImagesUrl,
    center,
    currentImageDirection,
    aerialGeoreference,
    directionImageUrl,
  } = config;

  // Load direction arrow image
  if (directionImageUrl && !map.hasImage(DIRECTION_SPRITE_ID)) {
    try {
      const image = await map.loadImage(directionImageUrl);
      map.addImage(DIRECTION_SPRITE_ID, image.data);
    } catch (error) {
      console.warn("Could not load direction arrow image:", error);
    }
  }

  // Add vector tiles source for other images
  const tilesUrl =
    showOtherImages && allImagesUrl ? allImagesUrl : vectorTilesUrl;
  if (tilesUrl && !map.getSource(SOURCE_IDS.images)) {
    map.addSource(SOURCE_IDS.images, {
      type: "vector",
      tiles: [tilesUrl],
      minzoom: 0,
      maxzoom: 14,
    });

    // Start hidden if in showOtherImages mode (toggle controls visibility)
    const initialVisibility = showOtherImages ? "none" : "visible";

    // Build filter to exclude current image if in showOtherImages mode
    // Convert imageId to number since vector tile properties are integers
    const excludeCurrentFilter: ExpressionSpecification | null =
      showOtherImages && imageId
        ? ["!=", ["get", "id"], parseInt(imageId, 10)]
        : null;

    // Add blurred background circles (heatmap effect, fades out at higher zoom)
    map.addLayer({
      id: LAYER_IDS.imageHeatmap,
      type: "circle",
      source: SOURCE_IDS.images,
      "source-layer": "image_points",
      filter: excludeCurrentFilter || ["literal", true],
      maxzoom: 17,
      layout: {
        visibility: initialVisibility,
      },
      paint: {
        "circle-blur": [
          "interpolate",
          ["linear"],
          ["zoom"],
          14.5,
          1.5,
          16,
          3,
        ],
        "circle-opacity": [
          "interpolate",
          ["exponential", 5],
          ["zoom"],
          14,
          1,
          17,
          0,
        ],
        "circle-radius": [
          "interpolate",
          ["exponential", 2],
          ["zoom"],
          10,
          25,
          20,
          100,
        ],
        "circle-color": colors.primary,
        "circle-pitch-alignment": "map",
        "circle-pitch-scale": "map",
      },
    });

    // Add direction markers (fade in at higher zoom, rendered under circles)
    if (map.hasImage(DIRECTION_SPRITE_ID)) {
      map.addLayer({
        id: LAYER_IDS.imageDirections,
        type: "symbol",
        source: SOURCE_IDS.images,
        "source-layer": "image_points",
        minzoom: 15,
        filter: excludeCurrentFilter
          ? ["all", ["has", "direction"], excludeCurrentFilter]
          : ["has", "direction"],
        layout: {
          "icon-image": DIRECTION_SPRITE_ID,
          "icon-overlap": "always",
          "icon-size": [
            "interpolate",
            ["exponential", 0.7],
            ["zoom"],
            15,
            0.3,
            20,
            1,
          ],
          "icon-rotate": ["to-number", ["get", "direction"]],
          "icon-rotation-alignment": "map",
          "icon-pitch-alignment": "map",
          visibility: initialVisibility,
        },
      });
    }

    // Add detail circles (blur transitions from blurry to sharp, on top of directions)
    map.addLayer({
      id: LAYER_IDS.imageCircles,
      type: "circle",
      source: SOURCE_IDS.images,
      "source-layer": "image_points",
      minzoom: 7,
      filter: excludeCurrentFilter || ["literal", true],
      layout: {
        visibility: initialVisibility,
      },
      paint: {
        "circle-blur": [
          "interpolate",
          ["exponential", 1.5],
          ["zoom"],
          9,
          5,
          13,
          1,
          15,
          0,
        ],
        "circle-opacity": [
          "interpolate",
          ["exponential", 1.5],
          ["zoom"],
          7,
          0,
          10,
          1,
        ],
        "circle-radius": [
          "interpolate",
          ["exponential", 0.6],
          ["zoom"],
          7,
          1,
          15,
          3,
          20,
          9,
        ],
        "circle-color": [
          "interpolate",
          ["linear"],
          ["zoom"],
          14,
          "#fff",
          15,
          colors.primary,
        ],
        "circle-stroke-color": "#fff",
        "circle-stroke-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          13.5,
          0,
          15,
          1,
          20,
          2,
        ],
        "circle-pitch-alignment": "map",
        "circle-pitch-scale": "map",
      },
    });

    // === Simple style layers (hidden by default) ===

    // Add simple direction markers (rendered under simple circles)
    if (map.hasImage(DIRECTION_SPRITE_ID)) {
      map.addLayer({
        id: LAYER_IDS.imageDirectionsSimple,
        type: "symbol",
        source: SOURCE_IDS.images,
        "source-layer": "image_points",
        filter: excludeCurrentFilter
          ? ["all", ["has", "direction"], excludeCurrentFilter]
          : ["has", "direction"],
        layout: {
          "icon-image": DIRECTION_SPRITE_ID,
          "icon-overlap": "always",
          "icon-size": 1,
          "icon-rotate": ["to-number", ["get", "direction"]],
          "icon-rotation-alignment": "map",
          "icon-pitch-alignment": "map",
          visibility: "none",
        },
      });
    }

    // Add simple circle layer (always visible at all zooms, on top of simple directions)
    map.addLayer({
      id: LAYER_IDS.imageCirclesSimple,
      type: "circle",
      source: SOURCE_IDS.images,
      "source-layer": "image_points",
      filter: excludeCurrentFilter || ["literal", true],
      layout: {
        visibility: "none",
      },
      paint: {
        "circle-radius": 8,
        "circle-color": colors.primary,
        "circle-stroke-color": "#fff",
        "circle-stroke-width": 2,
        "circle-pitch-alignment": "map",
        "circle-pitch-scale": "map",
      },
    });
  }

  // Add current image as GeoJSON layer (always visible, distinct color, on top)
  if (
    showOtherImages &&
    imageId &&
    center &&
    !map.getSource(SOURCE_IDS.currentImage)
  ) {
    map.addSource(SOURCE_IDS.currentImage, {
      type: "geojson",
      data: {
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: center,
        },
        properties: {
          id: imageId,
          direction: currentImageDirection,
        },
      },
    });

    // Add direction marker for current image
    if (map.hasImage(DIRECTION_SPRITE_ID) && currentImageDirection !== null) {
      map.addLayer({
        id: LAYER_IDS.currentImageDirection,
        type: "symbol",
        source: SOURCE_IDS.currentImage,
        layout: {
          "icon-image": DIRECTION_SPRITE_ID,
          "icon-overlap": "always",
          "icon-size": 1,
          "icon-rotate": currentImageDirection,
          "icon-rotation-alignment": "map",
          "icon-pitch-alignment": "map",
        },
        paint: {
          "icon-opacity": 1,
        },
      });
    }

    // Add circle for current image
    map.addLayer({
      id: LAYER_IDS.currentImageCircle,
      type: "circle",
      source: SOURCE_IDS.currentImage,
      paint: {
        "circle-radius": 8,
        "circle-color": colors.danger,
        "circle-stroke-color": "#fff",
        "circle-stroke-width": 2,
        "circle-pitch-alignment": "map",
        "circle-pitch-scale": "map",
      },
    });
  }

  // Add aerial georeference if provided
  if (aerialGeoreference && !map.getSource(SOURCE_IDS.aerialPolygon)) {
    map.addSource(SOURCE_IDS.aerialPolygon, {
      type: "geojson",
      data: {
        type: "Feature",
        geometry: aerialGeoreference,
        properties: null,
      },
    });

    map.addLayer({
      id: LAYER_IDS.aerialPolygonFill,
      type: "fill",
      source: SOURCE_IDS.aerialPolygon,
      paint: {
        "fill-color": colors.primary,
        "fill-opacity": 0.2,
      },
    });

    map.addLayer({
      id: LAYER_IDS.aerialPolygonOutline,
      type: "line",
      source: SOURCE_IDS.aerialPolygon,
      paint: {
        "line-color": colors.primary,
        "line-width": 2.5,
      },
    });
  }

  // Restore image layer visibility to match LayerControl state
  if (ctx.layerControl) {
    ctx.layerControl.applyImageLayerVisibility();
  }

  // When "Show Other Images" toggle controls visibility, re-hide layers
  // unless the toggle checkbox is currently checked (applyImageLayerVisibility
  // above doesn't know about the toggle and would make them visible).
  if (showOtherImages && imageId) {
    const toggle = document.getElementById(
      "show-other-images-toggle",
    ) as HTMLInputElement | null;
    if (!toggle || !toggle.checked) {
      window.toggleOtherImages?.(false);
    }
  }
}
