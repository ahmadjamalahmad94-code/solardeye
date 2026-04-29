
(function() {
  var buildId = "v20-sidebar-true-width-20260429";
  window.SOLARDEYE_SIDEBAR_BUILD = buildId;

  function shells() {
    return Array.prototype.slice.call(document.querySelectorAll(".app-shell.has-layout-sidebar"));
  }

  function setState(state) {
    document.body.classList.remove("sd-sidebar-expanded-v18", "sd-sidebar-collapsed-v18");
    document.body.classList.add(state === "expanded" ? "sd-sidebar-expanded-v18" : "sd-sidebar-collapsed-v18");

    shells().forEach(function(shell) {
      shell.classList.remove("sidebar-expanded", "sidebar-collapsed");
      shell.classList.add(state === "expanded" ? "sidebar-expanded" : "sidebar-collapsed");
      shell.dataset.sdSidebarState = state;
    });
  }

  function getState() {
    var shell = shells()[0];
    if (!shell) return "collapsed";
    return shell.classList.contains("sidebar-expanded") ? "expanded" : "collapsed";
  }

  window.sdToggleSidebarV18 = function(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    setState(getState() === "collapsed" ? "expanded" : "collapsed");
    return false;
  };

  // compatibility aliases
  window.sdToggleSidebarV17 = window.sdToggleSidebarV18;
  window.sdToggleSidebarV16 = window.sdToggleSidebarV18;
  window.sdToggleSidebarV15 = window.sdToggleSidebarV18;
  window.sdToggleSidebarV14 = window.sdToggleSidebarV18;
  window.sdToggleSidebarV13 = window.sdToggleSidebarV18;

  function wire() {
    document.querySelectorAll("#sdSidebarToggleV18, [data-sd-toggle-sidebar-v18], .sd-menu-btn-v11").forEach(function(btn) {
      if (btn.dataset.v18Wired === "1") return;
      btn.dataset.v18Wired = "1";
      btn.onclick = window.sdToggleSidebarV18;
      btn.addEventListener("click", window.sdToggleSidebarV18, true);
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
    if (closeBtn && closeBtn.dataset.v18Wired !== "1") {
      closeBtn.dataset.v18Wired = "1";
      closeBtn.addEventListener("click", function() {
        try { localStorage.setItem(key, "1"); } catch(e) {}
        notice.hidden = true;
      });
    }
  }

  function init() {
    // default closed every reload, exactly as requested
    setState("collapsed");
    wire();
    buildNotice();
    console.log("SolarDeye V18 sidebar loaded:", buildId);
  }

  document.addEventListener("click", function(e) {
    if (e.target.closest("#sdSidebarToggleV18, [data-sd-toggle-sidebar-v18], .sd-menu-btn-v11")) {
      window.sdToggleSidebarV18(e);
    }
  }, true);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  setTimeout(init, 100);
  setTimeout(wire, 500);
})();
