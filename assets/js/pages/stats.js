import Chart from "chart.js/auto";
import "chartjs-adapter-date-fns";

document.addEventListener("DOMContentLoaded", function () {
  // Get chart data from the page's data attributes
  const chartDataEl = document.getElementById("chart-data");
  if (!chartDataEl) {
    console.error("Chart data element not found");
    return;
  }

  const dailyLabels = JSON.parse(chartDataEl.dataset.dailyLabels || "[]");
  const dailyCounts = JSON.parse(chartDataEl.dataset.dailyCounts || "[]");
  const statusLabels = JSON.parse(chartDataEl.dataset.statusLabels || "[]");
  const statusCounts = JSON.parse(chartDataEl.dataset.statusCounts || "[]");

  // Daily Georeferences Chart
  const dailyCtx = document
    .getElementById("dailyGeoreferencesChart")
    .getContext("2d");

  // Get Bootstrap primary color from CSS variables
  const primaryColor = getComputedStyle(document.documentElement)
    .getPropertyValue("--bs-primary")
    .trim();

  // Convert labels and counts to data points with x (date) and y (count) values
  const dataPoints = dailyLabels.map((label, index) => ({
    x: label,
    y: dailyCounts[index],
  }));

  new Chart(dailyCtx, {
    type: "line",
    data: {
      datasets: [
        {
          label: "Cumulative Georeferences",
          data: dataPoints,
          borderColor: primaryColor,
          backgroundColor: `color-mix(in srgb, ${primaryColor} 20%, transparent)`,
          fill: true,
          tension: 0.1,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: "time",
          time: {
            unit: "day",
            displayFormats: {
              day: "MMM d, yyyy",
            },
            tooltipFormat: "PPP",
          },
          title: {
            display: true,
            text: "Date",
          },
        },
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: "Cumulative Georeferences",
          },
        },
      },
    },
  });

  // Image Status Pie Chart
  const statusCtx = document
    .getElementById("imageStatusChart")
    .getContext("2d");

  // Get Bootstrap theme colors from CSS variables
  const styles = getComputedStyle(document.documentElement);
  const secondaryColor = styles.getPropertyValue("--bs-secondary").trim();
  const dangerColor = styles.getPropertyValue("--bs-danger").trim();
  const warningColor = styles.getPropertyValue("--bs-warning").trim();
  const successColor = styles.getPropertyValue("--bs-success").trim();

  new Chart(statusCtx, {
    type: "pie",
    data: {
      labels: statusLabels,
      datasets: [
        {
          label: "Image Status",
          data: statusCounts,
          backgroundColor: [
            `color-mix(in srgb, ${secondaryColor} 70%, transparent)`,
            `color-mix(in srgb, ${dangerColor} 70%, transparent)`,
            `color-mix(in srgb, ${warningColor} 70%, transparent)`,
            `color-mix(in srgb, ${successColor} 70%, transparent)`,
          ],
          borderColor: [
            secondaryColor,
            dangerColor,
            warningColor,
            successColor,
          ],
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        tooltip: {
          callbacks: {
            label: function (context) {
              const value = context.parsed || 0;
              const imageWord = value === 1 ? "Image" : "Images";
              return ` ${value} ${imageWord}`;
            },
          },
        },
      },
    },
  });
});
