/* ═══════════════════════════════════════════════════════════════════════
   table_paginate_v1.js  —  v211 — 20260506
   Drop-in client-side pagination for any table:

   <table data-paginate data-page-size="10">
     <thead>...</thead>
     <tbody><tr>...</tr><tr>...</tr></tbody>
   </table>

   Optional attrs:
     data-page-size      Rows per page (default: 10)
     data-pager-target   Selector where the pager UI is injected
                         (default: appended right after the table)
   The script auto-discovers the page language from <html lang="...">
   to render Arabic / English labels.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  function isAr() {
    var lang = (document.documentElement.getAttribute('lang') || '').toLowerCase();
    return lang === 'ar' || lang.indexOf('ar-') === 0 ||
           document.documentElement.getAttribute('dir') === 'rtl';
  }
  var L = isAr()
    ? { prev: '‹ السابق', next: 'التالي ›', first: '« الأولى', last: 'الأخيرة »',
        page: 'الصفحة', of: 'من', show: 'عرض', rows: 'صف', empty: 'لا توجد سجلات' }
    : { prev: '‹ Prev', next: 'Next ›', first: '« First', last: 'Last »',
        page: 'Page', of: 'of', show: 'Showing', rows: 'rows', empty: 'No rows' };

  function paginate(table) {
    if (!table || table.dataset.pgInit === '1') return;
    table.dataset.pgInit = '1';
    var size = parseInt(table.dataset.pageSize, 10) || 20;
    var tbody = table.tBodies[0];
    if (!tbody) return;
    var allRows = Array.prototype.slice.call(tbody.rows).filter(function (r) {
      // Skip empty-state rows (single colspan cell with no useful content)
      return !r.classList.contains('pg-empty-row');
    });
    if (allRows.length <= size) return;

    var totalPages = Math.ceil(allRows.length / size);
    var page = 1;

    // Build pager UI
    var pager = document.createElement('nav');
    pager.className = 'pg-pager';
    pager.setAttribute('aria-label', 'pagination');

    var info = document.createElement('div');
    info.className = 'pg-info';

    var btns = document.createElement('div');
    btns.className = 'pg-btns';

    function btn(label, disabled, onClick, active) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'pg-btn' + (active ? ' is-active' : '');
      b.textContent = label;
      b.disabled = !!disabled;
      if (onClick) b.addEventListener('click', onClick);
      return b;
    }

    function render() {
      var start = (page - 1) * size;
      var end   = start + size;
      allRows.forEach(function (row, i) {
        row.style.display = (i >= start && i < end) ? '' : 'none';
      });
      info.textContent = L.show + ' ' + Math.min(start + 1, allRows.length) +
                         '–' + Math.min(end, allRows.length) +
                         ' / ' + allRows.length + ' ' + L.rows;
      btns.innerHTML = '';
      btns.appendChild(btn(L.first, page === 1,           function () { page = 1; render(); }));
      btns.appendChild(btn(L.prev,  page === 1,           function () { page = Math.max(1, page - 1); render(); }));
      // Numeric window: up to 5 pages around current
      var windowStart = Math.max(1, page - 2);
      var windowEnd   = Math.min(totalPages, windowStart + 4);
      windowStart = Math.max(1, windowEnd - 4);
      for (var p = windowStart; p <= windowEnd; p++) {
        (function (target) {
          btns.appendChild(btn(String(target), false, function () { page = target; render(); }, target === page));
        })(p);
      }
      btns.appendChild(btn(L.next,  page === totalPages, function () { page = Math.min(totalPages, page + 1); render(); }));
      btns.appendChild(btn(L.last,  page === totalPages, function () { page = totalPages; render(); }));
    }

    pager.appendChild(info);
    pager.appendChild(btns);

    var target = table.dataset.pagerTarget
      ? document.querySelector(table.dataset.pagerTarget)
      : null;
    if (target) {
      target.appendChild(pager);
    } else {
      // Insert directly after the table or its wrapper if scrollable
      var wrap = table.closest('.dvf-table-wrap, .lgs-table-wrap, .fin-table-wrap, .svch-table-wrap, .bkp-list-block, .pg-table-wrap');
      var anchor = wrap || table;
      if (anchor.parentNode) anchor.parentNode.insertBefore(pager, anchor.nextSibling);
    }
    render();
  }

  function bootAll() {
    var tables = document.querySelectorAll('table[data-paginate]');
    tables.forEach(paginate);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootAll);
  } else {
    bootAll();
  }
  // Expose for tables added later
  window.SDPaginate = { boot: bootAll, table: paginate };
})();
