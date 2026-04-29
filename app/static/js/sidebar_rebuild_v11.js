
(function() {
  var buildId = "v17-real-sidebar-toggle-20260429";
  window.SOLARDEYE_SIDEBAR_BUILD = buildId;

  function shells() {
    return Array.prototype.slice.call(document.querySelectorAll(".app-shell.has-layout-sidebar"));
  }

  function setState(state) {
    shells().forEach(function(shell) {
      shell.classList.remove("sidebar-expanded", "sidebar-collapsed");
      shell.classList.add(state === "expanded" ? "sidebar-expanded" : "sidebar-collapsed");
    });
  }

  function toggle(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    var shell = shells()[0];
    if (!shell) return false;
    var isCollapsed = shell.classList.contains("sidebar-collapsed");
    setState(isCollapsed ? "expanded" : "collapsed");
    return false;
  }

  window.sdToggleSidebarV17 = toggle;
  window.sdToggleSidebarV16 = toggle;
  window.sdToggleSidebarV15 = toggle;
  window.sdToggleSidebarV14 = toggle;
  window.sdToggleSidebarV13 = toggle;

  function wire() {
    var buttons = Array.prototype.slice.call(document.querySelectorAll("#sdSidebarToggleV17, [data-sd-toggle-sidebar], .sd-menu-btn-v11"));
    buttons.forEach(function(btn) {
      if (btn.dataset.v17Wired === "1") return;
      btn.dataset.v17Wired = "1";
      btn.onclick = toggle;
      btn.addEventListener("click", toggle, false);
      btn.addEventListener("pointerup", function(e) {
        if (e.pointerType !== "mouse") toggle(e);
      }, false);
    });
  }

  function buildNotice() {
    var notice = document.getElementById("devBuildNoticeV11");
    var closeBtn = document.getElementById("devBuildNoticeCloseV11");
    if (!notice) return;
    var key = "solardeye_seen_build_" + buildId;
    var seen = false;
    try { seen = localStorage.getItem(key) === "1"; } catch(e) {}
    if (!seen) notice.hidden = false;
    if (closeBtn && closeBtn.dataset.v17Wired !== "1") {
      closeBtn.dataset.v17Wired = "1";
      closeBtn.addEventListener("click", function() {
        try { localStorage.setItem(key, "1"); } catch(e) {}
        notice.hidden = true;
      });
    }
  }

  function init() {
    // As requested: default collapsed on every refresh, no localStorage state restore.
    setState("collapsed");
    wire();
    buildNotice();
    console.log("SolarDeye sidebar v17 loaded", buildId);
  }

  document.addEventListener("click", function(e) {
    if (e.target.closest("#sdSidebarToggleV17, [data-sd-toggle-sidebar], .sd-menu-btn-v11")) {
      toggle(e);
    }
  }, false);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  setTimeout(wire, 100);
  setTimeout(wire, 500);
})();
