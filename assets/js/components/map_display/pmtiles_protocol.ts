import maplibregl from "maplibre-gl";
import * as pmtiles from "pmtiles";

// Registered on window (not exported) because layer_control/ and the still-JS
// page bundles share one protocol registration per page through these globals.
window.pmtilesProtocolSetup = false;

window.setupPMTilesProtocol = function () {
  if (window.pmtilesProtocolSetup) return true;

  if (typeof pmtiles !== "undefined") {
    try {
      console.log("Setting up PMTiles protocol...");
      let protocol = new pmtiles.Protocol();
      maplibregl.addProtocol("pmtiles", protocol.tile);
      console.log("PMTiles protocol setup complete");
      window.pmtilesProtocolSetup = true;
      return true;
    } catch (error) {
      console.error("Error setting up PMTiles protocol:", error);
      return false;
    }
  } else {
    console.log("PMTiles library not yet available");
    return false;
  }
};
