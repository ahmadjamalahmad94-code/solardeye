(function(){
  const root=document.querySelector('[data-notifications-aggregated-center]');
  if(!root)return;
  const items=Array.from(root.querySelectorAll('[data-nc-item]'));
  const visibleCount=root.querySelector('[data-nc-visible-count]');
  const markUrl=root.dataset.markReadUrl;
  let tab='all';
  let statusFilter='open';
  let highOnly=false;
  function matches(item){
    const kind=item.dataset.kind||'system';
    const unread=Number(item.dataset.unread||0)>0;
    const archived=item.dataset.archived==='1';
    const status=(item.dataset.status||'').toLowerCase();
    const priority=(item.dataset.priority||'').toLowerCase();
    if(tab==='unread'&&!unread)return false;
    if(tab==='message'&&kind!=='message')return false;
    if(tab==='ticket'&&kind!=='ticket')return false;
    if(tab==='system'&&kind!=='system')return false;
    if(tab==='archive'&&!archived)return false;
    if(tab!=='archive'){
      if(statusFilter==='open'&&(archived||['closed','resolved'].includes(status)))return false;
      if(statusFilter==='closed'&&!['closed','resolved'].includes(status))return false;
    }
    if(highOnly&&!['high','urgent'].includes(priority))return false;
    return true;
  }
  function apply(){
    let count=0;
    items.forEach(item=>{const ok=matches(item);item.classList.toggle('is-hidden',!ok);if(ok)count++;});
    if(visibleCount)visibleCount.textContent=count;
  }
  root.querySelectorAll('[data-nc-tab]').forEach(btn=>btn.addEventListener('click',()=>{root.querySelectorAll('[data-nc-tab]').forEach(b=>b.classList.remove('active'));btn.classList.add('active');tab=btn.dataset.ncTab||'all';apply();}));
  root.querySelectorAll('[data-nc-status-filter]').forEach(input=>input.addEventListener('change',()=>{if(input.checked){statusFilter=input.value;apply();}}));
  const high=root.querySelector('[data-nc-priority-filter]'); if(high)high.addEventListener('change',()=>{highOnly=high.checked;apply();});
  const reset=root.querySelector('[data-nc-reset]'); if(reset)reset.addEventListener('click',()=>{tab='all';statusFilter='open';highOnly=false;root.querySelectorAll('[data-nc-tab]').forEach(b=>b.classList.toggle('active',b.dataset.ncTab==='all'));root.querySelectorAll('[data-nc-status-filter]').forEach(i=>i.checked=i.value==='open');if(high)high.checked=false;apply();});
  function postMark(data){if(!markUrl)return Promise.resolve();return fetch(markUrl,{method:'POST',body:data,headers:{'X-Requested-With':'XMLHttpRequest'}}).then(r=>r.json()).then(json=>{const c=json.count||0;document.querySelectorAll('#dashHeaderNotifCountV29,#dashHeaderNotifMiniCountV29,#notificationBellCount').forEach(el=>{el.textContent=c;el.classList.toggle('is-zero',c<=0);});return json;}).catch(()=>{});}
  root.querySelectorAll('[data-nc-open]').forEach(a=>a.addEventListener('click',()=>{const fd=new FormData();fd.append('group_key',a.dataset.groupKey||'');postMark(fd);}));
  const markAll=root.querySelector('[data-nc-mark-all]'); if(markAll)markAll.addEventListener('click',()=>{const fd=new FormData();fd.append('all','1');postMark(fd).then(()=>{items.forEach(item=>{item.dataset.unread='0';item.classList.remove('is-unread');const badge=item.querySelector('.nc-unread-v31');if(badge){badge.textContent='0 غير مقروءة';badge.classList.add('is-zero');}});const stat=root.querySelector('[data-stat-unread]');if(stat)stat.textContent='0';apply();});});
  apply();
})();
