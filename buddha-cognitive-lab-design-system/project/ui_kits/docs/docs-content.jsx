/* ============================================================
   Buddha Cognitive Lab — Docs & Blog content/data
   Exports: Icon, DASSETS, DOC_NAV, ARTICLE, POSTS
   ============================================================ */
const { useState: dUseState, useEffect: dUseEffect, useRef: dUseRef } = React;
const DASSETS = "../../assets/";

function Icon({ name, size = 18, stroke = 1.75, style, className }) {
  return <i data-lucide={name} className={className}
    style={{ width: size, height: size, strokeWidth: stroke, display: 'inline-flex', flex:'none', ...style }}></i>;
}

const DOC_NAV = [
  { group:'Get started', items:[
    { id:'intro', label:'Introduction' },
    { id:'quickstart', label:'Quickstart', on:true },
    { id:'concepts', label:'Core concepts' },
  ]},
  { group:'Building Buddhas', items:[
    { id:'design', label:'Designing a role' },
    { id:'tools', label:'Connecting tools' },
    { id:'goals', label:'Goals & guardrails' },
    { id:'memory', label:'Memory & context' },
  ]},
  { group:'Models', items:[
    { id:'frontier', label:'buddha-frontier-1' },
    { id:'swift', label:'buddha-swift-1' },
    { id:'deep', label:'buddha-deep-1' },
  ]},
  { group:'Reference', items:[
    { id:'api', label:'REST API', tag:'v1' },
    { id:'sdk', label:'Python SDK' },
    { id:'webhooks', label:'Webhooks' },
  ]},
];

/* The currently-open article (Quickstart). Blocks render in order. */
const ARTICLE = {
  crumb:['Docs','Get started','Quickstart'],
  title:'Quickstart',
  lead:'Design, employ, and observe your first autonomous Buddha in under five minutes — from the dashboard or the API.',
  toc:[
    { id:'before', label:'Before you begin' },
    { id:'design', label:'1 · Design the role' },
    { id:'employ', label:'2 · Employ it' },
    { id:'observe', label:'3 · Observe & delegate' },
    { id:'next', label:'Where to next' },
  ],
  blocks:[
    { t:'callout', cls:'', ic:'sparkles', html:'A <b>Buddha</b> is an autonomous AI employee: a role you shape, grant tools, and hold to an outcome. It works end-to-end while you rest.' },
    { t:'h2', id:'before', tx:'Before you begin' },
    { t:'p', html:'You’ll need a Buddha Cognitive Lab workspace and an API key. Create a key under <b>Settings → API keys</b>, then export it:' },
    { t:'code', lang:'bash', file:'terminal', lines:[
      [['cm','# Authenticate the CLI']],
      [['kw','export '],['nm','BUDDHA_API_KEY'],['pu','='],['st','"sk-buddha-…"']],
      [['fn','buddha '],['nm','login']],
    ]},
    { t:'h2', id:'design', tx:'1 · Design the role' },
    { t:'p', html:'Describe the employee you want. Give it a name, a goal stated as an outcome, the tools it may use, and the model that powers it.' },
    { t:'code', lang:'python', file:'hire_ops.py', lines:[
      [['kw','from '],['nm','buddha '],['kw','import '],['nm','Lab']],
      [],
      [['nm','lab '],['pu','= '],['fn','Lab'],['pu','()']],
      [],
      [['cm','# Shape an autonomous Operations employee']],
      [['nm','ops '],['pu','= '],['nm','lab'],['pu','.'],['fn','hire'],['pu','(']],
      [['pu','    '],['nm','name'],['pu','='],['st','"Operations Buddha"'],['pu',',']],
      [['pu','    '],['nm','goal'],['pu','='],['st','"Close the books monthly, < 0.1% variance"'],['pu',',']],
      [['pu','    '],['nm','tools'],['pu','='],['pu','['],['st','"stripe"'],['pu',', '],['st','"quickbooks"'],['pu',', '],['st','"gmail"'],['pu','],']],
      [['pu','    '],['nm','model'],['pu','='],['st','"buddha-frontier-1"'],['pu',',']],
      [['pu',')']],
    ]},
    { t:'callout', cls:'note', ic:'info', html:'Goals are <b>outcomes</b>, not task lists. State what “done” looks like; the Buddha plans the steps and adapts as reality changes.' },
    { t:'h2', id:'employ', tx:'2 · Employ it' },
    { t:'p', html:'Employing a Buddha onboards it to your connected tools and starts its first run. The call returns immediately with a handle you can poll or subscribe to.' },
    { t:'code', lang:'python', file:'hire_ops.py', lines:[
      [['nm','ops'],['pu','.'],['fn','employ'],['pu','()']],
      [['fn','print'],['pu','('],['nm','ops'],['pu','.'],['nm','status'],['pu',')  '],['cm','# → "running"']],
    ]},
    { t:'params', rows:[
      { n:'name', ty:'string', req:true, d:'Human-readable role name, e.g. “Support Buddha”.' },
      { n:'goal', ty:'string', req:true, d:'The outcome the employee owns, in plain language.' },
      { n:'tools', ty:'string[]', req:false, d:'Integrations the Buddha may use. It onboards itself to each.' },
      { n:'model', ty:'enum', req:false, d:'frontier-1 · swift-1 · deep-1. Defaults to frontier-1.' },
    ]},
    { t:'h2', id:'observe', tx:'3 · Observe & delegate' },
    { t:'p', html:'Every action a Buddha takes is traced. Watch the live timeline in the console, or stream events. When it needs a human decision, it lands in your <b>Inbox</b> — nothing else interrupts you.' },
    { t:'code', lang:'python', file:'watch.py', lines:[
      [['kw','for '],['nm','event '],['kw','in '],['nm','ops'],['pu','.'],['fn','stream'],['pu','():']],
      [['pu','    '],['fn','print'],['pu','('],['nm','event'],['pu','.'],['nm','summary'],['pu',')']],
    ]},
    { t:'callout', cls:'', ic:'shield-check', html:'<b>Guardrails first.</b> Buddhas ask before irreversible actions — refunds, sends, deletions — unless you grant explicit autonomy per tool.' },
    { t:'h2', id:'next', tx:'Where to next' },
    { t:'p', html:'You’ve employed your first autonomous teammate. Go deeper on shaping roles, wiring tools, and the guardrail model.' },
  ],
  prev:{ dir:'Previous', ti:'Introduction' },
  next:{ dir:'Next', ti:'Core concepts' },
};

const POSTS = [
  { id:'p1', feat:true, cat:'Research', title:'Long-horizon autonomy: how buddha-frontier-1 stays on task for days',
    excerpt:'A look at the memory architecture and self-checking loops that let a single agent own a multi-week outcome without drift.',
    author:'R', who:'Rahul', date:'May 28, 2026', read:'9 min' },
  { id:'p2', cat:'Engineering', title:'Designing guardrails that don’t get in the way',
    excerpt:'Permissioning irreversible actions per tool — and why “ask first” beats “undo later”.',
    author:'A', who:'Aisha', date:'May 14, 2026', read:'6 min' },
  { id:'p3', cat:'Product', title:'The one-person company is already here',
    excerpt:'What we learned watching solo founders run six-figure operations with a workforce of Buddhas.',
    author:'M', who:'Marco', date:'Apr 30, 2026', read:'7 min' },
  { id:'p4', cat:'Research', title:'Evaluating practical intelligence, not benchmarks',
    excerpt:'Why we measure our models on real, messy business work — and how we score it.',
    author:'R', who:'Rahul', date:'Apr 12, 2026', read:'8 min' },
  { id:'p5', cat:'Safety', title:'A calm interface for powerful agents',
    excerpt:'Design principles for keeping a human serenely in control of autonomous systems.',
    author:'A', who:'Aisha', date:'Mar 27, 2026', read:'5 min' },
];

const POST_BODY = {
  cat:'Research', title:'Long-horizon autonomy: how buddha-frontier-1 stays on task for days',
  who:'Rahul', av:'R', date:'May 28, 2026', read:'9 min',
  blocks:[
    { t:'p', html:'Most agents are sprinters. They do well on a single prompt and unravel over a long, branching task. The work that actually runs a business — closing books, nurturing a pipeline, shipping a research brief — is a <b>marathon</b>, measured in days, not turns.' },
    { t:'p', html:'<b>buddha-frontier-1</b> is built for the marathon. Three ideas do most of the work: durable memory, periodic self-checks, and an explicit goal it can always return to.' },
    { t:'h2', tx:'Memory that survives the context window' },
    { t:'p', html:'Rather than cramming everything into one prompt, a Buddha writes structured notes to durable memory as it goes — decisions, open questions, and a running model of the world it’s acting in. When it resumes, it reads the goal and the notes, not the entire history.' },
    { t:'quote', tx:'A long task is not a long prompt. It is a short prompt, held steady against a goal, many times over.' },
    { t:'h2', tx:'Self-checks instead of drift' },
    { t:'p', html:'Every few steps the agent stops and asks a plain question: <b>am I still serving the outcome?</b> If reality has changed — a payment failed, a lead went cold — it re-plans rather than barreling ahead. Drift is caught in minutes, not discovered in a weekly review.' },
    { t:'p', html:'The result is an employee you can trust with an outcome and leave alone. That, more than any benchmark, is what “frontier” means to us.' },
  ],
};

Object.assign(window, { Icon, DASSETS, DOC_NAV, ARTICLE, POSTS, POST_BODY });
