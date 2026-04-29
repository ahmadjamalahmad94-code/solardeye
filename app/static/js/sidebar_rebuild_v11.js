
(function() {
  var buildId = "v11-sidebar-rebuild-20260429";

  function forceDesktopSidebarOpen() {
    if (window.innerWidth <= 900) return;
    try {
      localStorage.setItem("sidebar-state", "expanded");
      localStorage.setItem("heavy_sidebar_admin_collapsed", "false");
      localStorage.setItem("heavy_sidebar_subscriber_collapsed", "false");
      localStorage.setItem("sidebar_collapsed", "false");
    } catch(e) {}

    document.body.classList.remove("sidebar-collapsed-v180", "sidebar-collapsed", "sidebar-open-v70");
    document.body.classList.add("sidebar-expanded-v11");

    document.querySelectorAll(".app-shell.has-layout-sidebar").forEach(function(shell) {
      shell.classList.remove("sidebar-collapsed");
      shell.classList.add("sidebar-expanded");
    });
  }

  function showDevNoticeOncePerBuild() {
    var notice = document.getElementById("devBuildNoticeV11");
    var closeBtn = document.getElementById("devBuildNoticeCloseV11");
    if (!notice) return;

    var key = "solardeye_seen_build_" + buildId;
    var seen = false;
    try { seen = localStorage.getItem(key) === "1"; } catch(e) {}

    if (!seen) {
      notice.hidden = false;
    }

    if (closeBtn) {
      closeBtn.addEventListener("click", function() {
        try { localStorage.setItem(key, "1"); } catch(e) {}
        notice.hidden = true;
      });
    }
  }

  forceDesktopSidebarOpen();
  showDevNoticeOncePerBuild();
  window.addEventListener("resize", forceDesktopSidebarOpen);
})();
