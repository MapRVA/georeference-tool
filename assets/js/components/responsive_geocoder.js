/**
 * ResponsiveGeocoder - A wrapper for MaplibreGeocoder that responds to screen size changes
 *
 * This module provides a geocoder that:
 * - Starts collapsed on small screens (≤1000px)
 * - Starts expanded on larger screens
 * - Automatically recreates itself when crossing the breakpoint to properly update hover behavior
 *
 * Usage:
 *   import { addResponsiveGeocoder } from './responsive_geocoder.js';
 *
 *   // With default Nominatim geocoder API (Richmond area)
 *   addResponsiveGeocoder(map);
 *
 *   // With custom geocoder API
 *   addResponsiveGeocoder(map, { geocoderApi: myCustomApi });
 *
 *   // With custom breakpoint
 *   addResponsiveGeocoder(map, { breakpoint: 768 });
 */

import MaplibreGeocoder from "@maplibre/maplibre-gl-geocoder";
import "@maplibre/maplibre-gl-geocoder/dist/maplibre-gl-geocoder.css";
import "../../styles/components/geocoder-overrides.css";
import maplibregl from "maplibre-gl";

/**
 * Default Nominatim geocoder API for Richmond area
 */
const createDefaultGeocoderApi = (email) => ({
  forwardGeocode: async (config) => {
    const features = [];
    try {
      const params = new URLSearchParams({
        q: config.query,
        format: "geojson",
        polygon_geojson: 1,
        addressdetails: 1,
        layer: "address",
        viewbox: "-117.51121814943878, 34.00530124508274,-117.29947444598987, 33.91357514704981",
        bounded: 1,
      });
      if (email) {
        params.set("email", email);
      }

      const request = `https://nominatim.openstreetmap.org/search?${params}`;
      const response = await fetch(request);
      const geojson = await response.json();
      for (const feature of geojson.features) {
        const center = [
          feature.bbox[0] + (feature.bbox[2] - feature.bbox[0]) / 2,
          feature.bbox[1] + (feature.bbox[3] - feature.bbox[1]) / 2,
        ];
        const point = {
          type: "Feature",
          geometry: { type: "Point", coordinates: center },
          place_name: feature.properties.display_name,
          properties: feature.properties,
          text: feature.properties.display_name,
          place_type: ["place"],
          center,
        };
        features.push(point);
      }
    } catch (e) {
      console.error(`Failed to forwardGeocode with error: ${e}`);
    }
    return { features };
  },
});

/**
 * Add a responsive geocoder control to a map
 *
 * @param {maplibregl.Map} map - The MapLibre map instance
 * @param {Object} options - Configuration options
 * @param {Object} options.geocoderApi - Custom geocoder API (default: Nominatim for Richmond area)
 * @param {number} options.breakpoint - Screen width breakpoint in pixels (default: 1000)
 * @param {string} options.placeholder - Placeholder text for the search input (default: "Search places")
 * @param {string} options.position - Map control position (default: "top-left")
 * @returns {Object} Object with cleanup function to remove the geocoder and event listener
 */
export function addResponsiveGeocoder(map, options = {}) {
  const {
    geocoderApi = createDefaultGeocoderApi(window.ADMIN_EMAIL),
    breakpoint = 1000,
    placeholder = "Search places",
    position = "top-left",
  } = options;

  const smallScreenQuery = window.matchMedia(`(max-width: ${breakpoint}px)`);

  const createGeocoder = (collapsed) => {
    return new MaplibreGeocoder(geocoderApi, {
      maplibregl,
      placeholder,
      collapsed,
    });
  };

  let geocoder = createGeocoder(smallScreenQuery.matches);
  map.addControl(geocoder, position);

  // Fix geocoder search on mobile Chrome
  const fixGeocoderInput = () => {
    const geocoderInput = map
      .getContainer()
      .querySelector(".maplibregl-ctrl-geocoder--input");
    if (geocoderInput) {
      geocoderInput.type = "search";
    }
  };
  fixGeocoderInput();

  // Recreate geocoder on resize to properly update collapsed behavior
  const handleResize = (e) => {
    map.removeControl(geocoder);
    geocoder = createGeocoder(e.matches);
    map.addControl(geocoder, position);
    fixGeocoderInput();
  };

  smallScreenQuery.addEventListener("change", handleResize);

  // Return cleanup function
  return {
    remove: () => {
      smallScreenQuery.removeEventListener("change", handleResize);
      map.removeControl(geocoder);
    },
    getGeocoder: () => geocoder,
  };
}
