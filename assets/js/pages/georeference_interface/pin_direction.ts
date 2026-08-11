// Pin placement, direction joystick, and the bearing line drawn from the pin.
import type { GeoJSONSource } from "maplibre-gl";
import { updateConfidenceValidation } from "./form";
import { emptyFeatureCollection, pinFeatureCollection } from "./geojson";
import type { GeoreferenceContext } from "./types";

/**
 * Project a point along a bearing for a given distance.
 * Returns [lng, lat] for the destination point.
 */
function destinationPoint(
  lngLat: [number, number],
  bearingDeg: number,
  distanceMeters: number,
): [number, number] {
  const R = 6371000; // Earth radius in meters
  const toRad = (d: number): number => (d * Math.PI) / 180;
  const toDeg = (r: number): number => (r * 180) / Math.PI;
  const lat1 = toRad(lngLat[1]);
  const lng1 = toRad(lngLat[0]);
  const bearing = toRad(bearingDeg);
  const angularDist = distanceMeters / R;

  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(angularDist) +
      Math.cos(lat1) * Math.sin(angularDist) * Math.cos(bearing),
  );
  const lng2 =
    lng1 +
    Math.atan2(
      Math.sin(bearing) * Math.sin(angularDist) * Math.cos(lat1),
      Math.cos(angularDist) - Math.sin(lat1) * Math.sin(lat2),
    );

  return [toDeg(lng2), toDeg(lat2)];
}

export function updateCoordinates(
  ctx: GeoreferenceContext,
  lng: number,
  lat: number,
): void {
  ctx.els.latitudeInput.value = lat.toFixed(6);
  ctx.els.longitudeInput.value = lng.toFixed(6);
  ctx.els.submitButton.disabled = false;
}

export function updateBearingLine(ctx: GeoreferenceContext): void {
  const { map, els, state } = ctx;
  const source = map.getSource<GeoJSONSource>("bearing-line");
  if (!source) return;

  const lat = parseFloat(els.latitudeInput.value);
  const lng = parseFloat(els.longitudeInput.value);
  const direction = state.currentDirection;

  const bearingLineVisible =
    state.bearingLineEnabled &&
    state.pinPlaced &&
    direction !== null &&
    !isNaN(lat) &&
    !isNaN(lng);

  // Sync image centerline with map bearing line visibility.
  // Uses `visibility` rather than `display` because OSD's overlay renderer
  // resets `display` to "block" on every repaint.
  if (state.osdCenterlineOverlay) {
    state.osdCenterlineOverlay.style.visibility = bearingLineVisible
      ? "visible"
      : "hidden";
  }
  const imageCenterline =
    document.querySelector<HTMLElement>(".image-centerline");
  if (imageCenterline) {
    imageCenterline.style.visibility = bearingLineVisible
      ? "visible"
      : "hidden";
  }

  if (bearingLineVisible) {
    // 5000 km should be plenty...
    const totalDist = 5000000;

    // Interpolate points along the great circle so the line curves correctly
    // when zoomed out on a Mercator projection
    const numSegments = Math.max(2, Math.ceil(64 * (totalDist / 20000000)));
    const stepDist = totalDist / numSegments;
    const origin: [number, number] = [lng, lat];
    const coordinates: [number, number][] = [origin];
    for (let i = 1; i <= numSegments; i++) {
      coordinates.push(destinationPoint(origin, direction, stepDist * i));
    }

    source.setData({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          geometry: { type: "LineString", coordinates },
          properties: {},
        },
      ],
    });
  } else {
    source.setData(emptyFeatureCollection());
  }
}

export function updateDirection(
  ctx: GeoreferenceContext,
  direction: number | null,
): void {
  const { map, els, state } = ctx;
  state.currentDirection = direction;

  if (direction !== null) {
    els.directionInput.value = Math.round(direction) + "°";
    els.directionInput.classList.remove("inactive");
  } else {
    els.directionInput.value = "";
    els.directionInput.classList.add("inactive");
    updateJoystickHandle(ctx, 0, 0);
  }

  // Update pin direction
  if (state.pinPlaced) {
    const lat = parseFloat(els.latitudeInput.value);
    const lng = parseFloat(els.longitudeInput.value);
    if (!isNaN(lat) && !isNaN(lng)) {
      map
        .getSource<GeoJSONSource>("pin")
        ?.setData(pinFeatureCollection(lng, lat, direction));
    }
  }

  // Update confidence validation based on new direction
  updateConfidenceValidation(ctx);

  // Update bearing centerline
  updateBearingLine(ctx);
}

function getJoystickMaxRadius(ctx: GeoreferenceContext): number {
  const containerRect = ctx.els.joystickContainer.getBoundingClientRect();
  const handleRect = ctx.els.joystickHandle.getBoundingClientRect();
  const handleMargin = handleRect.width / 2; // Half the handle size as margin
  return containerRect.width / 2 - handleMargin;
}

export function updateJoystickHandle(
  ctx: GeoreferenceContext,
  x: number,
  y: number,
): void {
  const maxRadius = getJoystickMaxRadius(ctx);
  const distance = Math.sqrt(x * x + y * y);

  if (distance > maxRadius) {
    const ratio = maxRadius / distance;
    x *= ratio;
    y *= ratio;
  }

  ctx.els.joystickHandle.style.transform =
    "translate(calc(-50% + " + x + "px), calc(-50% + " + y + "px))";
}

// Snap the joystick handle to the container edge at the given bearing.
export function setJoystickFromDirection(
  ctx: GeoreferenceContext,
  direction: number,
): void {
  const radians = ((direction - 90) * Math.PI) / 180;
  const radius = getJoystickMaxRadius(ctx);
  updateJoystickHandle(
    ctx,
    Math.cos(radians) * radius,
    Math.sin(radians) * radius,
  );
}

function updatePinLocation(
  ctx: GeoreferenceContext,
  lng: number,
  lat: number,
  direction: number | null,
): void {
  const source = ctx.map.getSource<GeoJSONSource>("pin");
  if (!source) return;

  source.setData(pinFeatureCollection(lng, lat, direction));
  ctx.map.setCenter([lng, lat]);
}

function handleJoystickMove(
  ctx: GeoreferenceContext,
  clientX: number,
  clientY: number,
): void {
  if (!ctx.state.pinPlaced) return;

  const rect = ctx.els.joystickContainer.getBoundingClientRect();
  const centerX = rect.left + rect.width / 2;
  const centerY = rect.top + rect.height / 2;
  const x = clientX - centerX;
  const y = clientY - centerY;

  // Calculate direction (0° is north)
  const angle = (Math.atan2(y, x) * 180) / Math.PI;
  let direction = (angle + 90) % 360;
  if (direction < 0) direction += 360;

  updateDirection(ctx, direction);
  updateJoystickHandle(ctx, x, y);
}

export function initJoystick(ctx: GeoreferenceContext): void {
  const { els, state } = ctx;

  // Mouse events
  els.joystickContainer.addEventListener("mousedown", (e) => {
    e.preventDefault();
    state.isJoystickDragging = true;
    handleJoystickMove(ctx, e.clientX, e.clientY);
  });

  document.addEventListener("mousemove", (e) => {
    if (state.isJoystickDragging) {
      handleJoystickMove(ctx, e.clientX, e.clientY);
    }
  });

  document.addEventListener("mouseup", () => {
    state.isJoystickDragging = false;
  });

  // Touch events
  els.joystickContainer.addEventListener("touchstart", (e) => {
    e.preventDefault();
    state.isJoystickDragging = true;
    const touch = e.touches[0];
    if (touch) handleJoystickMove(ctx, touch.clientX, touch.clientY);
  });

  document.addEventListener("touchmove", (e) => {
    if (state.isJoystickDragging) {
      e.preventDefault();
      const touch = e.touches[0];
      if (touch) handleJoystickMove(ctx, touch.clientX, touch.clientY);
    }
  });

  document.addEventListener("touchend", () => {
    state.isJoystickDragging = false;
  });
}

export function initCoordinateInputs(ctx: GeoreferenceContext): void {
  const { els, state } = ctx;

  els.latitudeInput.addEventListener("change", () => {
    const lat = parseFloat(els.latitudeInput.value);
    const lng = parseFloat(els.longitudeInput.value);
    if (!isNaN(lat) && !isNaN(lng) && lat >= -90 && lat <= 90) {
      updatePinLocation(ctx, lng, lat, state.currentDirection);
      state.pinPlaced = true;
      els.submitButton.disabled = false;
    }
  });

  els.longitudeInput.addEventListener("change", () => {
    const lng = parseFloat(els.longitudeInput.value);
    const lat = parseFloat(els.latitudeInput.value);
    if (!isNaN(lng) && !isNaN(lat) && lng >= -180 && lng <= 180) {
      updatePinLocation(ctx, lng, lat, state.currentDirection);
      state.pinPlaced = true;
      els.submitButton.disabled = false;
    }
  });

  els.directionInput.addEventListener("change", () => {
    if (!state.pinPlaced) return;

    const directionText = els.directionInput.value.replace("°", "");
    let direction = parseFloat(directionText);

    if (!isNaN(direction)) {
      direction = direction % 360;
      if (direction < 0) direction += 360;

      updateDirection(ctx, direction);
      setJoystickFromDirection(ctx, direction);
    }
  });

  document.getElementById("reset-direction")?.addEventListener("click", () => {
    if (!state.pinPlaced) return;
    updateDirection(ctx, null);
  });
}

// The checkbox is the source of truth; the browser restores its state on
// reload. Layer visibility is synced in restoreOverlayState() once the map's
// layers exist.
export function initBearingLineToggle(ctx: GeoreferenceContext): void {
  const { map, state } = ctx;
  const bearingLineToggle = document.getElementById(
    "bearing-line-toggle",
  ) as HTMLInputElement | null;
  if (!bearingLineToggle) return;

  state.bearingLineEnabled = bearingLineToggle.checked;

  bearingLineToggle.addEventListener("change", () => {
    state.bearingLineEnabled = bearingLineToggle.checked;
    const vis = state.bearingLineEnabled ? "visible" : "none";
    for (const layerId of ["bearing-line", "bearing-line-bg"]) {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", vis);
      }
    }
    updateBearingLine(ctx);
  });
}
