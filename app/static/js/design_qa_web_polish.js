/* ════════════════════════════════════════════════════════════════════════
   design_qa_web_polish.js — v37 progressive UI enhancements
   Web-only. No data mutation. No fetch. No backend or API calls.

   Each enhancement is a no-op if its target DOM isn't present, so this
   file is safe to ship alongside the existing showcase template. Once
   Codex adds the `.dqv37-*` audit markup, these handlers will light up.

   Enhancements (progressive, all optional):
     1. Section collapse/expand          — click .dqv37-section-head
     2. Severity filter chips            — click .dqv37-filter-chip
     3. Sticky section nav scroll-to     — click .dqv37-nav a
     4. Copy filename/route to clipboard — click .dqv37-code-pill[data-copy]
     5. Mark "عرض" buttons with no href  — auto-add .is-disabled

   All handlers are guarded; if a selector returns nothing, the handler
   silently returns. The page must remain fully functional without JS.
   ════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // Helpers ------------------------------------------------------------
  function $$(selector, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(selector));
  }

  function setActive(chips, target) {
    chips.forEach(function (chip) {
      if (chip === target) {
        chip.classList.add('is-active');
        chip.setAttribute('aria-selected', 'true');
      } else {
        chip.classList.remove('is-active');
        chip.setAttribute('aria-selected', 'false');
      }
    });
  }

  // 1. Section collapse/expand ----------------------------------------
  function bindCollapsibleSections() {
    var heads = $$('.dqv37-section-head');
    if (!heads.length) return;
    heads.forEach(function (head) {
      // Idempotent — don't bind twice on hot-reload.
      if (head.dataset.dqv37CollapseBound === '1') return;
      head.dataset.dqv37CollapseBound = '1';
      head.setAttribute('role', 'button');
      head.setAttribute('tabindex', '0');
      var section = head.closest('.dqv37-section');
      if (!section) return;
      function toggle() {
        section.classList.toggle('is-collapsed');
        var expanded = !section.classList.contains('is-collapsed');
        head.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      }
      head.setAttribute('aria-expanded', section.classList.contains('is-collapsed') ? 'false' : 'true');
      head.addEventListener('click', function (event) {
        // Don't toggle when the click came from the View button or a copy pill.
        if (event.target.closest('.dqv37-view-btn, .dqv37-code-pill')) return;
        toggle();
      });
      head.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          toggle();
        }
      });
    });
  }

  // 2. Severity filter chips ------------------------------------------
  function bindSeverityFilters() {
    var sections = $$('.dqv37-section');
    if (!sections.length) return;
    sections.forEach(function (section) {
      var chips = $$('.dqv37-filter-chip[data-dqv37-filter]', section);
      var rows = $$('.dqv37-row', section);
      if (!chips.length || !rows.length) return;

      function apply(filter) {
        var anyVisible = false;
        rows.forEach(function (row) {
          var severity = row.getAttribute('data-severity') || '';
          var show = (filter === 'all') ? true : (severity === filter);
          row.hidden = !show;
          if (show) anyVisible = true;
        });
        // Toggle an empty-state sibling if the consumer provided one.
        var empty = section.querySelector('.dqv37-empty.dqv37-empty-filtered');
        if (empty) empty.hidden = anyVisible;
      }

      chips.forEach(function (chip) {
        if (chip.dataset.dqv37FilterBound === '1') return;
        chip.dataset.dqv37FilterBound = '1';
        chip.addEventListener('click', function () {
          setActive(chips, chip);
          apply(chip.getAttribute('data-dqv37-filter') || 'all');
        });
      });

      // Initial paint — respect whichever chip is `.is-active`, otherwise "all".
      var activeChip = chips.find(function (c) { return c.classList.contains('is-active'); }) || chips[0];
      if (activeChip) apply(activeChip.getAttribute('data-dqv37-filter') || 'all');
    });
  }

  // 3. Sticky nav active state + smooth scroll -------------------------
  function bindNav() {
    var navLinks = $$('.dqv37-nav a[href^="#"]');
    if (!navLinks.length) return;
    navLinks.forEach(function (link) {
      if (link.dataset.dqv37NavBound === '1') return;
      link.dataset.dqv37NavBound = '1';
      link.addEventListener('click', function (event) {
        var hash = link.getAttribute('href') || '';
        if (!hash || hash === '#') return;
        var target = document.querySelector(hash);
        if (!target) return;
        event.preventDefault();
        // Expand the section if it's collapsed so the scroll target is visible.
        if (target.classList.contains('dqv37-section') && target.classList.contains('is-collapsed')) {
          target.classList.remove('is-collapsed');
          var head = target.querySelector('.dqv37-section-head');
          if (head) head.setAttribute('aria-expanded', 'true');
        }
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        navLinks.forEach(function (l) { l.classList.remove('is-active'); });
        link.classList.add('is-active');
      });
    });

    // Highlight the nearest section while scrolling. Uses IntersectionObserver
    // if available; otherwise leaves the manual click-to-set behavior intact.
    if (!('IntersectionObserver' in window)) return;
    var sections = navLinks
      .map(function (l) { return document.querySelector(l.getAttribute('href')); })
      .filter(Boolean);
    if (!sections.length) return;
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        var id = entry.target.id;
        if (!id) return;
        navLinks.forEach(function (l) {
          l.classList.toggle('is-active', l.getAttribute('href') === '#' + id);
        });
      });
    }, { rootMargin: '-30% 0px -60% 0px', threshold: 0 });
    sections.forEach(function (s) { io.observe(s); });
  }

  // 4. Copy-to-clipboard on code pills --------------------------------
  function bindCopyPills() {
    var pills = $$('.dqv37-code-pill[data-copy]');
    if (!pills.length) return;
    pills.forEach(function (pill) {
      if (pill.dataset.dqv37CopyBound === '1') return;
      pill.dataset.dqv37CopyBound = '1';
      pill.setAttribute('role', 'button');
      pill.setAttribute('tabindex', '0');
      pill.setAttribute('aria-label', pill.getAttribute('aria-label') || 'Copy');
      pill.title = pill.title || 'انقر للنسخ';

      function flash() {
        pill.classList.add('is-copied');
        setTimeout(function () { pill.classList.remove('is-copied'); }, 1100);
      }

      function copy() {
        var text = pill.getAttribute('data-copy') || pill.textContent || '';
        if (!text) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(flash, function () { /* swallow */ });
          return;
        }
        // Legacy fallback — execCommand is deprecated but still works on
        // older browsers/iframes where clipboard API is blocked.
        try {
          var ta = document.createElement('textarea');
          ta.value = text;
          ta.setAttribute('readonly', '');
          ta.style.position = 'absolute';
          ta.style.left = '-9999px';
          document.body.appendChild(ta);
          ta.select();
          document.execCommand('copy');
          document.body.removeChild(ta);
          flash();
        } catch (_) { /* silent */ }
      }

      pill.addEventListener('click', function (event) {
        event.preventDefault();
        copy();
      });
      pill.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          copy();
        }
      });
    });
  }

  // 5. Auto-disable View buttons that lack a real href ----------------
  function markEmptyViewButtons() {
    var btns = $$('.dqv37-view-btn');
    if (!btns.length) return;
    btns.forEach(function (btn) {
      if (btn.tagName === 'A') {
        var href = btn.getAttribute('href') || '';
        if (!href || href === '#' || href === '#!') {
          btn.classList.add('is-disabled');
          btn.setAttribute('aria-disabled', 'true');
          btn.removeAttribute('href');
        }
      } else if (btn.disabled) {
        btn.classList.add('is-disabled');
      }
    });
  }

  // Boot --------------------------------------------------------------
  function boot() {
    try { bindCollapsibleSections(); } catch (_) {}
    try { bindSeverityFilters();    } catch (_) {}
    try { bindNav();                 } catch (_) {}
    try { bindCopyPills();           } catch (_) {}
    try { markEmptyViewButtons();   } catch (_) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }

  // Expose a tiny re-init hook in case the audit content is re-rendered
  // dynamically by a future enhancement. No data mutation here.
  window.SolarDesignQAPolish = { rebind: boot };
})();
