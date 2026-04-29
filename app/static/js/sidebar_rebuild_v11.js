
(function() {
  var buildId = "v14-toggle-hard-fix-20260429";
  var buildKey = "solardeye_sidebar_build";
  var stateKey = "solardeye_sidebar_state";

  function getShells() {
    return Array.prototype.slice.call(document.querySelectorAll(".app-shell.has-layout-sidebar"));
  }

  function applyState(state) {
    getShells().forEach(function(shell) {
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
    var shell = getShells()[0];
    if (!shell) return "collapsed";
    return shell.classList.contains("sidebar-expanded") ? "expanded" : "collapsed";
  }

  function readState() {
    try {
      var seenBuild = localStorage.getItem(buildKey);
      if (seenBuild !== buildId) {
        localStorage.setItem(buildKey, buildId);
        localStorage.setItem(stateKey, "collapsed");
        return "collapsed";
      }
      return localStorage.getItem(stateKey) || "collapsed";
    } catch(e) {
      return "collapsed";
    }
  }

  window.sdToggleSidebarV14 = function(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
      if (event.stopImmediatePropagation) event.stopImmediatePropagation();
    }
    var next = currentState() === "collapsed" ? "expanded" : "collapsed";
    applyState(next);
    return false;
  };

  function wire() {
    var buttons = Array.prototype.slice.call(document.querySelectorAll("#sdSidebarToggleV14, .sd-menu-btn-v11"));
    buttons.forEach(function(btn) {
      if (btn.dataset.v14Wired === "1") return;
      btn.dataset.v14Wired = "1";
      btn.addEventListener("click", window.sdToggleSidebarV14, true);
      btn.addEventListener("pointerup", function(e) {
        // fallback for browsers/extensions that swallow click
        if (e.pointerType === "mouse") return;
        window.sdToggleSidebarV14(e);
      }, true);
    });
  }

  function initBuildNotice() {
    var notice = document.getElementById("devBuildNoticeV11");
    var closeBtn = document.getElementById("devBuildNoticeCloseV11");
    if (!notice) return;

    var seenKey = "solardeye_seen_build_" + buildId;
    var seen = false;
    try { seen = localStorage.getItem(seenKey) === "1"; } catch(e) {}
    if (!seen) notice.hidden = false;

    if (closeBtn && closeBtn.dataset.v14Wired !== "1") {
      closeBtn.dataset.v14Wired = "1";
      closeBtn.addEventListener("click", function() {
        try { localStorage.setItem(seenKey, "1"); } catch(e) {}
        notice.hidden = true;
      });
    }
  }

  function init() {
    applyState(readState());
    wire();
    initBuildNotice();
  }

  document.addEventListener("click", function(e) {
    if (e.target.closest("#sdSidebarToggleV14, .sd-menu-btn-v11")) {
      window.sdToggleSidebarV14(e);
    }
  }, true);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Rewire/reapply after legacy app.js potentially runs
  setTimeout(init, 100);
  setTimeout(wire, 500);
  setTimeout(function() { applyState(readState()); wire(); }, 900);
})();
