
(function(){
  // ===== Step nav (visual progress as user fills sections) =====
  var steps = document.querySelectorAll('.rg50-step');
  function setStep(target){
    steps.forEach(function(s){
      var key = s.dataset.step;
      var stepIdx = ['account','location','device'].indexOf(key);
      var targetIdx = ['account','location','device'].indexOf(target);
      s.classList.toggle('active', stepIdx === targetIdx);
      s.classList.toggle('done', stepIdx < targetIdx);
    });
  }
  document.querySelectorAll('.rg50-section').forEach(function(sec){
    sec.addEventListener('focusin', function(){ setStep(sec.dataset.section); });
  });

  // ===== Password visibility toggle =====
  document.querySelectorAll('[data-toggle]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var input = document.getElementById(btn.dataset.toggle);
      if (!input) return;
      var on = (input.type === 'password');
      input.type = on ? 'text' : 'password';
      var eye = btn.querySelector('.ic-eye');
      var eyeOff = btn.querySelector('.ic-eye-off');
      if (eye && eyeOff) { eye.style.display = on ? 'none' : ''; eyeOff.style.display = on ? '' : 'none'; }
    });
  });

  // ===== Password strength meter =====
  var pw = document.getElementById('rg50Password');
  var meter = document.getElementById('rg50Strength');
  var meterLbl = meter && meter.querySelector('.lvl');
  var labels = {"0": "\u2014", "1": "\u0636\u0639\u064a\u0641\u0629", "2": "\u0645\u062a\u0648\u0633\u0637\u0629", "3": "\u062c\u064a\u062f\u0629", "4": "\u0642\u0648\u064a\u0629"};
  function scorePassword(s){
    if (!s) return 0;
    var score = 0;
    if (s.length >= 6)  score++;
    if (s.length >= 10) score++;
    if (/[A-Z]/.test(s) && /[a-z]/.test(s)) score++;
    if (/\d/.test(s) && /[^A-Za-z0-9]/.test(s)) score++;
    return Math.min(score, 4);
  }
  if (pw && meter) {
    pw.addEventListener('input', function(){
      var lvl = scorePassword(pw.value);
      meter.dataset.level = String(lvl);
      if (meterLbl) meterLbl.textContent = labels[String(lvl)] || '—';
    });
  }

  // ===== Confirm-password match =====
  var confirmEl = document.getElementById('rg50ConfirmPassword');
  var matchEl   = document.getElementById('rg50Match');
  function checkMatch(){
    if (!pw || !confirmEl || !matchEl) return;
    if (!confirmEl.value) { matchEl.classList.remove('show','good','bad'); matchEl.textContent = ''; return; }
    matchEl.classList.add('show');
    var matchText = "\u2713 \u0643\u0644\u0645\u062a\u0627 \u0627\u0644\u0645\u0631\u0648\u0631 \u0645\u062a\u0637\u0627\u0628\u0642\u062a\u0627\u0646";
    var mismatchText = "\u2715 \u0643\u0644\u0645\u062a\u0627 \u0627\u0644\u0645\u0631\u0648\u0631 \u063a\u064a\u0631 \u0645\u062a\u0637\u0627\u0628\u0642\u062a\u064a\u0646";
    if (pw.value === confirmEl.value) {
      matchEl.classList.add('good'); matchEl.classList.remove('bad');
      matchEl.textContent = matchText;
    } else {
      matchEl.classList.add('bad'); matchEl.classList.remove('good');
      matchEl.textContent = mismatchText;
    }
  }
  confirmEl && confirmEl.addEventListener('input', checkMatch);
  pw && pw.addEventListener('input', checkMatch);

  // ===== Country / city / timezone / phone-prefix sync =====
  var country     = document.getElementById('rg50Country');
  var countryCode = document.getElementById('rg50CountryCode');
  var city        = document.getElementById('rg50City');
  var tz          = document.getElementById('rg50Timezone');
  var phonePrefix = document.getElementById('rg50PhonePrefix');
  var provider    = document.getElementById('rg50Provider');
  var preview     = document.getElementById('rg50ProviderPreview');
  var providerWrap= document.getElementById('rg50ProviderWrap');
  var radios      = document.querySelectorAll('input[name="has_energy_system"]');

  function setPhonePrefix(code, dial){
    if (!phonePrefix) return;
    var wanted = dial || '';
    var found = false;
    Array.from(phonePrefix.options).forEach(function(opt){
      if ((wanted && opt.value === wanted) || (code && opt.dataset.code === code)) { opt.selected = true; found = true; }
    });
    if (!found && wanted) {
      var opt = new Option(wanted, wanted);
      opt.dataset.code = code || '';
      phonePrefix.add(opt);
      phonePrefix.value = wanted;
    }
  }

  function syncCountry(){
    var opt = country && country.selectedOptions && country.selectedOptions[0];
    if (!opt) return;
    var code = opt.dataset.code || '';
    var dial = opt.dataset.dial || '';
    var suggested = opt.dataset.timezone || '';
    if (countryCode) countryCode.value = code;
    setPhonePrefix(code, dial);
    // Only update timezone if a real suggestion exists AND the user hasn't manually changed it
    if (tz && suggested && !tz.dataset.userChanged) {
      // Verify the suggested value actually exists as an option before setting
      var tzExists = Array.from(tz.options).some(function(o){ return o.value === suggested; });
      if (tzExists) tz.value = suggested;
    }
    var selectedCity = (city && city.dataset.selected) || '';
    var cities = (opt.dataset.cities || '').split('|').filter(Boolean);
    var chooseCityLabel = "???? ???????";
    var otherCityLabel = "????? ????";
    if (city) {
      city.innerHTML = '';
      city.appendChild(new Option(chooseCityLabel, ''));
      cities.forEach(function(name){ city.appendChild(new Option(name, name)); });
      city.appendChild(new Option(otherCityLabel, '__other__'));
      if (selectedCity && Array.from(city.options).some(function(o){ return o.value === selectedCity; })) {
        city.value = selectedCity;
      }
    }
  }

  function syncProvider(){
    var opt = provider && provider.selectedOptions && provider.selectedOptions[0];
    if (!opt || !preview) return;
    preview.innerHTML = '<strong>' + opt.textContent + '</strong>'
      + '<span>' + (opt.dataset.category || '') + '</span>'
      + '<p>' + (opt.dataset.note || '') + '</p>';
  }

  function syncIntent(){
    var selected = document.querySelector('input[name="has_energy_system"]:checked');
    if (providerWrap) providerWrap.classList.toggle('is-muted', selected && selected.value === 'no');
  }

  city && city.addEventListener('change', function(){
    if (this.value === '__other__') {
      var customCityPrompt = "???? ??? ???????";
      var custom = prompt(customCityPrompt);
      if (custom && custom.trim()) {
        var opt = new Option(custom.trim(), custom.trim());
        city.add(opt, city.options[city.options.length - 1]);
        city.value = custom.trim();
      } else {
        city.value = '';
      }
    }
  });
  tz && tz.addEventListener('change', function(){ tz.dataset.userChanged = '1'; });
  country && country.addEventListener('change', function(){ if (city) city.dataset.selected = ''; syncCountry(); });
  provider && provider.addEventListener('change', syncProvider);
  radios.forEach(function(r){ r.addEventListener('change', syncIntent); });


  // ===== Wizard step navigation =====
  var panels = Array.from(document.querySelectorAll('.rg50-step-panel'));
  var stepKeys = ['account','location','device'];
  var stepPills = Array.from(document.querySelectorAll('.rg50-step'));

  function showStep(target){
    var targetIdx = stepKeys.indexOf(target);
    if (targetIdx === -1) return;
    clearStepErrors();
    panels.forEach(function(p){
      p.classList.toggle('is-active', p.dataset.step === target);
    });
    stepPills.forEach(function(s){
      var idx = stepKeys.indexOf(s.dataset.step);
      s.classList.toggle('active', idx === targetIdx);
      s.classList.toggle('done', idx < targetIdx);
      s.classList.toggle('clickable', idx < targetIdx);
    });
    // Smooth-scroll the card into view
    var card = document.querySelector('.lg50-card');
    if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function clearStepErrors(){
    document.querySelectorAll('[data-step-error]').forEach(function(box){
      box.hidden = true;
      box.textContent = '';
    });
  }

  function setStepError(stepKey, message){
    var box = document.querySelector('[data-step-error="' + stepKey + '"]');
    if (!box) return;
    box.textContent = message;
    box.hidden = false;
  }

  function validateStep(stepKey){
    var panel = document.querySelector('.rg50-step-panel[data-step="' + stepKey + '"]');
    if (!panel) return true;
    var isEnPage = (document.documentElement.lang || document.body.dataset.lang || 'ar') === 'en';
    clearStepErrors();
    var ok = true;
    var firstBad = null;
    var customMessage = '';
    panel.querySelectorAll('input[required], select[required]').forEach(function(el){
      var holder = el.closest('.rg50-field-input');
      if (!el.value || (el.type === 'email' && el.value && !el.checkValidity())) {
        ok = false;
        if (holder) holder.classList.add('error');
        if (!firstBad) firstBad = el;
      } else {
        if (holder) holder.classList.remove('error');
      }
    });
    // Step 1 — confirm password match check
    if (stepKey === 'account') {
      var p1 = document.getElementById('rg50Password');
      var p2 = document.getElementById('rg50ConfirmPassword');
      if (p1 && p2 && p1.value && p2.value && p1.value !== p2.value) {
        ok = false;
        customMessage = isEnPage
          ? 'Password confirmation does not match.'
          : 'تأكيد كلمة المرور غير مطابق.';
        var holder = p2.closest('.rg50-field-input');
        if (holder) holder.classList.add('error');
        if (!firstBad) firstBad = p2;
      }
    }
    if (!ok && firstBad) {
      firstBad.focus();
      showValidationToast(stepKey, customMessage);
    }
    return ok;
  }

  // ── Validation toast ──────────────────────────────
  var _toastTimer = null;
  function showValidationToast(stepKey, customMessage) {
    var existing = document.getElementById('rg50ValToast');
    if (existing) existing.remove();
    if (_toastTimer) clearTimeout(_toastTimer);

    var isEnPage = (document.documentElement.lang || document.body.dataset.lang || 'ar') === 'en';
    var msgs = {
      account: isEnPage
        ? 'Please fill in all required fields (username and password).'
        : 'يرجى ملء جميع الحقول المطلوبة (اسم المستخدم وكلمة المرور).',
      location: isEnPage
        ? 'Please select your country and city before continuing.'
        : 'يرجى اختيار الدولة والمدينة للمتابعة.',
      device: isEnPage
        ? 'Please complete the required fields.'
        : 'يرجى إكمال الحقول المطلوبة.'
    };
    var msg = customMessage || msgs[stepKey] || (isEnPage ? 'Please fill in all required fields.' : 'يرجى ملء الحقول المطلوبة.');
    setStepError(stepKey, msg);

    var toast = document.createElement('div');
    toast.id = 'rg50ValToast';
    toast.setAttribute('role', 'alert');
    toast.style.cssText = [
      'position:fixed','bottom:24px',isEnPage ? 'right:24px' : 'left:24px',
      'background:#ef4444','color:#fff',
      'padding:12px 18px','border-radius:12px',
      'font-size:.88rem','font-weight:600','z-index:9999',
      'box-shadow:0 6px 24px rgba(0,0,0,.25)',
      'display:flex','align-items:center','gap:8px',
      'animation:rg50ToastIn .25s ease',
      'max-width:min(360px,90vw)'
    ].join(';');
    toast.innerHTML = '<span aria-hidden="true">⚠️</span><span>' + msg + '</span>';

    // Shake animation on the Next button
    var navRow = document.querySelector('.rg50-step-panel.is-active .rg50-nav');
    if (navRow) {
      navRow.style.animation = 'none';
      navRow.offsetHeight; // reflow
      navRow.style.animation = 'rg50Shake .4s ease';
      setTimeout(function(){ navRow.style.animation = ''; }, 500);
    }

    document.body.appendChild(toast);
    _toastTimer = setTimeout(function(){
      toast.style.opacity = '0';
      toast.style.transition = 'opacity .3s';
      setTimeout(function(){ toast.remove(); }, 350);
    }, 3500);
  }

  // Inject toast + shake keyframes if not already present
  (function(){
    if (document.getElementById('rg50ToastStyle')) return;
    var s = document.createElement('style');
    s.id = 'rg50ToastStyle';
    s.textContent = '@keyframes rg50ToastIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}'
      + '@keyframes rg50Shake{0%,100%{transform:translateX(0)}20%{transform:translateX(-6px)}40%{transform:translateX(6px)}60%{transform:translateX(-4px)}80%{transform:translateX(4px)}}';
    document.head.appendChild(s);
  })();
  // ─────────────────────────────────────────────────

  document.querySelectorAll('[data-next]').forEach(function(btn){
    btn.addEventListener('click', function(){
      // current step is the panel that contains this button
      var curPanel = btn.closest('.rg50-step-panel');
      var curKey = curPanel && curPanel.dataset.step;
      if (!validateStep(curKey)) return;
      showStep(btn.dataset.next);
    });
  });
  document.querySelectorAll('[data-back]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var t = btn.dataset.back;
      if (t) showStep(t);
    });
  });
  // Clickable step pills (only for completed steps)
  stepPills.forEach(function(s){
    s.addEventListener('click', function(){
      if (s.classList.contains('clickable')) showStep(s.dataset.step);
    });
  });

  // Make sure submit only fires from step 3
  var formEl = document.getElementById('rg50Form');
  if (formEl) {
    formEl.addEventListener('submit', function(e){
      // If user pressed Enter on step 1 or 2, advance instead of submitting
      var active = document.querySelector('.rg50-step-panel.is-active');
      var key = active && active.dataset.step;
      if (key !== 'device') {
        e.preventDefault();
        var nextBtn = active && active.querySelector('[data-next]');
        if (nextBtn) nextBtn.click();
      }
    });
  }

  syncCountry();
  syncProvider();
  syncIntent();

  // Subtle parallax
  var stage = document.querySelector('.lg50-stage');
  var grid  = document.querySelector('.lg50-showcase-grid');
  if (stage && grid && window.matchMedia('(min-width:1025px)').matches) {
    stage.addEventListener('mousemove', function(e){
      var x = (e.clientX / window.innerWidth - .5) * 12;
      var y = (e.clientY / window.innerHeight - .5) * 12;
      grid.style.transform = 'translate(' + x + 'px,' + y + 'px)';
    });
  }
})();
