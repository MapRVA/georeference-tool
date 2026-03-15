const buttons = [
  { icon: "fa-plus", title: "Zoom in", action: (v) => v.viewport.zoomBy(1.5) },
  { icon: "fa-minus", title: "Zoom out", action: (v) => v.viewport.zoomBy(0.667) },
  { icon: "fa-home", title: "Reset view", action: (v) => v.viewport.goHome() },
  { icon: "fa-expand", title: "Full screen", action: (v) => v.setFullScreen(!v.isFullPage()) },
];

export function addViewerButtons(viewer, container) {
  const group = document.createElement("div");
  Object.assign(group.style, {
    position: "absolute",
    top: "10px",
    right: "10px",
    zIndex: "10",
    borderRadius: "0.375rem",
    border: "1px solid rgba(0, 0, 0, 0.125)",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
  });

  for (const { icon, title, action } of buttons) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.title = title;
    btn.innerHTML = `<i class="fas ${icon}"></i>`;
    Object.assign(btn.style, {
      backgroundColor: "#fff",
      border: "none",
      borderBottom: "1px solid rgba(0, 0, 0, 0.125)",
      color: "#495057",
      fontSize: "0.875rem",
      width: "32px",
      height: "32px",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      cursor: "pointer",
      transition: "all 0.15s ease-in-out",
    });
    btn.addEventListener("mouseenter", () => {
      btn.style.backgroundColor = "#f8f9fa";
      btn.style.color = "#212529";
    });
    btn.addEventListener("mouseleave", () => {
      btn.style.backgroundColor = "#fff";
      btn.style.color = "#495057";
    });
    btn.addEventListener("mousedown", () => {
      btn.style.backgroundColor = "#e9ecef";
    });
    btn.addEventListener("mouseup", () => {
      btn.style.backgroundColor = "#f8f9fa";
    });
    btn.addEventListener("click", () => action(viewer));
    group.appendChild(btn);
  }

  // Remove border-bottom from last button
  group.lastElementChild.style.borderBottom = "none";

  container.style.position = "relative";
  container.appendChild(group);
}
