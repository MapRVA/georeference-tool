// Import image grid component (includes bulk selection and modal functionality)
import { imageGrid } from "../components/image_grid.js";

// Register the image grid component with Alpine
if (window.Alpine) {
  window.Alpine.data("imageGrid", imageGrid);
}
