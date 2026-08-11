// Staff-only controls for marking the current image's difficulty, plus the
// card badge and button-group restyling that follows a successful change.
import { getCsrfToken } from "./csrf";
import type { Difficulty, GeoreferenceContext } from "./types";

const DIFFICULTIES: readonly Difficulty[] = ["easy", "medium", "hard"];

const BOOTSTRAP_COLORS: Record<string, string> = {
  easy: "success",
  medium: "warning",
  hard: "danger",
};

function getBootstrapColor(difficulty: string): string {
  return BOOTSTRAP_COLORS[difficulty] ?? "secondary";
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function initDifficultyMarking(ctx: GeoreferenceContext): void {
  if (!ctx.config.isStaff) return;

  // Buttons already wired up, so re-styling the group never stacks listeners.
  const attached = new WeakSet<HTMLButtonElement>();

  function attach(button: HTMLButtonElement): void {
    if (attached.has(button)) return;
    button.addEventListener("click", handleDifficultyClick);
    attached.add(button);
  }

  function handleDifficultyClick(this: HTMLButtonElement): void {
    const clickedButton = this;
    const difficulty = clickedButton.dataset.difficulty;
    if (!difficulty) return;
    const csrfToken = getCsrfToken(ctx.config);

    clickedButton.disabled = true;
    const originalText = clickedButton.innerHTML;
    clickedButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

    const formData = new FormData();
    formData.append("difficulty", difficulty);
    formData.append("csrfmiddlewaretoken", csrfToken);

    fetch(ctx.urls.markDifficulty, {
      method: "POST",
      body: formData,
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Network response was not ok");
        }
        window.showAlert("success", `Image marked as ${difficulty}`);
        clickedButton.innerHTML = capitalize(difficulty);
        clickedButton.disabled = false;

        // Force reflow, then update the rest of the UI
        void clickedButton.offsetHeight;
        setTimeout(() => {
          updateDifficultyButtons(difficulty);
          updateDifficultyBadge(difficulty);
        }, 10);
      })
      .catch((error) => {
        console.error("Error:", error);
        window.showAlert(
          "danger",
          "Error marking difficulty. Please try again.",
        );
        clickedButton.disabled = false;
        clickedButton.innerHTML = originalText;
      });
  }

  function updateDifficultyButtons(newDifficulty: string): void {
    // Find the difficulty button group
    let buttonGroup: Element | null = null;
    for (const group of document.querySelectorAll(".btn-group")) {
      for (const btn of group.querySelectorAll("button")) {
        const text = (btn.textContent ?? "").toLowerCase().trim();
        if (
          btn.hasAttribute("data-difficulty") ||
          btn.classList.contains("mark-difficulty") ||
          DIFFICULTIES.some((d) => text.includes(d))
        ) {
          buttonGroup = group;
        }
      }
    }

    if (!buttonGroup) return;

    buttonGroup.querySelectorAll("button").forEach((button) => {
      const buttonText = (button.textContent ?? "").toLowerCase().trim();
      const buttonDifficulty = DIFFICULTIES.find((d) => buttonText.includes(d));
      if (!buttonDifficulty) return;

      if (buttonDifficulty === newDifficulty) {
        // Selected difficulty: highlight and disable
        button.className = `btn btn-sm btn-${getBootstrapColor(newDifficulty)}`;
        button.disabled = true;
        button.removeAttribute("data-difficulty");
      } else {
        // Other difficulties: make clickable
        button.className = `btn btn-sm btn-outline-${getBootstrapColor(buttonDifficulty)} mark-difficulty`;
        button.disabled = false;
        button.setAttribute("data-difficulty", buttonDifficulty);
        attach(button);
      }
      button.innerHTML = capitalize(buttonDifficulty);
    });
  }

  function updateDifficultyBadge(newDifficulty: string): void {
    const cardHeader = document.querySelector(".card-header");
    if (!cardHeader) return;

    const difficultyBadge = cardHeader.querySelector(".badge");

    if (difficultyBadge && difficultyBadge.innerHTML.includes("fa-signal")) {
      // Update existing badge
      difficultyBadge.className = `badge status-badge text-bg-${getBootstrapColor(newDifficulty)}`;
      difficultyBadge.innerHTML = `<i class="fas fa-signal me-1"></i>${capitalize(newDifficulty)}`;
    } else if (!difficultyBadge) {
      // Create new badge as a sibling of the h5, not inside it
      const newBadge = document.createElement("span");
      newBadge.className = `badge status-badge text-bg-${getBootstrapColor(newDifficulty)} ms-2`;
      newBadge.innerHTML = `<i class="fas fa-signal me-1"></i>${capitalize(newDifficulty)}`;
      cardHeader.appendChild(newBadge);
    }
  }

  document
    .querySelectorAll<HTMLButtonElement>(".mark-difficulty")
    .forEach(attach);
}
