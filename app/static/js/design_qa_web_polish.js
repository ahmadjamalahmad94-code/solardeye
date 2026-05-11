// v39-web-design-qa-visual-pagination
// Progressive client-side pagination for /admin/design-qa only.
(function () {
  'use strict';

  function all(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function isArabic() {
    var html = document.documentElement;
    return (html.getAttribute('lang') || 'ar').toLowerCase().indexOf('ar') === 0 || html.getAttribute('dir') === 'rtl';
  }

  var labels = isArabic() ? {
    previous: 'السابق',
    next: 'التالي',
    page: 'صفحة',
    of: 'من',
    rows: 'صفوف',
    showing: 'يعرض',
    view10: 'عرض 10',
    view15: 'عرض 15',
    all: 'الكل'
  } : {
    previous: 'Previous',
    next: 'Next',
    page: 'Page',
    of: 'of',
    rows: 'rows',
    showing: 'Showing',
    view10: 'Show 10',
    view15: 'Show 15',
    all: 'All'
  };

  function makeButton(text, className) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = className || '';
    button.textContent = text;
    return button;
  }

  function makeOption(value, text) {
    var option = document.createElement('option');
    option.value = value;
    option.textContent = text;
    return option;
  }

  function initPager(section) {
    if (section.dataset.dqv39PagerReady === '1') return;
    section.dataset.dqv39PagerReady = '1';

    var rows = all('[data-dqv39-row]', section);
    var pager = section.querySelector('[data-dqv39-pager]');
    if (!rows.length || !pager) return;

    var state = {
      page: 1,
      pageSize: parseInt(section.getAttribute('data-dqv39-page-size') || '10', 10) || 10
    };

    var meta = document.createElement('span');
    meta.className = 'dqv39-pager-meta';

    var actions = document.createElement('span');
    actions.className = 'dqv39-pager-actions';

    var prev = makeButton(labels.previous, 'dqv39-pager-prev');
    var next = makeButton(labels.next, 'dqv39-pager-next');
    var page = document.createElement('span');
    page.className = 'dqv39-pager-page';

    var select = document.createElement('select');
    select.className = 'dqv39-pager-size';
    select.setAttribute('aria-label', labels.showing);
    select.appendChild(makeOption('10', labels.view10));
    select.appendChild(makeOption('15', labels.view15));
    select.appendChild(makeOption('all', labels.all));
    select.value = String(state.pageSize);

    actions.appendChild(prev);
    actions.appendChild(page);
    actions.appendChild(next);
    actions.appendChild(select);
    pager.appendChild(meta);
    pager.appendChild(actions);

    function totalPages() {
      if (state.pageSize === 'all') return 1;
      return Math.max(1, Math.ceil(rows.length / state.pageSize));
    }

    function clampPage() {
      var pages = totalPages();
      if (state.page > pages) state.page = pages;
      if (state.page < 1) state.page = 1;
    }

    function render() {
      clampPage();
      var pages = totalPages();
      var start = state.pageSize === 'all' ? 0 : (state.page - 1) * state.pageSize;
      var end = state.pageSize === 'all' ? rows.length : start + state.pageSize;

      rows.forEach(function (row, index) {
        row.hidden = !(index >= start && index < end);
      });

      meta.textContent = labels.showing + ' ' + (state.pageSize === 'all' ? rows.length : Math.min(rows.length, state.pageSize)) + ' / ' + rows.length + ' ' + labels.rows;
      page.textContent = labels.page + ' ' + state.page + ' ' + labels.of + ' ' + pages;
      prev.disabled = state.page <= 1 || state.pageSize === 'all';
      next.disabled = state.page >= pages || state.pageSize === 'all';
    }

    prev.addEventListener('click', function () {
      state.page -= 1;
      render();
    });

    next.addEventListener('click', function () {
      state.page += 1;
      render();
    });

    select.addEventListener('change', function () {
      state.page = 1;
      state.pageSize = select.value === 'all' ? 'all' : parseInt(select.value, 10);
      render();
    });

    render();
  }

  function bindNav() {
    var links = all('.dqv39-nav a[href^="#"]');
    if (!links.length) return;

    links.forEach(function (link) {
      link.addEventListener('click', function (event) {
        var id = link.getAttribute('href');
        var target = id ? document.querySelector(id) : null;
        if (!target) return;
        event.preventDefault();
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        links.forEach(function (item) { item.classList.remove('is-active'); });
        link.classList.add('is-active');
      });
    });
  }

  function boot() {
    all('[data-dqv39-paginated]').forEach(initPager);
    bindNav();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
