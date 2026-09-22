/* ============================================================
   Hire Buddha — App main (state, mount, tweaks, icon refresh)
   ============================================================ */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "accent": "metallic",
  "density": "comfortable"
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [view, setView] = useState('workforce');
  const [selected, setSelected] = useState(null);   // selected buddha (detail)
  const [drawer, setDrawer] = useState(null);         // null = closed, {} / preset = open
  const [wf, setWf] = useState(WORKFORCE);

  useEffect(() => { document.documentElement.setAttribute('data-theme', t.theme); }, [t.theme]);
  useEffect(() => { document.documentElement.setAttribute('data-accent', t.accent); }, [t.accent]);

  // (re)create Lucide icons after every render
  useEffect(() => { if (window.lucide) window.lucide.createIcons(); });

  const openDetail = (b) => { setSelected(b); setView('detail'); };
  const openDrawer = (preset) => setDrawer(preset || {});
  const pauseB = (b) => { setWf(w => w.map(x => x.id===b.id ? {...x, status:'paused', task:'Paused by you — resume to continue'} : x)); setSelected(s => s && {...s, status:'paused'}); };
  const resumeB = (b) => { setWf(w => w.map(x => x.id===b.id ? {...x, status:'running'} : x)); setSelected(s => s && {...s, status:'running'}); };

  const counts = { workforce: wf.length, inbox: INBOX.length };

  const TITLES = {
    workforce:['Workforce', null],
    activity:['Activity', null],
    inbox:['Inbox', null],
    tools:['Tools', null],
    models:['Models', null],
    settings:['Settings', null],
  };
  const crumb = view==='detail' && selected
    ? <React.Fragment><span onClick={()=>setView('workforce')} style={{cursor:'pointer'}}>Workforce</span><Icon name="chevron-right" size={13} /><span style={{color:'var(--fg)'}}>{selected.name}</span></React.Fragment>
    : null;

  let body;
  if (view==='workforce') body = <WorkforceView onOpen={openDetail} onHire={()=>openDrawer()} />;
  else if (view==='detail' && selected) body = <AgentDetail b={selected} onPause={pauseB} onResume={resumeB} />;
  else if (view==='activity') body = <ActivityView />;
  else if (view==='inbox') body = <InboxView />;
  else if (view==='tools') body = <SimpleView icon="plug" title="Tools" lines={['Connect your stack.','Grant Gmail, Slack, Stripe, Notion and more — your Buddhas onboard themselves to whatever you connect.']} />;
  else if (view==='models') body = <SimpleView icon="cpu" title="Models" lines={['Frontier minds.','buddha-frontier-1, buddha-swift-1 and buddha-deep-1 power your workforce. Choose per role in the design step.']} />;
  else body = <SimpleView icon="settings" title="Settings" lines={['Workspace settings.','Manage members, billing, and data residency for Northwind Co.']} />;

  return (
    <div className="app">
      <Sidebar view={view==='detail'?'workforce':view} setView={(v)=>{setView(v);setSelected(null);}} counts={counts} onHire={()=>openDrawer()} />
      <div className="main">
        <Topbar title={(TITLES[view]||['',null])[0]} crumb={crumb} onHire={()=>openDrawer()} />
        <div className="content">{body}</div>
      </div>

      {drawer && <DesignDrawer preset={drawer.name?drawer:null} onClose={()=>setDrawer(null)} onEmploy={()=>{setDrawer(null);setView('workforce');}} />}

      <TweaksPanel>
        <TweakSection label="Theme" />
        <TweakRadio label="Surface" value={t.theme} options={['dark','light']} onChange={(v)=>setTweak('theme', v)} />
        <TweakSection label="Accent" />
        <TweakRadio label="Gold style" value={t.accent} options={['solid','metallic']} onChange={(v)=>setTweak('accent', v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
