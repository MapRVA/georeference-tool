// Colors from Bootstrap's CSS custom properties, read once at bundle load.
export const primaryColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-primary")
    .trim() || "#286071";

export const dangerColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-danger")
    .trim() || "#d52e1c";
