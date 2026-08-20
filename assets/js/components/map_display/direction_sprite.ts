import type { Map as MapLibreMap } from "maplibre-gl";
import { DIRECTION_SPRITE_ID } from "./layer_ids";

// Direction-arrow sprite for map pages that don't receive the arrow as a
// template-provided static asset URL (map_display does, via its config).
export const DIRECTION_SPRITE_URL =
  "https://maprva.org/img/surveillance-direction.png";

// Fetch and register the arrow under DIRECTION_SPRITE_ID. Safe to call again
// after a style swap discards the map's images.
//
// Callers that do have the static asset URL to hand (a template passing
// {% static %}, as map_display's config does) should pass it, so the page
// isn't making a cross-origin request for an icon it already ships.
export async function ensureDirectionSprite(
  map: MapLibreMap,
  url: string = DIRECTION_SPRITE_URL,
): Promise<void> {
  if (map.hasImage(DIRECTION_SPRITE_ID)) return;
  try {
    const image = await map.loadImage(url);
    if (!map.hasImage(DIRECTION_SPRITE_ID)) {
      map.addImage(DIRECTION_SPRITE_ID, image.data);
    }
  } catch (error) {
    console.warn("Could not load direction arrow image:", error);
  }
}
