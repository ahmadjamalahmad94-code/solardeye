
(function() {
  var buildId = 'v12-sidebar-collapsible-20260429';
  var buildKey = 'solardeye_sidebar_build';
  var stateKey = 'solardeye_sidebar_state';

  function getShells() {
    return Array.prototype.slice.call(document.querySelectorAll('.app-shell.has-layout-sidebar'));
  }

  function applyState(state) {
    getShells().forEach(function(shell) {
      shell.classList.remove('sidebar-collapsed', 'sidebar-expanded');
      shell.classList.add(state === 'expanded' ? 'sidebar-expanded' : 'sidebar-collapsed');
    });
    try {
      localStorage.setItem(stateKey, state);
      localStorage.setItem('sidebar-state', state);
      localStorage.setItem('heavy_sidebar_admin_collapsed', state === 'collapsed' ? 'true' : 'false');
      localStorage.setItem('heavy_sidebar_subscriber_collapsed', state === 'collapsed' ? 'true' : 'false');
      localStorage.setItem('sidebar_collapsed', state === 'collapsed' ? 'true' : 'false');
    } catch(e) {}
  }

  function readState() {
    try {
      var seenBuild = localStorage.getItem(buildKey);
      if (seenBuild !== buildId) {
        localStorage.setItem(buildKey, buildId);
        localStorage.setItem(stateKey, 'collapsed');
        return 'collapsed';
      }
      return localStorage.getItem(stateKey) || 'collapsed';
    } catch(e) {
      return 'collapsed';
    }
  }

  function toggle() {
    var shell = getShells()[0];
    if (!shell) return;
    var next = shell.classList.contains('sidebar-collapsed') ? 'expanded' : 'collapsed';
    applyState(next);
  }

  function wireToggle() {
    var btn = document.getElementById('sdSidebarToggleV12');
    if (btn) btn.addEventListener('click', toggle);
  }

  function initBuildNotice() {
    var notice = document.getElementById('devBuildNoticeV11');
    var closeBtn = document.getElementById('devBuildNoticeCloseV11');
    if (!notice) return;
    var seenKey = 'solardeye_seen_build_' + buildId;
    var seen = false;
    try { seen = localStorage.getItem(seenKey) === '1'; } catch(e) {}
    if (!seen) notice.hidden = false;
    if (closeBtn) closeBtn.addEventListener('click', function() {
      try { localStorage.setItem(seenKey, '1'); } catch(e) {}
      notice.hidden = true;
    });
  }

  function init() {
    applyState(readState());
    wireToggle();
    initBuildNotice();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
