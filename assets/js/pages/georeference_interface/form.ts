// Confidence-level form behavior: high confidence requires a direction, low
// confidence requires a note.
import type { GeoreferenceContext } from "./types";

export function updateConfidenceValidation(ctx: GeoreferenceContext): void {
  const { els, state } = ctx;
  if (!els.confidenceHighRadio) return;

  if (state.currentDirection === null) {
    // Disable high confidence when no direction is set
    els.confidenceHighRadio.disabled = true;
    // If high confidence was selected, switch to medium
    if (els.confidenceHighRadio.checked) {
      const mediumRadio = document.getElementById(
        "confidence-medium",
      ) as HTMLInputElement | null;
      if (mediumRadio) {
        mediumRadio.checked = true;
        // Trigger change event to update UI
        mediumRadio.dispatchEvent(new Event("change"));
      }
    }
  } else {
    els.confidenceHighRadio.disabled = false;
  }
}

export function initConfidenceRadios(ctx: GeoreferenceContext): void {
  const { els } = ctx;

  els.confidenceRadios.forEach((radio) => {
    radio.addEventListener("change", () => {
      // Notes are only required for low confidence
      const requireNotes = radio.value === "low";
      if (els.notesRequiredIndicator) {
        els.notesRequiredIndicator.style.display = requireNotes
          ? "inline"
          : "none";
      }
      if (els.notesHelpText) {
        els.notesHelpText.style.display = requireNotes ? "block" : "none";
      }
      els.confidenceNotes.required = requireNotes;

      updateConfidenceValidation(ctx);
    });
  });
}
