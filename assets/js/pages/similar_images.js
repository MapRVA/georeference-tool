// Import image grid component (includes bulk selection and modal functionality)
import { imageGrid } from "../components/image_grid.js";

// Register the image grid component with Alpine
// Use alpine:init event to ensure registration happens before Alpine.start()
document.addEventListener("alpine:init", () => {
  window.Alpine.data("imageGrid", imageGrid);
});
