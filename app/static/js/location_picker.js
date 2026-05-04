/* ════════════════════════════════════════════════════════════════════
   Solar Eye — Shared Location Picker
   ────────────────────────────────────────────────────────────────────
   Wires up any country / city / timezone trio across the site.

   Markup contract (any of the three may be missing — wiring is opt-in):
     <select data-loc-country>
       <option value="فلسطين"
               data-cities-ar='["نابلس", ...]'
               data-cities-en='["Nablus", ...]'
               data-tz="Asia/Hebron">فلسطين</option>
     </select>
     <select data-loc-city data-loc-current="<saved value>"></select>
     <select data-loc-timezone>...</select>

   Optional data attributes on the country <select>:
     data-loc-lang   "ar" | "en"   (defaults to <html lang>)

   When the country changes:
     • cities are repopulated from the chosen option's data-cities-* JSON
     • timezone auto-fills if user hasn't manually changed it (data-loc-tz-touched)

   Multiple groups on the same page work — each <select data-loc-country>
   binds to the nearest <select data-loc-city>/<select data-loc-timezone>
   inside the same <form> (or document, as a fallback).
═════════════════════════════════════════════════════════════════════ */
(function(){
  'use strict';

  function findPair(countryEl, attr){
    const form = countryEl.closest('form') || document;
    return form.querySelector('[' + attr + ']');
  }

  function lang(countryEl){
    return (countryEl.dataset.locLang
            || document.documentElement.getAttribute('lang')
            || 'ar') === 'en' ? 'en' : 'ar';
  }

  function placeholderText(isEn){
    return isEn ? '— Select city —' : '— اختر المدينة —';
  }

  function populateCities(countryEl, cityEl, preserveCurrent){
    if(!cityEl) return;
    const isEn = lang(countryEl) === 'en';
    const opt = countryEl.options[countryEl.selectedIndex];
    if(!opt || !opt.value){
      cityEl.innerHTML = '<option value="">' + placeholderText(isEn) + '</option>';
      return;
    }
    const raw = isEn ? opt.dataset.citiesEn : opt.dataset.citiesAr;
    let cities = [];
    try{ cities = JSON.parse(raw || '[]'); }catch(_){
      // Fallback: pipe-separated
      const fallback = opt.dataset.cities || '';
      cities = fallback ? fallback.split('|').filter(Boolean) : [];
    }
    const current = preserveCurrent ? (cityEl.dataset.locCurrent || cityEl.value || '') : '';
    let html = '<option value="">' + placeholderText(isEn) + '</option>';
    let matched = false;
    cities.forEach(function(c){
      const sel = (c === current) ? ' selected' : '';
      if(sel) matched = true;
      html += '<option value="' + escapeHtml(c) + '"' + sel + '>' + escapeHtml(c) + '</option>';
    });
    if(current && !matched){
      // Preserve a custom city the user typed before we became dropdowns
      html += '<option value="' + escapeHtml(current) + '" selected>' + escapeHtml(current) + ' ⚙</option>';
    }
    cityEl.innerHTML = html;
  }

  function autoTz(countryEl, tzEl){
    if(!tzEl || tzEl.dataset.locTzTouched === '1') return;
    const opt = countryEl.options[countryEl.selectedIndex];
    if(!opt) return;
    const tz = opt.dataset.tz || opt.dataset.timezone;
    if(!tz) return;
    const exists = Array.prototype.some.call(tzEl.options, function(o){ return o.value === tz; });
    if(exists) tzEl.value = tz;
  }

  function escapeHtml(s){
    return String(s).replace(/[&<>"']/g, function(ch){
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch];
    });
  }

  function wire(countryEl){
    if(countryEl.__locWired) return;
    countryEl.__locWired = true;

    const cityEl = findPair(countryEl, 'data-loc-city');
    const tzEl   = findPair(countryEl, 'data-loc-timezone');

    // Initial population — preserve saved city if it matches a known city
    populateCities(countryEl, cityEl, true);

    countryEl.addEventListener('change', function(){
      populateCities(countryEl, cityEl, false);
      autoTz(countryEl, tzEl);
    });

    if(tzEl){
      tzEl.addEventListener('change', function(){ tzEl.dataset.locTzTouched = '1'; });
    }
  }

  function wireAll(root){
    (root || document).querySelectorAll('select[data-loc-country]').forEach(wire);
  }

  // Boot
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', function(){ wireAll(); });
  } else {
    wireAll();
  }

  // Expose a re-wire hook for dynamically rendered forms
  window.SolarEyeLocationPicker = { wire: wire, wireAll: wireAll };
})();
