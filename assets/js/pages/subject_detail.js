// Import image grid component (includes bulk selection and modal functionality)
import { imageGrid } from "../components/image_grid.js";

// Register the image grid component with Alpine (Alpine.start() is called by index.js on DOMContentLoaded)
window.Alpine.data("imageGrid", imageGrid);
