/* ════════════════════════════════════════════════════════════════════
   live_fleet_v33b.js — v33-β Live Device Rail / Fleet Switcher

   Behaviour
   ─────────
   * On chip click: optimistic UI → POST /api/fleet/select →
     GET /api/devices/<id>/live-summary (or /api/fleet/overview for
     aggregate) → apply payload to existing data-bind text slots.
   * NO DOM restructuring. NO modification of the Flow Graph SVG, paths,
     animations, or boxes. We only update text inside ``[data-bind]``
     slots that already exist on the page.
   * Falls back to plain navigation on any unexpected error or when a
     network request fails.
   * Polls /api/fleet/summary every 30s to refresh chip status dots
     and SOC. Pauses while the tab is hidden, resumes on visibility.
   * Aborts any in-flight switch when a new chip is clicked.

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

  /* CSRF token from the meta tag set by base.html — every POST sends it. */
  function csrfToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? (m.getAttribute('content') || '') : '';
  }

  /* Utility: relative timestamp helper for "last seen" tooltips. */
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

  /* Format a power value in W with one decimal — matches existing format_power. */
  function fmtW(v) {
    if (v === null || v === undefined) return '—';
    var n = Number(v);
    if (!isFinite(n)) return '—';
    return (Math.abs(n) >= 1000) ? (n / 1000).toFixed(2) + ' kW'
                                 : n.toFixed(1) + ' W';
  }

  function fmtKwh(v) {
    if (v === null || v === undefined) return '—';
    var n = Number(v);
    return isFinite(n) ? (n.toFixed(2) + ' kWh') : '—';
  }

  /* Apply a value to every element with the given data-bind key. We
     only ever touch textContent — never structure. This is the same
     contract the existing live-poll uses. */
  function applyBind(key, text) {
    var nodes = document.querySelectorAll('[data-bind="' + key + '"]');
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].textContent = (text === null || text === undefined) ? '—' : String(text);
    }
  }

  /* The controller object. */
  var liveFleet = {
    _xhr: null,
    _pollTimer: null,
    _rail: null,
    _activeDeviceId: null,
    _aggregateMode: false,

    init: function () {
      this._rail = document.querySelector('[data-live-fleet-rail]');
      if (!this._rail) return;          // page has 0 or 1 device — rail not rendered

      var self = this;
      var chips = this._rail.querySelectorAll('[data-fleet-chip]');
      for (var i = 0; i < chips.length; i++) {
        chips[i].addEventListener('click', function (e) {
          self._onChipClick(e, this);
        });
      }

      // Read current state from the DOM (server-rendered)
      var active = this._rail.querySelector('[data-fleet-chip].is-active');
      if (active) {
        var did = active.getAttribute('data-fleet-chip');
        if (did === '__all__') { this._aggregateMode = true; this._activeDeviceId = null; }
        else { this._aggregateMode = false; this._activeDeviceId = parseInt(did, 10); }
      }

      // Initial summary fetch + polling (paused when tab hidden)
      this.refreshRail();
      this._startPolling();

      document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'hidden') self._stopPolling();
        else { self.refreshRail(); self._startPolling(); }
      });
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

    _onChipClick: function (e, chip) {
      // Modifier keys / middle click → let the browser do its thing
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1) return;
      e.preventDefault();
      var raw = chip.getAttribute('data-fleet-chip');
      var deviceId = (raw === '__all__') ? '__all__' : parseInt(raw, 10);
      this.switch(deviceId, chip);
    },

    switch: function (deviceId, chipEl) {
      var self = this;
      var rail = this._rail;
      if (!rail) return;

      // Cancel any previous in-flight switch
      if (this._xhr) {
        try { this._xhr.abort(); } catch (e) {}
        this._xhr = null;
      }

      // Optimistic UI
      rail.classList.add('is-swapping');
      var chips = rail.querySelectorAll('[data-fleet-chip]');
      for (var i = 0; i < chips.length; i++) chips[i].classList.remove('is-pending');
      if (chipEl) chipEl.classList.add('is-pending');

      // POST /api/fleet/select
      var selectUrl = rail.getAttribute('data-select-url');
      var ctrl = ('AbortController' in window) ? new AbortController() : null;
      this._xhr = ctrl;

      var fetchOpts = {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
          'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({ device_id: deviceId })
      };
      if (ctrl) fetchOpts.signal = ctrl.signal;

      fetch(selectUrl, fetchOpts).then(function (r) {
        if (!r.ok) throw new Error('select failed: ' + r.status);
        return r.json();
      }).then(function (data) {
        if (!data || !data.ok) throw new Error('select returned non-ok');
        self._aggregateMode = !!data.aggregate;
        self._activeDeviceId = self._aggregateMode ? null : (data.device_id || null);
        return self._fetchActivePayload();
      }).then(function (payload) {
        self._applyPayload(payload);
        self._markActiveChip(deviceId);
        self._announce(deviceId);
        self._updateUrl(deviceId);
        self.refreshRail();
      }).catch(function (err) {
        // Network or server error → fall back to navigation
        if (err && err.name === 'AbortError') return;
        if (chipEl && chipEl.href) {
          window.location.href = chipEl.href;
        } else if (typeof console !== 'undefined' && console.warn) {
          console.warn('[liveFleet] switch failed, no fallback URL', err);
        }
      }).then(function () {
        rail.classList.remove('is-swapping');
        for (var j = 0; j < chips.length; j++) chips[j].classList.remove('is-pending');
        self._xhr = null;
      });
    },

    _fetchActivePayload: function () {
      var rail = this._rail;
      if (this._aggregateMode) {
        return fetch(rail.getAttribute('data-overview-url'), {credentials: 'same-origin'})
          .then(function (r) { if (!r.ok) throw new Error('overview ' + r.status); return r.json(); });
      }
      var base = rail.getAttribute('data-live-summary-base') || '/api/devices/';
      var url = base + this._activeDeviceId + '/live-summary';
      return fetch(url, {credentials: 'same-origin'})
        .then(function (r) { if (!r.ok) throw new Error('live-summary ' + r.status); return r.json(); });
    },

    _applyPayload: function (p) {
      if (!p || !p.ok) return;
      // Aggregate-overview shape
      if (p.aggregate_mode && p.combined) {
        var c = p.combined;
        applyBind('latest.solar_power',       fmtW(c.solar_power));
        applyBind('latest.solar_power_short', fmtW(c.solar_power));
        applyBind('latest.home_load',         fmtW(c.home_load));
        applyBind('latest.home_load_short',   fmtW(c.home_load));
        applyBind('latest.grid_power',        fmtW(c.grid_power));
        applyBind('latest.grid_power_short',  fmtW(c.grid_power));
        // Aggregate has no single battery SOC — leave the existing slot
        // showing whatever the page rendered. Do NOT overwrite battery
        // data-bind slots in aggregate.
        return;
      }
      // Single-device shape
      if (p.has_reading && p.reading) {
        var r = p.reading;
        applyBind('latest.solar_power',        fmtW(r.solar_power));
        applyBind('latest.solar_power_short',  fmtW(r.solar_power));
        applyBind('latest.home_load',          fmtW(r.home_load));
        applyBind('latest.home_load_short',    fmtW(r.home_load));
        applyBind('latest.grid_power',         fmtW(r.grid_power));
        applyBind('latest.grid_power_short',   fmtW(r.grid_power));
        if (r.battery_soc !== null && r.battery_soc !== undefined) {
          applyBind('battery.soc_pct',   r.battery_soc);
          applyBind('battery.soc_label', r.battery_soc + '%');
        }
        if (r.battery_power !== null && r.battery_power !== undefined) {
          applyBind('battery.flow_w', fmtW(Math.abs(r.battery_power)));
          if (r.battery_power > 0)      applyBind('battery.mode_label', 'Charging');
          else if (r.battery_power < 0) applyBind('battery.mode_label', 'Discharging');
          else                          applyBind('battery.mode_label', '—');
        }
      }
    },

    _markActiveChip: function (deviceId) {
      if (!this._rail) return;
      var chips = this._rail.querySelectorAll('[data-fleet-chip]');
      for (var i = 0; i < chips.length; i++) {
        var c = chips[i];
        var raw = c.getAttribute('data-fleet-chip');
        var match = (deviceId === '__all__' && raw === '__all__') ||
                    (deviceId !== '__all__' && parseInt(raw, 10) === deviceId);
        if (match) {
          c.classList.add('is-active');
          c.setAttribute('aria-selected', 'true');
        } else {
          c.classList.remove('is-active');
          c.setAttribute('aria-selected', 'false');
        }
      }
    },

    _announce: function (deviceId) {
      if (!this._rail) return;
      var live = this._rail.querySelector('[data-fleet-aria-live]');
      if (!live) return;
      if (deviceId === '__all__') {
        live.textContent = 'Switched to all devices (aggregate view).';
      } else {
        var chip = this._rail.querySelector('[data-fleet-chip="' + deviceId + '"]');
        var name = chip ? (chip.querySelector('strong') || {}).textContent || ('device ' + deviceId) : ('device ' + deviceId);
        live.textContent = 'Switched to ' + name + '.';
      }
    },

    _updateUrl: function (deviceId) {
      if (!('history' in window) || !history.replaceState) return;
      try {
        var u = new URL(window.location.href);
        u.searchParams.delete('selected_device_id');
        history.replaceState(null, '', u.toString());
      } catch (e) {}
    },

    refreshRail: function () {
      if (!this._rail || document.visibilityState === 'hidden') return;
      var url = this._rail.getAttribute('data-summary-url');
      if (!url) return;
      var self = this;
      fetch(url, {credentials: 'same-origin'}).then(function (r) {
        if (!r.ok) return null;
        return r.json();
      }).then(function (payload) {
        if (!payload || !payload.ok) return;
        self._renderRailSummary(payload);
      }).catch(function () { /* swallow — polling is best-effort */ });
    },

    _renderRailSummary: function (p) {
      if (!this._rail) return;
      var devices = p.devices || [];
      for (var i = 0; i < devices.length; i++) {
        var d = devices[i];
        var chip = this._rail.querySelector('[data-fleet-chip="' + d.id + '"]');
        if (!chip) continue;
        // Status dot
        var dot = chip.querySelector('[data-fleet-chip-status]');
        if (dot) dot.setAttribute('data-fleet-chip-status', d.status || 'offline');
        // SOC + provider line
        var soc = chip.querySelector('[data-fleet-chip-soc]');
        if (soc) {
          if (d.battery_soc !== null && d.battery_soc !== undefined) {
            soc.textContent = '🔋 ' + d.battery_soc + '%';
          } else {
            soc.textContent = '—';
          }
        }
        // Alerts badge
        var alerts = chip.querySelector('[data-fleet-chip-alerts]');
        if (alerts) {
          var n = parseInt(d.alerts_count || 0, 10);
          if (n > 0) { alerts.textContent = String(Math.min(n, 99)); alerts.hidden = false; }
          else alerts.hidden = true;
        }
        // Tooltip with last update
        if (d.last_update_iso) {
          chip.setAttribute('title', 'last update: ' + relTime(d.last_update_iso) + ' ago');
        }
      }
    }
  };

  // Boot when DOM ready (defer attribute already ensures parsing complete)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      try { liveFleet.init(); } catch (e) { console && console.warn && console.warn('[liveFleet] init', e); }
    });
  } else {
    try { liveFleet.init(); } catch (e) { console && console.warn && console.warn('[liveFleet] init', e); }
  }

  window.liveFleet = liveFleet;
})();
