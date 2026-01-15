/**
 * Activity Feed page JavaScript
 *
 * Handles expandable georeference groups using Alpine.js.
 * The expand/collapse functionality is handled inline with x-data and x-show
 * in the templates, so this file is minimal for now.
 */

// Add x-cloak style to prevent flash of unstyled content
document.addEventListener("DOMContentLoaded", function () {
  // Ensure x-cloak elements are hidden until Alpine initializes
  const style = document.createElement("style");
  style.textContent = "[x-cloak] { display: none !important; }";
  document.head.appendChild(style);
});
