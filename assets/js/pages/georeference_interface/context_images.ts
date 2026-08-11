// Display modes for the already-georeferenced context images: hidden, ghost
// (visible but inert), or clickable (popups on click, pointer cursor).
import maplibregl from "maplibre-gl";
import type { MapLayerMouseEvent } from "maplibre-gl";
import {
  buildPopupWrapper,
  deduplicateFeatures,
} from "../../components/map_popup";
import {
  primaryColor,
  secondaryColor,
} from "../../components/map_display/colors";
import type {
  ContextDisplayMode,
  ContextImagesController,
  GeoreferenceContext,
} from "./types";

export function createContextImagesController(
  ctx: GeoreferenceContext,
): ContextImagesController {
  const { map, state } = ctx;

  const onClick = (e: MapLayerMouseEvent): void => {
    // Only show popup if in clickable mode
    if (state.contextDisplayMode !== "clickable") return;

    // Prevent the map click handler from firing when clicking on context images
    e.originalEvent.stopPropagation();

    const features = deduplicateFeatures(e.features ?? []);
    if (features.length === 0) return;

    // Close any existing popup
    if (state.activePopup) {
      state.activePopup.remove();
    }

    // Create and track new popup
    const popup = new maplibregl.Popup()
      .setLngLat(e.lngLat)
      .setDOMContent(buildPopupWrapper(features))
      .addTo(map);
    state.activePopup = popup;

    // Clear the popup reference when it's closed
    popup.on("close", () => {
      state.activePopup = null;
      // Reset cursor to crosshairs when popup closes
      if (!state.isHoveringContextImage) {
        map.getCanvas().style.cursor = "crosshair";
      }
    });
  };

  const onMouseEnter = (): void => {
    if (state.contextDisplayMode === "clickable") {
      map.getCanvas().style.cursor = "pointer";
      state.isHoveringContextImage = true;
    }
  };

  const onMouseLeave = (): void => {
    if (state.contextDisplayMode === "clickable") {
      map.getCanvas().style.cursor = "";
      state.isHoveringContextImage = false;
    }
  };

  function detachHandlers(): void {
    map.off("click", "context-image-circles", onClick);
    map.off("mouseenter", "context-image-circles", onMouseEnter);
    map.off("mouseleave", "context-image-circles", onMouseLeave);
  }

  function closeActivePopup(): void {
    if (state.activePopup) {
      state.activePopup.remove();
      state.activePopup = null;
    }
  }

  function setDirectionsVisibility(visibility: "visible" | "none"): void {
    if (map.getLayer("context-image-directions")) {
      map.setLayoutProperty(
        "context-image-directions",
        "visibility",
        visibility,
      );
    }
  }

  function updateDisplay(): void {
    if (!map.getLayer("context-image-circles")) return;

    switch (state.contextDisplayMode) {
      case "hidden":
        map.setLayoutProperty("context-image-circles", "visibility", "none");
        setDirectionsVisibility("none");
        closeActivePopup();
        detachHandlers();
        state.isHoveringContextImage = false;
        map.getCanvas().style.cursor = "crosshair";
        break;

      case "ghost":
        map.setLayoutProperty("context-image-circles", "visibility", "visible");
        setDirectionsVisibility("visible");
        // De-emphasized styling, completely non-interactive
        map.setPaintProperty(
          "context-image-circles",
          "circle-color",
          secondaryColor,
        );
        map.setPaintProperty("context-image-circles", "circle-opacity", 0.6);
        map.setPaintProperty(
          "context-image-circles",
          "circle-stroke-opacity",
          0.8,
        );
        closeActivePopup();
        detachHandlers();
        state.isHoveringContextImage = false;
        map.getCanvas().style.cursor = "crosshair";
        break;

      case "clickable":
        map.setLayoutProperty("context-image-circles", "visibility", "visible");
        setDirectionsVisibility("visible");
        // Active styling
        map.setPaintProperty(
          "context-image-circles",
          "circle-color",
          primaryColor,
        );
        map.setPaintProperty("context-image-circles", "circle-opacity", 1.0);
        map.setPaintProperty(
          "context-image-circles",
          "circle-stroke-opacity",
          1.0,
        );
        // Detach first so re-entering clickable mode never stacks handlers
        detachHandlers();
        map.on("click", "context-image-circles", onClick);
        map.on("mouseenter", "context-image-circles", onMouseEnter);
        map.on("mouseleave", "context-image-circles", onMouseLeave);
        break;
    }
  }

  return { updateDisplay };
}

// Wire the display-mode radios and read the initial mode from the checked one.
export function initContextDisplayControls(
  ctx: GeoreferenceContext,
  controller: ContextImagesController,
): void {
  const { state } = ctx;
  const contextDisplayRadios = document.querySelectorAll<HTMLInputElement>(
    'input[name="contextDisplay"]',
  );

  const checkedRadio = document.querySelector<HTMLInputElement>(
    'input[name="contextDisplay"]:checked',
  );
  if (checkedRadio) {
    state.contextDisplayMode = checkedRadio.value as ContextDisplayMode;
  }

  contextDisplayRadios.forEach((radio) => {
    radio.addEventListener("change", () => {
      if (radio.checked) {
        state.contextDisplayMode = radio.value as ContextDisplayMode;
        controller.updateDisplay();
      }
    });
  });
}
