/**
 * LayerControl - A shared MapLibre control for switching between base layers
 * and overlays.
 *
 * Base layers and overlays come from window.MAP_LAYERS_DATA (set by the
 * images.context_processors.site_settings context processor). Primary layers
 * (no collection) become base layer options; layers inside a collection become
 * overlay options.
 *
 * Usage:
 *   import { LayerControl } from "../components/layer_control";
 *
 *   // Basic usage (for georeference interfaces)
 *   map.addControl(new LayerControl(), "top-right");
 *
 *   // With image layer toggle (for map_display)
 *   map.addControl(new LayerControl({
 *     showImageLayerToggle: true,
 *     overlayLayerIds: OVERLAY_LAYER_IDS,
 *     beforeLayerId: LAYER_IDS.imageHeatmap,
 *   }), "top-right");
 */

import type { IControl, Map as MapLibreMap } from "maplibre-gl";
import "../../../styles/components/layer-control.css";
import {
  hideRasterBaseLayers,
  moveBaseLayerBelowOverlays,
  setDefaultStyleLayersVisibility,
  setRasterBaseLayerVisibility,
  setupRasterBaseLayer,
} from "./base_layers";
import {
  DEFAULT_SIMPLE_RADIUS,
  updateImageLayerVisibility,
  updateSimpleCircleRadius,
} from "./image_layers";
import {
  buildImageLayerPanel,
  type ImageLayerPanel,
} from "./image_layer_panel";
import { findBeforeLayerId, isOverlayLayerId } from "./layer_classification";
import {
  createLayerOffcanvas,
  populateBaseLayerButtons,
  populateCollectionSubmenus,
  showLayerLoadError,
  type LayerOffcanvas,
} from "./offcanvas";
import {
  addOverlayLayer,
  addOverlaySource,
  ensurePMTilesProtocol,
  hideOtherOverlayLayers,
} from "./overlay_layers";
import { showSwapIndicator } from "./swap_indicator";
import type {
  BaseLayer,
  ImageDisplayStyle,
  LayerCollectionData,
  LayerControlOptions,
  OverlayLayerConfig,
  PrimaryLayerData,
  ResolvedLayerControlOptions,
} from "./types";

export class LayerControl implements IControl {
  private readonly options: ResolvedLayerControlOptions;

  private baseLayers: Record<string, BaseLayer> = {};
  private collections: LayerCollectionData[] = [];
  private currentBaseLayer: string | null = null;
  private currentOverlay: OverlayLayerConfig | null = null;
  private defaultStyleUrl: string | null = null;
  // True while a non-default MapLibre style is loaded, so the next base layer
  // change knows it has to swap the default style back in first
  private nonDefaultStyleActive = false;

  private imageLayersVisible = true;
  private imageDisplayStyle: ImageDisplayStyle = "heatmap";
  private simpleCircleRadius = DEFAULT_SIMPLE_RADIUS;
  // True from the moment a style swap starts until the map settles, so the
  // control button reports the swap instead of the layer it is switching to
  private swapping = false;

  private map: MapLibreMap | undefined;
  private mapId = "";
  // Assigned in onAdd(), which MapLibre calls before anything else
  private container!: HTMLElement;
  private layerLabel!: HTMLElement;
  private triggerButton!: HTMLButtonElement;
  private offcanvas!: LayerOffcanvas;
  private imagePanel: ImageLayerPanel | null = null;
  private fullscreenChangeHandler: (() => void) | null = null;

  constructor(options: LayerControlOptions = {}) {
    this.options = {
      showImageLayerToggle: options.showImageLayerToggle ?? false,
      overlayLayerIds: options.overlayLayerIds ?? [],
      beforeLayerId: options.beforeLayerId ?? null,
      onBaseLayerChange: options.onBaseLayerChange ?? null,
      onStyleSwap: options.onStyleSwap ?? null,
    };
  }

  onAdd(map: MapLibreMap): HTMLElement {
    this.map = map;
    this.mapId = map.getContainer().id;

    this.container = document.createElement("div");
    this.container.className =
      "maplibregl-ctrl maplibregl-ctrl-group layer-control";
    // Both icons are present in the markup and swapped by CSS on aria-busy:
    // Font Awesome replaces these <i> elements with <svg> nodes, so toggling
    // icon classes from JS would fight that replacement.
    this.container.innerHTML = `
      <button type="button" class="layer-control-button" aria-label="Map layers" aria-busy="false">
        <i class="fas fa-layer-group layer-control-icon"></i>
        <i class="fas fa-spinner fa-spin layer-control-busy-icon"></i>
        <span class="layer-control-label"></span>
      </button>
    `;

    // The elements always exist: the markup was assigned via innerHTML above.
    this.layerLabel = this.container.querySelector<HTMLElement>(
      ".layer-control-label",
    )!;
    this.triggerButton = this.container.querySelector<HTMLButtonElement>(
      ".layer-control-button",
    )!;

    this.offcanvas = createLayerOffcanvas(this.mapId);
    this.triggerButton.addEventListener("click", () => {
      this.offcanvas.instance.show();
    });

    // Keep the offcanvas reachable when the map goes fullscreen
    this.fullscreenChangeHandler = () => this.handleFullscreenChange();
    document.addEventListener("fullscreenchange", this.fullscreenChangeHandler);

    if (map.loaded()) {
      this.initializeLayers();
    } else {
      map.on("load", () => this.initializeLayers());
    }

    this.renderLayerLabel();

    return this.container;
  }

  onRemove(): void {
    if (this.fullscreenChangeHandler) {
      document.removeEventListener(
        "fullscreenchange",
        this.fullscreenChangeHandler,
      );
      this.fullscreenChangeHandler = null;
    }

    this.offcanvas.instance.dispose();
    this.offcanvas.element.remove();
    this.container.remove();
    this.map = undefined;
  }

  /**
   * Apply the current image layer visibility. Called after a style swap, once
   * map_display has re-added its layers.
   */
  applyImageLayerVisibility(): void {
    if (!this.map) return;
    updateImageLayerVisibility(
      this.map,
      this.imageLayersVisible,
      this.imageDisplayStyle,
    );
  }

  private handleFullscreenChange(): void {
    if (!this.map) return;

    const mapContainer = this.map.getContainer();
    if (document.fullscreenElement === mapContainer) {
      // Map is now fullscreen - move offcanvas inside the map container
      mapContainer.appendChild(this.offcanvas.element);
    } else if (!document.fullscreenElement) {
      // Exited fullscreen - move offcanvas back to document.body
      document.body.appendChild(this.offcanvas.element);
    }
  }

  private initializeLayers(): void {
    const data = window.MAP_LAYERS_DATA;
    if (!data) {
      console.error("MAP_LAYERS_DATA not found on window");
      showLayerLoadError(this.offcanvas.overlayContainer);
      return;
    }

    if (data.primary_layers && data.primary_layers.length > 0) {
      this.buildBaseLayers(data.primary_layers);
    }
    this.collections = data.collections ?? [];

    populateBaseLayerButtons(
      this.offcanvas.baseLayersList,
      this.baseLayers,
      this.currentBaseLayer,
      (layerKey) => {
        if (layerKey === this.currentBaseLayer) return;
        this.switchToBaseLayer(layerKey);
        this.offcanvas.instance.hide();
      },
    );

    this.populateOverlays();
    this.renderLayerLabel();
  }

  /**
   * Build base layers from the primary_layers payload. The default style-type
   * layer is shown and hidden in place; other style-type layers swap the map
   * style, and XYZ layers get their own raster source and layer.
   */
  private buildBaseLayers(primaryLayers: PrimaryLayerData[]): void {
    for (const layer of primaryLayers) {
      const key = layer.slug;

      if (layer.type === "style" && layer.is_default) {
        this.baseLayers[key] = {
          name: layer.name,
          isDefault: true,
          type: "style",
          url: layer.url,
          setupLayer: () => {},
          activate: () => this.showDefaultStyleLayers(),
          deactivate: () => this.setDefaultStyleLayersVisible(false),
        };
        this.currentBaseLayer = key;
        this.defaultStyleUrl = layer.url;
      } else if (layer.type === "style") {
        this.baseLayers[key] = {
          name: layer.name,
          isDefault: false,
          type: "style",
          url: layer.url,
          setupLayer: () => {},
          activate: () => this.activateStyle(layer.url),
          deactivate: () => {},
        };
      } else if (layer.type === "xyz") {
        const sourceId = `base-${key}`;
        const layerId = `base-${key}-layer`;
        this.baseLayers[key] = {
          name: layer.name,
          isDefault: false,
          type: "xyz",
          sourceId,
          layerId,
          setupLayer: () =>
            this.setupRasterBase(
              sourceId,
              layerId,
              layer.url,
              layer.attribution || "",
            ),
          activate: () => this.activateRasterBase(layerId),
          deactivate: () => this.deactivateRasterBase(layerId),
        };
      }
    }

    // Fallback: if no default was set, use the first layer
    const firstKey = primaryLayers[0]?.slug;
    const firstLayer = firstKey ? this.baseLayers[firstKey] : undefined;
    if (!this.currentBaseLayer && firstKey && firstLayer) {
      firstLayer.isDefault = true;
      this.currentBaseLayer = firstKey;
    }

    for (const baseLayer of Object.values(this.baseLayers)) {
      baseLayer.setupLayer();
    }
  }

  private populateOverlays(): void {
    populateCollectionSubmenus(
      this.offcanvas.overlayContainer,
      this.collections,
      (overlay) => {
        this.switchToOverlayLayer(overlay);
        this.offcanvas.instance.hide();
      },
    );

    if (this.options.showImageLayerToggle) {
      this.imagePanel = buildImageLayerPanel(this.offcanvas.overlayContainer, {
        mapId: this.mapId,
        initialRadius: this.simpleCircleRadius,
        onToggleImageLayers: () => {
          this.toggleImageLayers();
          this.offcanvas.instance.hide();
        },
        onStyleChange: (style) => this.setImageDisplayStyle(style),
        onRadiusChange: (radius) => this.setSimpleCircleRadius(radius),
      });
    }
  }

  private switchToBaseLayer(newLayerKey: string): void {
    const newLayer = this.baseLayers[newLayerKey];
    if (!newLayer || newLayerKey === this.currentBaseLayer) return;

    const currentLayer = this.currentBaseLayer
      ? this.baseLayers[this.currentBaseLayer]
      : undefined;
    currentLayer?.deactivate();
    newLayer.activate();
    this.currentBaseLayer = newLayerKey;

    this.updateSelection();
    this.options.onBaseLayerChange?.(newLayerKey);
  }

  private isOverlay = (layerId: string): boolean =>
    isOverlayLayerId(layerId, this.options.overlayLayerIds);

  // Layers belonging to the map's own style: everything that is neither an
  // overlay nor one of our raster base layers.
  private isDefaultStyleLayer = (layerId: string): boolean =>
    !this.isOverlay(layerId) && !this.isCustomBaseLayer(layerId);

  private isCustomBaseLayer(layerId: string): boolean {
    return Object.values(this.baseLayers).some(
      (baseLayer) => baseLayer.type === "xyz" && baseLayer.layerId === layerId,
    );
  }

  private setupRasterBase(
    sourceId: string,
    layerId: string,
    url: string,
    attribution: string,
  ): void {
    if (!this.map) return;
    setupRasterBaseLayer(this.map, sourceId, layerId, url, attribution);
  }

  private activateRasterBase(layerId: string): void {
    if (this.nonDefaultStyleActive && this.defaultStyleUrl) {
      // Returning from a non-default style — restore default then show raster
      this.nonDefaultStyleActive = false;
      this.swapStyle(this.defaultStyleUrl, () => this.showRasterBase(layerId));
      return;
    }
    this.showRasterBase(layerId);
  }

  private showRasterBase(layerId: string): void {
    const map = this.map;
    if (!map) return;

    this.setDefaultStyleLayersVisible(false);
    hideRasterBaseLayers(map, this.baseLayers, layerId);
    if (map.getLayer(layerId)) {
      moveBaseLayerBelowOverlays(map, layerId, this.isOverlay);
      setRasterBaseLayerVisibility(map, layerId, true);
    }
  }

  private deactivateRasterBase(layerId: string): void {
    if (!this.map) return;
    setRasterBaseLayerVisibility(this.map, layerId, false);
  }

  private showDefaultStyleLayers(): void {
    if (this.nonDefaultStyleActive && this.defaultStyleUrl) {
      // Returning from a non-default style — restore the default style
      this.nonDefaultStyleActive = false;
      this.swapStyle(this.defaultStyleUrl);
      return;
    }

    if (!this.map) return;
    hideRasterBaseLayers(this.map, this.baseLayers);
    this.setDefaultStyleLayersVisible(true);
  }

  private setDefaultStyleLayersVisible(visible: boolean): void {
    if (!this.map) return;
    setDefaultStyleLayersVisibility(
      this.map,
      visible,
      this.isDefaultStyleLayer,
    );
  }

  private activateStyle(styleUrl: string): void {
    this.nonDefaultStyleActive = true;
    this.swapStyle(styleUrl);
  }

  /**
   * Swap the map style and restore the raster base layers and the active tile
   * overlay, both of which setStyle() destroys.
   */
  private swapStyle(styleUrl: string, afterRestore?: () => void): void {
    const map = this.map;
    if (!map) return;

    // Captured before the swap, since switching resets the overlay state
    const savedOverlay = this.currentOverlay;

    // Rebuilding a style's layers blocks the main thread for seconds on large
    // styles; report that on the button before the freeze starts
    showSwapIndicator(map, this.triggerButton, (swapping) => {
      this.swapping = swapping;
      this.renderLayerLabel();
    });

    map.setStyle(styleUrl);

    map.once("style.load", async () => {
      for (const baseLayer of Object.values(this.baseLayers)) {
        if (baseLayer.type === "xyz") baseLayer.setupLayer();
      }

      // Notify consumers to re-add their layers BEFORE restoring the overlay
      // tile layer. This ensures consumer layers (Geoman polygons, hint
      // markers, pins, etc.) exist when switchToOverlayLayer looks for the
      // layer to insert before, so the overlay raster ends up beneath them.
      if (this.options.onStyleSwap) {
        await this.options.onStyleSwap(map);
      }

      if (savedOverlay) {
        // Reset so switchToOverlayLayer re-adds instead of toggling off
        this.currentOverlay = null;
        this.switchToOverlayLayer(savedOverlay);
      }

      afterRestore?.();
    });
  }

  private switchToOverlayLayer(overlay: OverlayLayerConfig): void {
    const map = this.map;
    if (!map) return;

    const { layerId, tileUrl, tileType, attribution } = overlay;

    if (tileType === "pmtiles" && !ensurePMTilesProtocol()) {
      alert(
        "PMTiles map overlay layers are not available - PMTiles protocol not loaded.",
      );
      return;
    }

    // Clicking the active overlay turns it off
    if (this.currentOverlay?.layerId === layerId) {
      map.setLayoutProperty(layerId, "visibility", "none");
      this.currentOverlay = null;
      this.updateSelection();
      return;
    }

    hideOtherOverlayLayers(map, layerId);

    const sourceId = `${layerId}-source`;
    if (!addOverlaySource(map, sourceId, tileUrl, tileType, attribution)) {
      return;
    }

    if (!map.getLayer(layerId)) {
      const beforeId = findBeforeLayerId(map, this.options.beforeLayerId);
      if (!addOverlayLayer(map, layerId, sourceId, beforeId)) return;
    }

    map.setLayoutProperty(layerId, "visibility", "visible");
    this.currentOverlay = overlay;
    this.updateSelection();
  }

  private toggleImageLayers(): void {
    this.imageLayersVisible = !this.imageLayersVisible;
    this.applyImageLayerVisibility();
    this.imagePanel?.setImageLayersActive(this.imageLayersVisible);
    this.imagePanel?.setControlsEnabled(this.imageLayersVisible);
  }

  private setImageDisplayStyle(style: ImageDisplayStyle): void {
    this.imageDisplayStyle = style;
    this.applyImageLayerVisibility();
    this.imagePanel?.setRadiusVisible(style === "simple");
  }

  private setSimpleCircleRadius(radius: number): void {
    this.simpleCircleRadius = radius;
    if (!this.map) return;
    updateSimpleCircleRadius(this.map, radius);
  }

  private updateSelection(): void {
    const { element } = this.offcanvas;

    // Reset base layer and overlay selections, but not the independent image
    // layer toggle
    element.querySelectorAll(".layer-option").forEach((item) => {
      item.classList.remove("active");
    });
    element
      .querySelectorAll(
        '.overlay-layer:not([data-layer="georeferenced-images"])',
      )
      .forEach((item) => {
        item.classList.remove("active");
      });

    element
      .querySelector(`.layer-option[data-layer="${this.currentBaseLayer}"]`)
      ?.classList.add("active");

    if (this.currentOverlay) {
      element
        .querySelector(
          `.overlay-layer[data-layer="${this.currentOverlay.layerId}"]`,
        )
        ?.classList.add("active");
    }

    this.renderLayerLabel();
  }

  private renderLayerLabel(): void {
    if (this.swapping) {
      this.layerLabel.textContent = "Switching…";
      return;
    }

    const baseLayerName = this.currentBaseLayer
      ? (this.baseLayers[this.currentBaseLayer]?.name ?? "")
      : "";
    const overlayName = this.currentOverlay?.title;

    this.layerLabel.textContent = overlayName
      ? `${baseLayerName} + ${overlayName}`
      : baseLayerName;
  }
}
