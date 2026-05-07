/* Support Command Center — AJAX behaviors
 *
 * Behaviors:
 *   • KPI / filter chip click  → re-render inbox + counters without page reload
 *   • Inbox card click         → fetch single case JSON and swap detail+thread panels
 *   • Toolbar action submit    → POST as AJAX, toast feedback, reload selected case
 *   • Composer submit          → POST as AJAX, append message inline, clear textarea
 *   • Search box               → client-side filter over the visible inbox cards
 *   • Danger action (close)    → ask for confirmation before submitting
 */
(function () {
  'use strict';

  const root = document.querySelector('[data-support-center]');
  if (!root) return;

  const state = {
    filter: root.dataset.currentFilter || 'all',
    caseKey: root.dataset.currentCase || '',
    isLoading: false,
  };

  const cfg = {
    listUrl: root.dataset.listUrl,
    caseBaseUrl: root.dataset.caseBaseUrl,
    actionUrl: root.dataset.actionUrl,
  };

  const isEn = (document.documentElement.lang || 'ar').startsWith('en');
  const t = (ar, en) => (isEn ? en : ar);

  const csrfToken = () => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  };

  /* ────────────────────── Toast ────────────────────── */
  // Move the toast to <body> directly — otherwise its parent grid/main
  // container imposes a containing block on `position: fixed` and the
  // toast renders at the wrong horizontal position regardless of CSS
  // centering rules.
  function feedbackLayer() {
    let layer = document.querySelector('[data-sc-feedback-layer]');
    if (!layer) {
      layer = document.createElement('div');
      layer.className = 'sc-feedback-layer';
      layer.dataset.scFeedbackLayer = '1';
      document.body.appendChild(layer);
    }
    layer.style.setProperty('position', 'fixed', 'important');
    layer.style.setProperty('inset', '0', 'important');
    layer.style.setProperty('display', 'flex', 'important');
    layer.style.setProperty('justify-content', 'center', 'important');
    layer.style.setProperty('align-items', 'flex-start', 'important');
    layer.style.setProperty('padding-top', '16px', 'important');
    layer.style.setProperty('pointer-events', 'none', 'important');
    layer.style.setProperty('z-index', '100000', 'important');
    return layer;
  }

  function centerFeedbackNode(el) {
    if (!el) return;
    const layer = feedbackLayer();
    if (el.parentNode !== layer) layer.appendChild(el);
    el.style.setProperty('position', 'static', 'important');
    el.style.setProperty('top', 'auto', 'important');
    el.style.setProperty('bottom', 'auto', 'important');
    el.style.setProperty('left', 'auto', 'important');
    el.style.setProperty('right', 'auto', 'important');
    el.style.setProperty('inset-inline-start', 'auto', 'important');
    el.style.setProperty('inset-inline-end', 'auto', 'important');
    el.style.setProperty('margin', '0 auto', 'important');
    el.style.setProperty('transform', 'none', 'important');
    el.style.setProperty('width', 'max-content', 'important');
    el.style.setProperty('max-width', 'min(420px, calc(100vw - 28px))', 'important');
    el.style.setProperty('text-align', 'center', 'important');
    el.style.setProperty('pointer-events', 'auto', 'important');
    el.style.setProperty('z-index', '1', 'important');
  }

  const toastEl = root.querySelector('[data-sc-toast]');
  centerFeedbackNode(toastEl);
  document.querySelectorAll('.flash-stack-v61').forEach((stack) => {
    centerFeedbackNode(stack);
    stack.style.setProperty('display', 'grid', 'important');
    stack.style.setProperty('place-items', 'center', 'important');
  });

  let toastTimer = null;
  function toast(message, kind) {
    if (!toastEl) return;
    centerFeedbackNode(toastEl);
    toastEl.hidden = false;
    toastEl.dataset.kind = kind || 'info';
    toastEl.textContent = message;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, 4000);
  }

  /* ────────────────────── Helpers ────────────────────── */
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function setLoading(on) {
    state.isLoading = !!on;
    root.classList.toggle('is-loading', state.isLoading);
  }

  function updateKpis(stats) {
    if (!stats || typeof stats !== 'object') return;
    document.querySelectorAll('[data-stat-key]').forEach((el) => {
      const key = el.dataset.statKey;
      if (key in stats) el.textContent = stats[key];
    });
  }

  function updateActiveFilter(newFilter) {
    state.filter = newFilter;
    root.dataset.currentFilter = newFilter;
    document.querySelectorAll('[data-filter-target]').forEach((el) => {
      el.classList.toggle('is-active', el.dataset.filterTarget === newFilter);
    });
  }

  function updateActiveCase(newKey) {
    state.caseKey = newKey || '';
    root.dataset.currentCase = state.caseKey;
    document.querySelectorAll('[data-case-link]').forEach((el) => {
      el.classList.toggle('is-active', el.dataset.caseLink === state.caseKey);
    });
  }

  function pushUrl(filter, caseKey) {
    const url = new URL(cfg.caseBaseUrl, window.location.origin);
    if (filter) url.searchParams.set('filter', filter);
    if (caseKey) url.searchParams.set('case', caseKey);
    const lang = new URLSearchParams(window.location.search).get('lang');
    if (lang) url.searchParams.set('lang', lang);
    window.history.replaceState({}, '', url.toString());
  }

  /* ────────────────────── Render: inbox card from JSON ────────────────────── */
  function renderInboxCard(item) {
    const overdue = item.overdue
      ? `<span class="sc-pill priority-urgent">${t('متأخر', 'Overdue')}</span>`
      : '';
    const priority = (item.priority === 'high' || item.priority === 'urgent')
      ? `<span class="sc-pill priority-${escapeHtml(item.priority)}">${escapeHtml(item.priority_label)}</span>`
      : '';
    const preview = item.preview
      ? `<p class="sc-inbox-preview">${escapeHtml(item.preview)}</p>`
      : '';
    const subject = item.subject || t('بدون عنوان', 'Untitled');
    const ownerLabel = item.owner_label || t('غير متوفر', 'Not available');
    const isActive = state.caseKey === item.case_key ? 'is-active' : '';
    return `
      <button type="button"
              class="sc-inbox-card ${isActive} status-${escapeHtml(item.status)} priority-${escapeHtml(item.priority)}"
              data-case-link="${escapeHtml(item.case_key)}"
              data-case-search="${escapeHtml(((item.subject || '') + ' ' + ownerLabel + ' ' + item.case_key).toLowerCase())}">
        <span class="sc-inbox-avatar">${escapeHtml(item.owner_initial || '?')}</span>
        <div class="sc-inbox-text">
          <div class="sc-inbox-row1">
            <strong>${escapeHtml(subject)}</strong>
            <time>${escapeHtml(item.updated_at || '—')}</time>
          </div>
          <div class="sc-inbox-row2">
            <span class="sc-inbox-owner">${escapeHtml(ownerLabel)}</span>
            <span class="sc-inbox-ref">#${String(item.source_id).padStart(5, '0')}</span>
          </div>
          ${preview}
          <div class="sc-inbox-row3">
            <span class="sc-pill status-${escapeHtml(item.status)}">${escapeHtml(item.status_label)}</span>
            ${priority}
            ${overdue}
          </div>
        </div>
      </button>
    `;
  }

  function renderInbox(items) {
    const list = root.querySelector('[data-inbox-list]');
    if (!list) return;
    if (!items || !items.length) {
      list.innerHTML = `<p class="sc-empty-mini">${t('لا توجد طلبات ضمن هذا الفلتر.', 'No cases match this filter.')}</p>`;
      return;
    }
    list.innerHTML = items.map(renderInboxCard).join('');
  }

  /* ────────────────────── AJAX: fetch list ────────────────────── */
  async function fetchList(newFilter) {
    if (!cfg.listUrl) return;
    setLoading(true);
    try {
      const url = new URL(cfg.listUrl, window.location.origin);
      url.searchParams.set('filter', newFilter);
      const res = await fetch(url.toString(), {
        headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error('list failed');
      const data = await res.json();
      if (!data.ok) throw new Error(data.message || 'list error');
      updateActiveFilter(newFilter);
      updateKpis(data.stats || {});
      renderInbox(data.items || []);
      pushUrl(newFilter, state.caseKey);
    } catch (e) {
      toast(t('تعذر تحميل القائمة.', 'Could not load the queue.'), 'danger');
    } finally {
      setLoading(false);
    }
  }

  /* ────────────────────── AJAX: load a single case (full page reload) ────────────────────── */
  // The detail/thread panels are rendered server-side. To keep the page
  // consistent with all of its server-rendered logic (status maps, attachments,
  // canned replies macros), navigating to a different case does a soft reload
  // of those two panels by fetching the full page and swapping the panels in.
  // KPIs and inbox stay intact. This avoids duplicating large chunks of markup
  // in JS for every related sub-section.
  async function loadCase(caseKey) {
    if (!caseKey || caseKey === state.caseKey) return;
    setLoading(true);
    try {
      const url = new URL(cfg.caseBaseUrl, window.location.origin);
      url.searchParams.set('filter', state.filter);
      url.searchParams.set('case', caseKey);
      const lang = new URLSearchParams(window.location.search).get('lang');
      if (lang) url.searchParams.set('lang', lang);
      const res = await fetch(url.toString(), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin',
      });
      if (!res.ok) throw new Error('case fetch failed');
      const html = await res.text();
      const doc = new DOMParser().parseFromString(html, 'text/html');
      const newDetail = doc.querySelector('[data-detail-panel]');
      const newThread = doc.querySelector('[data-thread-panel]');
      const oldDetail = root.querySelector('[data-detail-panel]');
      const oldThread = root.querySelector('[data-thread-panel]');
      if (newDetail && oldDetail) oldDetail.replaceWith(newDetail);
      if (newThread && oldThread) oldThread.replaceWith(newThread);
      updateActiveCase(caseKey);
      pushUrl(state.filter, caseKey);
    } catch (e) {
      toast(t('تعذر فتح التذكرة.', 'Could not open the case.'), 'danger');
    } finally {
      setLoading(false);
    }
  }

  /* ────────────────────── AJAX: submit any action form ────────────────────── */
  async function submitActionForm(form, triggerBtn) {
    if (!form) return false;

    // Prevent double-submission: if a request is already in flight for this
    // form, ignore the duplicate trigger. The screenshot showed the same reply
    // arriving twice (once as reply, once as note) because both submit and
    // canned-action click handlers fired in sequence.
    if (form.dataset.submitting === '1') return false;
    form.dataset.submitting = '1';

    // For reply forms, RE-READ the active reply mode at submit time so a stale
    // is_internal_note flag from a tab switch can't cause the message to be
    // saved under the wrong role.
    if (form.matches('[data-sc-reply-form]')) {
      const activeTab = form.querySelector('[data-reply-mode].is-active');
      const noteFlag = form.querySelector('[data-internal-note-input]');
      if (noteFlag && activeTab) {
        noteFlag.value = (activeTab.dataset.replyMode === 'internal') ? '1' : '0';
      }
    }

    const formData = new FormData(form);
    if (triggerBtn && triggerBtn.name) {
      formData.set(triggerBtn.name, triggerBtn.value || '');
    }
    formData.set('format', 'json');
    if (!formData.get('csrf_token')) formData.set('csrf_token', csrfToken());

    // Disable submit-type buttons during the request to defeat fast double-clicks.
    const submitButtons = Array.from(form.querySelectorAll('button[type="submit"]'));
    submitButtons.forEach((b) => { b.disabled = true; });

    setLoading(true);
    try {
      const action = form.getAttribute('action') || cfg.actionUrl;
      const res = await fetch(action, {
        method: 'POST',
        body: formData,
        headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
        credentials: 'same-origin',
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        toast(data.message || t('تعذر تنفيذ الإجراء.', 'Could not run the action.'), 'danger');
        return false;
      }
      toast(data.message || t('تم.', 'Done.'), data.category || 'success');
      // Refresh the list so KPI counts update, and reload the active case
      // panel so status/priority/assignee/messages reflect the change.
      await fetchList(state.filter);
      const caseKey = data.case_key || state.caseKey;
      if (caseKey) {
        // force reload (state.caseKey === caseKey would short-circuit loadCase)
        const previous = state.caseKey;
        state.caseKey = '';
        await loadCase(caseKey);
        if (!state.caseKey) state.caseKey = previous;
      }
      // Reset the composer if this was a reply submission
      if (form.matches('[data-sc-reply-form]')) {
        const ta = form.querySelector('[data-reply-textarea]');
        if (ta) ta.value = '';
        const fileInput = form.querySelector('input[type="file"]');
        if (fileInput) fileInput.value = '';
        const closeAfter = form.querySelector('input[name="close_after_send"]');
        if (closeAfter) closeAfter.checked = false;
      }
      return true;
    } catch (e) {
      toast(t('فشل الاتصال بالخادم.', 'Server error.'), 'danger');
      return false;
    } finally {
      setLoading(false);
      submitButtons.forEach((b) => { b.disabled = false; });
      form.dataset.submitting = '';
    }
  }

  /* ────────────────────── Event delegation ────────────────────── */
  // Filter chips and KPI cards
  root.addEventListener('click', (event) => {
    const filterEl = event.target.closest('[data-filter-target]');
    if (filterEl) {
      event.preventDefault();
      const target = filterEl.dataset.filterTarget;
      if (target && target !== state.filter) fetchList(target);
      return;
    }

    const caseLink = event.target.closest('[data-case-link]');
    if (caseLink) {
      event.preventDefault();
      const key = caseLink.dataset.caseLink;
      if (key) loadCase(key);
      return;
    }

    if (event.target.closest('[data-sc-refresh]')) {
      event.preventDefault();
      fetchList(state.filter);
      return;
    }
  });

  // Form submissions (toolbar + composer + quick-action forms)
  root.addEventListener('submit', (event) => {
    const form = event.target.closest('[data-sc-action-form], [data-sc-reply-form]');
    if (!form) return;
    event.preventDefault();
    // Identify the submit button that triggered this form, so its
    // name/value (case_action=close etc.) is included in the payload.
    const trigger = (event.submitter || form.querySelector('button[type="submit"]:focus') || form.querySelector('button[type="submit"]'));
    // Confirmation for danger actions
    if (trigger && trigger.dataset.scConfirm) {
      if (!window.confirm(trigger.dataset.scConfirm)) return;
    }
    submitActionForm(form, trigger);
  });

  /* ────────────────────── Composer reply mode tabs ────────────────────── */
  root.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-reply-mode]');
    if (!tab) return;
    const form = tab.closest('[data-sc-reply-form]');
    if (!form) return;
    event.preventDefault();
    form.querySelectorAll('[data-reply-mode]').forEach((b) => b.classList.toggle('is-active', b === tab));
    const noteFlag = form.querySelector('[data-internal-note-input]');
    if (noteFlag) noteFlag.value = (tab.dataset.replyMode === 'internal') ? '1' : '0';
    form.classList.toggle('is-internal-note', tab.dataset.replyMode === 'internal');
  });

  /* ────────────────────── Canned replies drawer ────────────────────── */
  root.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-canned-toggle]');
    if (toggle) {
      event.preventDefault();
      const drawer = toggle.closest('[data-sc-reply-form]')?.querySelector('[data-canned-drawer]');
      if (drawer) drawer.hidden = !drawer.hidden;
      return;
    }
    const close = event.target.closest('[data-canned-close]');
    if (close) {
      event.preventDefault();
      const drawer = close.closest('[data-canned-drawer]');
      if (drawer) drawer.hidden = true;
      return;
    }
    const action = event.target.closest('[data-canned-action]');
    if (!action) return;
    event.preventDefault();
    const card = action.closest('[data-canned-card]');
    const form = action.closest('[data-sc-reply-form]');
    if (!card || !form) return;
    const text = card.dataset.cannedText || '';
    const status = card.dataset.cannedStatus || '';
    const ta = form.querySelector('[data-reply-textarea]');
    if (ta) ta.value = text;
    if (status) {
      const statusSelect = form.querySelector('[data-status-select]');
      if (statusSelect) statusSelect.value = status;
    }
    const drawer = form.querySelector('[data-canned-drawer]');
    if (drawer) drawer.hidden = true;
    if (action.dataset.cannedAction === 'send') {
      const sendBtn = form.querySelector('button[name="case_action"][value="send_reply"]');
      submitActionForm(form, sendBtn);
    }
  });

  /* Inbox search (client-side over rendered cards) */
  const searchInput = root.querySelector('[data-inbox-search]');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      const query = (searchInput.value || '').trim().toLowerCase();
      root.querySelectorAll('[data-inbox-list] [data-case-link]').forEach((card) => {
        const haystack = card.dataset.caseSearch || '';
        card.style.display = (!query || haystack.indexOf(query) !== -1) ? '' : 'none';
      });
    });
  }

  /* Shortcut: Ctrl/Cmd + K focuses search */
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && (event.key === 'k' || event.key === 'K')) {
      if (!searchInput) return;
      event.preventDefault();
      searchInput.focus();
      searchInput.select();
    }
  });
})();
