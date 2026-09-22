/* ============================================================
   Buddha Cognitive Lab — Docs & Blog app (components + mount)
   ============================================================ */
const { useState, useEffect } = React;

/* ---- code block renderer ---- */
function CodeBlock({ block }) {
  const [copied, setCopied] = useState(false);
  const text = block.lines.map(line => line.map(([,t])=>t).join('')).join('\n');
  const copy = () => { try { navigator.clipboard.writeText(text); } catch(e){} setCopied(true); setTimeout(()=>setCopied(false),1400); };
  return (
    <div className="cb">
      <div className="cb-bar">
        <Icon name="file-code" size={13} />
        <span>{block.file}</span><span className="lang">· {block.lang}</span>
        <span className="copy" onClick={copy}><Icon name={copied?'check':'copy'} size={13} />{copied?'copied':'copy'}</span>
      </div>
      <pre>{block.lines.map((line,i)=>(
        <div key={i}>{line.length===0 ? '\u00A0' : line.map(([cls,t],j)=><span key={j} className={cls}>{t}</span>)}</div>
      ))}</pre>
    </div>
  );
}

/* ---- article block dispatcher ---- */
function Block({ b }) {
  if (b.t==='h2') return <h2 id={b.id}>{b.tx}</h2>;
  if (b.t==='h3') return <h3>{b.tx}</h3>;
  if (b.t==='p')  return <p dangerouslySetInnerHTML={{__html:b.html}} />;
  if (b.t==='code') return <CodeBlock block={b} />;
  if (b.t==='callout') return (
    <div className={"callout "+(b.cls||'')}>
      <Icon name={b.ic} size={18} className="ic" />
      <div className="ct" dangerouslySetInnerHTML={{__html:b.html}} />
    </div>
  );
  if (b.t==='params') return (
    <table className="ptable">
      <thead><tr><th>Parameter</th><th>Type</th><th>Description</th></tr></thead>
      <tbody>{b.rows.map(r=>(
        <tr key={r.n}>
          <td><span className="pn">{r.n}</span>{r.req && <div className="pt" style={{color:'var(--gold-600)'}}>required</div>}</td>
          <td><span className="pt">{r.ty}</span></td>
          <td>{r.d}</td>
        </tr>
      ))}</tbody>
    </table>
  );
  return null;
}

/* ---- Header ---- */
function Header({ tab, setTab }) {
  return (
    <header className="hdr">
      <div className="hdr-in">
        <img className="hdr-logo" src={DASSETS+"logo-buddha-cognitive-lab-onblack.svg"} alt="Buddha Cognitive Lab" />
        <div className="hdr-tabs">
          {['Docs','Blog','Research'].map(t => (
            <div key={t} className={"hdr-tab"+(tab===t?" on":"")} onClick={()=>setTab(t)}>{t}</div>
          ))}
        </div>
        <div className="hdr-search">
          <Icon name="search" size={14} /><input placeholder="Search docs…" /><span className="k">/</span>
        </div>
        <button className="btn btn-primary" style={{marginLeft:14}}>Console <Icon name="arrow-up-right" size={14} /></button>
      </div>
    </header>
  );
}

/* ---- Docs view ---- */
function DocsView() {
  const [active, setActive] = useState('quickstart');
  const [toc, setToc] = useState(ARTICLE.toc[0].id);
  return (
    <div className="docs fade-in">
      <nav className="doc-nav">
        {DOC_NAV.map(g => (
          <div className="dn-group" key={g.group}>
            <h4>{g.group}</h4>
            {g.items.map(it => (
              <div key={it.id} className={"dn-item"+(active===it.id?" on":"")} onClick={()=>setActive(it.id)}>
                {it.label}{it.tag && <span className="tag">{it.tag}</span>}
              </div>
            ))}
          </div>
        ))}
      </nav>

      <article className="article">
        <div className="art-crumb">{ARTICLE.crumb.map((c,i)=>(
          <React.Fragment key={i}>{i>0 && <Icon name="chevron-right" size={12} />}<span className={i===ARTICLE.crumb.length-1?'gold':''}>{c}</span></React.Fragment>
        ))}</div>
        <h1>{ARTICLE.title}</h1>
        <p className="art-lead">{ARTICLE.lead}</p>
        {ARTICLE.blocks.map((b,i)=><Block key={i} b={b} />)}
        <div className="art-foot">
          <a><div className="dir"><Icon name="arrow-left" size={12} style={{verticalAlign:'-1px'}} /> {ARTICLE.prev.dir}</div><div className="ti">{ARTICLE.prev.ti}</div></a>
          <a className="next"><div className="dir">{ARTICLE.next.dir} <Icon name="arrow-right" size={12} style={{verticalAlign:'-1px'}} /></div><div className="ti">{ARTICLE.next.ti}</div></a>
        </div>
      </article>

      <aside className="otp">
        <h5>On this page</h5>
        {ARTICLE.toc.map(t => (
          <a key={t.id} className={toc===t.id?'on':''} onClick={()=>{setToc(t.id);const el=document.getElementById(t.id);if(el){const y=el.getBoundingClientRect().top+window.scrollY-80;window.scrollTo({top:y,behavior:'smooth'});}}}>{t.label}</a>
        ))}
      </aside>
    </div>
  );
}

/* ---- Blog index ---- */
function BlogIndex({ onOpen }) {
  return (
    <div className="blog fade-in">
      <div className="blog-hero">
        <div className="eyebrow">// From the lab</div>
        <h1>Research &amp; notes</h1>
        <p>How we build frontier minds that do real work — and what we learn watching them run.</p>
      </div>
      <div className="posts">
        {POSTS.map(p => (
          <div key={p.id} className={"post"+(p.feat?" feat":"")} onClick={()=>onOpen(p)}>
            <div className="post-art">
              <div className="glow"></div>
              <img src={DASSETS+"logo-mark-gold.svg"} />
              <img className="wm" src={DASSETS+"logo-mark-white.svg"} />
            </div>
            <div className="post-body">
              <div className="cat">{p.cat}</div>
              <h3>{p.title}</h3>
              <p>{p.excerpt}</p>
              <div className="post-meta">
                <span className="av">{p.author}</span>{p.who}<span>·</span>{p.date}<span>·</span>{p.read}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---- Blog post read ---- */
function BlogPost({ onBack }) {
  const b = POST_BODY;
  return (
    <div className="read fade-in">
      <div className="read-back" onClick={onBack}><Icon name="arrow-left" size={13} /> All posts</div>
      <div className="cat">{b.cat}</div>
      <h1>{b.title}</h1>
      <div className="read-meta"><span className="av">{b.av}</span>{b.who}<span>·</span>{b.date}<span>·</span>{b.read}</div>
      {b.blocks.map((x,i)=>{
        if (x.t==='h2') return <h2 key={i}>{x.tx}</h2>;
        if (x.t==='quote') return <blockquote key={i}>{x.tx}</blockquote>;
        return <p key={i} dangerouslySetInnerHTML={{__html:x.html}} />;
      })}
    </div>
  );
}

function Footer() {
  return (
    <footer className="foot">
      <div className="foot-in">
        <img src={DASSETS+"logo-buddha-cognitive-lab-onblack.svg"} alt="Buddha Cognitive Lab" />
        <span>© 2026 Buddha Cognitive Lab · Towards digital enlightenment</span>
        <div className="social"><a href="https://buddhalab.in">buddhalab.in</a><a href="#">@buddhalab</a></div>
      </div>
    </footer>
  );
}

/* ---- App ---- */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{ "theme": "dark" }/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [tab, setTab] = useState('Docs');
  const [post, setPost] = useState(null);

  useEffect(() => { document.documentElement.setAttribute('data-theme', t.theme); }, [t.theme]);
  useEffect(() => { if (window.lucide) window.lucide.createIcons(); });

  let body;
  if (tab==='Docs') body = <DocsView />;
  else if (tab==='Blog' || tab==='Research') body = post ? <BlogPost onBack={()=>setPost(null)} /> : <BlogIndex onOpen={(p)=>setPost(p)} />;

  return (
    <React.Fragment>
      <Header tab={tab} setTab={(x)=>{setTab(x);setPost(null);}} />
      {body}
      <Footer />
      <TweaksPanel>
        <TweakSection label="Theme" />
        <TweakRadio label="Surface" value={t.theme} options={['dark','light']} onChange={(v)=>setTweak('theme', v)} />
      </TweaksPanel>
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
