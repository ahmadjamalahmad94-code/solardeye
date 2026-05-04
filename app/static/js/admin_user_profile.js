/* ════════════════════════════════════════════════════════════════════
   Admin User Profile — Tab switching without page reload
   Pure DOM toggling (all panes already rendered, just show/hide)
═════════════════════════════════════════════════════════════════════ */
(function(){
  const root = document.querySelector('.up-page');
  if(!root) return;

  function activate(tab){
    // Toggle tab buttons
    root.querySelectorAll('[data-up-tab-btn]').forEach(btn => {
      const isActive = btn.dataset.upTabBtn === tab;
      btn.classList.toggle('is-active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    // Toggle panes
    root.querySelectorAll('[data-up-pane]').forEach(pane => {
      if(pane.dataset.upPane === tab){
        pane.removeAttribute('hidden');
      } else {
        pane.setAttribute('hidden', '');
      }
    });
    root.dataset.upTab = tab;
    // Update URL without reload
    try{
      const url = new URL(window.location.href);
      url.searchParams.set('tab', tab);
      window.history.replaceState({}, '', url.toString());
    }catch(_){}
    // Smooth scroll to top of pane on small screens
    if(window.innerWidth < 980){
      const pane = root.querySelector(`[data-up-pane="${tab}"]`);
      if(pane) pane.scrollIntoView({behavior:'smooth', block:'start'});
    }
  }

  // Click handler
  root.addEventListener('click', e => {
    const btn = e.target.closest('[data-up-tab-btn]');
    if(!btn) return;
    e.preventDefault();
    activate(btn.dataset.upTabBtn);
  });

  // Browser back/forward
  window.addEventListener('popstate', () => {
    const tab = new URL(window.location.href).searchParams.get('tab') || 'profile';
    activate(tab);
  });

  // If forms inside panes redirect back here, ensure correct tab is shown on load
  const initial = new URL(window.location.href).searchParams.get('tab') || 'profile';
  if(root.dataset.upTab !== initial) activate(initial);
})();

/* ════════════════════════════════════════════════════════════════════
   Country/City linked dropdowns + auto-timezone
   - When country changes, repopulate cities from data attribute
   - Auto-set timezone if user hasn't manually changed it
═════════════════════════════════════════════════════════════════════ */
(function(){
  const countryEl = document.getElementById('prof-country');
  const cityEl    = document.getElementById('prof-city');
  const tzEl      = document.getElementById('prof-timezone');
  if(!countryEl || !cityEl) return;

  const isEn = (document.documentElement.getAttribute('lang') || 'ar') === 'en';
  const placeholder = isEn ? '— Select city —' : '— اختر المدينة —';

  function populateCities(countryOption, preserveCity){
    if(!countryOption){
      cityEl.innerHTML = `<option value="">${placeholder}</option>`;
      return;
    }
    const raw = isEn ? countryOption.dataset.citiesEn : countryOption.dataset.citiesAr;
    let cities = [];
    try{ cities = JSON.parse(raw || '[]'); }catch(_){ cities = []; }
    const current = preserveCity || cityEl.dataset.current || '';
    let html = `<option value="">${placeholder}</option>`;
    let matched = false;
    cities.forEach(c => {
      const sel = (c === current) ? 'selected' : '';
      if(sel) matched = true;
      html += `<option value="${c}" ${sel}>${c}</option>`;
    });
    // If the saved city isn't in the list, keep it as a custom option so it's not lost
    if(current && !matched){
      html += `<option value="${current}" selected>${current} ⚙</option>`;
    }
    cityEl.innerHTML = html;
  }

  function autoSetTimezone(countryOption){
    if(!tzEl || !countryOption) return;
    if(tzEl.dataset.userTouched === '1') return;
    const tz = countryOption.dataset.tz;
    if(!tz) return;
    // Only flip if the new tz exists in the dropdown
    const exists = Array.from(tzEl.options).some(o => o.value === tz);
    if(exists) tzEl.value = tz;
  }

  // Initial population based on currently selected country
  const initialOption = countryEl.options[countryEl.selectedIndex];
  if(initialOption && initialOption.value) populateCities(initialOption, cityEl.dataset.current);

  countryEl.addEventListener('change', () => {
    const opt = countryEl.options[countryEl.selectedIndex];
    populateCities(opt, '');
    autoSetTimezone(opt);
  });

  if(tzEl){
    tzEl.addEventListener('change', () => { tzEl.dataset.userTouched = '1'; });
  }
})();

/* ════════════════════════════════════════════════════════════════════
   Subscription tab — quick "extend +N days" buttons
   Updates the End date field by N days (relative to current end date or today)
═════════════════════════════════════════════════════════════════════ */
(function(){
  const buttons = document.querySelectorAll('[data-extend-days]');
  const endInput = document.getElementById('sub-end-date');
  if(!buttons.length || !endInput) return;

  function pad(n){ return n < 10 ? '0' + n : '' + n; }
  function fmt(d){ return d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate()); }

  buttons.forEach(function(btn){
    btn.addEventListener('click', function(){
      const days = parseInt(btn.dataset.extendDays, 10) || 0;
      let base;
      if(endInput.value){
        base = new Date(endInput.value + 'T00:00:00');
        if(isNaN(base.getTime())) base = new Date();
      } else {
        base = new Date();
      }
      base.setDate(base.getDate() + days);
      endInput.value = fmt(base);
      // Visual feedback
      endInput.style.transition = 'background-color .25s';
      endInput.style.backgroundColor = '#ecfdf5';
      setTimeout(function(){ endInput.style.backgroundColor = ''; }, 600);
      // Focus + scroll into view so the user sees the change
      endInput.scrollIntoView({behavior:'smooth', block:'center'});
    });
  });
})();
