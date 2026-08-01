(() => {
    const root = document.documentElement;
    const stage = document.querySelector("[data-demo-stage]");

    function preferredTheme() {
        try {
            const parentScheme =
                window.parent.document.documentElement.dataset.mdColorScheme;
            if (parentScheme) {
                return parentScheme === "slate" ? "dark" : "light";
            }
        } catch {
            // The standalone specimen still follows the operating-system theme.
        }

        return window.matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light";
    }

    function syncTheme() {
        root.dataset.bsTheme = preferredTheme();
    }

    function resizeFrame() {
        if (!stage || !window.frameElement) {
            return;
        }

        const height = Math.ceil(stage.getBoundingClientRect().height + 2);
        window.frameElement.style.height = `${height}px`;
    }

    syncTheme();

    window.addEventListener("DOMContentLoaded", resizeFrame);
    window.addEventListener("load", resizeFrame);
    window.addEventListener("resize", resizeFrame);

    if (stage && "ResizeObserver" in window) {
        new ResizeObserver(resizeFrame).observe(stage);
    }

    if (document.fonts) {
        document.fonts.ready.then(resizeFrame);
    }

    try {
        const parentRoot = window.parent.document.documentElement;
        new MutationObserver(() => {
            syncTheme();
            resizeFrame();
        }).observe(parentRoot, {
            attributes: true,
            attributeFilter: ["data-md-color-scheme"],
        });
    } catch {
        window
            .matchMedia("(prefers-color-scheme: dark)")
            .addEventListener("change", syncTheme);
    }
})();
