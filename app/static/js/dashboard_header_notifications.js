
window.SOLARDEYE_DASH_HEADER_NOTIF_BUILD = "v33-notification-read-keep-list-20260429";

(function(){
  const root = document.querySelector('.dash-head-notif-v29');
  if(!root) return;

  const btn = root.querySelector('#dashHeaderNotifBtnV29');
  const list = root.querySelector('#dashHeaderNotifListV29');
  const count = root.querySelector('#dashHeaderNotifCountV29');
  const mini = root.querySelector('#dashHeaderNotifMiniCountV29');
  const feedUrl = root.dataset.feedUrl;
  const markReadUrl = root.dataset.markReadUrl;
  const centerUrl = root.dataset.centerUrl || '#';
  const cacheKey = 'solardeye:dashboardHeaderNotifications:last5:v33';
  let lastItems = [];

  function esc(s){
    return String(s || '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  }

  function setCount(n){
    const value = Math.max(0, Number(n || 0));
    if(count){
      count.textContent = value;
      count.dataset.count = String(value);
      count.classList.toggle('is-zero', value <= 0);
    }
    if(mini){
      mini.textContent = value;
      mini.classList.toggle('is-zero', value <= 0);
    }

    const global = document.getElementById('notificationBellCount');
    if(global){
      global.textContent = value;
      global.classList.toggle('is-zero', value <= 0);
    }
    const mail = document.getElementById('notificationMailCount');
    const ticket = document.getElementById('notificationTicketCount');
    if(mail && value <= 0) mail.textContent = '0';
    if(ticket && value <= 0) ticket.textContent = '0';
  }

  function kindLabel(kind){
    return kind === 'ticket' ? 'تذكرة' : 'رسالة';
  }

  function statusLabel(status){
    const ar = {new:'جديد', open:'مفتوح', assigned:'مخصص', pending:'قيد الانتظار', in_progress:'قيد المتابعة', waiting_user:'بانتظار المستخدم', resolved:'تم الحل', closed:'مغلق', read:'مقروء'};
    return ar[status] || status || '';
  }

  function normalizeItems(items){
    return (Array.isArray(items) ? items : [])
      .slice(0, 5)
      .map(item => ({
        kind: item.kind === 'ticket' ? 'ticket' : 'message',
        status: item.status || '',
        title: item.title || 'تحديث جديد',
        details: item.details || '',
        url: item.url || centerUrl,
        sender: item.sender || '',
        created_at: item.created_at || ''
      }));
  }

  function saveCache(items){
    try {
      localStorage.setItem(cacheKey, JSON.stringify(normalizeItems(items)));
    } catch(e) {}
  }

  function loadCache(){
    try {
      const raw = localStorage.getItem(cacheKey);
      const parsed = raw ? JSON.parse(raw) : [];
      return normalizeItems(parsed);
    } catch(e) {
      return [];
    }
  }

  function render(items, options={}){
    let displayItems = normalizeItems(items);
    if(!displayItems.length && options.useCache) displayItems = loadCache();
    lastItems = displayItems;
    if(!list) return;

    if(!displayItems.length){
      list.innerHTML = '<div class="dash-notif-empty-v29">لا توجد إشعارات حديثة حاليًا.<br>يمكنك فتح مركز الإشعارات لعرض السجل كاملًا.</div>';
      return;
    }

    const seenClass = options.seen ? ' is-seen-v33' : '';
    list.innerHTML = displayItems.map(item => {
      const kind = item.kind === 'ticket' ? 'ticket' : 'message';
      return `<a class="dash-notif-item-v29 kind-${esc(kind)} status-${esc(item.status)}${seenClass}" href="${esc(item.url)}">
        <div class="dash-notif-row-v29">
          <span class="dash-notif-kind-v29">${esc(kindLabel(kind))}</span>
          <span class="dash-notif-status-v29">${esc(options.seen ? 'مقروء' : statusLabel(item.status))}</span>
        </div>
        <h4>${esc(item.title)}</h4>
        <p>${esc(item.details)}</p>
        <div class="dash-notif-meta-v29">
          <span>${esc(item.sender || '')}</span>
          <small>${esc(item.created_at || '')}</small>
        </div>
      </a>`;
    }).join('');
  }

  function fetchFeed() {
    if(!feedUrl) return Promise.resolve({items: [], count: 0});
    return fetch(feedUrl, {headers:{'X-Requested-With':'XMLHttpRequest'}})
      .then(r => r.json())
      .then(data => {
        const items = normalizeItems(data.items || []);
        if(items.length) {
          saveCache(items);
          render(items);
        } else if(root.classList.contains('open')) {
          render([], {useCache: true, seen: true});
        } else {
          render([], {useCache: true, seen: true});
        }
        setCount(data.count || 0);
        return data;
      })
      .catch(() => {
        render([], {useCache: true, seen: true});
        return {items: [], count: 0};
      });
  }

  function markAllReadKeepList(){
    // Important: don't clear the visible list. We keep lastItems/cache visible and only zero counters.
    const keep = lastItems.length ? lastItems : loadCache();
    if(keep.length) render(keep, {seen: true});
    setCount(0);

    if(!markReadUrl) return Promise.resolve();
    return fetch(markReadUrl, {
      method: 'POST',
      body: new FormData(),
      headers: {'X-Requested-With':'XMLHttpRequest'}
    })
      .then(r => r.json())
      .then(() => {
        if(keep.length) render(keep, {seen: true});
        setCount(0);
      })
      .catch(() => {
        if(keep.length) render(keep, {seen: true});
        setCount(0);
      });
  }

  function openMenu(){
    root.classList.add('open');
    fetchFeed().then(() => {
      const keep = lastItems.length ? lastItems : loadCache();
      if(keep.length) saveCache(keep);
      markAllReadKeepList();
    });
  }

  function closeMenu(){
    root.classList.remove('open');
  }

  btn && btn.addEventListener('click', function(e){
    e.preventDefault();
    e.stopPropagation();
    if(root.classList.contains('open')) closeMenu();
    else openMenu();
  });

  document.addEventListener('click', function(e){
    if(!root.contains(e.target)) closeMenu();
  });

  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape') closeMenu();
  });

  // Initial load: show current count, but if already read keep cached list available.
  fetchFeed();
  setInterval(function(){
    if(!root.classList.contains('open')) fetchFeed();
  }, 15000);
})();
