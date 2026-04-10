import OpenSeadragon from "openseadragon";
import { addViewerButtons } from "../components/osd_buttons";

const el = document.getElementById("osd-viewer");
const manifestUrl = el.dataset.manifest;
const entriesData = JSON.parse(el.dataset.entries || "{}");
const pageUuids = JSON.parse(el.dataset.pageUuids || "[]");

let viewer = null;
let pages = [];
let currentPage = 0;
let overlays = [];  // overlay DOM elements for the current page

async function initViewer() {
  const res = await fetch(manifestUrl);
  const manifest = await res.json();

  pages = (manifest.items || []).map((canvas) => {
    const anno = canvas.items?.[0]?.items?.[0];
    const body = anno?.body;
    const service = body?.service?.[0];
    if (service) {
      return service.id + "/info.json";
    }
    return { type: "image", url: body?.id };
  });

  if (pages.length === 0) return;

  const params = new URLSearchParams(window.location.search);
  const startPage = Math.max(0, Math.min(parseInt(params.get("page") || "1", 10) - 1, pages.length - 1));
  currentPage = startPage;

  viewer = OpenSeadragon({
    element: el,
    showNavigationControl: false,
    visibilityRatio: 1,
    minZoomLevel: 0.5,
    defaultZoomLevel: 0,
    gestureSettingsMouse: { scrollToZoom: true },
    tileSources: [pages[currentPage]],
    drawer: "canvas",
  });

  addViewerButtons(viewer, el);

  // Render overlays once the tile source is loaded and coordinates are valid
  viewer.addHandler("open", renderOverlays);

  updatePageControls();
  showEntries(currentPage + 1);
}

function goToPage(index) {
  if (index < 0 || index >= pages.length || !viewer) return;
  currentPage = index;
  selectedIndex = -1;
  viewer.open(pages[currentPage]);
  updatePageControls();
  showEntries(currentPage + 1);
}

// Create OSD overlays for entries with bounding boxes on the current page.
// Must be called after the viewer's 'open' event fires so coordinate
// conversion works correctly.
function renderOverlays() {
  clearOverlays();
  const entries = entriesData[currentPage + 1];
  if (!entries) return;

  entries.forEach((entry, i) => {
    if (entry.x == null) return;
    const rect = viewer.viewport.imageToViewportRectangle(
      entry.x, entry.y, entry.w, entry.h,
    );
    const el = document.createElement("div");
    el.className = "annotation-overlay";
    el.dataset.entryIndex = i;
    viewer.addOverlay({ element: el, location: rect });
    overlays.push(el);
  });
}

function clearOverlays() {
  overlays.forEach((el) => viewer.removeOverlay(el));
  overlays = [];
}

let selectedIndex = -1;

function highlightEntry(index) {
  const deselecting = index === selectedIndex;

  // Deselect all overlays and list items
  overlays.forEach((el) => el.classList.remove("active"));
  document.querySelectorAll("#entries-container .list-group-item")
    .forEach((li) => li.classList.remove("entry-selected"));
  selectedIndex = -1;

  if (deselecting) return;

  // Activate the selected overlay (transparent → visible border)
  const overlay = overlays.find(
    (el) => parseInt(el.dataset.entryIndex) === index,
  );
  if (overlay) {
    overlay.classList.add("active");
  }

  const item = document.querySelector(`#entries-container .list-group-item[data-entry-index="${index}"]`);
  if (item) {
    item.classList.add("entry-selected");
  }

  selectedIndex = index;

  // Zoom to the entry's bounding box with 20% padding
  const entry = entriesData[currentPage + 1]?.[index];
  if (entry?.x != null) {
    const rect = viewer.viewport.imageToViewportRectangle(
      entry.x, entry.y, entry.w, entry.h,
    );
    viewer.viewport.fitBounds(
      new OpenSeadragon.Rect(
        rect.x - rect.width * 0.1,
        rect.y - rect.height * 0.1,
        rect.width * 1.2,
        rect.height * 1.2,
      ),
    );
  }
}

function updatePageControls() {
  const label = document.getElementById("page-label");
  const prevBtn = document.getElementById("page-prev");
  const nextBtn = document.getElementById("page-next");
  if (!label) return;

  label.textContent = `Page ${currentPage + 1} of ${pages.length}`;
  prevBtn.disabled = currentPage === 0;
  nextBtn.disabled = currentPage === pages.length - 1;

  const url = new URL(window.location);
  if (currentPage === 0) {
    url.searchParams.delete("page");
  } else {
    url.searchParams.set("page", currentPage + 1);
  }
  history.replaceState(null, "", url);

  const ocrLink = document.getElementById("page-ocr-link");
  if (ocrLink && pageUuids[currentPage]) {
    ocrLink.href = `/directories/pages/${pageUuids[currentPage]}/ocr/`;
    const hasEntries = entriesData[currentPage + 1]?.length > 0;
    ocrLink.classList.toggle("d-none", hasEntries);
  }

  if (pages.length <= 1) {
    document.getElementById("page-controls")?.classList.add("d-none");
  }
}

document.getElementById("page-prev")?.addEventListener("click", () => {
  goToPage(currentPage - 1);
});

document.getElementById("page-next")?.addEventListener("click", () => {
  goToPage(currentPage + 1);
});

function esc(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function formatPerson(p) {
  const name = [p.first_name, p.middle_name, p.last_name]
    .filter(Boolean)
    .join(" ");
  return name || "Unknown";
}

function renderEntry(e, index) {
  const parts = [];

  if (e.person) {
    parts.push(`<strong>${esc(formatPerson(e.person))}</strong>`);
  }
  if (e.occupation) {
    parts.push(esc(e.occupation));
  }
  if (e.business) {
    parts.push(esc(e.business));
  }
  if (e.address) {
    if (e.address_uuid) {
      parts.push(`<a href="/address/${esc(e.address_uuid)}/">${esc(e.address)}</a>`);
    } else {
      parts.push(esc(e.address));
    }
  }

  const summary = parts.length > 0
    ? parts.join('<span class="mx-2 text-muted">|</span>')
    : `<span class="text-muted">Entry #${e.id}</span>`;

  const original = e.original_text
    ? `<div class="font-monospace small text-muted">${esc(e.original_text)}</div>`
    : "";

  const entryIcon = e.approved
    ? `<i class="fas fa-check-circle text-success"></i>`
    : `<i class="fas fa-pen"></i>`;
  const entryTitle = e.approved ? "Approved" : "Edit this entry";
  const validateLink = e.uuid
    ? `<a href="/directories/entry/${e.uuid}/" class="ms-2 text-muted validate-link" title="${entryTitle}" onclick="event.stopPropagation();">${entryIcon}</a>`
    : "";

  const clickable = e.x != null ? ` style="cursor: pointer;" data-entry-index="${index}"` : "";

  return `<li class="list-group-item d-flex align-items-start${e.x != null ? " entry-has-bbox" : ""}"${clickable}><div class="flex-fill">${summary}${original}</div>${validateLink}</li>`;
}

function showEntries(pageNumber) {
  const container = document.getElementById("entries-container");
  const entries = entriesData[pageNumber];

  if (!entries || entries.length === 0) {
    container.innerHTML = "";
    return;
  }

  // Sort by reading order: detect columns from x midpoints, then
  // list each column top-to-bottom before moving to the next.
  const indexed = entries.map((e, i) => ({ entry: e, origIndex: i }));

  // Assign column index by clustering x midpoints: sort by midpoint,
  // find gaps larger than the median entry width, and split there.
  const withMid = indexed
    .filter((s) => s.entry.x != null)
    .map((s) => ({ ...s, mid: s.entry.x + (s.entry.w || 0) / 2 }));
  withMid.sort((a, b) => a.mid - b.mid);

  const widths = withMid.map((s) => s.entry.w || 1);
  const medianW = widths.slice().sort((a, b) => a - b)[Math.floor(widths.length / 2)] || 1;

  // Walk sorted midpoints; start a new column when the gap exceeds half the median width
  const colMap = new Map();
  let col = 0;
  for (let i = 0; i < withMid.length; i++) {
    if (i > 0 && withMid[i].mid - withMid[i - 1].mid > medianW * 0.5) {
      col++;
    }
    colMap.set(withMid[i].origIndex, col);
  }

  const sorted = indexed.sort((a, b) => {
    const aCol = colMap.get(a.origIndex) ?? 0;
    const bCol = colMap.get(b.origIndex) ?? 0;
    return aCol - bCol || (a.entry.y ?? 0) - (b.entry.y ?? 0);
  });

  container.innerHTML = `
    <h5>Entries on this page</h5>
    <ul class="list-group">${sorted.map((s) => renderEntry(s.entry, s.origIndex)).join("")}</ul>
  `;

  // Wire up click-to-highlight and hover outline for entries with bounding boxes
  container.querySelectorAll("[data-entry-index]").forEach((li) => {
    const idx = parseInt(li.dataset.entryIndex);
    li.addEventListener("click", () => {
      highlightEntry(idx);
    });
    li.addEventListener("mouseenter", () => {
      const overlay = overlays.find((el) => parseInt(el.dataset.entryIndex) === idx);
      if (overlay && !overlay.classList.contains("active")) {
        overlay.classList.add("hover");
      }
    });
    li.addEventListener("mouseleave", () => {
      const overlay = overlays.find((el) => parseInt(el.dataset.entryIndex) === idx);
      if (overlay) {
        overlay.classList.remove("hover");
      }
    });
  });
}

initViewer();
