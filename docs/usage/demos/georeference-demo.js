(() => {
    const mapElement = document.getElementById("georeference-demo-map");
    const joystickContainer = document.getElementById("joystick-container");
    const joystickHandle = document.getElementById("joystick-handle");

    if (
        !mapElement ||
        !joystickContainer ||
        !joystickHandle ||
        !window.maplibregl
    ) {
        return;
    }

    const pinSourceId = "georeference-demo-pin";
    const pinCircleLayerId = "georeference-demo-pin-circle";
    const pinDirectionLayerId = "georeference-demo-pin-direction";
    const directionImageId = "georeference-demo-direction";

    let pinCoordinates = null;
    let currentDirection = null;
    let isJoystickDragging = false;

    const dangerColor =
        getComputedStyle(document.documentElement)
            .getPropertyValue("--bs-danger")
            .trim() || "#d52e1c";

    const map = new window.maplibregl.Map({
        container: mapElement,
        style: "https://styles.maprva.org/openmaptiles-osm.json",
        center: [-77.434, 37.539],
        zoom: 17,
        attributionControl: false,
    });

    map.boxZoom.disable();
    map.doubleClickZoom.disable();
    map.dragPan.disable();
    map.dragRotate.disable();
    map.keyboard.disable();
    map.scrollZoom.disable();
    map.touchPitch.disable();
    map.touchZoomRotate.disable();

    map.addControl(
        new window.maplibregl.AttributionControl({ compact: false }),
        "bottom-right",
    );

    function pinData() {
        if (!pinCoordinates) {
            return {
                type: "FeatureCollection",
                features: [],
            };
        }

        const properties = {};
        if (currentDirection !== null) {
            properties.direction = currentDirection;
        }

        return {
            type: "FeatureCollection",
            features: [
                {
                    type: "Feature",
                    geometry: {
                        type: "Point",
                        coordinates: pinCoordinates,
                    },
                    properties,
                },
            ],
        };
    }

    function renderPin() {
        const source = map.getSource(pinSourceId);
        if (source) {
            source.setData(pinData());
        }
    }

    map.on("load", async () => {
        map.addSource(pinSourceId, {
            type: "geojson",
            data: pinData(),
        });

        map.addLayer({
            id: pinCircleLayerId,
            type: "circle",
            source: pinSourceId,
            paint: {
                "circle-radius": 8,
                "circle-color": dangerColor,
                "circle-stroke-color": "#fff",
                "circle-stroke-width": 2,
            },
        });

        try {
            const image = await map.loadImage("assets/surveillance-direction.png");
            map.addImage(directionImageId, image.data);
            map.addLayer(
                {
                    id: pinDirectionLayerId,
                    type: "symbol",
                    source: pinSourceId,
                    layout: {
                        "icon-image": directionImageId,
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
                    filter: ["has", "direction"],
                },
                pinCircleLayerId,
            );
            renderPin();
        } catch (error) {
            console.warn("Could not load the direction indicator:", error);
        }
    });

    map.on("click", (event) => {
        pinCoordinates = [event.lngLat.lng, event.lngLat.lat];
        joystickContainer.setAttribute("aria-disabled", "false");
        renderPin();
    });

    function joystickMaxRadius() {
        const containerRect = joystickContainer.getBoundingClientRect();
        const handleRect = joystickHandle.getBoundingClientRect();
        return containerRect.width / 2 - handleRect.width / 2;
    }

    function updateJoystick(clientX, clientY) {
        if (!pinCoordinates) {
            return;
        }

        const rect = joystickContainer.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        let x = clientX - centerX;
        let y = clientY - centerY;
        const maxRadius = joystickMaxRadius();
        const distance = Math.sqrt(x * x + y * y);

        if (distance > maxRadius) {
            const ratio = maxRadius / distance;
            x *= ratio;
            y *= ratio;
        }

        joystickHandle.style.transform =
            `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;

        const angle = (Math.atan2(y, x) * 180) / Math.PI;
        currentDirection = (angle + 90) % 360;
        if (currentDirection < 0) {
            currentDirection += 360;
        }

        renderPin();
    }

    joystickContainer.addEventListener("pointerdown", (event) => {
        if (!pinCoordinates) {
            return;
        }

        event.preventDefault();
        isJoystickDragging = true;
        joystickContainer.setPointerCapture(event.pointerId);
        updateJoystick(event.clientX, event.clientY);
    });

    joystickContainer.addEventListener("pointermove", (event) => {
        if (!isJoystickDragging) {
            return;
        }

        event.preventDefault();
        updateJoystick(event.clientX, event.clientY);
    });

    function stopJoystickDrag(event) {
        if (!isJoystickDragging) {
            return;
        }

        isJoystickDragging = false;
        if (joystickContainer.hasPointerCapture(event.pointerId)) {
            joystickContainer.releasePointerCapture(event.pointerId);
        }
    }

    joystickContainer.addEventListener("pointerup", stopJoystickDrag);
    joystickContainer.addEventListener("pointercancel", stopJoystickDrag);

    if ("ResizeObserver" in window) {
        new ResizeObserver(() => map.resize()).observe(mapElement);
    } else {
        window.addEventListener("resize", () => map.resize());
    }
})();
