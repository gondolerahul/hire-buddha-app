/* ============================================================
   Hire Buddha — App views: AgentDetail, ActivityView, InboxView,
   DesignDrawer, SimpleView
   ============================================================ */
const { useState: useState2, useEffect: useEffect2 } = React;

/* ---------------- Agent detail ---------------- */
function AgentDetail({ b, onPause, onResume }) {
  const max = Math.max(...b.spark);
  return (
    <div className="content-in fade-in">
      <div className="detail-head">
        <div className={"b-av "+(b.status==='running'?'':'')} style={{}}>
          <span className="ring" style={{borderColor: b.status==='running'?'var(--accent)':'transparent'}}></span>
          <img src={ASSETS+"logo-mark-gold.svg"} />
        </div>
        <div className="detail-title">
          <h1>{b.name}</h1>
          <div className="sub">
            <span className={"b-status st-"+b.status}><span className="d"></span>{STATUS_LABEL[b.status]}</span>
            <span>· {b.role.toLowerCase()}</span>
            <span>· employed {b.employed}</span>
            <span>· <span style={{color:'var(--gold-300)'}}>{b.model}</span></span>
          </div>
        </div>
        <div className="detail-actions">
          {b.status==='paused'
            ? <button className="btn btn-primary btn-sm" onClick={()=>onResume(b)}><Icon name="play" size={15} /> Resume</button>
            : <button className="btn btn-secondary btn-sm" onClick={()=>onPause(b)}><Icon name="pause" size={15} /> Pause</button>}
          <button className="btn btn-secondary btn-sm"><Icon name="sliders-horizontal" size={15} /> Configure</button>
        </div>
      </div>

      <div className="detail-grid">
        <div className="panel">
          <div className="panel-h">
            <Icon name="activity" size={16} style={{color:'var(--gold-300)'}} />
            <h3>Live activity</h3>
            <span className="right eyebrow">autonomous</span>
          </div>
          <div className="timeline">
            {b.timeline.map((t,i) => (
              <div className="tl-item" key={i}>
                <div className={"tl-dot "+t.cls}><Icon name={t.ic} size={14} /></div>
                <div className="tl-body">
                  <div className="tx" dangerouslySetInnerHTML={{__html:t.tx}} />
                  <div className="tm">{t.tm}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{display:'flex',flexDirection:'column',gap:22}}>
          <div className="panel">
            <div className="panel-h"><Icon name="gauge" size={16} style={{color:'var(--gold-300)'}} /><h3>This week</h3></div>
            <div className="spark">
              {b.spark.map((v,i)=><span key={i} className={v===max?'hi':''} style={{height:`${Math.max(8,v/max*48)}px`}}></span>)}
            </div>
            <div className="kv"><span className="k">Tasks today</span><span className="v">{b.tasksToday}</span></div>
            <div className="kv"><span className="k">Accuracy</span><span className="v" style={{color:'var(--positive)'}}>{b.accuracy}%</span></div>
            <div className="kv"><span className="k">Hours saved</span><span className="v">{b.hours}</span></div>
            <div className="kv"><span className="k">Model</span><span className="v"><span className="mono">{b.model}</span></span></div>
          </div>
          <div className="panel">
            <div className="panel-h"><Icon name="plug" size={16} style={{color:'var(--gold-300)'}} /><h3>Connected tools</h3></div>
            <div className="tool-list">
              {b.tools.map(t => <span className="tool-pill" key={t}><span className="d"></span>{t}</span>)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------------- Activity view ---------------- */
function ActivityView() {
  return (
    <div className="content-in fade-in">
      <div className="sec-head"><h2>Activity</h2><span className="ct">across your workforce</span>
        <div className="right"><button className="btn btn-secondary btn-sm"><Icon name="sliders-horizontal" size={14} /> Filter</button></div></div>
      <div className="feed">
        {ACTIVITY.map((a,i) => (
          <div className="feed-row" key={i}>
            <div className="feed-av"><img src={ASSETS+"logo-mark-gold.svg"} /></div>
            <div className="feed-tx"><span className="who">{a.who}</span> {a.tx}</div>
            <span className={"feed-tag "+a.cls}>{a.tag}</span>
            <span className="feed-tm">{a.tm}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------- Inbox view ---------------- */
function InboxView({ onResolve }) {
  const [items, setItems] = useState2(INBOX);
  const resolve = (i) => setItems(its => its.filter((_,x)=>x!==i));
  return (
    <div className="content-in fade-in">
      <div className="sec-head"><h2>Inbox</h2><span className="ct">{items.length} need your input</span></div>
      {items.length === 0 ? (
        <div className="empty">
          <div className="ic"><Icon name="check" size={24} /></div>
          <div style={{fontFamily:'var(--font-display)',fontWeight:600,fontSize:18,color:'var(--fg)'}}>Inbox zero.</div>
          <div style={{marginTop:6}}>Your workforce is running without you. Rest well.</div>
        </div>
      ) : (
        <div className="feed">
          {items.map((q,i) => (
            <div className="inbox-row" key={i}>
              <div className="feed-av"><img src={ASSETS+"logo-mark-gold.svg"} /></div>
              <div className="inbox-q">
                <div className="t">{q.t}</div>
                <div className="d"><span style={{color:'var(--gold-300)',fontFamily:'var(--font-mono)',fontSize:12}}>{q.who}</span> · {q.d}</div>
              </div>
              <span className="feed-tm">{q.tm}</span>
              <div className="inbox-act">
                <button className="btn btn-ghost btn-sm" onClick={()=>resolve(i)}>Dismiss</button>
                <button className="btn btn-primary btn-sm" onClick={()=>resolve(i)}>Approve</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- Simple placeholder views (Tools / Models / Settings) ---------------- */
function SimpleView({ icon, title, lines }) {
  return (
    <div className="content-in fade-in">
      <div className="sec-head"><h2>{title}</h2></div>
      <div className="empty">
        <div className="ic"><Icon name={icon} size={24} /></div>
        <div style={{fontFamily:'var(--font-display)',fontWeight:600,fontSize:18,color:'var(--fg)'}}>{lines[0]}</div>
        <div style={{marginTop:6,maxWidth:380,marginInline:'auto'}}>{lines[1]}</div>
      </div>
    </div>
  );
}

/* ---------------- Design drawer ---------------- */
function DesignDrawer({ preset, onClose, onEmploy }) {
  const [name, setName] = useState2(preset ? preset.name : '');
  const [goal, setGoal] = useState2(preset ? preset.task : '');
  const [tools, setTools] = useState2(preset ? preset.tools : ['gmail']);
  const [model, setModel] = useState2('buddha-frontier-1');
  const [done, setDone] = useState2(false);
  const toggle = (t) => setTools(ts => ts.includes(t) ? ts.filter(x=>x!==t) : [...ts, t]);

  useEffect2(() => {
    const esc = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', esc);
    if (window.lucide) window.lucide.createIcons();
    return () => window.removeEventListener('keydown', esc);
  });

  return (
    <div className="scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="drawer">
        {!done ? (
          <React.Fragment>
            <div className="drawer-head">
              <div className="b-av"><img src={ASSETS+"logo-mark-gold.svg"} /></div>
              <div><div className="t">Design a Buddha</div><div className="s">Shape a role · give it tools · employ it</div></div>
              <button className="drawer-x" onClick={onClose}><Icon name="x" size={18} /></button>
            </div>
            <div className="drawer-body">
              <div className="field">
                <label>Role name</label>
                <div className="hint">What should this employee be called?</div>
                <input value={name} onChange={e=>setName(e.target.value)} placeholder="e.g. Operations Buddha" />
              </div>
              <div className="field">
                <label>Goal</label>
                <div className="hint">Describe the outcome it owns, end to end.</div>
                <textarea rows={3} value={goal} onChange={e=>setGoal(e.target.value)} placeholder="Close the books every month with under 0.1% variance, and brief me weekly." />
              </div>
              <div className="field">
                <label>Tools it can use</label>
                <div className="hint">It onboards itself to whatever you grant.</div>
                <div className="tool-toggle">
                  {ALL_TOOLS.map(t => (
                    <button key={t} className={"tool"+(tools.includes(t)?" on":"")} onClick={()=>toggle(t)}>
                      {tools.includes(t) && <Icon name="check" size={12} />}{t}
                    </button>
                  ))}
                </div>
              </div>
              <div className="field">
                <label>Model</label>
                <div className="hint">The mind that powers it.</div>
                {MODELS.map(m => (
                  <div key={m.id} className={"model-opt"+(model===m.id?" on":"")} onClick={()=>setModel(m.id)}>
                    <span className="radio"></span>
                    <div><div className="mn">{m.name}</div><div className="md">{m.desc}</div></div>
                  </div>
                ))}
              </div>
            </div>
            <div className="drawer-foot">
              <span className="mono" style={{fontSize:12,color:'var(--fg-subtle)'}}>{tools.length} tool{tools.length!==1?'s':''} · {model}</span>
              <button className="btn btn-metal" onClick={()=>setDone(true)} disabled={!name}>
                <Icon name="badge-check" size={16} /> Employ this Buddha
              </button>
            </div>
          </React.Fragment>
        ) : (
          <div className="dsuccess">
            <div className="mark"><img src={ASSETS+"logo-mark-black.svg"} /></div>
            <h3>{name || 'Your Buddha'} is employed.</h3>
            <p>It’s onboarding to {tools.length} tool{tools.length!==1?'s':''} now and will start its first tasks in moments. You’ll get a brief when it’s done.</p>
            <button className="btn btn-primary" onClick={()=>onEmploy({ name, goal, tools, model })}>
              <Icon name="arrow-left" size={15} /> Back to workforce
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { AgentDetail, ActivityView, InboxView, SimpleView, DesignDrawer });
