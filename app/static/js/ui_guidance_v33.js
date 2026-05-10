(function () {
  function isRtl() {
    return document.documentElement.dir === 'rtl' || (document.body && document.body.dir === 'rtl');
  }

  function closeAll(except) {
    document.querySelectorAll('.ui-help-bubble.is-visible').forEach(function (bubble) {
      if (bubble !== except) bubble.classList.remove('is-visible');
    });
  }

  function ensureInlineHelp(control) {
    if (!control.dataset.fieldHelp || control.dataset.guidanceHelpBound === '1') return;
    control.dataset.guidanceHelpBound = '1';
    var label = control.closest('label');
    if (!label || label.querySelector('.ui-field-help')) return;
    var help = document.createElement('small');
    help.className = 'ui-field-help';
    help.textContent = control.dataset.fieldHelp;
    label.appendChild(help);
  }

  function makeHelpButton(host) {
    if (!host.dataset.helpText && !host.dataset.help) return null;
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'ui-help';
    button.setAttribute('aria-label', isRtl() ? 'شرح' : 'Help');
    button.setAttribute('aria-expanded', 'false');
    button.textContent = '?';
    return button;
  }

  function bindHelp(host) {
    if (host.dataset.guidanceBound === '1') return;
    var text = host.dataset.helpText || host.dataset.help || '';
    if (!text) return;
    host.dataset.guidanceBound = '1';

    var interactiveHost = host.matches('button, a, [role="button"]');
    var actionHost = interactiveHost && !host.matches('.ui-help');
    var button = host.matches('.ui-help') || interactiveHost ? host : makeHelpButton(host);
    if (!button) return;
    if (!host.matches('.ui-help') && !interactiveHost) {
      var label = host.querySelector('span, h2, h3, h4, strong') || host;
      if (label && label !== host) label.classList.add('ui-label-with-help');
      label.appendChild(button);
    }
    if (interactiveHost) {
      host.classList.add('ui-guidance-trigger');
    }

    var bubbleHost = host.parentElement || document.body;
    if (bubbleHost !== document.body && window.getComputedStyle(bubbleHost).position === 'static') {
      bubbleHost.style.position = 'relative';
    }

    var bubble = document.createElement('div');
    bubble.className = 'ui-help-bubble';
    bubble.setAttribute('role', 'tooltip');
    if (host.dataset.helpTitle) {
      var title = document.createElement('strong');
      title.className = 'ui-help-title';
      title.textContent = host.dataset.helpTitle;
      bubble.appendChild(title);
    }
    var body = document.createElement('span');
    body.textContent = text;
    bubble.appendChild(body);
    bubbleHost.appendChild(bubble);

    function position() {
      var rect = button.getBoundingClientRect();
      var parentRect = bubbleHost.getBoundingClientRect();
      bubble.style.top = (rect.bottom - parentRect.top + 8) + 'px';
      if (isRtl()) {
        bubble.style.right = Math.max(0, parentRect.right - rect.right) + 'px';
        bubble.style.left = 'auto';
      } else {
        bubble.style.left = Math.max(0, rect.left - parentRect.left) + 'px';
        bubble.style.right = 'auto';
      }
    }

    function show() {
      closeAll(bubble);
      position();
      bubble.classList.add('is-visible');
      button.setAttribute('aria-expanded', 'true');
    }
    function hide() {
      bubble.classList.remove('is-visible');
      button.setAttribute('aria-expanded', 'false');
    }
    function toggle(event) {
      event.preventDefault();
      event.stopPropagation();
      if (bubble.classList.contains('is-visible')) hide();
      else show();
    }

    if (actionHost) {
      button.addEventListener('click', hide);
    } else {
      button.addEventListener('click', toggle);
    }
    button.addEventListener('focus', show);
    button.addEventListener('blur', hide);
    button.addEventListener('mouseenter', show);
    button.addEventListener('mouseleave', hide);
    button.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') hide();
    });
  }

  function boot() {
    document.querySelectorAll('[data-field-help]').forEach(ensureInlineHelp);
    document.querySelectorAll('[data-help-text], .ui-help[data-help-text]').forEach(bindHelp);
  }

  document.addEventListener('click', function (event) {
    if (!event.target.closest('.ui-help') && !event.target.closest('.ui-help-bubble')) closeAll();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') closeAll();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
  window.SDGuidance = { boot: boot };
})();
