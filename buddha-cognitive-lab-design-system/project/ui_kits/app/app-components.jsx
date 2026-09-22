/* ============================================================
   Hire Buddha — App data + shell + workforce
   Exports: Icon, ASSETS, WORKFORCE, ACTIVITY, INBOX, MODELS, ALL_TOOLS,
            Sidebar, Topbar, KPIs, WorkforceView
   ============================================================ */
const { useState, useEffect, useRef } = React;
const ASSETS = "../../assets/";

function Icon({ name, size = 18, stroke = 1.75, style, className }) {
  return <i data-lucide={name} className={className}
    style={{ width: size, height: size, strokeWidth: stroke, display: 'inline-flex', flex: 'none', ...style }}></i>;
}

const MODELS = [
  { id:'buddha-frontier-1', name:'buddha-frontier-1', desc:'Most capable · long-horizon autonomy' },
  { id:'buddha-swift-1',    name:'buddha-swift-1',    desc:'Fast & economical · high-volume work' },
  { id:'buddha-deep-1',     name:'buddha-deep-1',     desc:'Deepest reasoning · research & analysis' },
];
const ALL_TOOLS = ['gmail','slack','stripe','notion','hubspot','quickbooks','calendar','sheets','zendesk','ramp','linkedin','web','github','salesforce'];

/* Employed Buddhas (the workspace's autonomous workforce) */
const WORKFORCE = [
  { id:'ops', name:'Operations Buddha', role:'OPS · AUTONOMOUS', status:'running', model:'buddha-frontier-1',
    task:'Reconciling October invoices in QuickBooks', tasksToday:42, accuracy:99.2, hours:618,
    tools:['stripe','quickbooks','gmail'], employed:'Aug 2025',
    spark:[5,7,6,9,8,11,10,13,12,14,13,16],
    timeline:[
      { ic:'check', cls:'ok', tx:'Closed and filed <b>September books</b> — variance under 0.1%.', tm:'2 min ago' },
      { ic:'file-text', cls:'gold', tx:'Reconciled 38 Stripe payouts against <span class="tool">quickbooks</span>.', tm:'34 min ago' },
      { ic:'mail', cls:'', tx:'Emailed 3 vendors about <b>mismatched invoices</b> via <span class="tool">gmail</span>.', tm:'1 hr ago' },
      { ic:'play', cls:'gold', tx:'Started monthly close run for <b>October</b>.', tm:'3 hr ago' },
    ]},
  { id:'support', name:'Support Buddha', role:'SUPPORT · AUTONOMOUS', status:'idle', model:'buddha-swift-1',
    task:'Inbox clear — watching for new tickets', tasksToday:128, accuracy:97.5, hours:512,
    tools:['zendesk','slack','notion'], employed:'Sep 2025',
    spark:[14,12,16,11,13,9,12,8,10,7,9,6],
    timeline:[
      { ic:'check', cls:'ok', tx:'Resolved ticket <b>#4821</b> — refund processed and confirmed.', tm:'8 min ago' },
      { ic:'message-square', cls:'', tx:'Answered 12 chats in <span class="tool">slack</span> shared inbox.', tm:'40 min ago' },
      { ic:'arrow-up', cls:'gold', tx:'Escalated 1 billing dispute to <b>you</b> for approval.', tm:'2 hr ago' },
    ]},
  { id:'sales', name:'Sales Buddha', role:'GROWTH · AUTONOMOUS', status:'running', model:'buddha-frontier-1',
    task:'Drafting outreach to 14 qualified leads', tasksToday:31, accuracy:96.0, hours:240,
    tools:['hubspot','gmail','calendar'], employed:'Oct 2025',
    spark:[3,5,4,6,8,7,9,10,9,12,11,13],
    timeline:[
      { ic:'user-plus', cls:'gold', tx:'Qualified <b>14 new leads</b> from this week’s signups.', tm:'12 min ago' },
      { ic:'calendar', cls:'ok', tx:'Booked 2 demos on your <span class="tool">calendar</span>.', tm:'1 hr ago' },
      { ic:'mail', cls:'', tx:'Sent 21 tailored outreach emails.', tm:'4 hr ago' },
    ]},
  { id:'research', name:'Research Buddha', role:'RESEARCH · AUTONOMOUS', status:'attention', model:'buddha-deep-1',
    task:'Needs your input: scope the competitor brief', tasksToday:6, accuracy:98.8, hours:96,
    tools:['web','notion','sheets'], employed:'Nov 2025',
    spark:[2,3,2,4,3,5,4,6,5,4,6,5],
    timeline:[
      { ic:'help-circle', cls:'', tx:'Asked <b>you</b>: should the brief include pricing teardown?', tm:'18 min ago' },
      { ic:'book-open', cls:'gold', tx:'Synthesized 22 sources into a <span class="tool">notion</span> doc.', tm:'2 hr ago' },
      { ic:'search', cls:'', tx:'Gathered market data across <span class="tool">web</span>.', tm:'5 hr ago' },
    ]},
  { id:'finance', name:'Finance Buddha', role:'FINANCE · AUTONOMOUS', status:'running', model:'buddha-frontier-1',
    task:'Forecasting Q1 runway from latest spend', tasksToday:9, accuracy:99.6, hours:184,
    tools:['ramp','stripe','sheets'], employed:'Sep 2025',
    spark:[6,6,7,7,8,8,9,9,10,11,12,12],
    timeline:[
      { ic:'trending-up', cls:'gold', tx:'Updated runway model — <b>17.2 months</b> at current burn.', tm:'25 min ago' },
      { ic:'check', cls:'ok', tx:'Categorized 214 <span class="tool">ramp</span> transactions.', tm:'3 hr ago' },
    ]},
  { id:'recruit', name:'Recruiting Buddha', role:'PEOPLE · AUTONOMOUS', status:'paused', model:'buddha-swift-1',
    task:'Paused by you — resume to continue sourcing', tasksToday:0, accuracy:95.4, hours:72,
    tools:['linkedin','gmail','calendar'], employed:'Nov 2025',
    spark:[4,5,3,6,4,2,3,1,2,0,0,0],
    timeline:[
      { ic:'pause', cls:'', tx:'Paused by <b>you</b> while the role is on hold.', tm:'Yesterday' },
      { ic:'users', cls:'gold', tx:'Shortlisted 8 candidates for <b>Senior Designer</b>.', tm:'2 days ago' },
    ]},
];

const ACTIVITY = [
  { who:'Operations Buddha', tx:'closed and filed September books — variance under 0.1%', tm:'2 min ago', tag:'done', cls:'ok' },
  { who:'Support Buddha', tx:'resolved ticket #4821 and processed a refund', tm:'8 min ago', tag:'done', cls:'ok' },
  { who:'Sales Buddha', tx:'qualified 14 new leads and started outreach', tm:'12 min ago', tag:'running', cls:'gold' },
  { who:'Research Buddha', tx:'asked you a question about the competitor brief', tm:'18 min ago', tag:'needs you', cls:'' },
  { who:'Finance Buddha', tx:'updated the Q1 runway model — 17.2 months', tm:'25 min ago', tag:'running', cls:'gold' },
  { who:'Support Buddha', tx:'answered 12 chats across the shared Slack inbox', tm:'40 min ago', tag:'done', cls:'ok' },
  { who:'Sales Buddha', tx:'booked 2 product demos on your calendar', tm:'1 hr ago', tag:'done', cls:'ok' },
  { who:'Operations Buddha', tx:'emailed 3 vendors about mismatched invoices', tm:'1 hr ago', tag:'done', cls:'ok' },
  { who:'Finance Buddha', tx:'categorized 214 Ramp transactions', tm:'3 hr ago', tag:'done', cls:'ok' },
];

const INBOX = [
  { who:'Research Buddha', t:'Scope question — competitor brief', d:'Should the brief include a pricing teardown? It adds ~2 hours but sharpens positioning.', tm:'18 min ago' },
  { who:'Support Buddha', t:'Approve refund — $480 billing dispute', d:'Customer disputes a duplicate charge. Evidence supports a refund. Approve to proceed.', tm:'2 hr ago' },
  { who:'Sales Buddha', t:'Approve outreach copy', d:'Drafted a 3-touch sequence for the enterprise segment. Review tone before it sends.', tm:'4 hr ago' },
];

/* ---------------- Sidebar ---------------- */
function Sidebar({ view, setView, counts, onHire }) {
  const items = [
    { id:'workforce', ic:'users-round', label:'Workforce', ct:counts.workforce },
    { id:'activity', ic:'activity', label:'Activity' },
    { id:'inbox', ic:'inbox', label:'Inbox', ct:counts.inbox },
  ];
  const lab = [
    { id:'tools', ic:'plug', label:'Tools' },
    { id:'models', ic:'cpu', label:'Models' },
    { id:'settings', ic:'settings', label:'Settings' },
  ];
  return (
    <aside className="side">
      <div className="side-logo"><img src={ASSETS+"logo-hire-buddha-onblack.svg"} alt="Hire Buddha" /></div>
      <div className="side-org">
        <span className="badge"><img src={ASSETS+"logo-mark-black.svg"} /></span>
        <div className="meta"><div className="nm">Northwind Co.</div><div className="pl">Studio plan · 6 employed</div></div>
        <Icon name="chevrons-up-down" size={15} className="chev" style={{color:'var(--fg-subtle)'}} />
      </div>
      <button className="btn btn-metal" style={{width:'100%',justifyContent:'center',marginBottom:4}} onClick={onHire}>
        <Icon name="plus" size={16} /> Hire a Buddha
      </button>
      <div className="nav-group">Workspace</div>
      {items.map(it => (
        <div key={it.id} className={"nav-item"+(view===it.id?" on":"")} onClick={()=>setView(it.id)}>
          <Icon name={it.ic} size={18} /><span>{it.label}</span>
          {it.ct ? <span className="ct">{it.ct}</span> : null}
        </div>
      ))}
      <div className="nav-group">Lab</div>
      {lab.map(it => (
        <div key={it.id} className={"nav-item"+(view===it.id?" on":"")} onClick={()=>setView(it.id)}>
          <Icon name={it.ic} size={18} /><span>{it.label}</span>
        </div>
      ))}
      <div className="side-foot">
        <span className="av">R</span>
        <div className="meta"><div className="nm">Rahul</div><div className="em">rahul@northwind.co</div></div>
      </div>
    </aside>
  );
}

/* ---------------- Topbar ---------------- */
function Topbar({ title, crumb, onHire }) {
  return (
    <div className="topbar">
      {crumb ? <div className="crumb">{crumb}</div> : <h1>{title}</h1>}
      <div className="search">
        <Icon name="search" size={15} />
        <input placeholder="Search workforce, runs, tools…" />
        <span className="k">⌘K</span>
      </div>
      <div className="top-right">
        <button className="icon-btn"><Icon name="bell" size={17} /><span className="dot"></span></button>
        <button className="icon-btn"><Icon name="life-buoy" size={17} /></button>
        <button className="btn btn-primary btn-sm" onClick={onHire}><Icon name="plus" size={15} /> Hire</button>
      </div>
    </div>
  );
}

/* ---------------- KPIs ---------------- */
function KPIs() {
  const data = [
    { ic:'users-round', lab:'Employed', val:'6', delta:'4 running now', cls:'gold' },
    { ic:'zap', lab:'Tasks today', val:'216', delta:'+38 vs yesterday', cls:'up' },
    { ic:'clock', lab:'Hours saved · mo', val:'1,742', delta:'+12%', cls:'up' },
    { ic:'target', lab:'Avg. accuracy', val:'98.1', sm:'%', delta:'across workforce', cls:'gold' },
  ];
  return (
    <div className="kpis">
      {data.map(k => (
        <div className="kpi" key={k.lab}>
          <div className="lab"><Icon name={k.ic} size={14} style={{color:'var(--gold-300)'}} />{k.lab}</div>
          <div className="val">{k.val}{k.sm && <small>{k.sm}</small>}</div>
          <div className={"delta "+k.cls}>{k.cls==='up' && <Icon name="trending-up" size={12} />}{k.delta}</div>
        </div>
      ))}
    </div>
  );
}

/* ---------------- Buddha card ---------------- */
const STATUS_LABEL = { running:'running', idle:'idle', paused:'paused', attention:'needs you' };
function BuddhaCard({ b, onOpen }) {
  return (
    <div className={"buddha "+b.status} onClick={()=>onOpen(b)}>
      <div className="buddha-top">
        <div className="b-av"><span className="ring"></span><img src={ASSETS+"logo-mark-gold.svg"} /></div>
        <div style={{minWidth:0}}>
          <div className="b-name">{b.name}</div>
          <div className="b-role">{b.role}</div>
        </div>
        <div className={"b-status st-"+b.status}><span className="d"></span>{STATUS_LABEL[b.status]}</div>
      </div>
      <div className="b-task">
        <Icon name={b.status==='attention'?'help-circle':b.status==='paused'?'pause':'loader'} size={15} className="ic" />
        <span>{b.task}</span>
      </div>
      <div className="b-meta">
        <div className="m"><span className="n">{b.tasksToday}</span><span className="l">tasks today</span></div>
        <div className="m"><span className="n">{b.accuracy}%</span><span className="l">accuracy</span></div>
        <div className="b-tools">
          {b.tools.slice(0,3).map(t => <span key={t} title={t}>{t.slice(0,2)}</span>)}
        </div>
      </div>
    </div>
  );
}

/* ---------------- Workforce view ---------------- */
function WorkforceView({ onOpen, onHire }) {
  const [filter, setFilter] = useState('all');
  const list = filter==='all' ? WORKFORCE : WORKFORCE.filter(b => filter==='active' ? (b.status==='running'||b.status==='idle') : b.status===filter);
  return (
    <div className="content-in fade-in">
      <KPIs />
      <div className="sec-head">
        <h2>Your workforce</h2><span className="ct">{WORKFORCE.length} employed</span>
        <div className="right">
          <div className="seg">
            {['all','active','attention'].map(f => (
              <button key={f} className={filter===f?'on':''} onClick={()=>setFilter(f)}>{f[0].toUpperCase()+f.slice(1)}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="wf-grid">
        {list.map(b => <BuddhaCard key={b.id} b={b} onOpen={onOpen} />)}
        <div className="hire-tile" onClick={onHire}>
          <div className="plus"><Icon name="plus" size={22} /></div>
          <div className="t">Design a new Buddha</div>
          <div className="s">Shape a role, give it tools, employ it.</div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { Icon, ASSETS, WORKFORCE, ACTIVITY, INBOX, MODELS, ALL_TOOLS, STATUS_LABEL, Sidebar, Topbar, KPIs, BuddhaCard, WorkforceView });
