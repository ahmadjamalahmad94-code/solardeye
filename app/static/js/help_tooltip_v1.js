/* ═══════════════════════════════════════════════════════════════════════
   help_tooltip_v1.js  —  v211 — 20260506
   Universal contextual help icons.

   Usage:
     <article class="some-card" data-help="نص الشرح هنا">...</article>

   At runtime this script auto-injects a small "?" badge in the corner of
   every element with [data-help]. Hover or click reveals a popover card
   with the explanation. Auto-positions for RTL/LTR.

   Or use directly with the <span class="help-icon" data-help="...">
   utility for inline help.
═══════════════════════════════════════════════════════════════════════ */
(function () {
  function isRtl() {
    return document.documentElement.getAttribute('dir') === 'rtl' ||
           (document.documentElement.getAttribute('lang') || '').toLowerCase().indexOf('ar') === 0;
  }

  function makeIcon(text) {
    var icon = document.createElement('span');
    icon.className = 'help-icon';
    icon.setAttribute('role', 'button');
    icon.setAttribute('aria-label', isRtl() ? 'شرح' : 'Help');
    icon.setAttribute('tabindex', '0');
    icon.dataset.help = text;
    icon.textContent = '?';
    return icon;
  }

  function makeBubble(text) {
    var bubble = document.createElement('div');
    bubble.className = 'help-bubble';
    bubble.textContent = text;
    return bubble;
  }

  function attachBubble(icon) {
    if (icon.dataset.helpBound === '1') return;
    icon.dataset.helpBound = '1';
    var text = icon.dataset.help || '';
    if (!text) return;

    // Make sure icon is positioned and parent isn't position:static
    var parent = icon.parentElement;
    if (parent) {
      var pos = window.getComputedStyle(parent).position;
      if (pos === 'static') parent.style.position = 'relative';
    }

    var bubble;
    function show() {
      if (!bubble) {
        bubble = makeBubble(text);
        // Append to icon's parent so it positions correctly
        (parent || document.body).appendChild(bubble);
      }
      bubble.classList.add('is-visible');
    }
    function hide() {
      if (bubble) bubble.classList.remove('is-visible');
    }
    function toggle() {
      if (bubble && bubble.classList.contains('is-visible')) hide();
      else show();
    }

    icon.addEventListener('mouseenter', show);
    icon.addEventListener('mouseleave', hide);
    icon.addEventListener('focus', show);
    icon.addEventListener('blur', hide);
    icon.addEventListener('click', function (e) {
      e.stopPropagation();
      toggle();
    });
    document.addEventListener('click', function (e) {
      if (bubble && bubble.classList.contains('is-visible') && !icon.contains(e.target) && !bubble.contains(e.target)) {
        hide();
      }
    });
    icon.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') hide();
    });
  }

  function autoInject() {
    // 1. Convert any inline .help-icon[data-help] (already-placed icons)
    document.querySelectorAll('.help-icon[data-help]').forEach(attachBubble);

    // 2. Auto-add a corner icon to elements that have data-help but aren't .help-icon
    document.querySelectorAll('[data-help]:not(.help-icon)').forEach(function (host) {
      if (host.dataset.helpBound === '1') return;
      host.dataset.helpBound = '1';
      var text = host.dataset.help || '';
      if (!text) return;
      // Make container position relative if needed
      if (window.getComputedStyle(host).position === 'static') {
        host.style.position = 'relative';
      }
      var icon = makeIcon(text);
      icon.classList.add('help-icon-corner');
      host.appendChild(icon);
      attachBubble(icon);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoInject);
  } else {
    autoInject();
  }
  window.SDHelp = { boot: autoInject, attach: attachBubble };
})();
