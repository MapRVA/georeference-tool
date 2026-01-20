// Import dependencies
import PhotoSwipe from "photoswipe";
import PhotoSwipeLightbox from "photoswipe/lightbox";

// Import vendor CSS
import "photoswipe/style.css";

// PhotoSwipe setup
function setupPhotoSwipeData(img) {
  const link = img.parentElement;
  link.setAttribute("data-pswp-width", img.naturalWidth);
  link.setAttribute("data-pswp-height", img.naturalHeight);
}

export function initImageViewer() {
  const lightbox = new PhotoSwipeLightbox({
    gallery: "#pswp-gallery",
    children: "a",
    showHideAnimationType: "fade",
    zoomAnimationDuration: 300,
    maxZoomLevel: 8,
    wheelToZoom: true,
    pswpModule: PhotoSwipe,
  });
  lightbox.init();

  // Image loading handlers
  const mainImage = document.getElementById("main-image");
  const imageFallback = document.getElementById("image-fallback");

  if (mainImage && imageFallback) {
    mainImage.onload = function () {
      imageFallback.style.setProperty("display", "none", "important");
      mainImage.style.display = "block";
      mainImage.style.visibility = "visible";
      setupPhotoSwipeData(this);
    };

    mainImage.onerror = function () {
      mainImage.style.display = "none";
      imageFallback.style.setProperty("display", "flex", "important");
    };

    // Handle already loaded images
    if (mainImage.complete) {
      if (mainImage.naturalHeight !== 0 && mainImage.naturalWidth !== 0) {
        imageFallback.style.setProperty("display", "none", "important");
        mainImage.style.display = "block";
        mainImage.style.visibility = "visible";
        setupPhotoSwipeData(mainImage);
      } else {
        mainImage.style.display = "none";
        imageFallback.style.setProperty("display", "flex", "important");
      }
    }
  }
}
