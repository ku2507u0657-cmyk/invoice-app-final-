/**
 * InvoiceFlow — Main JavaScript
 */

"use strict";

// ── Sidebar toggle (mobile) ───────────────────────────────
function toggleSidebar() {
  const sidebar = document.getElementById("sidebar");
  if (sidebar) sidebar.classList.toggle("open");
}

// Close sidebar when clicking outside on mobile
document.addEventListener("click", function (e) {
  const sidebar = document.getElementById("sidebar");
  const toggle = document.querySelector(".sidebar-toggle");
  if (!sidebar) return;
  if (
    window.innerWidth < 992 &&
    sidebar.classList.contains("open") &&
    !sidebar.contains(e.target) &&
    e.target !== toggle
  ) {
    sidebar.classList.remove("open");
  }
});

// ── Animate stat values on page load ─────────────────────
function animateCounters() {
  document.querySelectorAll(".stat-value").forEach((el) => {
    const raw = el.textContent.trim();
    const num = parseFloat(raw.replace(/[^0-9.]/g, ""));
    if (isNaN(num) || num === 0) return;

    const prefix = raw.startsWith("$") ? "$" : "";
    const isFloat = raw.includes(".");
    let start = 0;
    const duration = 800;
    const startTime = performance.now();

    function step(now) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = start + (num - start) * eased;
      el.textContent =
        prefix +
        (isFloat
          ? current.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
          : Math.round(current).toLocaleString("en-US"));
      if (progress < 1) requestAnimationFrame(step);
    }

    requestAnimationFrame(step);
  });
}

// ── Init ──────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function () {
  animateCounters();

  // Auto-dismiss flash messages after 5 seconds
  document.querySelectorAll(".alert.alert-dismissible").forEach(function (alert) {
    setTimeout(function () {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) bsAlert.close();
    }, 5000);
  });
});
