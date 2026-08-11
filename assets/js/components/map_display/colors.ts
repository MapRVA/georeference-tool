// Colors from Bootstrap's CSS custom properties, read once at bundle load.
export const primaryColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-primary")
    .trim() || "#286071";

export const dangerColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-danger")
    .trim() || "#d52e1c";

export const secondaryColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-secondary")
    .trim() || "#6c757d";

export const darkColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-dark")
    .trim() || "#212529";

export const lightColor =
  getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-light")
    .trim() || "#f8f9fa";
