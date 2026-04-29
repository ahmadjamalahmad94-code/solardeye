
(function() {
  var buildId = "v28-dashboard-header-single-row-20260429";
  window.SOLARDEYE_SIDEBAR_BUILD = buildId;

  function shells() {
    return Array.prototype.slice.call(document.querySelectorAll(".app-shell.has-layout-sidebar"));
  }

  function setState(state) {
    document.body.classList.remove("sd-sidebar-expanded-v21", "sd-sidebar-collapsed-v21");
    document.body.classList.add(state === "expanded" ? "sd-sidebar-expanded-v21" : "sd-sidebar-collapsed-v21");

    shells().forEach(function(shell) {
      shell.classList.remove("sidebar-expanded", "sidebar-collapsed");
      shell.classList.add(state === "expanded" ? "sidebar-expanded" : "sidebar-collapsed");
      shell.dataset.sdSidebarState = state;
    });
  }

  function getState() {
    return document.body.classList.contains("sd-sidebar-expanded-v21") ? "expanded" : "collapsed";
  }

  window.sdToggleSidebarV21 = function(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    setState(getState() === "collapsed" ? "expanded" : "collapsed");
    return false;
  };

  function wire() {
    document.querySelectorAll("#sdSidebarToggleV21, [data-sd-toggle-sidebar-v21], .sd-menu-btn-v11").forEach(function(btn) {
      if (btn.dataset.v21Wired === "1") return;
      btn.dataset.v21Wired = "1";
      btn.onclick = window.sdToggleSidebarV21;
      btn.addEventListener("click", window.sdToggleSidebarV21, true);
    });
  }

  function buildNotice() { return; }

  function init() {
    setState("collapsed");
    wire();
    buildNotice();
    console.log("SolarDeye V21 clean sidebar loaded:", buildId);
  }

  document.addEventListener("click", function(e) {
    if (e.target.closest("#sdSidebarToggleV21, [data-sd-toggle-sidebar-v21], .sd-menu-btn-v11")) {
      window.sdToggleSidebarV21(e);
    }
  }, true);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  setTimeout(wire, 100);
  setTimeout(wire, 500);
})();
