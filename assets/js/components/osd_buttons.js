const zoomButtons = [
  { icon: "fa-plus", title: "Zoom in", action: (v) => v.viewport.zoomBy(1.5) },
  {
    icon: "fa-minus",
    title: "Zoom out",
    action: (v) => v.viewport.zoomBy(0.667),
  },
  { icon: "fa-home", title: "Reset view", action: (v) => v.viewport.goHome() },
  {
    icon: "fa-expand",
    title: "Full screen",
    action: (v) => v.setFullScreen(!v.isFullPage()),
  },
];

function makeButton({ icon, title, onClick }) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "osd-btn";
  btn.title = title;
  btn.innerHTML = `<i class="fas ${icon}"></i>`;
  btn.addEventListener("click", onClick);
  return btn;
}

function setViewerInteractive(viewer, enabled) {
  viewer.setMouseNavEnabled(enabled);
  // OSD sets touch-action: none on both canvas and container; restore it when locked
  // so swipe/scroll gestures fall through to the page.
  const touchAction = enabled ? "none" : "auto";
  if (viewer.canvas) viewer.canvas.style.touchAction = touchAction;
  if (viewer.container) viewer.container.style.touchAction = touchAction;
}

export function addViewerButtons(viewer, container) {
  container.style.position = "relative";

  // Start locked
  setViewerInteractive(viewer, false);

  // --- Locked state: single unlock button ---
  const lockedGroup = document.createElement("div");
  lockedGroup.className = "osd-btn-group";
  lockedGroup.appendChild(
    makeButton({
      icon: "fa-search-plus",
      title: "Enable zoom",
      onClick: () => {
        setViewerInteractive(viewer, true);
        lockedGroup.style.display = "none";
        unlockedGroup.style.display = "flex";
      },
    }),
  );
  container.appendChild(lockedGroup);

  // --- Unlocked state: zoom controls + lock button ---
  const unlockedGroup = document.createElement("div");
  unlockedGroup.className = "osd-btn-group";
  unlockedGroup.style.display = "none";

  for (const { icon, title, action } of zoomButtons) {
    unlockedGroup.appendChild(
      makeButton({ icon, title, onClick: () => action(viewer) }),
    );
  }

  unlockedGroup.appendChild(
    makeButton({
      icon: "fa-lock",
      title: "Lock view",
      onClick: () => {
        viewer.viewport.goHome();
        setViewerInteractive(viewer, false);
        unlockedGroup.style.display = "none";
        lockedGroup.style.display = "flex";
      },
    }),
  );

  container.appendChild(unlockedGroup);
}
