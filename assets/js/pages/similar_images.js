// Import image grid component (includes bulk selection and modal functionality)
import { imageGrid } from "../components/image_grid.js";

// Register the image grid component with Alpine and start Alpine.
// This runs synchronously before DOMContentLoaded, ensuring the component
// is registered before Alpine processes the DOM.
window.Alpine.data("imageGrid", imageGrid);
window.Alpine.start();
window.AlpineStarted = true;
