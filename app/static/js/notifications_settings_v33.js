(function () {
  function openTarget(hash) {
    if (!hash || hash.length < 2) return;
    var target = document.querySelector(hash);
    if (!target) return;
    if (target.tagName && target.tagName.toLowerCase() === 'details') {
      target.open = true;
    }
  }

  function closestField(input) {
    return input ? input.closest('.ns-field') : null;
  }

  function syncWindowField(field) {
    var hidden = field.querySelector('[data-window-value]');
    var mode = field.querySelector('[data-window-mode]');
    var time = field.querySelector('[data-window-time]');
    if (!hidden || !mode || !time) return;
    if (mode.value === 'fixed') {
      time.disabled = false;
      time.classList.remove('muted');
      hidden.value = time.value || hidden.value || '08:00';
    } else {
      time.disabled = true;
      time.classList.add('muted');
      hidden.value = mode.value;
    }
  }

  function initWindowFields(root) {
    root.querySelectorAll('.ns-window-field').forEach(function (field) {
      var hidden = field.querySelector('[data-window-value]');
      var mode = field.querySelector('[data-window-mode]');
      var time = field.querySelector('[data-window-time]');
      if (!hidden || !mode || !time) return;
      var current = (hidden.value || '').trim();
      if (current === 'sunrise' || current === 'sunset') {
        mode.value = current;
      } else {
        mode.value = 'fixed';
        if (current) time.value = current;
      }
      mode.addEventListener('change', function () { syncWindowField(field); });
      time.addEventListener('input', function () { syncWindowField(field); });
      syncWindowField(field);
    });
  }

  function parseHours(value) {
    return (value || '')
      .split(',')
      .map(function (item) { return item.trim(); })
      .filter(Boolean);
  }

  function syncHourButtons(field) {
    var input = field.querySelector('[data-hours-value]');
    if (!input) return;
    var selected = parseHours(input.value);
    field.querySelectorAll('[data-hour]').forEach(function (button) {
      button.classList.toggle('active', selected.indexOf(button.dataset.hour) !== -1);
    });
  }

  function initHourPickers(root) {
    root.querySelectorAll('.ns-hours-field').forEach(function (field) {
      var input = field.querySelector('[data-hours-value]');
      if (!input) return;
      field.querySelectorAll('[data-hour]').forEach(function (button) {
        button.addEventListener('click', function () {
          var selected = parseHours(input.value);
          var hour = button.dataset.hour;
          var index = selected.indexOf(hour);
          if (index === -1) {
            selected.push(hour);
          } else {
            selected.splice(index, 1);
          }
          selected.sort();
          input.value = selected.join(',');
          input.dispatchEvent(new Event('input', { bubbles: true }));
          syncHourButtons(field);
        });
      });
      input.addEventListener('input', function () { syncHourButtons(field); });
      syncHourButtons(field);
    });
  }

  function setFieldVisible(field, visible) {
    if (!field) return;
    field.classList.toggle('is-hidden-by-mode', !visible);
  }

  function syncScheduleMode(select) {
    var form = select.closest('form') || select.closest('.ns-card-body');
    if (!form || !select.name) return;
    var prefix = select.name.replace(/_schedule_mode$/, '');
    var mode = select.value || 'interval';
    var intervalValue = closestField(form.querySelector('[name="' + prefix + '_interval_value"]'));
    var intervalUnit = closestField(form.querySelector('[name="' + prefix + '_interval_unit"]'));
    var intervalMinutes = closestField(form.querySelector('[name="' + prefix + '_interval_minutes"]'));
    var specificHours = closestField(form.querySelector('[name="' + prefix + '_specific_hours"]'));

    setFieldVisible(intervalValue, mode === 'interval');
    setFieldVisible(intervalUnit, mode === 'interval');
    setFieldVisible(intervalMinutes, mode === 'interval');
    setFieldVisible(specificHours, mode === 'specific' || mode === 'specific_hours');
  }

  function initScheduleModes(root) {
    root.querySelectorAll('select[name$="_schedule_mode"]').forEach(function (select) {
      select.addEventListener('change', function () { syncScheduleMode(select); });
      syncScheduleMode(select);
    });
  }

  function getValue(root, name, fallback) {
    var input = root.querySelector('[name="' + name + '"]');
    if (!input) return fallback || '';
    if (input.type === 'checkbox') return input.checked;
    return input.value || fallback || '';
  }

  function firstChannel(root, fallback) {
    var select = root.querySelector('select[name$="_channel"]');
    var value = select ? select.value : (fallback || 'telegram');
    if (value === 'both') return 'Telegram + SMS';
    if (value === 'sms') return 'SMS';
    if (value === 'none') return 'معطل';
    return 'Telegram';
  }

  function line(enabled, text) {
    return enabled ? text : null;
  }

  function renderMessage(lines) {
    var filtered = lines.filter(Boolean);
    if (!filtered.length) {
      filtered.push('سيتم إرسال تنبيه مختصر عند تحقق شروط هذا القسم.');
    }
    return filtered;
  }

  function renderPreviewLine(output, item) {
    if (item === '') {
      var gap = document.createElement('span');
      gap.className = 'preview-gap';
      output.appendChild(gap);
      return;
    }
    var paragraph = document.createElement('p');
    var raw = String(item);
    var strongMatch = raw.match(/^<strong>([\s\S]*)<\/strong>$/);
    if (strongMatch) {
      var strong = document.createElement('strong');
      strong.textContent = strongMatch[1];
      paragraph.appendChild(strong);
    } else {
      paragraph.textContent = raw;
    }
    output.appendChild(paragraph);
  }

  function renderPreview(output, lines) {
    output.textContent = '';
    lines.forEach(function (item) {
      renderPreviewLine(output, item);
    });
  }

  function buildPreview(kind, root) {
    var channel = firstChannel(root, kind === 'sms_critical' ? 'sms' : 'telegram');
    var lines = [];
    if (kind === 'periodic_day') {
      lines = [
        '<strong>☀️ تحديث نهاري</strong>',
        '🔋 البطارية: 76% | الإنتاج جيد',
        line(getValue(root, 'periodic_day_include_progress'), '📊 تقدم اليوم: 64% من الهدف'),
        line(getValue(root, 'periodic_day_include_summary'), '📅 الملخص: استهلاك المنزل مستقر والشحن مناسب'),
        line(getValue(root, 'periodic_day_include_device'), '🔧 الجهاز: الجهاز الحالي متصل ويعمل'),
        line(getValue(root, 'periodic_day_include_weather'), '🌤️ الطقس: غيوم متوسطة قد تخفف الإنتاج'),
        line(getValue(root, 'periodic_day_include_loads'), '🏠 الأحمال: الغسالة مسموحة، السخان مؤجل'),
        line(getValue(root, 'periodic_day_include_sunset'), '🌇 الغروب المتوقع: 18:05، الشحن كاف حتى المساء')
      ];
    } else if (kind === 'periodic_night') {
      lines = [
        '<strong>🌙 تحديث ليلي</strong>',
        '🔋 البطارية: 68% | التفريغ طبيعي',
        line(getValue(root, 'periodic_night_include_progress'), '📊 تقدم الليل: الاستهلاك ضمن المتوقع'),
        line(getValue(root, 'periodic_night_include_summary'), '📌 الملخص: لا توجد مخاطر حرجة حاليا'),
        line(getValue(root, 'periodic_night_include_device'), '🔧 الجهاز: آخر مزامنة حديثة'),
        line(getValue(root, 'periodic_night_include_loads'), '🏠 الأحمال الليلية: 420W'),
        line(getValue(root, 'periodic_night_include_eta'), '⏳ الوقت المتبقي التقريبي: 5 ساعات')
      ];
    } else if (kind === 'sunset') {
      lines = [
        '<strong>🌇 تنبيه ما قبل الغروب</strong>',
        'تحليل فرص اكتمال البطارية قبل نهاية الشمس.',
        line(getValue(root, 'pre_sunset_include_soc'), '🔋 نسبة البطارية: 74%'),
        line(getValue(root, 'pre_sunset_include_charge_power'), '⚡ قدرة الشحن الحالية: 1.8kW'),
        line(getValue(root, 'pre_sunset_include_eta'), '⏳ وقت الامتلاء المتوقع: ساعتان'),
        line(getValue(root, 'pre_sunset_include_advice'), '💡 النصيحة: خفف الأحمال العالية حتى بعد الغروب'),
        line(getValue(root, 'pre_sunset_only_if_not_full'), '✅ يرسل فقط إذا كانت البطارية لن تمتلئ')
      ];
    } else if (kind === 'weather') {
      lines = [
        '<strong>🌤️ تنبيه الطقس</strong>',
        'عتبة الغيوم الحالية: ' + getValue(root, 'weather_cloud_threshold', '60') + '%',
        line(getValue(root, 'weather_test_include_next_hour'), '⏱️ الساعة القادمة: احتمال انخفاض إنتاج الشمس'),
        line(getValue(root, 'weather_test_include_smart_tip'), '💡 نصيحة: أجل الأحمال الكبيرة عند زيادة الغيوم')
      ];
    } else if (kind === 'battery') {
      lines = [
        '<strong>🔋 تنبيه البطارية</strong>',
        'حالة البطارية الحالية آمنة مع متابعة الشحن.',
        line(getValue(root, 'battery_test_include_day_summary'), '📅 ملخص اليوم: الإنتاج يغطي معظم الأحمال'),
        line(getValue(root, 'battery_test_include_sunset'), '🌇 الغروب: راقب الشحن قبل نهاية النهار'),
        line(getValue(root, 'battery_test_include_loads'), '🏠 الأحمال: لا توجد أحمال ممنوعة الآن')
      ];
    } else if (kind === 'load') {
      lines = [
        '<strong>🏠 تنبيه الأحمال</strong>',
        'حد الحمل الليلي: ' + getValue(root, 'night_max_load_w', '500') + 'W',
        line(getValue(root, 'load_alert_include_allowed'), '✅ مسموح الآن: الإضاءة، الشواحن، الغسالة الخفيفة'),
        line(getValue(root, 'load_alert_include_blocked'), '⛔ مؤجل: السخان أو أي حمل عالي')
      ];
    } else if (kind === 'daily_report') {
      lines = [
        '<strong>📋 التقرير اليومي</strong>',
        'ملخص صباحي لحالة الطاقة.',
        line(getValue(root, 'daily_report_include_totals'), '📊 الإجماليات: إنتاج 18.4kWh، استهلاك 14.2kWh'),
        line(getValue(root, 'daily_report_include_yesterday'), '↔️ مقارنة أمس: الإنتاج أعلى بنسبة 8%'),
        line(getValue(root, 'daily_report_include_device'), '🔧 الجهاز: الجهاز الحالي')
      ];
    } else if (kind === 'discharge') {
      lines = [
        '<strong>🌙 تنبيه التفريغ الليلي</strong>',
        'خطوة التفريغ: ' + getValue(root, 'night_discharge_percent_step', '5') + '%',
        line(getValue(root, 'night_discharge_include_device'), '🔧 الجهاز: آخر مزامنة قبل دقائق'),
        line(getValue(root, 'night_discharge_include_energy'), '⚡ الطاقة المتبقية: 6.2kWh')
      ];
    } else if (kind === 'sms_critical') {
      channel = 'SMS';
      var batteryLimit = getValue(root, 'sms_critical_battery_threshold_percent', '20');
      var emergencyLimit = getValue(root, 'sms_critical_emergency_battery_percent', '10');
      var runtimeLimit = getValue(root, 'sms_critical_runtime_threshold_hours', '2');
      var syncLimit = getValue(root, 'sms_critical_sync_stale_minutes', '30');
      var loadLimit = getValue(root, 'sms_critical_evening_load_threshold_w', '800');
      var deficitLimit = getValue(root, 'sms_critical_morning_deficit_threshold_w', '300');
      lines = [
        '<strong>تنبيه مهم: حالة تحتاج انتباهًا سريعًا</strong>',
        line(getValue(root, 'sms_critical_battery_enabled'), 'البطارية منخفضة: وصلت إلى ' + batteryLimit + '% أو أقل.'),
        line(getValue(root, 'sms_critical_emergency_enabled'), 'تنبيه طارئ: البطارية قد تصل إلى ' + emergencyLimit + '%.'),
        line(getValue(root, 'sms_critical_runtime_enabled'), 'الوقت المتوقع لنفاد البطارية أقل من ' + runtimeLimit + ' ساعة.'),
        line(getValue(root, 'sms_critical_evening_load_enabled'), 'تنبيه حمل ليلي مرتفع: الاستهلاك فوق ' + loadLimit + ' واط.'),
        line(getValue(root, 'sms_critical_sync_enabled'), 'لم تصل بيانات جديدة منذ أكثر من ' + syncLimit + ' دقيقة.'),
        line(getValue(root, 'sms_critical_day_zero_enabled'), 'إنتاج الشمس منخفض جدًا أثناء النهار.'),
        line(getValue(root, 'sms_critical_no_load_enabled'), 'لا توجد أحمال آمنة للتشغيل الآن.'),
        line(getValue(root, 'sms_critical_morning_deficit_enabled'), 'عجز صباحي: الحمل أعلى من الإنتاج بأكثر من ' + deficitLimit + ' واط.'),
        'يرجى تقليل الأحمال غير الضرورية والتحقق من النظام.'
      ];
    }
    return { channel: channel, lines: renderMessage(lines) };
  }

  function updatePreview(shell) {
    var output = shell.querySelector('[data-preview-output]');
    var channelTarget = shell.querySelector('[data-preview-channel]');
    if (!output) return;
    var kind = shell.dataset.previewSection || output.dataset.previewKind;
    var preview = buildPreview(kind, shell);
    renderPreview(output, preview.lines);
    if (channelTarget) channelTarget.textContent = preview.channel;
  }

  function initLivePreview(root) {
    root.querySelectorAll('[data-preview-section]').forEach(function (shell) {
      shell.querySelectorAll('input, select, textarea').forEach(function (control) {
        control.addEventListener('input', function () { updatePreview(shell); });
        control.addEventListener('change', function () { updatePreview(shell); });
      });
      updatePreview(shell);
    });
  }

  function normalizeChannelValue(value) {
    value = (value || 'none').toLowerCase();
    if (value === 'disabled' || value === 'off' || value === 'false' || value === '') return 'none';
    if (['telegram', 'sms', 'both', 'none'].indexOf(value) === -1) return 'none';
    return value;
  }

  function syncChannelRouter(router) {
    var hidden = router.querySelector('[data-channel-router-value]');
    var telegram = router.querySelector('[data-channel-choice="telegram"]');
    var sms = router.querySelector('[data-channel-choice="sms"]');
    if (!hidden || !telegram || !sms) return;

    var value = 'none';
    if (telegram.checked && sms.checked) value = 'both';
    else if (telegram.checked) value = 'telegram';
    else if (sms.checked) value = 'sms';
    hidden.value = value;

    router.classList.toggle('is-none', value === 'none');
    router.classList.toggle('is-telegram', value === 'telegram' || value === 'both');
    router.classList.toggle('is-sms', value === 'sms' || value === 'both');
    router.querySelectorAll('.ns-channel-chip').forEach(function (chip) {
      var input = chip.querySelector('input');
      chip.classList.toggle('is-active', !!(input && input.checked));
    });
  }

  function initChannelRouters(root) {
    root.querySelectorAll('[data-channel-router]').forEach(function (router) {
      var hidden = router.querySelector('[data-channel-router-value]');
      var telegram = router.querySelector('[data-channel-choice="telegram"]');
      var sms = router.querySelector('[data-channel-choice="sms"]');
      if (!hidden || !telegram || !sms) return;

      var initial = normalizeChannelValue(hidden.value);
      telegram.checked = initial === 'telegram' || initial === 'both';
      sms.checked = initial === 'sms' || initial === 'both';

      router.querySelectorAll('[data-channel-choice]').forEach(function (input) {
        input.addEventListener('change', function () { syncChannelRouter(router); });
      });
      syncChannelRouter(router);
    });
  }

  function initLogPagination(root) {
    var container = root.querySelector('[data-log-container]');
    if (!container || !container.dataset.logUrl) return;

    container.addEventListener('click', function (event) {
      var button = event.target.closest('[data-log-page]');
      if (!button || button.disabled) return;
      event.preventDefault();
      var page = parseInt(button.dataset.logPage, 10);
      if (!page || page < 1) return;
      var url = new URL(container.dataset.logUrl, window.location.origin);
      url.searchParams.set('page', page);
      container.classList.add('loading');
      fetch(url.toString(), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
        credentials: 'same-origin'
      })
        .then(function (response) { return response.json(); })
        .then(function (payload) {
          if (!payload || !payload.ok) throw new Error('bad log response');
          container.innerHTML = payload.html;
        })
        .catch(function () {
          container.classList.add('has-error');
        })
        .finally(function () {
          container.classList.remove('loading');
        });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    openTarget(window.location.hash);
    document.querySelectorAll('.ns-nav a[href^="#"]').forEach(function (link) {
      link.addEventListener('click', function () {
        openTarget(link.getAttribute('href'));
      });
    });
    initWindowFields(document);
    initHourPickers(document);
    initScheduleModes(document);
    initLivePreview(document);
    initChannelRouters(document);
    initLogPagination(document);
  });
})();
