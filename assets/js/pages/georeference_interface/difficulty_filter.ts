// Difficulty filter toggles shown above the interface when browsing for the
// next image to georeference (hidden when a specific image was requested).
import type { GeoreferenceConfig } from "./types";

const DIFFICULTY_COLORS: Record<string, string> = {
  easy: "success",
  medium: "warning",
  hard: "danger",
  unlabeled: "secondary",
};

function getDifficultyColor(difficulty: string | undefined): string {
  return (difficulty && DIFFICULTY_COLORS[difficulty]) || "secondary";
}

// An active toggle renders as a solid button, an inactive one as an outline.
function isToggleActive(button: Element): boolean {
  return ["btn-success", "btn-warning", "btn-danger", "btn-secondary"].some(
    (cls) => button.classList.contains(cls),
  );
}

function updateDifficultyButtonState(
  button: HTMLButtonElement,
  isActive: boolean,
): void {
  const color = getDifficultyColor(button.dataset.difficulty);
  button.className = isActive
    ? `btn btn-sm btn-${color} difficulty-toggle`
    : `btn btn-sm btn-outline-${color} difficulty-toggle`;
}

// Rebuild the single plus-separated difficulty URL parameter from the active
// toggles and reload.
function updateDifficultyFilter(): void {
  const urlParams = new URLSearchParams(window.location.search);
  const difficultyToggles = document.querySelectorAll<HTMLButtonElement>(
    ".difficulty-toggle",
  );

  urlParams.delete("difficulty");

  const activeDifficulties: string[] = [];
  difficultyToggles.forEach((button) => {
    const difficulty = button.dataset.difficulty;
    if (difficulty && isToggleActive(button)) {
      activeDifficulties.push(difficulty);
    }
  });

  if (activeDifficulties.length > 0) {
    urlParams.set("difficulty", activeDifficulties.join("+"));
  }

  window.location.href = window.location.pathname + "?" + urlParams.toString();
}

export function initializeDifficultyToggles(config: GeoreferenceConfig): void {
  const difficultyToggles = document.querySelectorAll<HTMLButtonElement>(
    ".difficulty-toggle",
  );
  const currentFilters = config.difficultyFilters || [];

  difficultyToggles.forEach((button) => {
    const difficulty = button.dataset.difficulty;
    updateDifficultyButtonState(
      button,
      currentFilters.some((filter) => filter === difficulty),
    );

    button.addEventListener("click", () => {
      updateDifficultyButtonState(button, !isToggleActive(button));
      updateDifficultyFilter();
    });
  });
}
