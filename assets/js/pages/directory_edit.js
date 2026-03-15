import Sortable from "sortablejs";

const OCR_STATUS_LABELS = {
  "": { text: "Not OCR'd", class: "text-bg-light text-dark", icon: "minus-circle" },
  pending: { text: "OCR queued", class: "text-bg-secondary", icon: "clock" },
  processing: {
    text: "OCR running…",
    class: "text-bg-info",
    icon: "spinner fa-spin",
  },
  complete: { text: "OCR done", class: "text-bg-success", icon: "check" },
  failed: {
    text: "OCR failed",
    class: "text-bg-danger",
    icon: "exclamation-triangle",
  },
};

const TILE_STATUS_LABELS = {
  "": { text: "Not queued", class: "text-bg-light text-dark", icon: "minus-circle" },
  pending: { text: "Tiles queued", class: "text-bg-secondary", icon: "clock" },
  processing: {
    text: "Generating tiles…",
    class: "text-bg-info",
    icon: "spinner fa-spin",
  },
  complete: { text: "Tiles ready", class: "text-bg-success", icon: "check" },
  failed: {
    text: "Tile generation failed",
    class: "text-bg-danger",
    icon: "exclamation-triangle",
  },
};

document.addEventListener("alpine:init", () => {
  Alpine.data("directoryEdit", () => ({
    pages: [],
    uploadQueue: [],
    isDragging: false,
    sortable: null,
    pollTimer: null,
    ocrBusy: false,
    ocrMessage: "",
    ocrSuccess: false,

    init() {
      const config = window.directoryEditConfig;
      this.pages = config.existingPages.map((p) => ({
        id: p.id,
        imageUrl: p.imageUrl,
        filename: p.filename,
        tileStatus: p.tileStatus || "pending",
        ocrStatus: p.ocrStatus || "",
        entryCount: p.entryCount || 0,
      }));

      this.$nextTick(() => {
        this.renderPages();
        this.initSortable();
        this.startPolling();
      });
    },

    destroy() {
      this.stopPolling();
    },

    startPolling() {
      this.stopPolling();
      this.pollTimer = setInterval(() => this.pollStatuses(), 5000);
    },

    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },

    async pollStatuses() {
      // Only poll if there are pages that aren't complete
      const needsPoll = this.pages.some(
        (p) =>
          p.tileStatus === "pending" ||
          p.tileStatus === "processing" ||
          p.ocrStatus === "pending" ||
          p.ocrStatus === "processing",
      );
      if (!needsPoll) {
        this.stopPolling();
        return;
      }

      const config = window.directoryEditConfig;
      try {
        const res = await fetch(config.statusUrl);
        if (!res.ok) return;
        const statuses = await res.json();

        this.pages.forEach((page) => {
          const status = statuses[page.id];
          if (!status) return;

          let changed = false;

          if (status.tile_status !== page.tileStatus) {
            page.tileStatus = status.tile_status;
            changed = true;

            if (status.tile_status === "failed") {
              showError(
                `Tile generation failed for ${page.filename}: ${status.tile_error}`,
              );
            }
          }

          if (status.ocr_status !== page.ocrStatus) {
            page.ocrStatus = status.ocr_status;
            changed = true;

            if (status.ocr_status === "failed") {
              showError(
                `OCR failed for ${page.filename}: ${status.ocr_error}`,
              );
            }
          }

          if (changed) {
            this.updatePageStatus(page);
          }
        });
      } catch {
        // Silently ignore polling errors
      }
    },

    updatePageStatus(page) {
      const grid = this.$refs.pageGrid;
      if (!grid) return;
      const col = grid.querySelector(`[data-id="${page.id}"]`);
      if (!col) return;

      const tileStatus = TILE_STATUS_LABELS[page.tileStatus] || TILE_STATUS_LABELS[""];
      const ocrStatus = OCR_STATUS_LABELS[page.ocrStatus] || OCR_STATUS_LABELS[""];
      const canQueue = page.tileStatus !== "pending" && page.tileStatus !== "processing";

      // Update tile badge
      const tileBadge = col.querySelector(".js-tile-badge");
      if (tileBadge) {
        tileBadge.className = `badge ${tileStatus.class} mt-1 js-tile-badge`;
        tileBadge.innerHTML = `<i class="fas fa-${tileStatus.icon} me-1"></i>${tileStatus.text}`;
      }

      // Update OCR badge
      const ocrBadge = col.querySelector(".js-ocr-badge");
      if (ocrBadge) {
        ocrBadge.className = `badge ${ocrStatus.class} mt-1 js-ocr-badge`;
        ocrBadge.innerHTML = `<i class="fas fa-${ocrStatus.icon} me-1"></i>${ocrStatus.text}`;
      }

      // Update queue button
      const footer = col.querySelector(".card-footer");
      if (!footer) return;
      const existingQueueBtn = footer.querySelector(".js-queue-btn");
      if (canQueue && !existingQueueBtn) {
        const btn = document.createElement("button");
        btn.className = "btn btn-outline-primary btn-sm js-queue-btn";
        btn.title = "Generate tiles";
        btn.innerHTML = `<i class="fas fa-redo"></i>`;
        btn.addEventListener("click", () => this.queueTiles(page.id));
        footer.insertBefore(btn, footer.firstChild);
      } else if (!canQueue && existingQueueBtn) {
        existingQueueBtn.remove();
      }
    },

    renderPages() {
      const grid = this.$refs.pageGrid;
      if (!grid) return;
      grid.innerHTML = "";

      this.pages.forEach((page, index) => {
        const tileStatus = TILE_STATUS_LABELS[page.tileStatus] || TILE_STATUS_LABELS[""];
        const ocrStatus = OCR_STATUS_LABELS[page.ocrStatus] || OCR_STATUS_LABELS[""];
        const canQueue =
          page.tileStatus !== "pending" && page.tileStatus !== "processing";
        const col = document.createElement("div");
        col.className = "col-6 col-md-4 col-lg-3 col-xl-2";
        col.dataset.id = page.id;
        const viewUrl = `${window.directoryEditConfig.viewUrl}?page=${index + 1}`;
        col.innerHTML = `
          <div class="card page-card h-100">
            <a href="${viewUrl}"><img src="${page.imageUrl}" class="page-thumb card-img-top" alt="Page ${index + 1}"></a>
            <div class="card-body p-2 text-center">
              <a href="${viewUrl}" class="text-decoration-none text-reset"><small class="fw-bold">Page ${index + 1}</small></a>
              <br>
              <small class="text-muted text-truncate d-block">${page.filename}</small>
              <span class="badge ${tileStatus.class} mt-1 js-tile-badge">
                <i class="fas fa-${tileStatus.icon} me-1"></i>${tileStatus.text}
              </span>
              <span class="badge ${ocrStatus.class} mt-1 js-ocr-badge">
                <i class="fas fa-${ocrStatus.icon} me-1"></i>${ocrStatus.text}
              </span>
              <br>
              <small class="text-muted"><i class="fas fa-book me-1"></i>${page.entryCount} ${page.entryCount === 1 ? "entry" : "entries"}</small>
            </div>
            <div class="card-footer p-1 text-center d-flex justify-content-center gap-1">
              ${canQueue ? `<button class="btn btn-outline-primary btn-sm js-queue-btn" title="Generate tiles"><i class="fas fa-redo"></i></button>` : ""}
              <a href="${window.directoryEditConfig.ocrUrlTemplate.replace("00000000-0000-0000-0000-000000000000", page.id)}" class="btn btn-outline-secondary btn-sm" title="OCR this page">
                <i class="fas fa-eye"></i>
              </a>
              <button class="btn btn-outline-danger btn-sm js-delete-btn" title="Delete page">
                <i class="fas fa-trash"></i>
              </button>
            </div>
          </div>
        `;
        col.querySelector(".js-delete-btn").addEventListener("click", () => {
          this.deletePage(page.id);
        });
        const queueBtn = col.querySelector(".js-queue-btn");
        if (queueBtn) {
          queueBtn.addEventListener("click", () => {
            this.queueTiles(page.id);
          });
        }
        grid.appendChild(col);
      });
    },

    initSortable() {
      const grid = this.$refs.pageGrid;
      if (!grid) return;
      if (this.sortable) this.sortable.destroy();

      this.sortable = new Sortable(grid, {
        animation: 150,
        ghostClass: "sortable-ghost",
        draggable: "[data-id]",
        onEnd: () => this.onSortEnd(),
      });
    },

    onSortEnd() {
      const grid = this.$refs.pageGrid;
      const ids = Array.from(grid.querySelectorAll("[data-id]")).map((el) =>
        el.dataset.id,
      );
      const pageMap = Object.fromEntries(this.pages.map((p) => [p.id, p]));
      this.pages = ids.map((id) => pageMap[id]).filter(Boolean);

      // Update page numbers in DOM
      grid.querySelectorAll("[data-id]").forEach((el, i) => {
        const label = el.querySelector(".fw-bold");
        if (label) label.textContent = `Page ${i + 1}`;
      });

      this.saveOrder(ids);
    },

    handleDrop(event) {
      this.isDragging = false;
      const files = Array.from(event.dataTransfer.files);
      if (files.length) this.handleFiles(files);
    },

    async handleFiles(fileList) {
      const files = Array.from(fileList).filter((f) =>
        /\.(jpe?g|png|tiff?|webp)$/i.test(f.name),
      );
      if (!files.length) return;

      // Reset file input immediately so subsequent selections trigger @change
      if (this.$refs.fileInput) this.$refs.fileInput.value = "";

      for (const file of files) {
        this.uploadQueue.push({
          name: file.name,
          file: file,
          progress: 0,
          done: false,
          error: null,
        });
      }

      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const queueItem = this.uploadQueue.find(
          (q) => q.name === file.name && !q.done && !q.error,
        );
        await this.uploadFile(file, queueItem);
      }
    },

    async uploadFile(file, queueItem) {
      const config = window.directoryEditConfig;

      try {
        const presignRes = await fetch(config.presignUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": config.csrfToken,
          },
          body: JSON.stringify({ filename: file.name }),
        });

        if (!presignRes.ok) {
          const err = await presignRes.json();
          throw new Error(err.error || "Failed to get upload URL");
        }

        const presignData = await presignRes.json();
        if (queueItem) queueItem.progress = 10;

        await new Promise((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("PUT", presignData.upload_url);
          xhr.setRequestHeader("Content-Type", presignData.content_type);

          xhr.upload.onprogress = (e) => {
            if (e.lengthComputable && queueItem) {
              queueItem.progress = 10 + Math.round((e.loaded / e.total) * 80);
            }
          };

          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve();
            } else {
              reject(new Error(`Upload failed: ${xhr.status}`));
            }
          };

          xhr.onerror = () => reject(new Error("Upload failed"));
          xhr.send(file);
        });

        if (queueItem) queueItem.progress = 95;

        const confirmRes = await fetch(config.confirmUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": config.csrfToken,
          },
          body: JSON.stringify({
            page_uuid: presignData.page_uuid,
            public_url: presignData.public_url,
            filename: presignData.filename,
          }),
        });

        if (!confirmRes.ok) throw new Error("Failed to confirm upload");

        this.pages.push({
          id: presignData.page_uuid,
          imageUrl: presignData.public_url,
          filename: file.name,
          tileStatus: "pending",
          ocrStatus: "",
          entryCount: 0,
        });

        if (queueItem) {
          queueItem.progress = 100;
          queueItem.done = true;
        }

        this.renderPages();
        this.initSortable();
        this.startPolling();
      } catch (err) {
        if (queueItem) queueItem.error = err.message;
        showError(`Upload failed for ${file.name}: ${err.message}`);
      }
    },

    async saveOrder(ids) {
      const config = window.directoryEditConfig;
      await fetch(config.reorderUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": config.csrfToken,
        },
        body: JSON.stringify({ page_ids: ids }),
      });
    },

    async queueTiles(pageId) {
      const config = window.directoryEditConfig;
      const url = config.queueTilesUrlTemplate.replace("00000000-0000-0000-0000-000000000000", pageId);
      const res = await fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": config.csrfToken },
      });

      if (res.ok) {
        const page = this.pages.find((p) => p.id === pageId);
        if (page) page.tileStatus = "pending";
        this.renderPages();
        this.initSortable();
        this.startPolling();
        showSuccess("Tile generation queued.");
      } else {
        const data = await res.json().catch(() => ({}));
        showError(data.error || "Failed to queue tile generation.");
      }
    },

    ocrRemainingCount() {
      return this.pages.filter(
        (p) => p.ocrStatus !== "pending" && p.ocrStatus !== "processing" && p.ocrStatus !== "complete",
      ).length;
    },

    async queueOcrRemaining() {
      const config = window.directoryEditConfig;
      const model = this.$refs.ocrModel?.value;
      if (!model) return;

      this.ocrBusy = true;
      this.ocrMessage = "";
      try {
        const res = await fetch(config.queueOcrUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": config.csrfToken,
          },
          body: JSON.stringify({ model }),
        });
        const data = await res.json();
        if (data.success) {
          this.ocrSuccess = true;
          this.ocrMessage = `Queued OCR for ${data.queued} page${data.queued === 1 ? "" : "s"}.`;
          // Mark pages as pending locally
          this.pages.forEach((p) => {
            if (p.ocrStatus !== "pending" && p.ocrStatus !== "processing" && p.ocrStatus !== "complete") {
              p.ocrStatus = "pending";
            }
          });
          this.renderPages();
          this.initSortable();
          this.startPolling();
        } else {
          this.ocrSuccess = false;
          this.ocrMessage = data.error || "Failed to queue OCR.";
        }
      } catch {
        this.ocrSuccess = false;
        this.ocrMessage = "Network error.";
      } finally {
        this.ocrBusy = false;
      }
    },

    async retryUpload(queueItem) {
      queueItem.error = null;
      queueItem.progress = 0;
      await this.uploadFile(queueItem.file, queueItem);
    },

    pendingDeleteId: null,
    deleteModal: null,

    deletePage(pageId) {
      this.pendingDeleteId = pageId;
      if (!this.deleteModal) {
        this.deleteModal = new bootstrap.Modal(
          document.getElementById("deletePageModal"),
        );
      }
      this.deleteModal.show();
    },

    async confirmDelete() {
      const pageId = this.pendingDeleteId;
      if (!pageId) return;
      this.deleteModal.hide();

      const config = window.directoryEditConfig;
      const url = config.deleteUrlTemplate.replace("00000000-0000-0000-0000-000000000000", pageId);
      const res = await fetch(url, {
        method: "DELETE",
        headers: { "X-CSRFToken": config.csrfToken },
      });

      if (res.ok) {
        this.pages = this.pages.filter((p) => p.id !== pageId);
        this.renderPages();
        this.initSortable();
        showSuccess("Page deleted.");
      } else {
        showError("Failed to delete page.");
      }
    },
  }));
});
