document.addEventListener("DOMContentLoaded", function () {
  const toggleBtn = document.getElementById("togglePublicBtn");

  if (toggleBtn) {
    toggleBtn.addEventListener("click", function () {
      const albumId = this.dataset.albumId;
      const isCurrentlyPublic = this.dataset.isPublic === "true";
      const newPublicStatus = !isCurrentlyPublic;

      this.disabled = true;
      const originalText = this.innerHTML;
      this.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Updating...';

      const csrfInput = document.querySelector('[name="csrfmiddlewaretoken"]');
      const csrfToken = csrfInput ? csrfInput.value : "";

      if (!csrfToken) {
        console.error("CSRF token not found");
        toggleBtn.disabled = false;
        toggleBtn.innerHTML = originalText;
        const alertDiv = document.createElement("div");
        alertDiv.className =
          "alert alert-danger alert-dismissible fade show position-fixed";
        alertDiv.style.cssText =
          "top: 20px; right: 20px; z-index: 9999; min-width: 300px;";
        alertDiv.innerHTML = `
                    Error: CSRF token not found
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                `;
        document.body.appendChild(alertDiv);
        setTimeout(() => alertDiv.remove(), 5000);
        return;
      }

      fetch(`/album/${albumId}/toggle-public/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({
          public: newPublicStatus,
        }),
      })
        .then((response) => response.json())
        .then((data) => {
          if (data.success) {
            // Update button state
            toggleBtn.dataset.isPublic = newPublicStatus.toString();

            if (newPublicStatus) {
              toggleBtn.className = "btn btn-sm btn-outline-primary";
              toggleBtn.innerHTML = '<i class="fas fa-globe me-1"></i>Public';
            } else {
              toggleBtn.className = "btn btn-sm btn-secondary";
              toggleBtn.innerHTML = '<i class="fas fa-lock me-1"></i>Private';
            }

            // Show success message
            const alertDiv = document.createElement("div");
            alertDiv.className =
              "alert alert-success alert-dismissible fade show position-fixed";
            alertDiv.style.cssText =
              "top: 20px; right: 20px; z-index: 9999; min-width: 300px;";
            alertDiv.innerHTML = `
                        Album is now ${newPublicStatus ? "public" : "private"}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                    `;
            document.body.appendChild(alertDiv);
            setTimeout(() => alertDiv.remove(), 5000);
          } else {
            throw new Error(data.error || "Failed to update album status");
          }
        })
        .catch((error) => {
          console.error("Error:", error);
          const alertDiv = document.createElement("div");
          alertDiv.className =
            "alert alert-danger alert-dismissible fade show position-fixed";
          alertDiv.style.cssText =
            "top: 20px; right: 20px; z-index: 9999; min-width: 300px;";
          alertDiv.innerHTML = `
                    Error updating album: ${error.message}
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                `;
          document.body.appendChild(alertDiv);
          setTimeout(() => alertDiv.remove(), 5000);
        })
        .finally(() => {
          toggleBtn.disabled = false;
          if (
            !toggleBtn.innerHTML.includes("Public") &&
            !toggleBtn.innerHTML.includes("Private")
          ) {
            toggleBtn.innerHTML = originalText;
          }
        });
    });
  }
});
