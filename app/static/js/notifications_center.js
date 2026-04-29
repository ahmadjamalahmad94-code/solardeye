
(function () {
  const buildId = "v26-notifications-center-polish-20260429";
  window.SOLARDEYE_NOTIFICATIONS_BUILD = buildId;

  function updateCounts(root) {
    const toggles = Array.from(root.querySelectorAll("[data-section-toggle]"));
    if (!toggles.length) return;
    const enabled = toggles.filter((el) => el.checked).length;
    const disabled = toggles.length - enabled;
    const enabledNode = root.querySelector("#enabledSectionsCount");
    const disabledNode = root.querySelector("#disabledSectionsCount");
    if (enabledNode) enabledNode.textContent = enabled;
    if (disabledNode) disabledNode.textContent = disabled;

    root.querySelectorAll(".notify-tab-btn").forEach((btn) => {
      const target = btn.dataset.target;
      const panel = target ? root.querySelector("#" + CSS.escape(target)) : null;
      const badge = btn.querySelector(".tab-live-badge");
      const sectionToggle = panel ? panel.querySelector("[data-section-toggle]") : null;
      if (badge && sectionToggle) {
        badge.textContent = sectionToggle.checked ? "ON" : "OFF";
        btn.classList.toggle("is-disabled", !sectionToggle.checked);
      }
    });
  }

  function setupTabs(root) {
    root.querySelectorAll(".notify-tab-btn").forEach((btn) => {
      if (btn.dataset.v26Wired === "1") return;
      btn.dataset.v26Wired = "1";
      btn.addEventListener("click", () => {
        const target = btn.dataset.target;
        if (!target) return;
        root.querySelectorAll(".notify-tab-btn").forEach((b) => b.classList.remove("active"));
        root.querySelectorAll(".notify-tab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        const panel = root.querySelector("#" + CSS.escape(target));
        if (panel) panel.classList.add("active");
      });
    });
  }

  function setupToggles(root) {
    root.querySelectorAll("[data-section-toggle]").forEach((input) => {
      if (input.dataset.v26Wired === "1") return;
      input.dataset.v26Wired = "1";
      input.addEventListener("change", () => updateCounts(root));
    });
  }

  function init() {
    document.querySelectorAll("[data-notifications-center]").forEach((root) => {
      setupTabs(root);
      setupToggles(root);
      updateCounts(root);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
