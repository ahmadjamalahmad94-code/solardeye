window.SOLARDEYE_DASH_HEADER_NOTIF_BUILD = "v32-notification-kind-badges-20260429";

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
  let lastItems = [];
  let openedOnce = false;

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
    // keep the hidden global counter synced if it exists
    const global = document.getElementById('notificationBellCount');
    if(global){
      global.textContent = value;
      global.classList.toggle('is-zero', value <= 0);
    }
  }

  function kindLabel(kind){
    return kind === 'ticket' ? 'تذكرة' : 'رسالة';
  }

  function statusLabel(status){
    const ar = {new:'جديد', open:'مفتوح', assigned:'مخصص', pending:'قيد الانتظار', in_progress:'قيد المتابعة', waiting_user:'بانتظار المستخدم', resolved:'تم الحل', closed:'مغلق', read:'مقروء'};
    return ar[status] || status || '';
  }

  function render(items){
    lastItems = Array.isArray(items) ? items.slice(0,5) : [];
    if(!list) return;
    if(!lastItems.length){
      list.innerHTML = '<div class="dash-notif-empty-v29">لا توجد إشعارات حديثة حاليًا.<br>يمكنك فتح مركز الإشعارات لعرض السجل كاملًا.</div>';
      return;
    }
    list.innerHTML = lastItems.map(item => {
      const kind = item.kind === 'ticket' ? 'ticket' : 'message';
      const title = item.title || 'تحديث جديد';
      const details = item.details || '';
      const url = item.url || centerUrl;
      return `<a class="dash-notif-item-v29 kind-${esc(kind)} status-${esc(item.status)}" href="${esc(url)}">
        <div class="dash-notif-row-v29">
          <span class="dash-notif-kind-v29">${esc(kindLabel(kind))}</span>
          <span class="dash-notif-status-v29">${esc(statusLabel(item.status))}</span>
        </div>
        <h4>${esc(title)}</h4>
        <p>${esc(details)}</p>
        <div class="dash-notif-meta-v29">
          <span>${esc(item.sender || '')}</span>
          <small>${esc(item.created_at || '')}</small>
        </div>
      </a>`;
    }).join('');
  }

  function fetchFeed(){
    if(!feedUrl) return Promise.resolve();
    return fetch(feedUrl, {headers:{'X-Requested-With':'XMLHttpRequest'}})
      .then(r => r.json())
      .then(data => {
        setCount(data.count || 0);
        render(data.items || []);
        return data;
      })
      .catch(() => {
        if(list) list.innerHTML = '<div class="dash-notif-empty-v29">تعذر تحميل الإشعارات الآن.</div>';
      });
  }

  function markAllRead(){
    if(!markReadUrl) return Promise.resolve();
    return fetch(markReadUrl, {
      method: 'POST',
      body: new FormData(),
      headers: {'X-Requested-With':'XMLHttpRequest'}
    })
      .then(r => r.json())
      .then(data => {
        setCount(0);
        return data;
      })
      .catch(() => {
        setCount(0);
      });
  }

  function openMenu(){
    root.classList.add('open');
    fetchFeed().then(() => {
      // Opening the menu counts as seen/read, while keeping the loaded latest 5 visible.
      markAllRead();
      openedOnce = true;
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

  fetchFeed();
  setInterval(function(){
    if(!root.classList.contains('open')) fetchFeed();
  }, 15000);
})();
