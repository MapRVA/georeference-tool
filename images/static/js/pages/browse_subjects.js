document.addEventListener("DOMContentLoaded", function () {
  // Initialize MapLibre GL map with OpenStreetMap style
  const map = new maplibregl.Map({
    container: "subjects-map",
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        },
      },
      layers: [
        {
          id: "osm-layer",
          type: "raster",
          source: "osm",
        },
      ],
    },
    center: [-77.43916, 37.54376],
    zoom: 13,
  });

  // Add OSM elements tiles layer
  map.on("load", function () {
    console.log("Map loaded, adding OSM elements source");

    map.addSource("osm-elements", {
      type: "vector",
      tiles: [
        window.location.origin + "/api/v1/osm_element_tiles/{z}/{x}/{y}.pbf",
      ],
      minzoom: 0,
      maxzoom: 14,
      scheme: "xyz",
    });

    console.log("Source added, adding layers");

    // Add vector tiles source for regular image georeferences
    map.addSource("images", {
      type: "vector",
      tiles: [window.location.origin + "/api/v1/tiles/{z}/{x}/{y}.mvt"],
      minzoom: 0,
      maxzoom: 18,
    });

    // Load direction arrow image asynchronously
    (async () => {
      try {
        const image = await map.loadImage(
          "https://maprva.org/img/surveillance-direction.png",
        );
        map.addImage("image-direction", image.data);

        // Add direction markers for image georeferences
        map.addLayer({
          id: "image-directions",
          type: "symbol",
          source: "images",
          "source-layer": "image_points",
          filter: ["has", "direction"],
          layout: {
            "icon-image": "image-direction",
            "icon-overlap": "always",
            "icon-size": {
              stops: [
                [5, 0.3],
                [15, 1],
              ],
            },
            "icon-rotate": ["to-number", ["get", "direction"]],
            "icon-rotation-alignment": "map",
            "icon-pitch-alignment": "map",
          },
          paint: {
            "icon-opacity": 0, // Hidden by default, will show on hover
          },
        });
      } catch (error) {
        console.warn("Could not load direction arrow image:", error);
      }
    })();

    // Add circle layer for image georeferences
    map.addLayer({
      id: "image-circles",
      type: "circle",
      source: "images",
      "source-layer": "image_points",
      paint: {
        "circle-radius": 8,
        "circle-color": "green",
        "circle-stroke-color": "#fff",
        "circle-stroke-width": 2,
        "circle-opacity": 0, // Hidden by default, will show on hover
        "circle-stroke-opacity": 0, // Hide stroke initially too
      },
    });

    console.log("Image circles layer added");

    map.addLayer({
      id: "osm-elements-points",
      type: "circle",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: ["==", ["get", "geom_type"], "ST_Point"],
      paint: {
        "circle-radius": 6,
        "circle-color": "#ff6b35",
        "circle-opacity": 0.7,
        "circle-stroke-width": 2,
        "circle-stroke-color": "#fff",
      },
    });

    map.addLayer({
      id: "osm-elements-lines",
      type: "line",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: ["==", ["get", "geom_type"], "ST_LineString"],
      paint: {
        "line-color": "#ff6b35",
        "line-width": 2,
        "line-opacity": 0.7,
      },
    });

    map.addLayer({
      id: "osm-elements-polygons",
      type: "fill",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: ["==", ["get", "geom_type"], "ST_MultiPolygon"],
      paint: {
        "fill-color": "#ff6b35",
        "fill-opacity": 0.5,
      },
    });

    map.addLayer({
      id: "osm-elements-polygons-stroke",
      type: "line",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: ["==", ["get", "geom_type"], "ST_MultiPolygon"],
      paint: {
        "line-color": "#ff6b35",
        "line-width": 2,
        "line-opacity": 0.7,
      },
    });

    console.log("Layers added successfully");

    // Add hover tooltip for subject names
    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
    });

    const layerIds = [
      "osm-elements-points",
      "osm-elements-lines",
      "osm-elements-polygons",
    ];

    layerIds.forEach((layerId) => {
      map.on("mousemove", layerId, (e) => {
        map.getCanvas().style.cursor = "pointer";

        if (e.features.length > 0) {
          const feature = e.features[0];
          const subjectName =
            feature.properties.subject_name || "Unknown Subject";
          console.log("Feature properties:", feature.properties);
          const imageIds = feature.properties.image_ids
            ? feature.properties.image_ids.split(",").filter((id) => id)
            : [];

          console.log(
            "Hovering subject:",
            subjectName,
            "Raw image_ids:",
            feature.properties.image_ids,
            "Parsed:",
            imageIds,
          );

          // Show the popup
          popup
            .setLngLat(e.lngLat)
            .setHTML(
              `<div style="cursor: pointer; white-space: nowrap; line-height: 1; border-radius: 1em;"><strong>${subjectName}</strong></div>`,
            )
            .addTo(map);

          // Filter and highlight image georeferences for this subject
          if (imageIds.length > 0) {
            const numIds = imageIds.map((id) => parseInt(id));
            console.log("Filtering to IDs:", numIds);

            // Use a match expression to highlight only these IDs
            const filter = ["in", ["get", "id"], ["literal", numIds]];
            console.log("Filter expression:", filter);

            // Set paint property to show only matching circles at full opacity
            map.setPaintProperty("image-circles", "circle-opacity", [
              "case",
              filter,
              1, // Matching images: full opacity
              0, // Non-matching images: hidden
            ]);
            // Keep circles green, hide stroke on non-matching
            map.setPaintProperty("image-circles", "circle-stroke-opacity", [
              "case",
              filter,
              1, // Matching images: visible stroke
              0, // Non-matching images: hidden stroke
            ]);

            if (map.getLayer("image-directions")) {
              map.setPaintProperty("image-directions", "icon-opacity", [
                "case",
                filter,
                1, // Matching: visible
                0, // Non-matching: hidden
              ]);
            }
          } else {
            // No images for this subject, hide all circles
            map.setPaintProperty("image-circles", "circle-opacity", 0);
            map.setPaintProperty("image-circles", "circle-stroke-opacity", 0);
            if (map.getLayer("image-directions")) {
              map.setPaintProperty("image-directions", "icon-opacity", 0);
            }
          }
        }
      });

      map.on("mouseleave", layerId, () => {
        map.getCanvas().style.cursor = "";
        popup.remove();

        // Reset to hidden state (no images visible)
        map.setPaintProperty("image-circles", "circle-opacity", 0);
        map.setPaintProperty("image-circles", "circle-stroke-opacity", 0);
        if (map.getLayer("image-directions")) {
          map.setPaintProperty("image-directions", "icon-opacity", 0);
        }
      });

      map.on("click", layerId, (e) => {
        if (e.features.length > 0) {
          const feature = e.features[0];
          const subjectSlug = feature.properties.subject_slug;

          if (subjectSlug) {
            window.location.href = `/subjects/${subjectSlug}/`;
          }
        }
      });
    });
  });

  map.on("error", function (e) {
    console.error("Map error:", e);
  });
});
