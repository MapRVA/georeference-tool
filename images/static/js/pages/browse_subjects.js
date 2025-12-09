document.addEventListener("DOMContentLoaded", function () {
  const mapContainer = document.getElementById("subjects-map");
  if (!mapContainer) return; // Exit if no map on this page

  // Initialize MapLibre GL map with Protomaps white style
  const map = new maplibregl.Map({
    container: "subjects-map",
    style: `https://api.protomaps.com/styles/v5/white/en.json?key=${window.PROTOMAPS_API_KEY}`,
    center: [-77.43916, 37.54376],
    zoom: 13,
  });

  // Add fullscreen control
  map.addControl(new maplibregl.FullscreenControl());

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
      attribution: "Subject geometries © OpenStreetMap Contributors",
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

    // Large polygons (background)
    map.addLayer({
      id: "osm-elements-polygons-large-fill",
      type: "fill",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: [
        "all",
        [
          "in",
          ["get", "geom_type"],
          ["literal", ["ST_Polygon", "ST_MultiPolygon"]],
        ],
        [">=", ["get", "geometry_area"], 3e-6],
      ],
      paint: {
        "fill-color": "#ff6b35",
        "fill-opacity": 0.3,
      },
    });

    map.addLayer({
      id: "osm-elements-polygons-large-stroke",
      type: "line",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: [
        "all",
        [
          "in",
          ["get", "geom_type"],
          ["literal", ["ST_Polygon", "ST_MultiPolygon"]],
        ],
        [">=", ["get", "geometry_area"], 3e-6],
      ],
      paint: {
        "line-color": "#ff6b35",
        "line-width": 2,
        "line-opacity": 0.5,
      },
    });

    // Small polygons (on top)
    map.addLayer({
      id: "osm-elements-polygons-small-fill",
      type: "fill",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: [
        "all",
        [
          "in",
          ["get", "geom_type"],
          ["literal", ["ST_Polygon", "ST_MultiPolygon"]],
        ],
        ["<", ["get", "geometry_area"], 3e-6],
      ],
      paint: {
        "fill-color": "#ff6b35",
        "fill-opacity": 0.6,
      },
    });

    map.addLayer({
      id: "osm-elements-polygons-small-stroke",
      type: "line",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: [
        "all",
        [
          "in",
          ["get", "geom_type"],
          ["literal", ["ST_Polygon", "ST_MultiPolygon"]],
        ],
        ["<", ["get", "geometry_area"], 3e-6],
      ],
      paint: {
        "line-color": "#ff6b35",
        "line-width": 2,
        "line-opacity": 0.8,
      },
    });

    // Lines (above polygons)
    map.addLayer({
      id: "osm-elements-lines",
      type: "line",
      source: "osm-elements",
      "source-layer": "osm_elements",
      filter: [
        "in",
        ["get", "geom_type"],
        ["literal", ["ST_LineString", "ST_MultiLineString"]],
      ],
      paint: {
        "line-color": "#ff6b35",
        "line-width": 4,
        "line-opacity": 0.7,
      },
    });

    // Points (on top of everything)
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

    console.log("Layers added successfully");

    // Add hover tooltip for subject names
    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
    });

    const layerIds = [
      "osm-elements-points",
      "osm-elements-lines",
      "osm-elements-polygons-large-fill",
      "osm-elements-polygons-large-stroke",
      "osm-elements-polygons-small-fill",
      "osm-elements-polygons-small-stroke",
    ];

    // Debounce timer for hover interactions
    let hoverTimeout;

    // Use a single mousemove handler that queries features and picks the topmost one
    map.on("mousemove", (e) => {
      const features = map.queryRenderedFeatures(e.point, {
        layers: layerIds,
      });

      if (features.length > 0) {
        // The first feature in the array is the topmost rendered feature
        const feature = features[0];
        map.getCanvas().style.cursor = "pointer";

        const subjectName =
          feature.properties.subject_name || "Unknown Subject";
        const imageIds = feature.properties.image_ids
          ? feature.properties.image_ids.split(",").filter((id) => id)
          : [];

        // Show the popup immediately
        popup
          .setLngLat(e.lngLat)
          .setHTML(
            `<div class="bg-body text-body" style="cursor: pointer; white-space: nowrap; line-height: 1; border-radius: 1em;"><strong>${subjectName}</strong></div>`,
          )
          .addTo(map);

        // Debounce only the expensive georeference operations
        clearTimeout(hoverTimeout);
        hoverTimeout = setTimeout(() => {
          // Filter and highlight image georeferences for this subject
          if (imageIds.length > 0) {
            const numIds = imageIds.map((id) => parseInt(id));
            const filter = ["in", ["get", "id"], ["literal", numIds]];

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
        }, 10); // 10ms debounce delay for expensive operations only
      } else {
        // No features under cursor
        map.getCanvas().style.cursor = "";
        popup.remove();
        // Clear debounce timeout
        clearTimeout(hoverTimeout);
        // Reset to hidden state (no images visible)
        map.setPaintProperty("image-circles", "circle-opacity", 0);
        map.setPaintProperty("image-circles", "circle-stroke-opacity", 0);
        if (map.getLayer("image-directions")) {
          map.setPaintProperty("image-directions", "icon-opacity", 0);
        }
      }
    });

    // Click handler
    map.on("click", (e) => {
      const features = map.queryRenderedFeatures(e.point, {
        layers: layerIds,
      });

      if (features.length > 0) {
        const feature = features[0];
        const subjectSlug = feature.properties.subject_slug;
        if (subjectSlug) {
          window.location.href = `/subjects/${subjectSlug}/`;
        }
      }
    });
  });

  map.on("error", function (e) {
    console.error("Map error:", e);
  });
});
