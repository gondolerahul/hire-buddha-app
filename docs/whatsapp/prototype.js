(function(){
  const esc = v => String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const WA = window.WA = {
    screens:{},actions:{},state:{},esc:esc,
    ui:{
      button(label,action,kind='secondary'){return '<button type="button" class="btn '+(kind==='secondary'?'':kind)+'" data-action="'+esc(action)+'">'+label+'</button>'},
      badge(label,tone='neutral'){return '<span class="badge '+tone+'">'+label+'</span>'},
      panel(title,body,extra=''){return '<section class="card"><div class="card-header"><h2>'+title+'</h2>'+extra+'</div><div class="card-body">'+body+'</div></section>'},
      field(label,value='',hint='',type='text'){const id='f'+Math.random().toString(36).slice(2,8);return '<div class="field"><label for="'+id+'">'+label+'</label><input id="'+id+'" type="'+type+'" value="'+esc(value)+'">'+(hint?'<small>'+hint+'</small>':'')+'</div>'},
      select(label,options){const id='s'+Math.random().toString(36).slice(2,8);return '<div class="field"><label for="'+id+'">'+label+'</label><select id="'+id+'">'+options.map(o=>'<option>'+esc(o)+'</option>').join('')+'</select></div>'},
      table(headers,rows){return '<div class="table-wrap"><table><thead><tr>'+headers.map(h=>'<th scope="col">'+h+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>'},
      kpis(items){return '<div class="kpis">'+items.map(x=>'<div class="card metric"><div class="metric-label">'+x.label+'</div><div class="metric-value">'+x.value+'</div><div class="metric-detail">'+(x.detail||'')+'</div></div>').join('')+'</div>'},
      notice(text,tone='neutral'){return '<div class="notice '+tone+'">'+text+'</div>'},
      phone(body,title='Aarunya Living'){return '<div class="phone-preview"><div class="phone-top">●●● <span style="margin:0 62px">10:42</span> ▰▰▰</div><div class="phone-header"><span class="avatar" style="min-width:28px;height:28px;background:#425c4d;color:#fff">AL</span><div><strong>'+title+'</strong><small>Business account</small></div></div><div class="phone-body"><div class="phone-bubble">'+body+'</div></div><div class="phone-foot">Message</div></div>'}
    },
    icon(name){const d={
      grid:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
      server:'<rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/>',
      bot:'<rect x="3" y="7" width="18" height="13" rx="3"/><path d="M12 3v4m-4 7h.01M16 14h.01M9 17h6"/>',
      radio:'<path d="M5 16a10 10 0 0 1 14 0M8 19a6 6 0 0 1 8 0M12 22h.01M2 13a15 15 0 0 1 20 0"/>',
      phone:'<path d="M5 4c0 9 6 15 15 15l2-4-5-2-2 2c-3-1-5-3-6-6l2-2-2-5-4 2Z"/>',
      activity:'<path d="M2 12h4l3-8 6 16 3-8h4"/>',
      megaphone:'<path d="M3 11v3a2 2 0 0 0 2 2h2l3 5h3l-3-6 11-5V5L9 10H5a2 2 0 0 0-2 1Z"/>',
      message:'<path d="M21 11.5a8.4 8.4 0 0 1-9 8.5 9 9 0 0 1-4-.9L3 21l1.9-5A9 9 0 0 1 12 3a9 9 0 0 1 9 8.5Z"/><path d="M8 12h8"/>',
      folder:'<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10H3Z"/>',
      chart:'<path d="M3 20h18M6 17V9m6 8V4m6 13v-6"/>',
      wallet:'<rect x="3" y="6" width="18" height="15" rx="2"/><path d="M3 8V5a2 2 0 0 1 2-2h14M16 13h5"/>',
      shield:'<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
      sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>'
    };return '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+(d[name]||d.grid)+'</svg>'},
    get id(){return (location.hash||'#overview').slice(1)},
    go(id){if(!this.screens[id]){this.toast('This screen is unavailable.');return}this.closeModal();if(this.id===id)this.render();else location.hash=id;window.scrollTo(0,0)},
    render(){const id=this.screens[this.id]?this.id:'overview',screen=this.screens[id];if(!screen)return;const content=screen.render();document.title=screen.title+' · HireBuddha WhatsApp concept';document.getElementById('screen').innerHTML='<header class="page-head"><div><div class="eyebrow">WHATSAPP / '+(screen.eyebrow||screen.group||'WORKSPACE')+'</div><h1>'+screen.title+'</h1>'+(screen.subtitle?'<p>'+screen.subtitle+'</p>':'')+'</div>'+(screen.actions?'<div class="page-actions">'+screen.actions+'</div>':'')+'</header>'+content;document.querySelectorAll('#workspace-nav a').forEach(a=>a.classList.toggle('active',a.dataset.group===screen.group));document.querySelectorAll('.nav-children [data-go]').forEach(b=>b.classList.toggle('active',b.dataset.go==='overview'&&id!=='number'&&id!=='campaigns'||b.dataset.go===id))},
    modal(title,body){const d=document.getElementById('dialog');document.getElementById('dialog-title').innerHTML=title;document.getElementById('dialog-content').innerHTML=body;if(!d.open)d.showModal()},
    closeModal(){const d=document.getElementById('dialog');if(d&&d.open)d.close()},
    toast(message){const t=document.getElementById('toast');t.textContent=message;t.style.display='block';clearTimeout(this._toastTimer);this._toastTimer=setTimeout(()=>t.style.display='none',4000)},
    start(){document.querySelectorAll('[data-icon]').forEach(el=>el.innerHTML=this.icon(el.dataset.icon));const nav=[['Overview','overview'],['Connect','connect'],['Numbers','number'],['Inbox','inbox'],['Automations','automation'],['Templates','templates'],['Catalogues','catalogues'],['Flows','forms'],['Contacts','contacts'],['Campaigns','campaigns'],['Analytics','analytics'],['Settings','settings'],['Screen map','journeys']];document.getElementById('workspace-nav').innerHTML=nav.map(([label,id])=>'<a href="#'+id+'" data-group="'+(this.screens[id]&&this.screens[id].group||'')+'">'+label+'</a>').join('');document.addEventListener('click',e=>{const go=e.target.closest('[data-go]');if(go){e.preventDefault();this.go(go.dataset.go);return}const b=e.target.closest('[data-action]');if(b){e.preventDefault();const fn=this.actions[b.dataset.action];if(fn)fn(b,e);else this.toast('This opens an existing HireBuddha area in the product.')}});document.getElementById('close-dialog').addEventListener('click',()=>this.closeModal());document.getElementById('dialog').addEventListener('click',e=>{if(e.target.id==='dialog')this.closeModal()});window.addEventListener('hashchange',()=>{this.closeModal();this.render();window.scrollTo(0,0)});this.actions.theme=()=>{const light=document.documentElement.dataset.theme==='light';document.documentElement.dataset.theme=light?'dark':'light';document.getElementById('theme-label').textContent=light?'Luminescence Mode':'Eclipse Mode'};this.render()}
  };
})();

