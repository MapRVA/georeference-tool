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
          borderColor: "rgba(75, 192, 192, 1)",
          backgroundColor: "rgba(75, 192, 192, 0.2)",
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
  new Chart(statusCtx, {
    type: "pie",
    data: {
      labels: statusLabels,
      datasets: [
        {
          label: "Image Status",
          data: statusCounts,
          backgroundColor: [
            "rgba(108, 117, 125, 0.7)", // Grey
            "rgba(255, 99, 132, 0.7)", // Light Red
            "rgba(255, 205, 86, 0.7)", // Yellow
            "rgba(75, 192, 192, 0.7)", // Green
          ],
          borderColor: [
            "rgba(108, 117, 125, 1)",
            "rgba(255, 99, 132, 1)",
            "rgba(255, 205, 86, 1)",
            "rgba(75, 192, 192, 1)",
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
