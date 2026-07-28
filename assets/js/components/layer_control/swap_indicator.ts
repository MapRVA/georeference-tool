// Swapping between MapLibre style base layers rebuilds every layer's buckets
// and blocks the main thread while they upload — measured at ~3.9s for the
// 248-layer OpenStreetMap style in Firefox. Nothing here makes that faster; the
// indicator just stops the freeze from reading as a crash. The control button
// carries it: `aria-busy` swaps the layers icon for a spinner (CSS, so the
// compositor keeps it moving while the main thread is busy) and the caller
// renders "Switching…" in place of the layer name.
import type { Map as MapLibreMap } from "maplibre-gl";

// Safety net: if "idle" never arrives (style load error, map removed mid-swap),
// don't leave the button spinning forever.
const FALLBACK_TIMEOUT_MS = 15000;

export function showSwapIndicator(
  map: MapLibreMap,
  button: HTMLElement,
  onSwappingChange: (swapping: boolean) => void,
): void {
  const setSwapping = (swapping: boolean): void => {
    button.setAttribute("aria-busy", swapping ? "true" : "false");
    onSwappingChange(swapping);
  };

  let settled = false;
  const settle = (): void => {
    if (settled) return;
    settled = true;
    window.clearTimeout(fallbackTimer);
    map.off("idle", settle);
    setSwapping(false);
  };

  const fallbackTimer = window.setTimeout(settle, FALLBACK_TIMEOUT_MS);
  map.once("idle", settle);

  setSwapping(true);
}
