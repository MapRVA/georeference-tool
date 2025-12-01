/**
 * Notification/Alert Utility
 *
 * Provides a consistent way to show Bootstrap alerts across the application.
 * Alerts are displayed as toast-style notifications in the top-right corner.
 */

/**
 * Show a Bootstrap alert notification
 * @param {string} type - Alert type: 'success', 'danger', 'warning', 'info', 'primary', 'secondary'
 * @param {string} message - Message to display (can include HTML)
 * @param {number} duration - Duration in milliseconds before auto-dismiss (default: 5000)
 */
window.showAlert = function(type, message, duration = 5000) {
  const alertDiv = document.createElement("div");
  alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
  alertDiv.style.cssText =
    "top: 20px; right: 20px; z-index: 9999; min-width: 300px;";
  alertDiv.innerHTML = `
    ${message}
    <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
  `;

  document.body.appendChild(alertDiv);

  // Auto-dismiss after duration
  if (duration > 0) {
    setTimeout(() => {
      alertDiv.classList.remove('show');
      // Wait for fade animation before removing
      setTimeout(() => alertDiv.remove(), 150);
    }, duration);
  }
};

/**
 * Convenience methods for common alert types
 */
window.showSuccess = function(message, duration) {
  window.showAlert('success', message, duration);
};

window.showError = function(message, duration) {
  window.showAlert('danger', message, duration);
};

window.showWarning = function(message, duration) {
  window.showAlert('warning', message, duration);
};

window.showInfo = function(message, duration) {
  window.showAlert('info', message, duration);
};
