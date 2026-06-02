// Homepage entry point.
//
// Initializes the IIIF deep-zoom viewer used by the Featured Image card. The
// viewer styles are shared with the image detail page. initImageViewer() is a
// no-op when neither the IIIF viewer nor a plain <img> is present, so this is
// safe to run even when no image is featured.
import "../../styles/components/image-viewer.css";

import { initImageViewer } from "../components/image_viewer.js";

document.addEventListener("DOMContentLoaded", function () {
  initImageViewer();
});
