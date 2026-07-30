import type { Map as MapLibreMap, Point } from "maplibre-gl";
import {
  IMAGE_CIRCLES_LAYER,
  IMAGE_DIRECTIONS_LAYER,
  SUBJECT_LAYER_IDS,
} from "./layers";
import { SUBJECT_MAP_EVENTS } from "./types";
import type { SubjectFeatureProperties, SubjectHit } from "./types";

// Rewriting the image-point paint properties is the expensive part of a
// hover, so it trails the panel update by a beat.
const HIGHLIGHT_DEBOUNCE_MS = 10;

export interface SubjectInteractions {
  // Re-applies the current highlight after a style swap has rebuilt the
  // layers from scratch.
  reapplyHighlight(): void;
}

// Wires hover previews, click-to-pin, and the image-point highlight. State
// reaches the panel as window CustomEvents, so this module knows nothing
// about the DOM beyond the map canvas.
export function registerSubjectInteractions(
  map: MapLibreMap,
): SubjectInteractions {
  // The slug the user committed to by clicking. While set, hovering other
  // subjects must not steal the panel.
  let pinnedSlug: string | null = null;
  let hoveredSlug: string | null = null;
  let highlightedImageIds: number[] = [];
  let highlightTimeout: number | undefined;

  function dispatch(name: string, detail?: SubjectHit): void {
    window.dispatchEvent(new CustomEvent(name, { detail }));
  }

  // Layers are absent between a setStyle() and the following styledata, and
  // querying a missing layer makes MapLibre fire an error event.
  function queryableLayers(): string[] {
    return SUBJECT_LAYER_IDS.filter((id) => map.getLayer(id));
  }

  function subjectAt(point: Point): SubjectHit | null {
    const layers = queryableLayers();
    if (layers.length === 0) return null;

    const feature = map.queryRenderedFeatures(point, { layers })[0];
    if (!feature) return null;

    const properties = feature.properties as Partial<SubjectFeatureProperties>;
    if (!properties.subject_slug) return null;

    return {
      slug: properties.subject_slug,
      title: properties.subject_name || "Unknown subject",
      imageIds: (properties.image_ids ?? "")
        .split(",")
        .filter(Boolean)
        .map(Number)
        .filter((id) => !Number.isNaN(id)),
    };
  }

  // Reveals exactly the given images and hides every other point. An empty
  // list restores the default state, where no image points are drawn.
  function applyHighlight(imageIds: number[]): void {
    highlightedImageIds = imageIds;

    const opacity = imageIds.length
      ? ["case", ["in", ["get", "id"], ["literal", imageIds]], 1, 0]
      : 0;

    if (map.getLayer(IMAGE_CIRCLES_LAYER)) {
      map.setPaintProperty(IMAGE_CIRCLES_LAYER, "circle-opacity", opacity);
      map.setPaintProperty(
        IMAGE_CIRCLES_LAYER,
        "circle-stroke-opacity",
        opacity,
      );
    }
    if (map.getLayer(IMAGE_DIRECTIONS_LAYER)) {
      map.setPaintProperty(IMAGE_DIRECTIONS_LAYER, "icon-opacity", opacity);
    }
  }

  function reset(): void {
    pinnedSlug = null;
    hoveredSlug = null;
    window.clearTimeout(highlightTimeout);
    applyHighlight([]);
  }

  map.on("mousemove", (e) => {
    const hit = subjectAt(e.point);
    map.getCanvas().style.cursor = hit ? "pointer" : "";

    if (pinnedSlug) return;

    if (!hit) {
      if (hoveredSlug === null) return;
      hoveredSlug = null;
      window.clearTimeout(highlightTimeout);
      applyHighlight([]);
      dispatch(SUBJECT_MAP_EVENTS.clear);
      return;
    }

    if (hit.slug === hoveredSlug) return;
    hoveredSlug = hit.slug;
    dispatch(SUBJECT_MAP_EVENTS.preview, hit);

    window.clearTimeout(highlightTimeout);
    highlightTimeout = window.setTimeout(
      () => applyHighlight(hit.imageIds),
      HIGHLIGHT_DEBOUNCE_MS,
    );
  });

  // A tap arrives here too, which is what makes the panel reachable on
  // touch: it pins the subject instead of navigating away from the map.
  map.on("click", (e) => {
    const hit = subjectAt(e.point);

    if (!hit) {
      if (!pinnedSlug) return;
      reset();
      dispatch(SUBJECT_MAP_EVENTS.clear);
      return;
    }

    pinnedSlug = hit.slug;
    hoveredSlug = hit.slug;
    window.clearTimeout(highlightTimeout);
    applyHighlight(hit.imageIds);
    dispatch(SUBJECT_MAP_EVENTS.pin, hit);
  });

  window.addEventListener(SUBJECT_MAP_EVENTS.closed, () => reset());

  return {
    reapplyHighlight: () => applyHighlight(highlightedImageIds),
  };
}
