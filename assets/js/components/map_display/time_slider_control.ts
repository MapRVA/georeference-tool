import type maplibregl from "maplibre-gl";
import { LAYER_IDS } from "./layer_ids";

// Time Slider Control Class
export class TimeSliderControl implements maplibregl.IControl {
  _minYear: number;
  _maxYear: number;
  _mapId: string;
  _map: maplibregl.Map | undefined;
  _outerContainer!: HTMLDivElement;
  _sliderPanel!: HTMLElement;
  _startSlider!: HTMLInputElement;
  _endSlider!: HTMLInputElement;
  _rangeLabel!: HTMLElement;
  _sliderRange!: HTMLElement;

  constructor(minYear: number, maxYear: number, mapId: string) {
    this._minYear = minYear;
    this._maxYear = maxYear;
    this._mapId = mapId;
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

  applyFilter() {
    const map = this._map;
    if (!map) return;

    const startYear = parseInt(this._startSlider.value);
    const endYear = parseInt(this._endSlider.value);

    const dateRange: maplibregl.ExpressionSpecification[] = [
      ["<=", ["get", "fuzzy_start_decdate"], endYear],
      [">=", ["get", "fuzzy_end_decdate"], startYear],
    ];

    const filter: maplibregl.ExpressionSpecification = ["all", ...dateRange];
    const directionFilter: maplibregl.ExpressionSpecification = [
      "all",
      ["has", "direction"],
      ...dateRange,
    ];

    // Heatmap style layers
    if (map.getLayer(LAYER_IDS.imageHeatmap)) {
      map.setFilter(LAYER_IDS.imageHeatmap, filter);
    }
    if (map.getLayer(LAYER_IDS.imageCircles)) {
      map.setFilter(LAYER_IDS.imageCircles, filter);
    }
    if (map.getLayer(LAYER_IDS.imageDirections)) {
      map.setFilter(LAYER_IDS.imageDirections, directionFilter);
    }

    // Simple style layers
    if (map.getLayer(LAYER_IDS.imageCirclesSimple)) {
      map.setFilter(LAYER_IDS.imageCirclesSimple, filter);
    }
    if (map.getLayer(LAYER_IDS.imageDirectionsSimple)) {
      map.setFilter(LAYER_IDS.imageDirectionsSimple, directionFilter);
    }
  }

  onRemove() {
    if (this._outerContainer && this._outerContainer.parentNode) {
      this._outerContainer.parentNode.removeChild(this._outerContainer);
    }
    this._map = undefined;
  }
}
