/* =====================================================================
   Notifications Center — v40 Modern Redesign · Behavior
   SolarDeye Platform · 2026-04-30
   ===================================================================== */
(function () {
  'use strict';

  const root = document.querySelector('[data-ncv40-root]');
  if (!root) return;

  const items = Array.from(root.querySelectorAll('[data-ncv40-item]'));
  const visibleCountEl = root.querySelector('[data-ncv40-visible-count]');
  const list = root.querySelector('[data-ncv40-list]');
  const emptyEl = root.querySelector('[data-ncv40-empty]');
  const markUrl = root.dataset.markReadUrl || '';

  /* ---------------- State ---------------- */
  const state = {
    tab: 'all',
    statusFilter: 'all',
    priorityFilter: 'all',
    search: '',
  };

  /* ---------------- Utilities ---------------- */
  function debounce(fn, wait) {
    let t = 0;
    return function () {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), wait);
    };
  }

  function showToast(message, type) {
    let toast = document.querySelector('.ncv40-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.className = 'ncv40-toast';
      document.body.appendChild(toast);
    }
    const color = type === 'success' ? '#16a34a' :
                  type === 'error'   ? '#ef4444' : '#2563eb';
    toast.style.background = color;
    toast.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" ' +
      'stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>' +
      '<span></span>';
    toast.querySelector('span').textContent = message;
    toast.classList.add('is-visible');
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => toast.classList.remove('is-visible'), 2400);
  }

  /* ---------------- Filtering ---------------- */
  function matches(item) {
    const kind     = (item.dataset.kind || 'system').toLowerCase();
    const unread   = Number(item.dataset.unread || 0) > 0;
    const archived = item.dataset.archived === '1';
    const status   = (item.dataset.status || '').toLowerCase();
    const priority = (item.dataset.priority || '').toLowerCase();
    const text     = (item.dataset.search || '').toLowerCase();

    if (state.tab === 'unread'  && !unread) return false;
    if (state.tab === 'message' && kind !== 'message') return false;
    if (state.tab === 'ticket'  && kind !== 'ticket') return false;
    if (state.tab === 'system'  && kind !== 'system') return false;
    if (state.tab === 'archive' && !archived) return false;

    if (state.tab !== 'archive') {
      if (state.statusFilter === 'open'   && (archived || ['closed', 'resolved'].includes(status))) return false;
      if (state.statusFilter === 'closed' && !['closed', 'resolved'].includes(status)) return false;
    }

    if (state.priorityFilter === 'high' && !['high', 'urgent'].includes(priority)) return false;

    if (state.search && text.indexOf(state.search) === -1) return false;

    return true;
  }

  function apply() {
    let count = 0;
    items.forEach(item => {
      const ok = matches(item);
      item.classList.toggle('is-hidden', !ok);
      if (ok) count++;
    });
    if (visibleCountEl) visibleCountEl.textContent = count;
    if (emptyEl) emptyEl.style.display = count === 0 ? '' : 'none';
  }

  /* ---------------- Tabs ---------------- */
  root.querySelectorAll('[data-ncv40-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      root.querySelectorAll('[data-ncv40-tab]').forEach(b => b.classList.remove('is-active'));
      btn.classList.add('is-active');
      state.tab = btn.dataset.ncv40Tab || 'all';

      // Sync stat-card highlights when tabs are clicked
      root.querySelectorAll('[data-ncv40-stat]').forEach(s => s.classList.remove('is-active'));
      const linked = root.querySelector('[data-ncv40-stat="' + state.tab + '"]');
      if (linked) linked.classList.add('is-active');

      apply();
    });
  });

  /* ---------------- Stat cards (clickable) ---------------- */
  root.querySelectorAll('[data-ncv40-stat]').forEach(card => {
    card.addEventListener('click', () => {
      const target = card.dataset.ncv40Stat;
      const tabBtn = root.querySelector('[data-ncv40-tab="' + target + '"]');
      if (tabBtn) tabBtn.click();
    });
  });

  /* ---------------- Filters ---------------- */
  root.querySelectorAll('[data-ncv40-status]').forEach(input => {
    input.addEventListener('change', () => {
      if (input.checked) {
        state.statusFilter = input.value;
        apply();
      }
    });
  });

  root.querySelectorAll('[data-ncv40-priority]').forEach(input => {
    input.addEventListener('change', () => {
      if (input.checked) {
        state.priorityFilter = input.value;
        apply();
      }
    });
  });

  /* ---------------- Search ---------------- */
  const search = root.querySelector('[data-ncv40-search]');
  if (search) {
    search.addEventListener('input', debounce(() => {
      state.search = (search.value || '').trim().toLowerCase();
      apply();
    }, 180));
  }

  /* ---------------- Reset ---------------- */
  const reset = root.querySelector('[data-ncv40-reset]');
  if (reset) {
    reset.addEventListener('click', () => {
      state.tab = 'all';
      state.statusFilter = 'all';
      state.priorityFilter = 'all';
      state.search = '';
      if (search) search.value = '';

      root.querySelectorAll('[data-ncv40-tab]').forEach(b =>
        b.classList.toggle('is-active', b.dataset.ncv40Tab === 'all'));
      root.querySelectorAll('[data-ncv40-stat]').forEach(s =>
        s.classList.toggle('is-active', s.dataset.ncv40Stat === 'all'));
      root.querySelectorAll('[data-ncv40-status]').forEach(i =>
        i.checked = i.value === 'all');
      root.querySelectorAll('[data-ncv40-priority]').forEach(i =>
        i.checked = i.value === 'all');

      apply();
    });
  }

  /* ---------------- Mark as read ---------------- */
  function postMark(formData) {
    if (!markUrl) return Promise.resolve({});
    const csrfToken =
      document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
      document.body?.dataset?.csrfToken ||
      '';
    return fetch(markUrl, {
      method: 'POST',
      body: formData,
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrfToken,
      },
      credentials: 'same-origin',
    })
      .then(r => r.json())
      .then(json => {
        const c = json.count || 0;
        document.querySelectorAll(
          '#dashHeaderNotifCountV29,#dashHeaderNotifMiniCountV29,#notificationBellCount,[data-ncv40-sidebar-badge]'
        ).forEach(el => {
          el.textContent = c;
          el.classList.toggle('is-zero', c <= 0);
          if (c <= 0) el.style.display = 'none';
          else el.style.display = '';
        });
        return json;
      })
      .catch(() => ({}));
  }

  /* Open links: mark group as read on navigation */
  root.querySelectorAll('[data-ncv40-open]').forEach(a => {
    a.addEventListener('click', () => {
      const fd = new FormData();
      fd.append('group_key', a.dataset.groupKey || '');
      postMark(fd);
    });
  });

  /* Row click acts like the open button */
  root.querySelectorAll('[data-ncv40-item]').forEach(row => {
    row.addEventListener('click', e => {
      if (e.target.closest('a, button')) return;
      const link = row.querySelector('[data-ncv40-open]');
      if (link) link.click();
    });
  });

  /* Mark all */
  const markAll = root.querySelector('[data-ncv40-mark-all]');
  if (markAll) {
    markAll.addEventListener('click', () => {
      const fd = new FormData();
      fd.append('all', '1');
      postMark(fd).then(() => {
        items.forEach(item => {
          item.dataset.unread = '0';
          item.classList.remove('is-unread');
          const badge = item.querySelector('.ncv40-unread-badge');
          if (badge) {
            badge.textContent = '0';
            badge.classList.add('is-zero');
          }
        });
        const stat = root.querySelector('[data-ncv40-stat-unread]');
        if (stat) stat.textContent = '0';
        showToast('تم تحديد الكل كمقروء', 'success');
        apply();
      });
    });
  }

  /* Initial render */
  apply();
})();
