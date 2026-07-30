import { SLUG_PLACEHOLDER, SUBJECT_MAP_EVENTS } from "./types";
import type { SubjectHit, SubjectMapInfo } from "./types";

// Sweeping the pointer across a dense cluster shouldn't fire a request per
// geometry; a pin fetches straight away.
const HOVER_FETCH_DEBOUNCE_MS = 150;

// One subject's details never change within a page view, so a slug is only
// ever fetched once.
const infoCache = new Map<string, SubjectMapInfo>();

let fetchTimeout: number | undefined;
let inFlight: AbortController | null = null;

type SubjectPanel = {
  $el: HTMLElement;
  open: boolean;
  pinned: boolean;
  loading: boolean;
  slug: string | null;
  title: string;
  detail: SubjectMapInfo | null;
  infoUrlTemplate: string;
  subjectUrlTemplate: string;
  readonly subjectUrl: string;
  readonly countsLabel: string;
  init(): void;
  preview(hit: SubjectHit): void;
  pin(hit: SubjectHit): void;
  dismiss(): void;
  close(): void;
  show(hit: SubjectHit, pinned: boolean): void;
  loadDetail(slug: string, immediate: boolean): void;
};

// Registers the Alpine component backing the map's info card. Runs at module
// scope so it lands before Alpine.start() in assets/index.js.
export function registerSubjectPanel(): void {
  window.Alpine.data(
    "subjectsMapPanel",
    (): SubjectPanel => ({
      $el: document.body,
      open: false,
      pinned: false,
      loading: false,
      slug: null,
      title: "",
      detail: null,
      infoUrlTemplate: "",
      subjectUrlTemplate: "",

      init() {
        this.infoUrlTemplate = this.$el.dataset.infoUrl ?? "";
        this.subjectUrlTemplate = this.$el.dataset.subjectUrl ?? "";
      },

      // Available from the first frame, before the fetch resolves, so the
      // "View subject" link is never a dead end.
      get subjectUrl(): string {
        if (!this.slug) return "#";
        return this.subjectUrlTemplate.replace(
          SLUG_PLACEHOLDER,
          encodeURIComponent(this.slug),
        );
      },

      get countsLabel(): string {
        if (!this.detail) return "";
        const { total_images: total, georeferenced_images: located } =
          this.detail;
        const images = `${total} image${total === 1 ? "" : "s"}`;
        return located > 0 ? `${images} · ${located} georeferenced` : images;
      },

      preview(hit: SubjectHit) {
        if (this.pinned) return;
        this.show(hit, false);
      },

      pin(hit: SubjectHit) {
        this.show(hit, true);
      },

      // The map reports nothing under the pointer. It only sends this when
      // dropping the panel is right — a hover leaving a subject, or a click
      // on bare map that already released the pin — so it needn't check
      // `pinned` itself.
      dismiss() {
        this.open = false;
        this.pinned = false;
        this.slug = null;
      },

      // Dismissed from the panel's own UI, so the map has to be told to drop
      // its pin and highlight.
      close() {
        if (!this.open) return;
        this.dismiss();
        window.dispatchEvent(new CustomEvent(SUBJECT_MAP_EVENTS.closed));
      },

      show(hit: SubjectHit, pinned: boolean) {
        const changed = hit.slug !== this.slug;
        this.slug = hit.slug;
        this.title = hit.title;
        this.pinned = pinned;
        this.open = true;
        if (changed || !this.detail) this.loadDetail(hit.slug, pinned);
      },

      // The tile gives us a title immediately; everything else arrives here.
      loadDetail(slug: string, immediate: boolean) {
        window.clearTimeout(fetchTimeout);
        inFlight?.abort();

        const cached = infoCache.get(slug);
        if (cached) {
          this.detail = cached;
          this.loading = false;
          return;
        }

        this.detail = null;
        this.loading = true;

        const request = () => {
          const controller = new AbortController();
          inFlight = controller;

          fetch(
            this.infoUrlTemplate.replace(
              SLUG_PLACEHOLDER,
              encodeURIComponent(slug),
            ),
            { signal: controller.signal },
          )
            .then((response) => {
              if (!response.ok) throw new Error(`HTTP ${response.status}`);
              return response.json() as Promise<SubjectMapInfo>;
            })
            .then((info) => {
              infoCache.set(slug, info);
              // The pointer may have moved on while this was in flight.
              if (this.slug !== slug) return;
              this.detail = info;
              this.loading = false;
            })
            .catch((error: unknown) => {
              if (error instanceof Error && error.name === "AbortError") return;
              console.warn("Could not load subject details:", error);
              // Leave the panel showing the title alone rather than an error.
              if (this.slug === slug) this.loading = false;
            });
        };

        if (immediate) request();
        else fetchTimeout = window.setTimeout(request, HOVER_FETCH_DEBOUNCE_MS);
      },
    }),
  );
}
