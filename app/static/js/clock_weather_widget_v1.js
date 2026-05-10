/* ────────────────────────────────────────────────────────────────────────────
 * Clock + Weather widget — v33-μ refinement (profile-only mode)
 * SolarDeye
 *
 * Renders a live clock (HH:MM) + weather chip (icon + temp + city) into any
 * element marked with `data-cwx`, using ONLY data the user has saved on
 * their profile:
 *
 *   <body data-user-tz="Asia/Hebron" data-user-city="Nablus" data-user-country="Palestine">
 *
 * v33-μ change vs. v1 reference:
 *   · NO browser geolocation.
 *   · NO IP-based geolocation.
 *   · NO automatic POST to /api/me/timezone (endpoint not registered).
 *   · The widget reads the profile-supplied country/city/timezone, then
 *     uses Open-Meteo geocoding (free, no key) to translate the city name
 *     into lat/lon and fetch current weather.
 *   · If profile city/timezone are missing, the widget renders an empty
 *     state and the page also shows a friendly setup hint via the
 *     `_clock_weather_bar.html` partial (server-rendered).
 *   · Open-Meteo lat/lon is cached client-side keyed by city|country so
 *     the user doesn't pay the geocoding round-trip on every page load.
 *
 * Public API (window.SolarCWX):
 *   - SolarCWX.init({ tz, city, country, lang })
 *   - SolarCWX.refreshWeather()
 *   - SolarCWX.savedTz
 * ────────────────────────────────────────────────────────────────────────── */
(function(){
  'use strict';

  // ── Lang detection ────────────────────────────────────────────────────────
  var docLang = (document.documentElement && document.documentElement.lang) || 'ar';
  var IS_EN = String(docLang).toLowerCase().indexOf('en') === 0;

  // ── WMO weather code → state lookup (matches landing.html convention) ─────
  function wmoState(code, isDay){
    if (!isDay) return 'night';
    if (code === 0) return 'sunny';
    if (code >= 1 && code <= 3) return 'cloudy';
    if (code >= 45 && code <= 48) return 'fog';
    if ((code >= 51 && code <= 57) || (code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return 'rainy';
    if ((code >= 71 && code <= 77) || (code >= 85 && code <= 86)) return 'snowy';
    if (code >= 95 && code <= 99) return 'storm';
    return 'sunny';
  }
  var STATE_META = {
    sunny:  {icon:'☀️', en:'Sunny',  ar:'مشمس'},
    cloudy: {icon:'☁️', en:'Cloudy', ar:'غائم'},
    rainy:  {icon:'🌧️', en:'Rainy',  ar:'ممطر'},
    storm:  {icon:'⛈️', en:'Storm',  ar:'عاصفة'},
    snowy:  {icon:'❄️', en:'Snowy',  ar:'ثلج'},
    fog:    {icon:'🌫️', en:'Fog',    ar:'ضباب'},
    night:  {icon:'🌙', en:'Night',  ar:'ليل'}
  };

  // ── Local cache (lat/lon only — NOT a location source) ────────────────────
  // Keyed by profileKey = "city|country" so when the user updates their
  // profile, the cache is invalidated automatically.
  var CACHE_KEY = 'solar_cwx_v33mu';
  function readCache(){
    try { return JSON.parse(localStorage.getItem(CACHE_KEY) || '{}') || {}; }
    catch(_) { return {}; }
  }
  function writeCache(patch){
    try {
      var cur = readCache();
      var next = Object.assign({}, cur, patch || {});
      localStorage.setItem(CACHE_KEY, JSON.stringify(next));
    } catch(_) {}
  }

  // ── Public state ──────────────────────────────────────────────────────────
  var state = {
    tz: null,            // IANA id (e.g. "Asia/Hebron") — from profile only
    city: '',            // saved profile city
    country: '',         // saved profile country
    lat: null,           // resolved by Open-Meteo geocoding from city+country
    lon: null,
    weather: null,       // {state, temp, code, raw}
    containers: [],
    tickHandle: null,
    refreshHandle: null
  };

  // ── DOM helpers ───────────────────────────────────────────────────────────
  function el(tag, attrs, children){
    var node = document.createElement(tag);
    if (attrs) for (var k in attrs){
      if (k === 'class') node.className = attrs[k];
      else if (k === 'text') node.textContent = attrs[k];
      else if (k === 'html') node.innerHTML = attrs[k];
      else node.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(function(c){ if (c) node.appendChild(c); });
    return node;
  }

  // ── Render a single widget container ──────────────────────────────────────
  function renderContainer(host){
    host.classList.add('cwx');
    host.innerHTML = '';
    var clock = el('span', {class:'cwx-clock', dir:'ltr', 'data-cwx-clock':'1', text:'--:--'});
    var weather = el('span', {class:'cwx-weather', 'data-cwx-weather':'1'}, [
      el('span', {class:'cwx-weather-icon', text:'☀️'}),
      el('span', {class:'cwx-weather-text', text:'—'})
    ]);
    var sep = el('span', {class:'cwx-sep', text:'·'});
    host.appendChild(clock);
    host.appendChild(sep);
    host.appendChild(weather);
    state.containers.push(host);
  }

  // ── Tick the clock for every container ───────────────────────────────────
  function paintClock(){
    if (!state.containers.length) return;
    if (!state.tz){
      // No saved timezone — keep the placeholder; the empty state is shown by
      // the server-rendered partial. We do NOT guess from the browser.
      state.containers.forEach(function(host){
        var c = host.querySelector('[data-cwx-clock]');
        if (c) c.textContent = '--:--';
      });
      return;
    }
    var now;
    try {
      var fmt = new Intl.DateTimeFormat('en-GB', {
        hour: '2-digit', minute: '2-digit', hour12: false, timeZone: state.tz
      });
      now = fmt.format(new Date());
    } catch(_) {
      // Bad/unknown timezone string — show placeholder, never browser fallback
      now = '--:--';
    }
    state.containers.forEach(function(host){
      var c = host.querySelector('[data-cwx-clock]');
      if (c) c.textContent = now;
    });
  }

  function paintWeather(){
    if (!state.containers.length) return;
    var w = state.weather;
    var stateKey = (w && w.state) || 'sunny';
    var meta = STATE_META[stateKey] || STATE_META.sunny;
    var label = (IS_EN ? meta.en : meta.ar);
    var temp = (w && typeof w.temp === 'number') ? Math.round(w.temp) + '°' : '';
    var city = state.city ? state.city : '';
    var combined = [temp, label, city].filter(Boolean).join(' · ');
    state.containers.forEach(function(host){
      host.setAttribute('data-cwx-state', stateKey);
      var ic = host.querySelector('.cwx-weather-icon');
      var tx = host.querySelector('.cwx-weather-text');
      if (ic) ic.textContent = meta.icon;
      if (tx) tx.textContent = combined || label;
    });
  }

  function paintWeatherUnavailable(){
    if (!state.containers.length) return;
    var label = IS_EN ? 'Weather unavailable' : 'الطقس غير متاح مؤقتًا';
    state.containers.forEach(function(host){
      host.setAttribute('data-cwx-state', 'cloudy');
      var ic = host.querySelector('.cwx-weather-icon');
      var tx = host.querySelector('.cwx-weather-text');
      if (ic) ic.textContent = '🌥️';
      if (tx) tx.textContent = label;
    });
  }

  // ── Open-Meteo current weather (no auth, no key) ──────────────────────────
  function fetchWeatherFor(lat, lon){
    var url = 'https://api.open-meteo.com/v1/forecast'
            + '?latitude='  + encodeURIComponent(lat)
            + '&longitude=' + encodeURIComponent(lon)
            + '&current_weather=true&timezone=auto';
    return fetch(url).then(function(r){
      if (!r.ok) throw new Error('weather_http_' + r.status);
      return r.json();
    }).then(function(j){
      if (!j || !j.current_weather) throw new Error('no_weather');
      var cw = j.current_weather;
      var stateKey = wmoState(cw.weathercode, cw.is_day === 1);
      state.weather = {state:stateKey, temp: cw.temperature, code: cw.weathercode, raw: cw};
      paintWeather();
      return j;
    });
  }

  // ── Open-Meteo geocoding for the saved profile city ───────────────────────
  // Weather lookup is by saved profile city/country only. This is not browser
  // geolocation and not IP geolocation.
  // Returns Promise<{lat, lon, name}> or rejects on no match.
  function geocodeByCity(city, country){
    if (!city) return Promise.reject(new Error('no_city'));
    var docLangShort = IS_EN ? 'en' : 'ar';
    var url = 'https://geocoding-api.open-meteo.com/v1/search'
            + '?name=' + encodeURIComponent(city)
            + '&count=8&language=' + docLangShort + '&format=json';
    return fetch(url).then(function(r){
      if (!r.ok) throw new Error('geocode_http_' + r.status);
      return r.json();
    }).then(function(j){
      var hits = (j && j.results) || [];
      if (!hits.length) throw new Error('geocode_empty');
      var pick = null;
      if (country){
        var cLow = country.toLowerCase();
        for (var i = 0; i < hits.length; i++){
          var h = hits[i];
          var hCountry = (h.country || '').toLowerCase();
          var hCode = (h.country_code || '').toLowerCase();
          if (hCountry === cLow || hCode === cLow.slice(0,2)){
            pick = h; break;
          }
          if (hCountry.indexOf(cLow) !== -1 || cLow.indexOf(hCountry) !== -1){
            if (!pick) pick = h;
          }
        }
      }
      if (!pick) pick = hits[0];
      return {lat: pick.latitude, lon: pick.longitude, name: pick.name || city};
    });
  }

  // ── Boot ──────────────────────────────────────────────────────────────────
  function boot(opts){
    opts = opts || {};
    // 1) Read profile-supplied location ONLY.
    var bodyTz      = (document.body && document.body.getAttribute('data-user-tz')) || '';
    var bodyCity    = (document.body && document.body.getAttribute('data-user-city')) || '';
    var bodyCountry = (document.body && document.body.getAttribute('data-user-country')) || '';

    state.tz      = opts.tz      || bodyTz      || null;
    state.city    = opts.city    || bodyCity    || '';
    state.country = opts.country || bodyCountry || '';

    // 2) Render every host element on the page.
    Array.prototype.slice.call(document.querySelectorAll('[data-cwx]')).forEach(renderContainer);
    if (!state.containers.length) return;

    // 3) Start the clock immediately (will paint --:-- if no timezone).
    paintClock();
    if (state.tickHandle) clearInterval(state.tickHandle);
    state.tickHandle = setInterval(paintClock, 30 * 1000);

    // 4) Without a saved city, we cannot fetch weather. Show a calm
    //    "weather unavailable" line and stop — the partial's empty state
    //    already nudges the user toward their profile.
    if (!state.city){
      paintWeatherUnavailable();
      return;
    }

    // 5) With a saved city, geocode → fetch weather. Cache lat/lon keyed by
    //    profile so it survives reloads but invalidates when the user
    //    updates their profile.
    var profileKey = (state.city + '|' + state.country).toLowerCase();
    var cached = readCache();
    var pending;
    if (cached.profileKey === profileKey && cached.lat && cached.lon){
      state.lat = cached.lat;
      state.lon = cached.lon;
      pending = fetchWeatherFor(state.lat, state.lon);
    } else {
      pending = geocodeByCity(state.city, state.country).then(function(pos){
        state.lat = pos.lat;
        state.lon = pos.lon;
        if (pos.name) state.city = pos.name;
        writeCache({lat: state.lat, lon: state.lon, city: state.city, profileKey: profileKey});
        return fetchWeatherFor(state.lat, state.lon);
      });
    }
    pending.catch(function(err){
      try { console.warn('[cwx] weather fetch failed:', err && err.message || err); } catch(_) {}
      paintWeatherUnavailable();
    });

    // 6) Refresh weather every 15 minutes if we have a resolved lat/lon.
    if (state.refreshHandle) clearInterval(state.refreshHandle);
    state.refreshHandle = setInterval(function(){
      if (state.lat && state.lon) fetchWeatherFor(state.lat, state.lon).catch(function(){});
    }, 15 * 60 * 1000);
  }

  // ── Expose ────────────────────────────────────────────────────────────────
  window.SolarCWX = {
    init: boot,
    refreshWeather: function(){
      if (state.lat && state.lon) return fetchWeatherFor(state.lat, state.lon);
      return Promise.reject(new Error('no_resolved_location'));
    },
    get savedTz(){ return state.tz; },
    _state: state
  };

  // Auto-init once the DOM is ready, picking up tz/city/country from <body>.
  function autoInit(){ boot({}); }
  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', autoInit, {once:true});
  } else {
    autoInit();
  }
})();
