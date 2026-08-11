import type { GeoreferenceConfig } from "./types";

// One CSRF lookup for every POST on the page: hidden form input first, then
// the meta tag, then the token serialized into the config object.
export function getCsrfToken(config: GeoreferenceConfig): string {
  return (
    document.querySelector<HTMLInputElement>(
      'input[name="csrfmiddlewaretoken"]',
    )?.value ||
    document
      .querySelector('meta[name="csrf-token"]')
      ?.getAttribute("content") ||
    config.csrfToken
  );
}

// Make sure the hidden CSRF input exists for code that reads it from the DOM.
export function ensureCsrfInput(config: GeoreferenceConfig): void {
  if (document.querySelector('input[name="csrfmiddlewaretoken"]')) return;
  const csrfInput = document.createElement("input");
  csrfInput.type = "hidden";
  csrfInput.name = "csrfmiddlewaretoken";
  csrfInput.value = config.csrfToken;
  document.body.appendChild(csrfInput);
}
