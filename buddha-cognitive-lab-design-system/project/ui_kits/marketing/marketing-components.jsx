/* ============================================================
   Hire Buddha — Marketing components
   Exports to window: Icon, Nav, Hero, HowItWorks, AgentGallery,
   Closing, Footer, DesignModal, AGENTS
   ============================================================ */
const { useState, useEffect, useRef } = React;

/* Lucide icon wrapper — SVG is created centrally by App (see refreshIcons) */
function Icon({ name, size = 20, stroke = 1.75, style }) {
  return <i data-lucide={name} style={{ width: size, height: size, strokeWidth: stroke, display: 'inline-flex', ...style }}></i>;
}

const LOGO = "../../assets/";

const AGENTS = [
  { id:'ops',   name:'Operations Buddha', role:'OPS · AUTONOMOUS', icon:'workflow',
    desc:'Runs billing, invoicing and reconciliation end-to-end. Reports to you weekly.',
    tools:['stripe','quickbooks','gmail'] },
  { id:'support', name:'Support Buddha', role:'SUPPORT · AUTONOMOUS', icon:'life-buoy',
    desc:'Answers tickets across email and chat. Escalates only what truly needs you.',
    tools:['zendesk','slack','notion'] },
  { id:'sales', name:'Sales Buddha', role:'GROWTH · AUTONOMOUS', icon:'trending-up',
    desc:'Researches leads, drafts tailored outreach, and books meetings on your calendar.',
    tools:['hubspot','gmail','calendar'] },
  { id:'research', name:'Research Buddha', role:'RESEARCH · AUTONOMOUS', icon:'flask-conical',
    desc:'Reads, synthesizes, and briefs you on any topic — with citations, not vibes.',
    tools:['web','arxiv','docs'] },
  { id:'finance', name:'Finance Buddha', role:'FINANCE · AUTONOMOUS', icon:'landmark',
    desc:'Tracks spend, forecasts runway, and files clean reports every month.',
    tools:['ramp','stripe','sheets'] },
  { id:'recruit', name:'Recruiting Buddha', role:'PEOPLE · AUTONOMOUS', icon:'users-round',
    desc:'Sources candidates, screens for fit, and schedules — you just meet the best.',
    tools:['linkedin','gmail','calendar'] },
];

const ALL_TOOLS = ['gmail','slack','stripe','notion','hubspot','quickbooks','calendar','sheets','zendesk','ramp','linkedin','web'];

/* ---------------- Nav ---------------- */
function Nav({ onDesign }) {
  return (
    <nav className="nav">
      <div className="wrap nav-inner">
        <a href="#top"><img className="nav-logo" src={LOGO+"logo-hire-buddha-onblack.svg"} alt="Hire Buddha" /></a>
        <div className="nav-links">
          <a href="#how">Product</a>
          <a href="#agents">Agents</a>
          <a href="#research">Research</a>
          <a href="#docs">Docs</a>
          <a href="#pricing">Pricing</a>
        </div>
        <div className="nav-right">
          <button className="btn btn-ghost">Sign in</button>
          <button className="btn btn-primary" onClick={onDesign}>Design your Buddha <span aria-hidden>→</span></button>
        </div>
      </div>
    </nav>
  );
}

/* ---------------- Console preview ---------------- */
function ConsolePreview() {
  return (
    <div className="console reveal">
      <div className="console-bar">
        <span className="console-dot"></span><span className="console-dot"></span><span className="console-dot"></span>
        <span className="console-title">workforce · 4 employed</span>
      </div>
      <div className="console-body">
        <div className="crow sel">
          <div className="cav"><img src={LOGO+"logo-mark-gold.svg"} /></div>
          <div className="cmeta"><div className="cnm">Operations Buddha</div><div className="csub">stripe · quickbooks · gmail</div></div>
          <div className="cstat"><span className="d"></span>running</div>
        </div>
        <div className="crow">
          <div className="cav"><img src={LOGO+"logo-mark-white.svg"} style={{opacity:.75}} /></div>
          <div className="cmeta"><div className="cnm">Support Buddha</div><div className="csub">zendesk · slack</div></div>
          <div className="cstat" style={{color:'var(--positive)'}}><span className="d" style={{background:'var(--positive)'}}></span>idle</div>
        </div>
        <div className="crow">
          <div className="cav"><img src={LOGO+"logo-mark-white.svg"} style={{opacity:.75}} /></div>
          <div className="cmeta"><div className="cnm">Research Buddha</div><div className="csub">web · arxiv · docs</div></div>
          <div className="cstat"><span className="d"></span>running</div>
        </div>
      </div>
    </div>
  );
}

/* ---------------- Hero ---------------- */
function Hero({ variant, metallic, onDesign }) {
  const cta = (
    <div className="hero-cta">
      <button className={"btn btn-lg "+(metallic?"metallic":"btn-primary")} onClick={onDesign}>Design your Buddha <span aria-hidden>→</span></button>
      <button className="btn btn-lg btn-secondary">See it work</button>
    </div>
  );
  const eyebrow = <div className="eyebrow hero-eyebrow">// Buddha Cognitive Lab</div>;
  const sub = <p className="hero-sub">Design an autonomous AI employee — give it your tools and your goals — and let it run your business, end to end.</p>;
  const note = <div className="hero-note">No headcount. No onboarding. One mind, fully employed.</div>;

  if (variant === 'split') {
    return (
      <header className="hero split" id="top">
        <div className="hero-glow" style={{left:'-200px',top:'-160px'}}></div>
        <div className="wrap">
          <div className="hero-grid">
            <div>
              {eyebrow}
              <h1>HIRE MINDS,<br/>NOT HEADCOUNT</h1>
              {sub}{cta}{note}
            </div>
            <ConsolePreview />
          </div>
        </div>
      </header>
    );
  }
  if (variant === 'mark') {
    return (
      <header className="hero mark" id="top">
        <div className="hero-glow" style={{left:'-160px',top:'-120px'}}></div>
        <div className="wrap">
          <div className="hero-grid">
            <div className="hero-medallion"><img src={LOGO+"logo-mark-black.svg"} /></div>
            <div>
              {eyebrow}
              <h1>HIRE MINDS,<br/>NOT HEADCOUNT</h1>
              {sub}{cta}{note}
            </div>
          </div>
        </div>
      </header>
    );
  }
  // centered (default)
  return (
    <header className="hero centered" id="top">
      <div className="hero-glow" style={{left:'50%',top:'-120px',transform:'translateX(-50%)'}}></div>
      <img className="hero-watermark" src={LOGO+"logo-mark-gold.svg"} />
      <div className="wrap">
        {eyebrow}
        <h1>HIRE MINDS,<br/>NOT HEADCOUNT</h1>
        {sub}{cta}{note}
      </div>
    </header>
  );
}

/* ---------------- How it works ---------------- */
const STEPS = [
  { n:'01', ico:'wand-2', t:'Design', d:'Shape a role. Name it, set a goal, choose its tools and the model that powers it.' },
  { n:'02', ico:'badge-check', t:'Employ', d:'Hire your Buddha with one click. It onboards itself to your systems and learns your way.' },
  { n:'03', ico:'workflow', t:'Automate', d:'It runs the work end-to-end — quietly, precisely, while you do what only you can.' },
];
function HowItWorks() {
  return (
    <section className="section" id="how">
      <div className="wrap">
        <div className="section-head reveal">
          <div className="eyebrow">// How it works</div>
          <h2>Three steps to your<br/>first autonomous employee.</h2>
        </div>
        <div className="steps">
          {STEPS.map(s => (
            <div className="step reveal" key={s.n}>
              <div className="step-num">{s.n}</div>
              <div className="step-ico"><Icon name={s.ico} size={22} /></div>
              <h3>{s.t}</h3>
              <p>{s.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------- Agent gallery ---------------- */
function AgentGallery({ onHire }) {
  return (
    <section className="section" id="agents" style={{paddingTop:0}}>
      <div className="wrap">
        <div className="section-head center reveal">
          <div className="eyebrow">// Pre-trained Buddhas</div>
          <h2>Start with a role. Make it yours.</h2>
          <p className="section-lead">Each Buddha arrives trained for the work. Hire one as-is, or open it up and design every detail.</p>
        </div>
        <div className="agents">
          {AGENTS.map(a => (
            <div className="agent reveal" key={a.id} onClick={() => onHire(a)}>
              <div className="agent-top">
                <div className="agent-av"><img src={LOGO+"logo-mark-gold.svg"} /></div>
                <div><h3>{a.name}</h3><div className="role">{a.role}</div></div>
              </div>
              <p>{a.desc}</p>
              <div className="chips">{a.tools.map(t => <span className="chip" key={t}>{t}</span>)}</div>
              <div className="agent-foot">
                <span className="agent-hire">Hire this Buddha <span aria-hidden>→</span></span>
                <Icon name={a.icon} size={18} style={{color:'var(--fg-faint)'}} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------------- Closing CTA ---------------- */
function Closing({ metallic, onDesign }) {
  return (
    <section className="closing" id="pricing">
      <div className="closing-glow"></div>
      <img className="closing-mark" src={LOGO+"logo-mark-gold.svg"} />
      <div className="wrap">
        <div className="eyebrow" style={{marginBottom:'22px'}}>// Begin</div>
        <h2 className="reveal">TOWARDS DIGITAL<br/>ENLIGHTENMENT</h2>
        <p className="reveal">Your workforce begins with one. Design it now — it’s working before your coffee’s cold.</p>
        <button className={"btn btn-lg "+(metallic?"metallic":"btn-primary")} onClick={onDesign}>Design your Buddha <span aria-hidden>→</span></button>
      </div>
    </section>
  );
}

/* ---------------- Footer ---------------- */
const FOOT = [
  { h:'Product', items:['Overview','Agents','Pricing','Changelog'] },
  { h:'Lab', items:['Research','Models','Safety','Publications'] },
  { h:'Company', items:['About','Careers','Blog','Contact'] },
];
function Footer() {
  return (
    <footer className="footer" id="docs">
      <div className="wrap">
        <div className="footer-grid">
          <div>
            <img className="footer-logo" src={LOGO+"logo-buddha-cognitive-lab-onblack.svg"} alt="Buddha Cognitive Lab" />
            <div className="footer-tag">A frontier AI research lab. Building minds with practical applicability.</div>
          </div>
          {FOOT.map(col => (
            <div key={col.h}>
              <h4>{col.h}</h4>
              <ul>{col.items.map(i => <li key={i}><a href="#">{i}</a></li>)}</ul>
            </div>
          ))}
        </div>
        <div className="footer-bottom">
          <span>© 2026 Buddha Cognitive Lab · Towards digital enlightenment</span>
          <div className="social"><a href="https://buddhalab.in">buddhalab.in</a><a href="#">@buddhalab</a></div>
        </div>
      </div>
    </footer>
  );
}

/* ---------------- Design modal ---------------- */
function DesignModal({ preset, onClose }) {
  const [name, setName] = useState(preset ? preset.name : 'Operations Buddha');
  const [goal, setGoal] = useState(preset ? preset.desc : '');
  const [tools, setTools] = useState(preset ? preset.tools : ['gmail']);
  const [model, setModel] = useState('buddha-frontier-1');
  const [hired, setHired] = useState(false);

  const toggle = (t) => setTools(ts => ts.includes(t) ? ts.filter(x=>x!==t) : [...ts, t]);

  useEffect(() => {
    const esc = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, []);

  return (
    <div className="scrim" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        {!hired ? (
          <React.Fragment>
            <div className="modal-head">
              <div className="agent-av"><img src={LOGO+"logo-mark-gold.svg"} /></div>
              <div className="modal-title">Design your Buddha</div>
              <button className="modal-x" onClick={onClose}><Icon name="x" size={18} /></button>
            </div>
            <div className="modal-body">
              <div className="field"><label>Role name</label>
                <input value={name} onChange={e=>setName(e.target.value)} placeholder="e.g. Operations Buddha" /></div>
              <div className="field"><label>Goal — what should it own?</label>
                <input value={goal} onChange={e=>setGoal(e.target.value)} placeholder="Close the books every month, end to end" /></div>
              <div className="field"><label>Tools it can use</label>
                <div className="tool-toggle">
                  {ALL_TOOLS.map(t => (
                    <button key={t} className={"tool"+(tools.includes(t)?" on":"")} onClick={()=>toggle(t)}>{t}</button>
                  ))}
                </div></div>
              <div className="field"><label>Model</label>
                <select value={model} onChange={e=>setModel(e.target.value)}>
                  <option value="buddha-frontier-1">buddha-frontier-1 · most capable</option>
                  <option value="buddha-swift-1">buddha-swift-1 · fast & economical</option>
                  <option value="buddha-deep-1">buddha-deep-1 · long-horizon reasoning</option>
                </select></div>
            </div>
            <div className="modal-foot">
              <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
              <button className="btn metallic" onClick={()=>setHired(true)}>Hire this Buddha <span aria-hidden>→</span></button>
            </div>
          </React.Fragment>
        ) : (
          <div className="success">
            <div className="success-mark"><img src={LOGO+"logo-mark-black.svg"} /></div>
            <h3>{name} is employed.</h3>
            <p>It’s onboarding to {tools.length} tool{tools.length!==1?'s':''} now and will start its first tasks in moments. You’ll get a brief when it’s done.</p>
            <div style={{marginTop:'26px'}}><button className="btn btn-primary" onClick={onClose}>Back to workforce</button></div>
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { Icon, Nav, Hero, ConsolePreview, HowItWorks, AgentGallery, Closing, Footer, DesignModal, AGENTS });
