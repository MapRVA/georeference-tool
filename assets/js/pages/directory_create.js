document.addEventListener("alpine:init", () => {
  Alpine.data("directoryCreate", () => ({
    title: "",
    slug: "",
    manualSlug: false,

    generateSlug() {
      if (this.manualSlug) return;
      this.slug = this.title
        .toLowerCase()
        .replace(/[^a-z0-9\s-]/g, "")
        .replace(/\s+/g, "-")
        .replace(/-+/g, "-")
        .replace(/^-|-$/g, "");
    },
  }));
});
