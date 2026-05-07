/* ═══════════════════════════════════════════════════════════════════════
   portal_support_v3.js  —  v211 — 20260506
   Subscriber support center: row → thread switcher + open/closed filter.
═══════════════════════════════════════════════════════════════════════ */
(function(){
  var page = document.querySelector('[data-portal-support-page]');
  if (!page) return;

  // Switch active thread on row click
  var rows = page.querySelectorAll('[data-case-row]');
  var threads = page.querySelectorAll('[data-case-panel]');
  rows.forEach(function(row){
    row.addEventListener('click', function(){
      var key = row.getAttribute('data-case-target');
      rows.forEach(function(r){ r.classList.toggle('is-active', r === row); });
      threads.forEach(function(t){
        t.classList.toggle('is-active', t.getAttribute('data-case-panel') === key);
      });
    });
  });

  // Search filter
  var search = document.getElementById('portalSupportSearch');
  if (search) {
    search.addEventListener('input', function(){
      var q = (search.value || '').toLowerCase().trim();
      rows.forEach(function(r){
        var t = (r.getAttribute('data-title') || '').toLowerCase();
        r.style.display = (!q || t.includes(q)) ? '' : 'none';
      });
    });
  }

  // Open / closed pills (KPI buttons)
  page.querySelectorAll('[data-portal-filter]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var which = btn.getAttribute('data-portal-filter');
      rows.forEach(function(r){
        var st = r.getAttribute('data-case-state');
        r.style.display = (which === 'open' && st !== 'closed') || (which === 'closed' && st === 'closed') ? '' : 'none';
      });
    });
  });
})();
