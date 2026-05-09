/* ════════════════════════════════════════════════════════════════════
   live_fleet_v33b.js — v33-β Live Device Rail / Fleet Switcher

   Behaviour
   ─────────
   * Click on any chip lets the browser navigate via the chip's
     <a href="?selected_device_id=N&lang=…"> link. The server-side
     before_request hook in services/device_context updates session
     and persists user.preferred_device_id, then 302-redirects so the
     entire page re-renders with the new device. This guarantees that
     EVERY device-scoped value on the page (label, hero, KPIs, Flow
     Graph data-bind values, predictions, weather, alerts) matches
     the newly-selected device atomically.
   * Polls /api/fleet/summary every 30s to refresh chip status dots,
     SOC chips, and alert badges. Pauses while the tab is hidden,
     resumes on visibility.
   * Tiny carousel UX: chevron buttons + scroll progress bar.

   Locked components NOT touched:
     - <section class="d40-card d40-flow-card span-full"> and its children
     - All .flow-svg / .flow-box / .track-* / .dot-* / .energy-* selectors
     - The existing _device_switcher.html partial
     - All admin templates and CSS

   Public surface: window.liveFleet
═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  var POLL_DEFAULT_MS = 30000;

  function csrfToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? (m.getAttribute('content') || '') : '';
  }

  function relTime(iso) {
    if (!iso) return '';
    try {
      var t = new Date(iso).getTime();
      var s = Math.max(0, Math.round((Date.now() - t) / 1000));
      if (s < 60)   return s + 's';
      if (s < 3600) return Math.round(s / 60) + 'm';
      if (s < 86400) return Math.round(s / 3600) + 'h';
      return Math.round(s / 86400) + 'd';
    } catch (e) { return ''; }
  }

  var liveFleet = {
    _xhr: null,
    _pollTimer: null,
    _rail: null,
    _activeDeviceId: null,
    _aggregateMode: false,
    _updateScroll: null,

    init: function () {
      this._rail = document.querySelector('[data-live-fleet-rail]');
      if (!this._rail) return;

      var self = this;
      var chips = this._rail.querySelectorAll('[data-fleet-chip]');
      for (var i = 0; i < chips.length; i++) {
        chips[i].addEventListener('click', function (e) {
          self._onChipClick(e, this);
        });
      }

      var active = this._rail.querySelector('[data-fleet-chip].is-active');
      if (active) {
        var did = active.getAttribute('data-fleet-chip');
        if (did === '__all__') { this._aggregateMode = true; this._activeDeviceId = null; }
        else { this._aggregateMode = false; this._activeDeviceId = parseInt(did, 10); }
      }

      this.refreshRail();
      this._startPolling();

      document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'hidden') self._stopPolling();
        else { self.refreshRail(); self._startPolling(); }
      });

      this._initScrollControls();
    },

    /* Wire chevron buttons + scroll progress bar. RTL-aware. */
    _initScrollControls: function () {
      var rail  = this._rail;
      var track = rail.querySelector('.lfr-track');
      if (!track) return;
      var prev  = rail.querySelector('.lfr-nav-prev');
      var next  = rail.querySelector('.lfr-nav-next');
      var bar   = rail.querySelector('.lfr-progress-bar');
      var self  = this;

      function isRTL() {
        try { return getComputedStyle(track).direction === 'rtl'; }
        catch (e) { return document.documentElement.dir === 'rtl'; }
      }

      function update() {
        var max = track.scrollWidth - track.clientWidth;
        var hasOverflow = max > 1;
        if (prev) prev.hidden = !hasOverflow;
        if (next) next.hidden = !hasOverflow;
        if (!hasOverflow) {
          if (bar) bar.style.width = '100%';
          return;
        }
        var cur = Math.abs(track.scrollLeft);
        var pct = Math.max(0, Math.min(1, cur / max));
        if (bar) bar.style.width = (Math.max(15, pct * 100)).toFixed(1) + '%';
        if (prev) {
          if (pct < 0.02) prev.setAttribute('disabled', '');
          else            prev.removeAttribute('disabled');
        }
        if (next) {
          if (pct > 0.98) next.setAttribute('disabled', '');
          else            next.removeAttribute('disabled');
        }
      }

      function scrollByDir(dir) {
        var card = track.querySelector('[data-fleet-chip]');
        var step = card ? (card.getBoundingClientRect().width + 10) * 1.5 : 220;
        var rtl  = isRTL();
        var delta = (rtl ? -1 : 1) * dir * step;
        track.scrollBy({ left: delta, behavior: 'smooth' });
      }

      track.addEventListener('scroll', update, { passive: true });
      window.addEventListener('resize', update);
      if (prev) prev.addEventListener('click', function () { scrollByDir(-1); });
      if (next) next.addEventListener('click', function () { scrollByDir(1); });

      if (window.requestAnimationFrame) {
        requestAnimationFrame(function () { requestAnimationFrame(update); });
      } else {
        setTimeout(update, 32);
      }
      self._updateScroll = update;
    },

    _startPolling: function () {
      var self = this;
      this._stopPolling();
      var ms = POLL_DEFAULT_MS;
      try {
        var raw = this._rail.getAttribute('data-poll-seconds');
        if (raw) ms = Math.max(parseInt(raw, 10) * 1000, 5000);
      } catch (e) {}
      this._pollTimer = setInterval(function () { self.refreshRail(); }, ms);
    },

    _stopPolling: function () {
      if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = null; }
    },

    /* Click handler: do NOT preventDefault. Let the <a href> navigate
       so the server can re-render the entire page consistently. We add
       an optimistic class for the brief visual flash before the new
       page paints. */
    _onChipClick: function (e, chip) {
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return;
      var rail = this._rail;
      if (rail) rail.classList.add('is-swapping');
      var chips = rail ? rail.querySelectorAll('[data-fleet-chip]') : [];
      for (var i = 0; i < chips.length; i++) chips[i].classList.remove('is-pending');
      if (chip) chip.classList.add('is-pending');
      // Cancel polling so the abandoned page can't race the new render.
      if (this._xhr) { try { this._xhr.abort(); } catch (e2) {} this._xhr = null; }
      this._stopPolling();
      // Browser will follow chip.href — full reload, server-side render.
    },

    /* Public switch() — kept for backward compatibility with any caller
       that wants to switch programmatically (e.g. window.liveFleet.switch).
       Delegates to a navigation; consistency is the priority. */
    switch: function (deviceId, chipEl) {
      if (chipEl && chipEl.href) {
        window.location.href = chipEl.href;
      } else {
        var lang = document.documentElement.getAttribute('lang') || 'ar';
        window.location.href = '?selected_device_id=' + encodeURIComponent(deviceId) + '&lang=' + encodeURIComponent(lang);
      }
    },

    refreshRail: function () {
      if (!this._rail || document.visibilityState === 'hidden') return;
      var url = this._rail.getAttribute('data-summary-url');
      if (!url) return;
      var self = this;
      var ctrl = ('AbortController' in window) ? new AbortController() : null;
      this._xhr = ctrl;
      var opts = { credentials: 'same-origin' };
      if (ctrl) opts.signal = ctrl.signal;
      fetch(url, opts).then(function (r) {
        if (!r.ok) return null;
        return r.json();
      }).then(function (payload) {
        if (!payload || !payload.ok) return;
        self._renderRailSummary(payload);
      }).catch(function () { /* swallow */ })
        .then(function () { self._xhr = null; });
    },

    _renderRailSummary: function (p) {
      if (!this._rail) return;
      if (this._updateScroll) {
        try { this._updateScroll(); } catch (e) {}
      }
      var devices = p.devices || [];
      for (var i = 0; i < devices.length; i++) {
        var d = devices[i];
        var chip = this._rail.querySelector('[data-fleet-chip="' + d.id + '"]');
        if (!chip) continue;
        var dot = chip.querySelector('[data-fleet-chip-status]');
        if (dot) dot.setAttribute('data-fleet-chip-status', d.status || 'offline');
        var soc = chip.querySelector('[data-fleet-chip-soc]');
        if (soc) {
          if (d.battery_soc !== null && d.battery_soc !== undefined) {
            soc.textContent = d.battery_soc + '%';
          } else {
            soc.textContent = '—';
          }
        }
        var alerts = chip.querySelector('[data-fleet-chip-alerts]');
        if (alerts) {
          var n = parseInt(d.alerts_count || 0, 10);
          if (n > 0) { alerts.textContent = String(Math.min(n, 99)); alerts.hidden = false; }
          else alerts.hidden = true;
        }
        if (d.last_update_iso) {
          chip.setAttribute('title', 'last update: ' + relTime(d.last_update_iso) + ' ago');
        }
      }
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      try { liveFleet.init(); } catch (e) { console && console.warn && console.warn('[liveFleet] init', e); }
    });
  } else {
    try { liveFleet.init(); } catch (e) { console && console.warn && console.warn('[liveFleet] init', e); }
  }

  window.liveFleet = liveFleet;
})();
