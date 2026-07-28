import type { ScaleHelpers, ScaleVisibilityConfig } from "./types";

// Zoom thresholds per image scale (5 = broadest views down to 1 = most
// zoomed-in). Referenced by map_display.html's enable_scale_visibility flag.
export const SCALE_VISIBILITY_ZOOMS: ScaleVisibilityConfig = {
  5: { pinpointZoom: 0, fullDetailZoom: 10 },
  4: { pinpointZoom: 11, fullDetailZoom: 14 },
  3: { pinpointZoom: 12, fullDetailZoom: 15 },
  2: { pinpointZoom: 13, fullDetailZoom: 16.5 },
  1: { pinpointZoom: 16.5, fullDetailZoom: 17.5 },
};

// Build scale visibility helper functions
export const buildScaleHelpers = (
  enableScaleVisibility: boolean,
  scaleVisibilityConfig: ScaleVisibilityConfig = SCALE_VISIBILITY_ZOOMS,
): ScaleHelpers => {
  if (!enableScaleVisibility) {
    return {
      isFullDetail: () => true,
    };
  }

  const getScaleConfig = (scale: number) => {
    if (!scale || scale === 0 || scale === 6) {
      return { pinpointZoom: 0, fullDetailZoom: 0 };
    }
    return (
      scaleVisibilityConfig[scale] || { pinpointZoom: 99, fullDetailZoom: 99 }
    );
  };

  const isFullDetail = (scale: number, zoom: number) => {
    const config = getScaleConfig(scale);
    return zoom >= config.fullDetailZoom;
  };

  return {
    isFullDetail,
  };
};
