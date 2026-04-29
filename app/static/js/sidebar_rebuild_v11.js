
(function() {
  var buildId = "v16-missing-sidebar-script-20260429";
  var buildKey = "solardeye_sidebar_build";
  var stateKey = "solardeye_sidebar_state";

  window.SOLARDEYE_SIDEBAR_BUILD = buildId;

  function shells() {
    return Array.prototype.slice.call(document.querySelectorAll(".app-shell.has-layout-sidebar"));
  }

  function applyState(state) {
    shells().forEach(function(shell) {
      shell.classList.remove("sidebar-collapsed", "sidebar-expanded");
      shell.classList.add(state === "expanded" ? "sidebar-expanded" : "sidebar-collapsed");
    });
    try {
      localStorage.setItem(stateKey, state);
      localStorage.setItem("sidebar-state", state);
      localStorage.setItem("heavy_sidebar_admin_collapsed", state === "collapsed" ? "true" : "false");
      localStorage.setItem("heavy_sidebar_subscriber_collapsed", state === "collapsed" ? "true" : "false");
      localStorage.setItem("sidebar_collapsed", state === "collapsed" ? "true" : "false");
    } catch(e) {}
  }

  function currentState() {
    var shell = shells()[0];
    if (!shell) return "collapsed";
    return shell.classList.contains("sidebar-expanded") ? "expanded" : "collapsed";
  }

  function readState() {
    try {
      if (localStorage.getItem(buildKey) !== buildId) {
        localStorage.setItem(buildKey, buildId);
        localStorage.setItem(stateKey, "collapsed");
        return "collapsed";
      }
      return localStorage.getItem(stateKey) || "collapsed";
    } catch(e) {
      return "collapsed";
    }
  }

  window.sdToggleSidebarV16 = function(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    var next = currentState() === "collapsed" ? "expanded" : "collapsed";
    applyState(next);
    return false;
  };

  // Backward aliases
  window.sdToggleSidebarV15 = window.sdToggleSidebarV16;
  window.sdToggleSidebarV14 = window.sdToggleSidebarV16;
  window.sdToggleSidebarV13 = window.sdToggleSidebarV16;

  function wire() {
    document.querySelectorAll("#sdSidebarToggleV16, #sdSidebarToggleV15, #sdSidebarToggleV14, #sdSidebarToggleV13, .sd-menu-btn-v11").forEach(function(btn) {
      if (btn.dataset.v16Wired === "1") return;
      btn.dataset.v16Wired = "1";
      btn.addEventListener("click", window.sdToggleSidebarV16, false);
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
    if (closeBtn && closeBtn.dataset.v16Wired !== "1") {
      closeBtn.dataset.v16Wired = "1";
      closeBtn.addEventListener("click", function() {
        try { localStorage.setItem(key, "1"); } catch(e) {}
        notice.hidden = true;
      });
    }
  }

  function init() {
    applyState(readState());
    wire();
    buildNotice();
    console.log("SolarDeye sidebar loaded:", buildId);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  setTimeout(init, 100);
  setTimeout(wire, 500);
})();
