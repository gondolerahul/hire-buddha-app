/* ============================================================
   Hire Buddha — Marketing app (mount + tweaks + reveal)
   ============================================================ */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "heroVariant": "centered",
  "accent": "metallic",
  "theme": "dark"
}/*EDITMODE-END*/;

function useReveal(dep) {
  useEffect(() => {
    const els = [...document.querySelectorAll('.reveal')];
    const io = new IntersectionObserver((entries) => {
      entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } });
    }, { threshold: 0.12 });
    els.forEach(el => io.observe(el));
    return () => io.disconnect();
  }, [dep]);
}

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [preset, setPreset] = useState(undefined);      // undefined = closed
  const [open, setOpen] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', t.theme);
  }, [t.theme]);

  // Render Lucide icons after every render (step + agent + modal icons)
  useEffect(() => { if (window.lucide) window.lucide.createIcons(); });

  useReveal(t.heroVariant);

  const openBlank = () => { setPreset(null); setOpen(true); };
  const openWith = (a) => { setPreset(a); setOpen(true); };
  const metallic = t.accent === 'metallic';

  return (
    <React.Fragment>
      <Nav onDesign={openBlank} />
      <Hero variant={t.heroVariant} metallic={metallic} onDesign={openBlank} />
      <HowItWorks />
      <AgentGallery onHire={openWith} />
      <Closing metallic={metallic} onDesign={openBlank} />
      <Footer />

      {open && <DesignModal preset={preset} onClose={() => setOpen(false)} />}

      <TweaksPanel>
        <TweakSection label="Hero" />
        <TweakRadio label="Direction" value={t.heroVariant}
          options={['centered','split','mark']}
          onChange={(v) => setTweak('heroVariant', v)} />
        <TweakSection label="Accent" />
        <TweakRadio label="Gold style" value={t.accent}
          options={['solid','metallic']}
          onChange={(v) => setTweak('accent', v)} />
        <TweakSection label="Theme" />
        <TweakRadio label="Surface" value={t.theme}
          options={['dark','light']}
          onChange={(v) => setTweak('theme', v)} />
      </TweaksPanel>
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
