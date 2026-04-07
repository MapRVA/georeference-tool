import OpenSeadragon from "openseadragon";
import { addViewerButtons } from "../components/osd_buttons";

function initViewer() {
  const cfg = window.pageOcrConfig;
  const el = document.getElementById("osd-viewer");
  if (!el) return;

  const options = {
    element: el,
    showNavigationControl: false,
    visibilityRatio: 1,
    minZoomLevel: 0.5,
    defaultZoomLevel: 0,
    gestureSettingsMouse: { scrollToZoom: true },
  };

  if (cfg.iiifInfoUrl) {
    options.tileSources = [cfg.iiifInfoUrl];
  } else if (cfg.imageUrl) {
    options.tileSources = [{ type: "image", url: cfg.imageUrl }];
  }

  const viewer = OpenSeadragon(options);
  addViewerButtons(viewer, el);
}

document.addEventListener("DOMContentLoaded", initViewer);

document.addEventListener("alpine:init", () => {
  Alpine.data("pageOcr", () => ({
    status: "",
    ocrError: "",
    ocrRunning: false,
    pollTimer: null,

    entries: [],
    hasSavedEntries: false,
    entriesLocked: false,

    // Pipeline artifacts for the debug tabs
    hydratedPrompt: "",
    llmResponse: "",
    enrichedEntries: "",
    parseError: "",

    saving: false,

    init() {
      const cfg = window.pageOcrConfig;
      this.entriesLocked = cfg.entriesLocked || false;
      if (cfg.initialStatus === "pending" || cfg.initialStatus === "processing") {
        this.ocrRunning = true;
        this.status = cfg.initialStatus;
        this.startPolling();
      } else if (cfg.initialStatus === "complete" || cfg.initialStatus === "failed") {
        this.poll();
      }
    },

    destroy() {
      this.stopPolling();
    },

    startPolling() {
      this.stopPolling();
      this.poll();
      this.pollTimer = setInterval(() => this.poll(), 2000);
    },

    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },

    async poll() {
      const cfg = window.pageOcrConfig;
      try {
        const res = await fetch(cfg.statusUrl);
        if (!res.ok) return;
        const data = await res.json();

        this.status = data.ocr_status;
        this.ocrError = data.ocr_error || "";
        this.hasSavedEntries = data.has_saved_entries || false;

        if (data.ocr_raw) {
          // ocr_raw may be a parsed object (from the view) or a JSON string (legacy)
          let raw = data.ocr_raw;
          if (typeof raw === "string") {
            try { raw = JSON.parse(raw); } catch { raw = null; }
          }
          if (raw) {
            if (Array.isArray(raw)) {
              // Legacy format: ocr_raw is a plain array of entries
              this.enrichedEntries = JSON.stringify(raw, null, 2);
              if (this.entries.length === 0 && raw.length > 0) {
                this.entries = raw.map((e) => this.normalizeEntry(e));
              }
            } else {
              // Structured format with pipeline artifacts
              this.hydratedPrompt = raw.prompt || "";
              this.llmResponse = raw.llm_response || "";
              this.parseError = raw.parse_error || "";
              this.enrichedEntries = JSON.stringify(raw.entries || [], null, 2);
              if (this.entries.length === 0 && raw.entries && raw.entries.length > 0) {
                this.entries = raw.entries.map((e) => this.normalizeEntry(e));
              }
            }
          }
        }

        if (data.ocr_status === "complete" || data.ocr_status === "failed") {
          this.stopPolling();
          this.ocrRunning = false;
        }
      } catch {}
    },

    async runOcr() {
      const cfg = window.pageOcrConfig;
      const prompt = this.$refs.prompt.value.trim();
      const model = this.$refs.model?.value;

      if (!prompt) return;
      if (!model) return;

      this.ocrRunning = true;
      this.status = "pending";
      this.entries = [];
      this.hydratedPrompt = "";
      this.llmResponse = "";
      this.enrichedEntries = "";
      this.parseError = "";
      this.saveSuccess = false;
      this.saveError = "";
      this.ocrError = "";

      try {
        const res = await fetch(cfg.runUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": cfg.csrfToken,
          },
          body: JSON.stringify({ prompt, model }),
        });

        if (res.ok) {
          this.startPolling();
        } else {
          const data = await res.json().catch(() => ({}));
          this.ocrError = data.error || "Failed to submit OCR task.";
          this.ocrRunning = false;
          this.status = "failed";
        }
      } catch (err) {
        this.ocrError = "Network error: " + err.message;
        this.ocrRunning = false;
        this.status = "failed";
      }
    },

    normalizeEntry(raw) {
      return {
        original_text: raw.original_text || "",
        first_name: raw.first_name || "",
        middle_name: raw.middle_name || "",
        last_name: raw.last_name || "",
        "addr:housenumber": raw["addr:housenumber"] || "",
        "addr:street": raw["addr:street"] || "",
        "addr:city": raw["addr:city"] || "",
        "addr:postcode": raw["addr:postcode"] || "",
        "addr:district": raw["addr:district"] || "",
        "addr:state": raw["addr:state"] || "",
        "addr:place": raw["addr:place"] || "",
        "addr:neighbourhood": raw["addr:neighbourhood"] || "",
        "addr:suburb": raw["addr:suburb"] || "",
        "addr:hamlet": raw["addr:hamlet"] || "",
        "addr:province": raw["addr:province"] || "",
        "addr:floor": raw["addr:floor"] || "",
        occupation: raw.occupation || "",
        business: raw.business || "",
        x: raw.x ?? null,
        y: raw.y ?? null,
        w: raw.w ?? null,
        h: raw.h ?? null,
      };
    },

    addEntry() {
      this.entries.push(this.normalizeEntry({}));
    },

    removeEntry(index) {
      this.entries.splice(index, 1);
    },

    async saveEntries() {
      const cfg = window.pageOcrConfig;
      this.saving = true;

      try {
        const res = await fetch(cfg.saveEntriesUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": cfg.csrfToken,
          },
          body: JSON.stringify({ entries: this.entries }),
        });

        if (res.ok) {
          const data = await res.json();
          this.hasSavedEntries = true;
          this.entriesLocked = true;
          showSuccess(`${data.entry_count} entries saved.`);
        } else {
          const data = await res.json().catch(() => ({}));
          showError(data.error || "Save failed.");
        }
      } catch (err) {
        showError("Network error: " + err.message);
      } finally {
        this.saving = false;
      }
    },

    get formattedLlmResponse() {
      if (!this.llmResponse) return "";
      // Try to pretty-print if it's JSON, otherwise show as-is
      try {
        return JSON.stringify(JSON.parse(this.llmResponse), null, 2);
      } catch {
        return this.llmResponse;
      }
    },
  }));
});
