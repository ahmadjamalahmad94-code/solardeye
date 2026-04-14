document.addEventListener('DOMContentLoaded', () => {
  const body = document.body;
  const themeButtons = Array.from(document.querySelectorAll('.theme-btn'));
  const langToggle = document.getElementById('langToggle');

  const currentLang = () => body.dataset.lang === 'en' ? 'en' : 'ar';
  const applyTranslations = () => {
    document.documentElement.lang = currentLang();
    document.documentElement.dir = currentLang() === 'en' ? 'ltr' : 'rtl';
    document.querySelectorAll('[data-ar][data-en]').forEach((el) => {
      el.textContent = currentLang() === 'en' ? el.dataset.en : el.dataset.ar;
    });
  };

  if (langToggle) {
    langToggle.addEventListener('click', () => {
      const url = new URL(window.location.href);
      const nextLang = currentLang() === 'en' ? 'ar' : 'en';
      url.searchParams.set('lang', nextLang);
      window.location.href = url.toString();
    });
  }

  applyTranslations();
  const applyTheme = (theme) => {
    body.classList.remove('theme-minimal', 'theme-saas', 'theme-glow');
    body.classList.add(theme);
    localStorage.setItem('ui_theme', theme);
    themeButtons.forEach((btn) => btn.classList.toggle('active', btn.dataset.theme === theme));
  };
  applyTheme(localStorage.getItem('ui_theme') || 'theme-saas');
  themeButtons.forEach((btn) => btn.addEventListener('click', () => applyTheme(btn.dataset.theme)));

  const clock = document.getElementById('liveClock');
  const fmt = () => new Intl.DateTimeFormat(currentLang() === 'en' ? 'en-GB' : 'ar-EG', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const tick = () => { if (clock) clock.textContent = fmt().format(new Date()); };
  tick();
  setInterval(tick, 1000);

  const parse = (v, fallback = []) => { try { return JSON.parse(v || '[]'); } catch { return fallback; } };
  const sidebarToggle = document.getElementById('sidebarToggle');
  const appShell = document.getElementById('appShell');
  if (sidebarToggle && appShell) {
    if (localStorage.getItem('sidebar_collapsed') === 'true') appShell.classList.add('sidebar-collapsed');
    sidebarToggle.addEventListener('click', () => {
      appShell.classList.toggle('sidebar-collapsed');
      localStorage.setItem('sidebar_collapsed', appShell.classList.contains('sidebar-collapsed'));
    });
  }

  const baseOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: { legend: { labels: { font: { family: 'Cairo' } } } },
    scales: {
      x: { ticks: { font: { family: 'Cairo' }, maxRotation: 0, minRotation: 0 } },
      y: { beginAtZero: true, ticks: { font: { family: 'Cairo' } } }
    }
  };

  const powerChart = document.getElementById('powerChart');
  if (powerChart) {
    new Chart(powerChart.getContext('2d'), {
      type: 'line',
      data: {
        labels: parse(powerChart.dataset.labels),
        datasets: [
          { label: 'الطاقة الشمسية', data: parse(powerChart.dataset.solar), borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.08)', fill: true, tension: 0.35, pointRadius: 4, borderWidth: 3 },
          { label: 'استهلاك البيت', data: parse(powerChart.dataset.load), borderColor: '#ec4899', tension: 0.35, pointRadius: 4, borderWidth: 3 },
          { label: 'الشبكة', data: parse(powerChart.dataset.grid), borderColor: '#94a3b8', borderDash: [6,4], tension: 0.25, pointRadius: 3, borderWidth: 2 },
          { label: 'البطارية (شحن/تفريغ)', data: parse(powerChart.dataset.battery), borderColor: '#10b981', tension: 0.35, pointRadius: 4, borderWidth: 3 },
        ]
      },
      options: { ...baseOptions, scales: { x: baseOptions.scales.x, y: { ...baseOptions.scales.y, ticks: { ...baseOptions.scales.y.ticks, callback: (v) => v + ' W' } } } }
    });
  }

  const batteryChart = document.getElementById('batteryChart');
  if (batteryChart) {
    new Chart(batteryChart.getContext('2d'), {
      type: 'line',
      data: { labels: parse(batteryChart.dataset.labels), datasets: [{ label: '% SOC', data: parse(batteryChart.dataset.battery), borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.08)', fill: true, tension: 0.35, pointRadius: 4, borderWidth: 3 }] },
      options: { ...baseOptions, scales: { x: baseOptions.scales.x, y: { beginAtZero: true, suggestedMax: 100, ticks: { font: { family: 'Cairo' } } } } }
    });
  }

  const statsProfileChart = document.getElementById('statsProfileChart');
  if (statsProfileChart) {
    const kind = statsProfileChart.dataset.kind || 'day';
    new Chart(statsProfileChart.getContext('2d'), {
      type: kind === 'day' ? 'line' : 'bar',
      data: { labels: parse(statsProfileChart.dataset.labels), datasets: kind === 'day' ? [
        { label: 'الطاقة الشمسية', data: parse(statsProfileChart.dataset.solar), borderColor: '#f59e0b', tension: 0.35, pointRadius: 4, borderWidth: 3 },
        { label: 'استهلاك البيت', data: parse(statsProfileChart.dataset.home), borderColor: '#ec4899', tension: 0.35, pointRadius: 4, borderWidth: 3 },
        { label: 'البطارية', data: parse(statsProfileChart.dataset.battery), borderColor: '#10b981', tension: 0.35, pointRadius: 4, borderWidth: 3 },
        { label: '% SOC', data: parse(statsProfileChart.dataset.soc), borderColor: '#3b82f6', yAxisID: 'y1', tension: 0.35, pointRadius: 4, borderWidth: 3 }
      ] : [
        { label: 'الطاقة الشمسية', data: parse(statsProfileChart.dataset.solar), backgroundColor: 'rgba(245,158,11,.85)' },
        { label: 'استهلاك البيت', data: parse(statsProfileChart.dataset.home), backgroundColor: 'rgba(236,72,153,.85)' },
        { label: 'البطارية', data: parse(statsProfileChart.dataset.battery), backgroundColor: 'rgba(16,185,129,.85)' },
        { label: 'الشبكة', data: parse(statsProfileChart.dataset.grid), backgroundColor: 'rgba(148,163,184,.85)' },
      ] },
      options: { ...baseOptions, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { font: { family: 'Cairo' } } } }, scales: { x: baseOptions.scales.x, y: baseOptions.scales.y, y1: { beginAtZero: true, suggestedMax: 100, position: 'right', grid: { drawOnChartArea: false }, ticks: { font: { family: 'Cairo' } } } } }
    });
  }

  const statsUsageChart = document.getElementById('statsUsageChart');
  if (statsUsageChart) {
    new Chart(statsUsageChart.getContext('2d'), {
      type: 'bar',
      data: { labels: parse(statsUsageChart.dataset.labels), datasets: [
        { label: 'الطاقة الشمسية', data: parse(statsUsageChart.dataset.solar), backgroundColor: 'rgba(245,158,11,.85)' },
        { label: 'استهلاك البيت', data: parse(statsUsageChart.dataset.home), backgroundColor: 'rgba(236,72,153,.85)' },
        { label: 'البطارية', data: parse(statsUsageChart.dataset.battery), backgroundColor: 'rgba(16,185,129,.85)' },
        { label: 'الشبكة', data: parse(statsUsageChart.dataset.grid), backgroundColor: 'rgba(148,163,184,.85)' },
      ] },
      options: { ...baseOptions, maintainAspectRatio: false, plugins: { legend: { position: 'bottom', labels: { font: { family: 'Cairo' } } } } }
    });
  }


  document.querySelectorAll('[data-tabs="notifications-tabs"]').forEach((tabsRoot) => {
    const buttons = tabsRoot.querySelectorAll('.notify-tab-btn');
    const panels = tabsRoot.querySelectorAll('.notify-tab-panel');

    const updateNotificationPanel = (panel) => {
      const previewRoot = panel.querySelector('[data-preview-root]');
      const sectionToggle = panel.querySelector('[data-section-toggle]');
      const linkedButton = tabsRoot.querySelector(`.notify-tab-btn[data-target="${panel.id}"]`);
      const sectionEnabled = !sectionToggle || sectionToggle.checked;

      if (previewRoot) {
        previewRoot.classList.toggle('preview-disabled', !sectionEnabled);
      }
      if (linkedButton) {
        linkedButton.classList.toggle('is-off', !sectionEnabled);
        const badge = linkedButton.querySelector('.tab-live-badge');
        if (badge) badge.textContent = sectionEnabled ? 'ON' : 'OFF';
      }

      panel.querySelectorAll('[data-preview-toggle]').forEach((input) => {
        const key = input.dataset.previewToggle;
        const visible = sectionEnabled && input.checked;
        panel.querySelectorAll(`[data-preview-key="${key}"]`).forEach((line) => {
          line.classList.toggle('is-hidden', !visible);
        });
      });
    };

    const updateCounters = () => {
      const enabled = Array.from(panels).filter((panel) => {
        const toggle = panel.querySelector('[data-section-toggle]');
        return !toggle || toggle.checked;
      }).length;
      const enabledNode = document.getElementById('enabledSectionsCount');
      const disabledNode = document.getElementById('disabledSectionsCount');
      if (enabledNode) enabledNode.textContent = String(enabled);
      if (disabledNode) disabledNode.textContent = String(Math.max(panels.length - enabled, 0));
    };

    buttons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const target = btn.dataset.target;
        buttons.forEach((b) => b.classList.toggle('active', b === btn));
        panels.forEach((panel) => panel.classList.toggle('active', panel.id === target));
      });
    });

    panels.forEach((panel) => {
      panel.querySelectorAll('[data-preview-toggle], [data-section-toggle]').forEach((input) => {
        input.addEventListener('change', () => {
          updateNotificationPanel(panel);
          updateCounters();
        });
      });
      updateNotificationPanel(panel);
    });
    updateCounters();
  });



  const notificationsForm = document.getElementById('notificationsSettingsForm');
  const ajaxBanner = document.getElementById('notificationAjaxStatus');
  const showAjaxBanner = (message, ok = true) => {
    if (!ajaxBanner) return;
    ajaxBanner.hidden = false;
    ajaxBanner.textContent = message;
    ajaxBanner.classList.toggle('is-error', !ok);
    ajaxBanner.classList.toggle('is-success', !!ok);
    window.clearTimeout(showAjaxBanner._timer);
    showAjaxBanner._timer = window.setTimeout(() => {
      ajaxBanner.hidden = true;
    }, 3500);
  };

  const postNotificationAjax = async (url, formData) => {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json',
      },
      body: formData,
      credentials: 'same-origin',
      redirect: 'follow',
    });

    const contentType = response.headers.get('content-type') || '';
    const rawText = await response.text();
    let data = null;

    if (contentType.includes('application/json')) {
      try {
        data = JSON.parse(rawText);
      } catch (_err) {
        throw new Error('رد JSON غير صالح من السيرفر');
      }
    } else {
      if (response.status === 401) {
        throw new Error('انتهت جلسة تسجيل الدخول. أعد تسجيل الدخول ثم جرّب مرة أخرى.');
      }
      if (response.redirected || /<!doctype html>/i.test(rawText)) {
        throw new Error('السيرفر أعاد صفحة HTML بدل JSON. أعد تسجيل الدخول أو راجع مسار الاختبار.');
      }
      throw new Error(rawText || 'تعذر قراءة رد السيرفر');
    }

    if (!response.ok || !data.ok) {
      throw new Error(data.message || 'فشل تنفيذ الطلب');
    }
    return data;
  };

  if (notificationsForm) {
    // تم تعطيل الإرسال عبر AJAX في مركز الإشعارات عمدًا.
    // نعتمد على submit عادي + redirect + flash messages لأنه أضمن على Render.

    notificationsForm.querySelectorAll('[data-ajax-test]').forEach((btn) => {
      btn.addEventListener('click', async (event) => {
        event.preventDefault();
        const formData = new FormData(notificationsForm);
        if (btn.name) formData.set(btn.name, btn.value);
        const action = btn.getAttribute('formaction') || notificationsForm.action;
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = '...جاري الإرسال';
        try {
          const data = await postNotificationAjax(action, formData);
          showAjaxBanner(data.message || 'تم الإرسال', true);
        } catch (error) {
          showAjaxBanner(error.message || 'تعذر إرسال الاختبار', false);
        } finally {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      });
    });

    document.querySelectorAll('form[data-ajax-notification]').forEach((form) => {
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const submitter = event.submitter || form.querySelector('button[type="submit"]');
        const formData = new FormData(form);
        if (submitter?.name) formData.set(submitter.name, submitter.value);
        const originalText = submitter ? submitter.textContent : '';
        if (submitter) {
          submitter.disabled = true;
          submitter.textContent = '...جاري الإرسال';
        }
        try {
          const data = await postNotificationAjax(form.action, formData);
          showAjaxBanner(data.message || 'تم الإرسال', true);
        } catch (error) {
          showAjaxBanner(error.message || 'تعذر إرسال الاختبار', false);
        } finally {
          if (submitter) {
            submitter.disabled = false;
            submitter.textContent = originalText;
          }
        }
      });
    });
  }

  const reportsMainChart = document.getElementById('reportsMainChart');
  if (reportsMainChart) {
    const kind = reportsMainChart.dataset.kind || 'day';
    const lineDatasets = [
      { label: 'الطاقة الشمسية', data: parse(reportsMainChart.dataset.solar), borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,.08)', fill: true, tension: 0.38, pointRadius: 3, pointHoverRadius: 5, borderWidth: 3 },
      { label: 'استهلاك البيت', data: parse(reportsMainChart.dataset.home), borderColor: '#ec4899', tension: 0.34, pointRadius: 3, pointHoverRadius: 5, borderWidth: 3 },
      { label: 'البطارية', data: parse(reportsMainChart.dataset.battery), borderColor: '#10b981', tension: 0.34, pointRadius: 3, pointHoverRadius: 5, borderWidth: 3 },
      { label: '% SOC', data: parse(reportsMainChart.dataset.soc), borderColor: '#3b82f6', yAxisID: 'y1', tension: 0.34, pointRadius: 3, pointHoverRadius: 5, borderWidth: 3 }
    ];
    const barDatasets = [
      { label: 'الطاقة الشمسية', data: parse(reportsMainChart.dataset.solar), backgroundColor: 'rgba(245,158,11,.82)', borderRadius: 10, maxBarThickness: 34 },
      { label: 'استهلاك البيت', data: parse(reportsMainChart.dataset.home), backgroundColor: 'rgba(236,72,153,.82)', borderRadius: 10, maxBarThickness: 34 },
      { label: 'البطارية', data: parse(reportsMainChart.dataset.battery), backgroundColor: 'rgba(16,185,129,.82)', borderRadius: 10, maxBarThickness: 34 },
      { label: 'الشبكة', data: parse(reportsMainChart.dataset.grid), backgroundColor: 'rgba(148,163,184,.82)', borderRadius: 10, maxBarThickness: 34 },
    ];
    new Chart(reportsMainChart.getContext('2d'), {
      type: kind === 'day' ? 'line' : 'bar',
      data: {
        labels: parse(reportsMainChart.dataset.labels),
        datasets: kind === 'day' ? lineDatasets : barDatasets,
      },
      options: {
        ...baseOptions,
        maintainAspectRatio: false,
        layout: { padding: { top: 6, right: 10, bottom: 0, left: 6 } },
        plugins: {
          legend: { position: 'top', align: 'start', labels: { usePointStyle: true, boxWidth: 10, padding: 16, font: { family: 'Cairo' } } },
          tooltip: { rtl: true, titleFont: { family: 'Cairo' }, bodyFont: { family: 'Cairo' } }
        },
        scales: {
          x: { ...baseOptions.scales.x, grid: { display: false }, ticks: { ...baseOptions.scales.x.ticks, padding: 8 } },
          y: { ...baseOptions.scales.y, ticks: { ...baseOptions.scales.y.ticks, padding: 8 } },
          y1: { beginAtZero: true, suggestedMax: 100, position: 'right', grid: { drawOnChartArea: false }, ticks: { font: { family: 'Cairo' }, padding: 8 } }
        }
      }
    });
  }



  const batteryLabSocChart = document.getElementById('batteryLabSocChart');
  if (batteryLabSocChart) {
    new Chart(batteryLabSocChart.getContext('2d'), {
      type: 'line',
      data: {
        labels: parse(batteryLabSocChart.dataset.labels),
        datasets: [{
          label: 'نسبة البطارية %',
          data: parse(batteryLabSocChart.dataset.soc),
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,0.08)',
          fill: true,
          tension: 0.28,
          pointRadius: 2,
          pointHoverRadius: 4,
          borderWidth: 3
        }]
      },
      options: {
        ...baseOptions,
        maintainAspectRatio: false,
        layout: { padding: { top: 10, right: 12, bottom: 4, left: 8 } },
        plugins: {
          legend: { position: 'top', align: 'start', labels: { usePointStyle: true, boxWidth: 9, padding: 14, font: { family: 'Cairo' } } },
          tooltip: { rtl: true, titleFont: { family: 'Cairo' }, bodyFont: { family: 'Cairo' } }
        },
        scales: {
          x: { ...baseOptions.scales.x, grid: { display: false }, ticks: { ...baseOptions.scales.x.ticks, autoSkip: true, maxTicksLimit: 8, padding: 8 } },
          y: { beginAtZero: false, suggestedMin: 0, suggestedMax: 100, ticks: { font: { family: 'Cairo' }, callback: (v) => v + '%', padding: 8 } }
        }
      }
    });
  }

  const batteryLabPowerChart = document.getElementById('batteryLabPowerChart');
  if (batteryLabPowerChart) {
    new Chart(batteryLabPowerChart.getContext('2d'), {
      type: 'line',
      data: {
        labels: parse(batteryLabPowerChart.dataset.labels),
        datasets: [
          { label: 'قدرة البطارية W', data: parse(batteryLabPowerChart.dataset.power), borderColor: '#10b981', backgroundColor: 'rgba(16,185,129,0.05)', tension: 0.28, pointRadius: 2, pointHoverRadius: 4, borderWidth: 3, fill: false },
          { label: 'الجهد V', data: parse(batteryLabPowerChart.dataset.voltage), borderColor: '#f59e0b', tension: 0.24, pointRadius: 2, pointHoverRadius: 4, borderWidth: 3, yAxisID: 'y1' },
          { label: 'التيار A', data: parse(batteryLabPowerChart.dataset.current), borderColor: '#8b5cf6', tension: 0.24, pointRadius: 2, pointHoverRadius: 4, borderWidth: 3, yAxisID: 'y2' }
        ]
      },
      options: {
        ...baseOptions,
        maintainAspectRatio: false,
        layout: { padding: { top: 10, right: 12, bottom: 4, left: 8 } },
        plugins: {
          legend: { position: 'top', align: 'start', labels: { usePointStyle: true, boxWidth: 9, padding: 14, font: { family: 'Cairo' } } },
          tooltip: { rtl: true, titleFont: { family: 'Cairo' }, bodyFont: { family: 'Cairo' } }
        },
        scales: {
          x: { ...baseOptions.scales.x, grid: { display: false }, ticks: { ...baseOptions.scales.x.ticks, autoSkip: true, maxTicksLimit: 8, padding: 8 } },
          y: { ...baseOptions.scales.y, ticks: { ...baseOptions.scales.y.ticks, callback: (v) => v + ' W', padding: 8 } },
          y1: { beginAtZero: false, position: 'right', grid: { drawOnChartArea: false }, ticks: { font: { family: 'Cairo' }, callback: (v) => v + ' V', padding: 8 } },
          y2: { beginAtZero: false, position: 'right', grid: { drawOnChartArea: false }, display: false, ticks: { font: { family: 'Cairo' }, callback: (v) => v + ' A' } }
        }
      }
    });
  }

  const reportsMixChart = document.getElementById('reportsMixChart');
  if (reportsMixChart) {
    const mixValues = parse(reportsMixChart.dataset.values).map((v) => Number(v || 0));
    const total = mixValues.reduce((a, b) => a + b, 0);
    new Chart(reportsMixChart.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: ['شمس → المنزل', 'بطارية → المنزل', 'شبكة → المنزل'],
        datasets: [{
          data: total > 0 ? mixValues : [1, 0, 0],
          backgroundColor: ['rgba(245,158,11,.92)', 'rgba(16,185,129,.92)', 'rgba(59,130,246,.88)'],
          borderColor: ['#ffffff', '#ffffff', '#ffffff'],
          borderWidth: 4,
          hoverOffset: 8,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '64%',
        plugins: {
          legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 10, padding: 16, font: { family: 'Cairo' } } },
          tooltip: {
            rtl: true,
            titleFont: { family: 'Cairo' },
            bodyFont: { family: 'Cairo' },
            callbacks: {
              label: (ctx) => `${ctx.label}: ${ctx.parsed} kWh`
            }
          }
        }
      }
    });
  }
});
