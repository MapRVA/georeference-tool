import type maplibregl from "maplibre-gl";
import { LAYER_IDS } from "./layer_ids";

// A layer the slider filters by date range. requiresDirection and extraFilter
// reproduce the layer's base filter, which setFilter() overwrites wholesale.
export interface TimeSliderTarget {
  layerId: string;
  requiresDirection?: boolean;
  extraFilter?: maplibregl.ExpressionSpecification | null;
}

// The map_display image point layers, filtered by default.
export const DEFAULT_TIME_SLIDER_TARGETS: TimeSliderTarget[] = [
  { layerId: LAYER_IDS.imageHeatmap },
  { layerId: LAYER_IDS.imageCircles },
  { layerId: LAYER_IDS.imageDirections, requiresDirection: true },
  { layerId: LAYER_IDS.imageCirclesSimple },
  { layerId: LAYER_IDS.imageDirectionsSimple, requiresDirection: true },
];

// Time Slider Control Class
export class TimeSliderControl implements maplibregl.IControl {
  _minYear: number;
  _maxYear: number;
  _mapId: string;
  _targets: TimeSliderTarget[];
  _map: maplibregl.Map | undefined;
  _outerContainer!: HTMLDivElement;
  _sliderPanel!: HTMLElement;
  _startSlider!: HTMLInputElement;
  _endSlider!: HTMLInputElement;
  _rangeLabel!: HTMLElement;
  _sliderRange!: HTMLElement;

  constructor(
    minYear: number,
    maxYear: number,
    mapId: string,
    targets: TimeSliderTarget[] = DEFAULT_TIME_SLIDER_TARGETS,
  ) {
    this._minYear = minYear;
    this._maxYear = maxYear;
    this._mapId = mapId;
    this._targets = targets;
  }

  onAdd(map: maplibregl.Map) {
    this._map = map;
    this._outerContainer = document.createElement("div");
    this._outerContainer.className = "maplibregl-ctrl";

    const isSmallScreen = window.matchMedia("(max-width: 1000px)").matches;
    const collapseClass = isSmallScreen ? "collapse" : "collapse show";
    const ariaExpanded = isSmallScreen ? "false" : "true";

    this._outerContainer.innerHTML = `
            <div class="time-slider-control">
                <div class="time-slider-toolbar">
                    <div class="time-slider-header">
                        <span class="time-slider-label">Date Range</span>
                        <span id="time-slider-range-label-${this._mapId}" class="time-slider-range-label"></span>
                    </div>
                    <button type="button"
                            class="time-slider-toggle"
                            data-bs-toggle="collapse"
                            data-bs-target="#time-slider-body-${this._mapId}"
                            aria-expanded="${ariaExpanded}"
                            aria-controls="time-slider-body-${this._mapId}"
                            aria-label="Date filter">
                        <i class="fas fa-calendar-days"></i>
                    </button>
                    <button type="button"
                            class="time-slider-close"
                            data-bs-toggle="collapse"
                            data-bs-target="#time-slider-body-${this._mapId}"
                            aria-label="Close date filter">
                        <i class="fas fa-square-up-right"></i>
                    </button>
                </div>
                <div class="${collapseClass}" id="time-slider-body-${this._mapId}">
                    <div class="time-slider-container">
                        <div class="slider-track"></div>
                        <div class="slider-range" id="slider-range-${this._mapId}"></div>
                        <input type="range" id="start-slider-${this._mapId}" min="${this._minYear}" max="${this._maxYear}" value="${this._minYear}">
                        <input type="range" id="end-slider-${this._mapId}" min="${this._minYear}" max="${this._maxYear}" value="${this._maxYear}">
                    </div>
                </div>
            </div>
        `;

    // The elements always exist: the markup was assigned via innerHTML above.
    this._sliderPanel = this._outerContainer.querySelector<HTMLElement>(
      ".time-slider-control",
    )!;
    this._startSlider = this._sliderPanel.querySelector<HTMLInputElement>(
      `#start-slider-${this._mapId}`,
    )!;
    this._endSlider = this._sliderPanel.querySelector<HTMLInputElement>(
      `#end-slider-${this._mapId}`,
    )!;
    this._rangeLabel = this._sliderPanel.querySelector<HTMLElement>(
      `#time-slider-range-label-${this._mapId}`,
    )!;
    this._sliderRange = this._sliderPanel.querySelector<HTMLElement>(
      `#slider-range-${this._mapId}`,
    )!;

    this.setupEventListeners();
    this.updateView();

    return this._outerContainer;
  }

  setupEventListeners() {
    this._startSlider.addEventListener("input", () => {
      if (parseInt(this._startSlider.value) > parseInt(this._endSlider.value)) {
        this._endSlider.value = this._startSlider.value;
      }
      this.updateView();
      this.applyFilter();
    });

    this._endSlider.addEventListener("input", () => {
      if (parseInt(this._endSlider.value) < parseInt(this._startSlider.value)) {
        this._startSlider.value = this._endSlider.value;
      }
      this.updateView();
      this.applyFilter();
    });
  }

  updateView() {
    this._rangeLabel.textContent = `${this._startSlider.value} - ${this._endSlider.value}`;

    const range = this._maxYear - this._minYear;
    if (range === 0) return;

    const startPercent =
      ((Number(this._startSlider.value) - this._minYear) / range) * 100;
    const endPercent =
      ((Number(this._endSlider.value) - this._minYear) / range) * 100;

    this._sliderRange.style.left = `${startPercent}%`;
    this._sliderRange.style.width = `${endPercent - startPercent}%`;
  }

  // Also called from outside after style swaps recreate the target layers
  // with their base filters, which would otherwise silently drop the range.
  applyFilter() {
    const map = this._map;
    if (!map) return;

    const startYear = parseInt(this._startSlider.value);
    const endYear = parseInt(this._endSlider.value);

    // At the full range, restore the base filters instead of date-filtering,
    // so undated images stay visible until the range is actually narrowed.
    const fullRange =
      startYear === this._minYear && endYear === this._maxYear;
    const dateRange: maplibregl.ExpressionSpecification[] = fullRange
      ? []
      : [
          ["<=", ["get", "fuzzy_start_decdate"], endYear],
          [">=", ["get", "fuzzy_end_decdate"], startYear],
        ];

    for (const target of this._targets) {
      if (!map.getLayer(target.layerId)) continue;

      const clauses: maplibregl.ExpressionSpecification[] = [];
      if (target.requiresDirection) clauses.push(["has", "direction"]);
      if (target.extraFilter) clauses.push(target.extraFilter);
      clauses.push(...dateRange);

      map.setFilter(target.layerId, clauses.length ? ["all", ...clauses] : null);
    }
  }

  // Show or hide the whole control (e.g. while the layers it filters are
  // hidden). The filter state is preserved either way.
  setVisible(visible: boolean) {
    if (this._outerContainer) {
      this._outerContainer.style.display = visible ? "" : "none";
    }
  }

  onRemove() {
    if (this._outerContainer && this._outerContainer.parentNode) {
      this._outerContainer.parentNode.removeChild(this._outerContainer);
    }
    this._map = undefined;
  }
}

/**
 * Insert the slider directly after the layer control so it sits between the
 * layer control and the navigation controls; falls back to addControl when no
 * layer control is on the map.
 */
export function insertTimeSlider(
  map: maplibregl.Map,
  slider: TimeSliderControl,
): void {
  const layerControlElement = map
    .getContainer()
    .querySelector(".layer-control");
  if (layerControlElement && layerControlElement.parentNode) {
    layerControlElement.parentNode.insertBefore(
      slider.onAdd(map),
      layerControlElement.nextSibling,
    );
  } else {
    map.addControl(slider, "top-right");
  }
}
