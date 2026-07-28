// "Data Overlays" section of the offcanvas: the georeferenced-images toggle,
// the heatmap/simple display switch, and the simple-mode point size slider.
import {
  SIMPLE_RADIUS_MAX,
  SIMPLE_RADIUS_MIN,
  strokeWidthForRadius,
} from "./image_layers";
import type { ImageDisplayStyle } from "./types";

export interface ImageLayerPanelOptions {
  mapId: string;
  initialRadius: number;
  onToggleImageLayers: () => void;
  onStyleChange: (style: ImageDisplayStyle) => void;
  onRadiusChange: (radius: number) => void;
}

export interface ImageLayerPanel {
  setImageLayersActive(active: boolean): void;
  // Grey out the display-style controls while the image layers are hidden
  setControlsEnabled(enabled: boolean): void;
  setRadiusVisible(visible: boolean): void;
}

function addSectionHeader(container: HTMLElement, title: string): void {
  const header = document.createElement("h6");
  header.className = "text-muted small text-uppercase mb-2 mt-3";
  header.textContent = title;
  container.appendChild(header);
}

export function buildImageLayerPanel(
  overlayContainer: HTMLElement,
  options: ImageLayerPanelOptions,
): ImageLayerPanel {
  const divider = document.createElement("hr");
  divider.className = "my-3 border-2 opacity-50";
  overlayContainer.appendChild(divider);

  addSectionHeader(overlayContainer, "Data Overlays");

  const listGroup = document.createElement("div");
  listGroup.className = "list-group list-group-flush mb-2";

  const imageLayerItem = document.createElement("button");
  imageLayerItem.type = "button";
  imageLayerItem.className =
    "list-group-item list-group-item-action overlay-layer active";
  imageLayerItem.dataset.layer = "georeferenced-images";
  imageLayerItem.textContent = "Georeferenced Images";
  imageLayerItem.addEventListener("click", (event) => {
    event.preventDefault();
    options.onToggleImageLayers();
  });

  listGroup.appendChild(imageLayerItem);
  overlayContainer.appendChild(listGroup);

  addSectionHeader(overlayContainer, "Display Style");

  const styleGroup = document.createElement("div");
  styleGroup.className = "btn-group w-100";
  styleGroup.setAttribute("role", "group");
  styleGroup.setAttribute("aria-label", "Image display style");

  const heatmapButton = document.createElement("button");
  heatmapButton.type = "button";
  heatmapButton.className = "btn btn-outline-primary active";
  heatmapButton.dataset.style = "heatmap";
  heatmapButton.textContent = "Heatmap";

  const simpleButton = document.createElement("button");
  simpleButton.type = "button";
  simpleButton.className = "btn btn-outline-primary";
  simpleButton.dataset.style = "simple";
  simpleButton.textContent = "Simple";

  const selectStyle = (style: ImageDisplayStyle): void => {
    heatmapButton.classList.toggle("active", style === "heatmap");
    simpleButton.classList.toggle("active", style === "simple");
    options.onStyleChange(style);
  };

  heatmapButton.addEventListener("click", (event) => {
    event.preventDefault();
    selectStyle("heatmap");
  });

  simpleButton.addEventListener("click", (event) => {
    event.preventDefault();
    selectStyle("simple");
  });

  styleGroup.appendChild(heatmapButton);
  styleGroup.appendChild(simpleButton);
  overlayContainer.appendChild(styleGroup);

  // Point size slider, only relevant (and only shown) in simple mode
  const radiusContainer = document.createElement("div");
  radiusContainer.className = "mt-3";
  radiusContainer.style.display = "none";
  radiusContainer.id = `radius-slider-container-${options.mapId}`;

  const radiusLabel = document.createElement("label");
  radiusLabel.className = "form-label small text-muted";
  radiusLabel.textContent = "Point Size";

  const sliderWrapper = document.createElement("div");
  sliderWrapper.className = "radius-slider-wrapper";

  const radiusSlider = document.createElement("input");
  radiusSlider.type = "range";
  radiusSlider.className = "form-range";
  radiusSlider.min = String(SIMPLE_RADIUS_MIN);
  radiusSlider.max = String(SIMPLE_RADIUS_MAX);
  radiusSlider.value = String(options.initialRadius);
  radiusSlider.id = `radius-slider-${options.mapId}`;

  // Tooltip previewing the point at the selected size
  const tooltip = document.createElement("div");
  tooltip.className = "radius-slider-tooltip";

  const tooltipDot = document.createElement("span");
  tooltipDot.className = "radius-slider-tooltip-dot";

  const tooltipText = document.createElement("span");

  tooltip.appendChild(tooltipDot);
  tooltip.appendChild(tooltipText);

  const updateTooltipPosition = (): void => {
    const fraction =
      (Number(radiusSlider.value) - SIMPLE_RADIUS_MIN) /
      (SIMPLE_RADIUS_MAX - SIMPLE_RADIUS_MIN);
    const thumbWidth = 16;
    const left =
      fraction * (radiusSlider.offsetWidth - thumbWidth) + thumbWidth / 2;
    tooltip.style.left = `${left}px`;
  };

  const updateTooltipContent = (radius: number): void => {
    tooltipDot.style.width = `${radius * 2}px`;
    tooltipDot.style.height = `${radius * 2}px`;
    tooltipDot.style.borderWidth = `${strokeWidthForRadius(radius)}px`;
    tooltipText.textContent = String(radius);
  };

  const setTooltipVisible = (visible: boolean): void => {
    tooltip.style.opacity = visible ? "1" : "0";
    if (visible) updateTooltipPosition();
  };

  updateTooltipContent(options.initialRadius);

  radiusSlider.addEventListener("input", () => {
    const radius = parseInt(radiusSlider.value, 10);
    options.onRadiusChange(radius);
    updateTooltipContent(radius);
    updateTooltipPosition();
  });

  radiusSlider.addEventListener("mouseenter", () => setTooltipVisible(true));
  radiusSlider.addEventListener("mouseleave", () => setTooltipVisible(false));
  radiusSlider.addEventListener("focus", () => setTooltipVisible(true));
  radiusSlider.addEventListener("blur", () => setTooltipVisible(false));

  sliderWrapper.appendChild(tooltip);
  sliderWrapper.appendChild(radiusSlider);
  radiusContainer.appendChild(radiusLabel);
  radiusContainer.appendChild(sliderWrapper);
  overlayContainer.appendChild(radiusContainer);

  return {
    setImageLayersActive(active) {
      imageLayerItem.classList.toggle("active", active);
    },

    setControlsEnabled(enabled) {
      heatmapButton.disabled = !enabled;
      simpleButton.disabled = !enabled;
      radiusSlider.disabled = !enabled;

      for (const element of [styleGroup, radiusContainer]) {
        element.style.opacity = enabled ? "1" : "0.5";
        element.style.pointerEvents = enabled ? "auto" : "none";
      }
    },

    setRadiusVisible(visible) {
      radiusContainer.style.display = visible ? "block" : "none";
    },
  };
}
