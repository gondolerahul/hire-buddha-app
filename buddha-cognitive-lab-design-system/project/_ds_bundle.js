/* @ds-bundle: {"format":3,"namespace":"BuddhaCognitiveLabDesignSystem_dc9495","components":[],"sourceHashes":{"ui_kits/app/app-components.jsx":"cee262cca695","ui_kits/app/app-main.jsx":"3612a41dd816","ui_kits/app/app-views.jsx":"cbc8c9d79765","ui_kits/app/tweaks-panel.jsx":"6591467622ed","ui_kits/docs/docs-app.jsx":"a7be31d4ea7c","ui_kits/docs/docs-content.jsx":"fd32b9d62ac4","ui_kits/docs/tweaks-panel.jsx":"6591467622ed","ui_kits/marketing/app.jsx":"69910f970605","ui_kits/marketing/marketing-components.jsx":"1b32815c725e","ui_kits/marketing/tweaks-panel.jsx":"6591467622ed"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.BuddhaCognitiveLabDesignSystem_dc9495 = window.BuddhaCognitiveLabDesignSystem_dc9495 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// ui_kits/app/app-components.jsx
try { (() => {
/* ============================================================
   Hire Buddha — App data + shell + workforce
   Exports: Icon, ASSETS, WORKFORCE, ACTIVITY, INBOX, MODELS, ALL_TOOLS,
            Sidebar, Topbar, KPIs, WorkforceView
   ============================================================ */
const {
  useState,
  useEffect,
  useRef
} = React;
const ASSETS = "../../assets/";
function Icon({
  name,
  size = 18,
  stroke = 1.75,
  style,
  className
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": name,
    className: className,
    style: {
      width: size,
      height: size,
      strokeWidth: stroke,
      display: 'inline-flex',
      flex: 'none',
      ...style
    }
  });
}
const MODELS = [{
  id: 'buddha-frontier-1',
  name: 'buddha-frontier-1',
  desc: 'Most capable · long-horizon autonomy'
}, {
  id: 'buddha-swift-1',
  name: 'buddha-swift-1',
  desc: 'Fast & economical · high-volume work'
}, {
  id: 'buddha-deep-1',
  name: 'buddha-deep-1',
  desc: 'Deepest reasoning · research & analysis'
}];
const ALL_TOOLS = ['gmail', 'slack', 'stripe', 'notion', 'hubspot', 'quickbooks', 'calendar', 'sheets', 'zendesk', 'ramp', 'linkedin', 'web', 'github', 'salesforce'];

/* Employed Buddhas (the workspace's autonomous workforce) */
const WORKFORCE = [{
  id: 'ops',
  name: 'Operations Buddha',
  role: 'OPS · AUTONOMOUS',
  status: 'running',
  model: 'buddha-frontier-1',
  task: 'Reconciling October invoices in QuickBooks',
  tasksToday: 42,
  accuracy: 99.2,
  hours: 618,
  tools: ['stripe', 'quickbooks', 'gmail'],
  employed: 'Aug 2025',
  spark: [5, 7, 6, 9, 8, 11, 10, 13, 12, 14, 13, 16],
  timeline: [{
    ic: 'check',
    cls: 'ok',
    tx: 'Closed and filed <b>September books</b> — variance under 0.1%.',
    tm: '2 min ago'
  }, {
    ic: 'file-text',
    cls: 'gold',
    tx: 'Reconciled 38 Stripe payouts against <span class="tool">quickbooks</span>.',
    tm: '34 min ago'
  }, {
    ic: 'mail',
    cls: '',
    tx: 'Emailed 3 vendors about <b>mismatched invoices</b> via <span class="tool">gmail</span>.',
    tm: '1 hr ago'
  }, {
    ic: 'play',
    cls: 'gold',
    tx: 'Started monthly close run for <b>October</b>.',
    tm: '3 hr ago'
  }]
}, {
  id: 'support',
  name: 'Support Buddha',
  role: 'SUPPORT · AUTONOMOUS',
  status: 'idle',
  model: 'buddha-swift-1',
  task: 'Inbox clear — watching for new tickets',
  tasksToday: 128,
  accuracy: 97.5,
  hours: 512,
  tools: ['zendesk', 'slack', 'notion'],
  employed: 'Sep 2025',
  spark: [14, 12, 16, 11, 13, 9, 12, 8, 10, 7, 9, 6],
  timeline: [{
    ic: 'check',
    cls: 'ok',
    tx: 'Resolved ticket <b>#4821</b> — refund processed and confirmed.',
    tm: '8 min ago'
  }, {
    ic: 'message-square',
    cls: '',
    tx: 'Answered 12 chats in <span class="tool">slack</span> shared inbox.',
    tm: '40 min ago'
  }, {
    ic: 'arrow-up',
    cls: 'gold',
    tx: 'Escalated 1 billing dispute to <b>you</b> for approval.',
    tm: '2 hr ago'
  }]
}, {
  id: 'sales',
  name: 'Sales Buddha',
  role: 'GROWTH · AUTONOMOUS',
  status: 'running',
  model: 'buddha-frontier-1',
  task: 'Drafting outreach to 14 qualified leads',
  tasksToday: 31,
  accuracy: 96.0,
  hours: 240,
  tools: ['hubspot', 'gmail', 'calendar'],
  employed: 'Oct 2025',
  spark: [3, 5, 4, 6, 8, 7, 9, 10, 9, 12, 11, 13],
  timeline: [{
    ic: 'user-plus',
    cls: 'gold',
    tx: 'Qualified <b>14 new leads</b> from this week’s signups.',
    tm: '12 min ago'
  }, {
    ic: 'calendar',
    cls: 'ok',
    tx: 'Booked 2 demos on your <span class="tool">calendar</span>.',
    tm: '1 hr ago'
  }, {
    ic: 'mail',
    cls: '',
    tx: 'Sent 21 tailored outreach emails.',
    tm: '4 hr ago'
  }]
}, {
  id: 'research',
  name: 'Research Buddha',
  role: 'RESEARCH · AUTONOMOUS',
  status: 'attention',
  model: 'buddha-deep-1',
  task: 'Needs your input: scope the competitor brief',
  tasksToday: 6,
  accuracy: 98.8,
  hours: 96,
  tools: ['web', 'notion', 'sheets'],
  employed: 'Nov 2025',
  spark: [2, 3, 2, 4, 3, 5, 4, 6, 5, 4, 6, 5],
  timeline: [{
    ic: 'help-circle',
    cls: '',
    tx: 'Asked <b>you</b>: should the brief include pricing teardown?',
    tm: '18 min ago'
  }, {
    ic: 'book-open',
    cls: 'gold',
    tx: 'Synthesized 22 sources into a <span class="tool">notion</span> doc.',
    tm: '2 hr ago'
  }, {
    ic: 'search',
    cls: '',
    tx: 'Gathered market data across <span class="tool">web</span>.',
    tm: '5 hr ago'
  }]
}, {
  id: 'finance',
  name: 'Finance Buddha',
  role: 'FINANCE · AUTONOMOUS',
  status: 'running',
  model: 'buddha-frontier-1',
  task: 'Forecasting Q1 runway from latest spend',
  tasksToday: 9,
  accuracy: 99.6,
  hours: 184,
  tools: ['ramp', 'stripe', 'sheets'],
  employed: 'Sep 2025',
  spark: [6, 6, 7, 7, 8, 8, 9, 9, 10, 11, 12, 12],
  timeline: [{
    ic: 'trending-up',
    cls: 'gold',
    tx: 'Updated runway model — <b>17.2 months</b> at current burn.',
    tm: '25 min ago'
  }, {
    ic: 'check',
    cls: 'ok',
    tx: 'Categorized 214 <span class="tool">ramp</span> transactions.',
    tm: '3 hr ago'
  }]
}, {
  id: 'recruit',
  name: 'Recruiting Buddha',
  role: 'PEOPLE · AUTONOMOUS',
  status: 'paused',
  model: 'buddha-swift-1',
  task: 'Paused by you — resume to continue sourcing',
  tasksToday: 0,
  accuracy: 95.4,
  hours: 72,
  tools: ['linkedin', 'gmail', 'calendar'],
  employed: 'Nov 2025',
  spark: [4, 5, 3, 6, 4, 2, 3, 1, 2, 0, 0, 0],
  timeline: [{
    ic: 'pause',
    cls: '',
    tx: 'Paused by <b>you</b> while the role is on hold.',
    tm: 'Yesterday'
  }, {
    ic: 'users',
    cls: 'gold',
    tx: 'Shortlisted 8 candidates for <b>Senior Designer</b>.',
    tm: '2 days ago'
  }]
}];
const ACTIVITY = [{
  who: 'Operations Buddha',
  tx: 'closed and filed September books — variance under 0.1%',
  tm: '2 min ago',
  tag: 'done',
  cls: 'ok'
}, {
  who: 'Support Buddha',
  tx: 'resolved ticket #4821 and processed a refund',
  tm: '8 min ago',
  tag: 'done',
  cls: 'ok'
}, {
  who: 'Sales Buddha',
  tx: 'qualified 14 new leads and started outreach',
  tm: '12 min ago',
  tag: 'running',
  cls: 'gold'
}, {
  who: 'Research Buddha',
  tx: 'asked you a question about the competitor brief',
  tm: '18 min ago',
  tag: 'needs you',
  cls: ''
}, {
  who: 'Finance Buddha',
  tx: 'updated the Q1 runway model — 17.2 months',
  tm: '25 min ago',
  tag: 'running',
  cls: 'gold'
}, {
  who: 'Support Buddha',
  tx: 'answered 12 chats across the shared Slack inbox',
  tm: '40 min ago',
  tag: 'done',
  cls: 'ok'
}, {
  who: 'Sales Buddha',
  tx: 'booked 2 product demos on your calendar',
  tm: '1 hr ago',
  tag: 'done',
  cls: 'ok'
}, {
  who: 'Operations Buddha',
  tx: 'emailed 3 vendors about mismatched invoices',
  tm: '1 hr ago',
  tag: 'done',
  cls: 'ok'
}, {
  who: 'Finance Buddha',
  tx: 'categorized 214 Ramp transactions',
  tm: '3 hr ago',
  tag: 'done',
  cls: 'ok'
}];
const INBOX = [{
  who: 'Research Buddha',
  t: 'Scope question — competitor brief',
  d: 'Should the brief include a pricing teardown? It adds ~2 hours but sharpens positioning.',
  tm: '18 min ago'
}, {
  who: 'Support Buddha',
  t: 'Approve refund — $480 billing dispute',
  d: 'Customer disputes a duplicate charge. Evidence supports a refund. Approve to proceed.',
  tm: '2 hr ago'
}, {
  who: 'Sales Buddha',
  t: 'Approve outreach copy',
  d: 'Drafted a 3-touch sequence for the enterprise segment. Review tone before it sends.',
  tm: '4 hr ago'
}];

/* ---------------- Sidebar ---------------- */
function Sidebar({
  view,
  setView,
  counts,
  onHire
}) {
  const items = [{
    id: 'workforce',
    ic: 'users-round',
    label: 'Workforce',
    ct: counts.workforce
  }, {
    id: 'activity',
    ic: 'activity',
    label: 'Activity'
  }, {
    id: 'inbox',
    ic: 'inbox',
    label: 'Inbox',
    ct: counts.inbox
  }];
  const lab = [{
    id: 'tools',
    ic: 'plug',
    label: 'Tools'
  }, {
    id: 'models',
    ic: 'cpu',
    label: 'Models'
  }, {
    id: 'settings',
    ic: 'settings',
    label: 'Settings'
  }];
  return /*#__PURE__*/React.createElement("aside", {
    className: "side"
  }, /*#__PURE__*/React.createElement("div", {
    className: "side-logo"
  }, /*#__PURE__*/React.createElement("img", {
    src: ASSETS + "logo-hire-buddha-onblack.svg",
    alt: "Hire Buddha"
  })), /*#__PURE__*/React.createElement("div", {
    className: "side-org"
  }, /*#__PURE__*/React.createElement("span", {
    className: "badge"
  }, /*#__PURE__*/React.createElement("img", {
    src: ASSETS + "logo-mark-black.svg"
  })), /*#__PURE__*/React.createElement("div", {
    className: "meta"
  }, /*#__PURE__*/React.createElement("div", {
    className: "nm"
  }, "Northwind Co."), /*#__PURE__*/React.createElement("div", {
    className: "pl"
  }, "Studio plan \xB7 6 employed")), /*#__PURE__*/React.createElement(Icon, {
    name: "chevrons-up-down",
    size: 15,
    className: "chev",
    style: {
      color: 'var(--fg-subtle)'
    }
  })), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-metal",
    style: {
      width: '100%',
      justifyContent: 'center',
      marginBottom: 4
    },
    onClick: onHire
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "plus",
    size: 16
  }), " Hire a Buddha"), /*#__PURE__*/React.createElement("div", {
    className: "nav-group"
  }, "Workspace"), items.map(it => /*#__PURE__*/React.createElement("div", {
    key: it.id,
    className: "nav-item" + (view === it.id ? " on" : ""),
    onClick: () => setView(it.id)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: it.ic,
    size: 18
  }), /*#__PURE__*/React.createElement("span", null, it.label), it.ct ? /*#__PURE__*/React.createElement("span", {
    className: "ct"
  }, it.ct) : null)), /*#__PURE__*/React.createElement("div", {
    className: "nav-group"
  }, "Lab"), lab.map(it => /*#__PURE__*/React.createElement("div", {
    key: it.id,
    className: "nav-item" + (view === it.id ? " on" : ""),
    onClick: () => setView(it.id)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: it.ic,
    size: 18
  }), /*#__PURE__*/React.createElement("span", null, it.label))), /*#__PURE__*/React.createElement("div", {
    className: "side-foot"
  }, /*#__PURE__*/React.createElement("span", {
    className: "av"
  }, "R"), /*#__PURE__*/React.createElement("div", {
    className: "meta"
  }, /*#__PURE__*/React.createElement("div", {
    className: "nm"
  }, "Rahul"), /*#__PURE__*/React.createElement("div", {
    className: "em"
  }, "rahul@northwind.co"))));
}

/* ---------------- Topbar ---------------- */
function Topbar({
  title,
  crumb,
  onHire
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "topbar"
  }, crumb ? /*#__PURE__*/React.createElement("div", {
    className: "crumb"
  }, crumb) : /*#__PURE__*/React.createElement("h1", null, title), /*#__PURE__*/React.createElement("div", {
    className: "search"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "search",
    size: 15
  }), /*#__PURE__*/React.createElement("input", {
    placeholder: "Search workforce, runs, tools\u2026"
  }), /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "\u2318K")), /*#__PURE__*/React.createElement("div", {
    className: "top-right"
  }, /*#__PURE__*/React.createElement("button", {
    className: "icon-btn"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "bell",
    size: 17
  }), /*#__PURE__*/React.createElement("span", {
    className: "dot"
  })), /*#__PURE__*/React.createElement("button", {
    className: "icon-btn"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "life-buoy",
    size: 17
  })), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary btn-sm",
    onClick: onHire
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "plus",
    size: 15
  }), " Hire")));
}

/* ---------------- KPIs ---------------- */
function KPIs() {
  const data = [{
    ic: 'users-round',
    lab: 'Employed',
    val: '6',
    delta: '4 running now',
    cls: 'gold'
  }, {
    ic: 'zap',
    lab: 'Tasks today',
    val: '216',
    delta: '+38 vs yesterday',
    cls: 'up'
  }, {
    ic: 'clock',
    lab: 'Hours saved · mo',
    val: '1,742',
    delta: '+12%',
    cls: 'up'
  }, {
    ic: 'target',
    lab: 'Avg. accuracy',
    val: '98.1',
    sm: '%',
    delta: 'across workforce',
    cls: 'gold'
  }];
  return /*#__PURE__*/React.createElement("div", {
    className: "kpis"
  }, data.map(k => /*#__PURE__*/React.createElement("div", {
    className: "kpi",
    key: k.lab
  }, /*#__PURE__*/React.createElement("div", {
    className: "lab"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: k.ic,
    size: 14,
    style: {
      color: 'var(--gold-300)'
    }
  }), k.lab), /*#__PURE__*/React.createElement("div", {
    className: "val"
  }, k.val, k.sm && /*#__PURE__*/React.createElement("small", null, k.sm)), /*#__PURE__*/React.createElement("div", {
    className: "delta " + k.cls
  }, k.cls === 'up' && /*#__PURE__*/React.createElement(Icon, {
    name: "trending-up",
    size: 12
  }), k.delta))));
}

/* ---------------- Buddha card ---------------- */
const STATUS_LABEL = {
  running: 'running',
  idle: 'idle',
  paused: 'paused',
  attention: 'needs you'
};
function BuddhaCard({
  b,
  onOpen
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "buddha " + b.status,
    onClick: () => onOpen(b)
  }, /*#__PURE__*/React.createElement("div", {
    className: "buddha-top"
  }, /*#__PURE__*/React.createElement("div", {
    className: "b-av"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ring"
  }), /*#__PURE__*/React.createElement("img", {
    src: ASSETS + "logo-mark-gold.svg"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "b-name"
  }, b.name), /*#__PURE__*/React.createElement("div", {
    className: "b-role"
  }, b.role)), /*#__PURE__*/React.createElement("div", {
    className: "b-status st-" + b.status
  }, /*#__PURE__*/React.createElement("span", {
    className: "d"
  }), STATUS_LABEL[b.status])), /*#__PURE__*/React.createElement("div", {
    className: "b-task"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: b.status === 'attention' ? 'help-circle' : b.status === 'paused' ? 'pause' : 'loader',
    size: 15,
    className: "ic"
  }), /*#__PURE__*/React.createElement("span", null, b.task)), /*#__PURE__*/React.createElement("div", {
    className: "b-meta"
  }, /*#__PURE__*/React.createElement("div", {
    className: "m"
  }, /*#__PURE__*/React.createElement("span", {
    className: "n"
  }, b.tasksToday), /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "tasks today")), /*#__PURE__*/React.createElement("div", {
    className: "m"
  }, /*#__PURE__*/React.createElement("span", {
    className: "n"
  }, b.accuracy, "%"), /*#__PURE__*/React.createElement("span", {
    className: "l"
  }, "accuracy")), /*#__PURE__*/React.createElement("div", {
    className: "b-tools"
  }, b.tools.slice(0, 3).map(t => /*#__PURE__*/React.createElement("span", {
    key: t,
    title: t
  }, t.slice(0, 2))))));
}

/* ---------------- Workforce view ---------------- */
function WorkforceView({
  onOpen,
  onHire
}) {
  const [filter, setFilter] = useState('all');
  const list = filter === 'all' ? WORKFORCE : WORKFORCE.filter(b => filter === 'active' ? b.status === 'running' || b.status === 'idle' : b.status === filter);
  return /*#__PURE__*/React.createElement("div", {
    className: "content-in fade-in"
  }, /*#__PURE__*/React.createElement(KPIs, null), /*#__PURE__*/React.createElement("div", {
    className: "sec-head"
  }, /*#__PURE__*/React.createElement("h2", null, "Your workforce"), /*#__PURE__*/React.createElement("span", {
    className: "ct"
  }, WORKFORCE.length, " employed"), /*#__PURE__*/React.createElement("div", {
    className: "right"
  }, /*#__PURE__*/React.createElement("div", {
    className: "seg"
  }, ['all', 'active', 'attention'].map(f => /*#__PURE__*/React.createElement("button", {
    key: f,
    className: filter === f ? 'on' : '',
    onClick: () => setFilter(f)
  }, f[0].toUpperCase() + f.slice(1)))))), /*#__PURE__*/React.createElement("div", {
    className: "wf-grid"
  }, list.map(b => /*#__PURE__*/React.createElement(BuddhaCard, {
    key: b.id,
    b: b,
    onOpen: onOpen
  })), /*#__PURE__*/React.createElement("div", {
    className: "hire-tile",
    onClick: onHire
  }, /*#__PURE__*/React.createElement("div", {
    className: "plus"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "plus",
    size: 22
  })), /*#__PURE__*/React.createElement("div", {
    className: "t"
  }, "Design a new Buddha"), /*#__PURE__*/React.createElement("div", {
    className: "s"
  }, "Shape a role, give it tools, employ it."))));
}
Object.assign(window, {
  Icon,
  ASSETS,
  WORKFORCE,
  ACTIVITY,
  INBOX,
  MODELS,
  ALL_TOOLS,
  STATUS_LABEL,
  Sidebar,
  Topbar,
  KPIs,
  BuddhaCard,
  WorkforceView
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/app-components.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/app-main.jsx
try { (() => {
/* ============================================================
   Hire Buddha — App main (state, mount, tweaks, icon refresh)
   ============================================================ */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark",
  "accent": "metallic",
  "density": "comfortable"
} /*EDITMODE-END*/;
function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [view, setView] = useState('workforce');
  const [selected, setSelected] = useState(null); // selected buddha (detail)
  const [drawer, setDrawer] = useState(null); // null = closed, {} / preset = open
  const [wf, setWf] = useState(WORKFORCE);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', t.theme);
  }, [t.theme]);
  useEffect(() => {
    document.documentElement.setAttribute('data-accent', t.accent);
  }, [t.accent]);

  // (re)create Lucide icons after every render
  useEffect(() => {
    if (window.lucide) window.lucide.createIcons();
  });
  const openDetail = b => {
    setSelected(b);
    setView('detail');
  };
  const openDrawer = preset => setDrawer(preset || {});
  const pauseB = b => {
    setWf(w => w.map(x => x.id === b.id ? {
      ...x,
      status: 'paused',
      task: 'Paused by you — resume to continue'
    } : x));
    setSelected(s => s && {
      ...s,
      status: 'paused'
    });
  };
  const resumeB = b => {
    setWf(w => w.map(x => x.id === b.id ? {
      ...x,
      status: 'running'
    } : x));
    setSelected(s => s && {
      ...s,
      status: 'running'
    });
  };
  const counts = {
    workforce: wf.length,
    inbox: INBOX.length
  };
  const TITLES = {
    workforce: ['Workforce', null],
    activity: ['Activity', null],
    inbox: ['Inbox', null],
    tools: ['Tools', null],
    models: ['Models', null],
    settings: ['Settings', null]
  };
  const crumb = view === 'detail' && selected ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    onClick: () => setView('workforce'),
    style: {
      cursor: 'pointer'
    }
  }, "Workforce"), /*#__PURE__*/React.createElement(Icon, {
    name: "chevron-right",
    size: 13
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--fg)'
    }
  }, selected.name)) : null;
  let body;
  if (view === 'workforce') body = /*#__PURE__*/React.createElement(WorkforceView, {
    onOpen: openDetail,
    onHire: () => openDrawer()
  });else if (view === 'detail' && selected) body = /*#__PURE__*/React.createElement(AgentDetail, {
    b: selected,
    onPause: pauseB,
    onResume: resumeB
  });else if (view === 'activity') body = /*#__PURE__*/React.createElement(ActivityView, null);else if (view === 'inbox') body = /*#__PURE__*/React.createElement(InboxView, null);else if (view === 'tools') body = /*#__PURE__*/React.createElement(SimpleView, {
    icon: "plug",
    title: "Tools",
    lines: ['Connect your stack.', 'Grant Gmail, Slack, Stripe, Notion and more — your Buddhas onboard themselves to whatever you connect.']
  });else if (view === 'models') body = /*#__PURE__*/React.createElement(SimpleView, {
    icon: "cpu",
    title: "Models",
    lines: ['Frontier minds.', 'buddha-frontier-1, buddha-swift-1 and buddha-deep-1 power your workforce. Choose per role in the design step.']
  });else body = /*#__PURE__*/React.createElement(SimpleView, {
    icon: "settings",
    title: "Settings",
    lines: ['Workspace settings.', 'Manage members, billing, and data residency for Northwind Co.']
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "app"
  }, /*#__PURE__*/React.createElement(Sidebar, {
    view: view === 'detail' ? 'workforce' : view,
    setView: v => {
      setView(v);
      setSelected(null);
    },
    counts: counts,
    onHire: () => openDrawer()
  }), /*#__PURE__*/React.createElement("div", {
    className: "main"
  }, /*#__PURE__*/React.createElement(Topbar, {
    title: (TITLES[view] || ['', null])[0],
    crumb: crumb,
    onHire: () => openDrawer()
  }), /*#__PURE__*/React.createElement("div", {
    className: "content"
  }, body)), drawer && /*#__PURE__*/React.createElement(DesignDrawer, {
    preset: drawer.name ? drawer : null,
    onClose: () => setDrawer(null),
    onEmploy: () => {
      setDrawer(null);
      setView('workforce');
    }
  }), /*#__PURE__*/React.createElement(TweaksPanel, null, /*#__PURE__*/React.createElement(TweakSection, {
    label: "Theme"
  }), /*#__PURE__*/React.createElement(TweakRadio, {
    label: "Surface",
    value: t.theme,
    options: ['dark', 'light'],
    onChange: v => setTweak('theme', v)
  }), /*#__PURE__*/React.createElement(TweakSection, {
    label: "Accent"
  }), /*#__PURE__*/React.createElement(TweakRadio, {
    label: "Gold style",
    value: t.accent,
    options: ['solid', 'metallic'],
    onChange: v => setTweak('accent', v)
  })));
}
ReactDOM.createRoot(document.getElementById('root')).render(/*#__PURE__*/React.createElement(App, null));
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/app-main.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/app-views.jsx
try { (() => {
/* ============================================================
   Hire Buddha — App views: AgentDetail, ActivityView, InboxView,
   DesignDrawer, SimpleView
   ============================================================ */
const {
  useState: useState2,
  useEffect: useEffect2
} = React;

/* ---------------- Agent detail ---------------- */
function AgentDetail({
  b,
  onPause,
  onResume
}) {
  const max = Math.max(...b.spark);
  return /*#__PURE__*/React.createElement("div", {
    className: "content-in fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "detail-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "b-av " + (b.status === 'running' ? '' : ''),
    style: {}
  }, /*#__PURE__*/React.createElement("span", {
    className: "ring",
    style: {
      borderColor: b.status === 'running' ? 'var(--accent)' : 'transparent'
    }
  }), /*#__PURE__*/React.createElement("img", {
    src: ASSETS + "logo-mark-gold.svg"
  })), /*#__PURE__*/React.createElement("div", {
    className: "detail-title"
  }, /*#__PURE__*/React.createElement("h1", null, b.name), /*#__PURE__*/React.createElement("div", {
    className: "sub"
  }, /*#__PURE__*/React.createElement("span", {
    className: "b-status st-" + b.status
  }, /*#__PURE__*/React.createElement("span", {
    className: "d"
  }), STATUS_LABEL[b.status]), /*#__PURE__*/React.createElement("span", null, "\xB7 ", b.role.toLowerCase()), /*#__PURE__*/React.createElement("span", null, "\xB7 employed ", b.employed), /*#__PURE__*/React.createElement("span", null, "\xB7 ", /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--gold-300)'
    }
  }, b.model)))), /*#__PURE__*/React.createElement("div", {
    className: "detail-actions"
  }, b.status === 'paused' ? /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary btn-sm",
    onClick: () => onResume(b)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "play",
    size: 15
  }), " Resume") : /*#__PURE__*/React.createElement("button", {
    className: "btn btn-secondary btn-sm",
    onClick: () => onPause(b)
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "pause",
    size: 15
  }), " Pause"), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-secondary btn-sm"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sliders-horizontal",
    size: 15
  }), " Configure"))), /*#__PURE__*/React.createElement("div", {
    className: "detail-grid"
  }, /*#__PURE__*/React.createElement("div", {
    className: "panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "panel-h"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "activity",
    size: 16,
    style: {
      color: 'var(--gold-300)'
    }
  }), /*#__PURE__*/React.createElement("h3", null, "Live activity"), /*#__PURE__*/React.createElement("span", {
    className: "right eyebrow"
  }, "autonomous")), /*#__PURE__*/React.createElement("div", {
    className: "timeline"
  }, b.timeline.map((t, i) => /*#__PURE__*/React.createElement("div", {
    className: "tl-item",
    key: i
  }, /*#__PURE__*/React.createElement("div", {
    className: "tl-dot " + t.cls
  }, /*#__PURE__*/React.createElement(Icon, {
    name: t.ic,
    size: 14
  })), /*#__PURE__*/React.createElement("div", {
    className: "tl-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "tx",
    dangerouslySetInnerHTML: {
      __html: t.tx
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "tm"
  }, t.tm)))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 22
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "panel-h"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "gauge",
    size: 16,
    style: {
      color: 'var(--gold-300)'
    }
  }), /*#__PURE__*/React.createElement("h3", null, "This week")), /*#__PURE__*/React.createElement("div", {
    className: "spark"
  }, b.spark.map((v, i) => /*#__PURE__*/React.createElement("span", {
    key: i,
    className: v === max ? 'hi' : '',
    style: {
      height: `${Math.max(8, v / max * 48)}px`
    }
  }))), /*#__PURE__*/React.createElement("div", {
    className: "kv"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Tasks today"), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, b.tasksToday)), /*#__PURE__*/React.createElement("div", {
    className: "kv"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Accuracy"), /*#__PURE__*/React.createElement("span", {
    className: "v",
    style: {
      color: 'var(--positive)'
    }
  }, b.accuracy, "%")), /*#__PURE__*/React.createElement("div", {
    className: "kv"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Hours saved"), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, b.hours)), /*#__PURE__*/React.createElement("div", {
    className: "kv"
  }, /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "Model"), /*#__PURE__*/React.createElement("span", {
    className: "v"
  }, /*#__PURE__*/React.createElement("span", {
    className: "mono"
  }, b.model)))), /*#__PURE__*/React.createElement("div", {
    className: "panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "panel-h"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "plug",
    size: 16,
    style: {
      color: 'var(--gold-300)'
    }
  }), /*#__PURE__*/React.createElement("h3", null, "Connected tools")), /*#__PURE__*/React.createElement("div", {
    className: "tool-list"
  }, b.tools.map(t => /*#__PURE__*/React.createElement("span", {
    className: "tool-pill",
    key: t
  }, /*#__PURE__*/React.createElement("span", {
    className: "d"
  }), t)))))));
}

/* ---------------- Activity view ---------------- */
function ActivityView() {
  return /*#__PURE__*/React.createElement("div", {
    className: "content-in fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sec-head"
  }, /*#__PURE__*/React.createElement("h2", null, "Activity"), /*#__PURE__*/React.createElement("span", {
    className: "ct"
  }, "across your workforce"), /*#__PURE__*/React.createElement("div", {
    className: "right"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn btn-secondary btn-sm"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "sliders-horizontal",
    size: 14
  }), " Filter"))), /*#__PURE__*/React.createElement("div", {
    className: "feed"
  }, ACTIVITY.map((a, i) => /*#__PURE__*/React.createElement("div", {
    className: "feed-row",
    key: i
  }, /*#__PURE__*/React.createElement("div", {
    className: "feed-av"
  }, /*#__PURE__*/React.createElement("img", {
    src: ASSETS + "logo-mark-gold.svg"
  })), /*#__PURE__*/React.createElement("div", {
    className: "feed-tx"
  }, /*#__PURE__*/React.createElement("span", {
    className: "who"
  }, a.who), " ", a.tx), /*#__PURE__*/React.createElement("span", {
    className: "feed-tag " + a.cls
  }, a.tag), /*#__PURE__*/React.createElement("span", {
    className: "feed-tm"
  }, a.tm)))));
}

/* ---------------- Inbox view ---------------- */
function InboxView({
  onResolve
}) {
  const [items, setItems] = useState2(INBOX);
  const resolve = i => setItems(its => its.filter((_, x) => x !== i));
  return /*#__PURE__*/React.createElement("div", {
    className: "content-in fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sec-head"
  }, /*#__PURE__*/React.createElement("h2", null, "Inbox"), /*#__PURE__*/React.createElement("span", {
    className: "ct"
  }, items.length, " need your input")), items.length === 0 ? /*#__PURE__*/React.createElement("div", {
    className: "empty"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ic"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "check",
    size: 24
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 600,
      fontSize: 18,
      color: 'var(--fg)'
    }
  }, "Inbox zero."), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 6
    }
  }, "Your workforce is running without you. Rest well.")) : /*#__PURE__*/React.createElement("div", {
    className: "feed"
  }, items.map((q, i) => /*#__PURE__*/React.createElement("div", {
    className: "inbox-row",
    key: i
  }, /*#__PURE__*/React.createElement("div", {
    className: "feed-av"
  }, /*#__PURE__*/React.createElement("img", {
    src: ASSETS + "logo-mark-gold.svg"
  })), /*#__PURE__*/React.createElement("div", {
    className: "inbox-q"
  }, /*#__PURE__*/React.createElement("div", {
    className: "t"
  }, q.t), /*#__PURE__*/React.createElement("div", {
    className: "d"
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--gold-300)',
      fontFamily: 'var(--font-mono)',
      fontSize: 12
    }
  }, q.who), " \xB7 ", q.d)), /*#__PURE__*/React.createElement("span", {
    className: "feed-tm"
  }, q.tm), /*#__PURE__*/React.createElement("div", {
    className: "inbox-act"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn btn-ghost btn-sm",
    onClick: () => resolve(i)
  }, "Dismiss"), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary btn-sm",
    onClick: () => resolve(i)
  }, "Approve"))))));
}

/* ---------------- Simple placeholder views (Tools / Models / Settings) ---------------- */
function SimpleView({
  icon,
  title,
  lines
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "content-in fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sec-head"
  }, /*#__PURE__*/React.createElement("h2", null, title)), /*#__PURE__*/React.createElement("div", {
    className: "empty"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ic"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: icon,
    size: 24
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: 'var(--font-display)',
      fontWeight: 600,
      fontSize: 18,
      color: 'var(--fg)'
    }
  }, lines[0]), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: 6,
      maxWidth: 380,
      marginInline: 'auto'
    }
  }, lines[1])));
}

/* ---------------- Design drawer ---------------- */
function DesignDrawer({
  preset,
  onClose,
  onEmploy
}) {
  const [name, setName] = useState2(preset ? preset.name : '');
  const [goal, setGoal] = useState2(preset ? preset.task : '');
  const [tools, setTools] = useState2(preset ? preset.tools : ['gmail']);
  const [model, setModel] = useState2('buddha-frontier-1');
  const [done, setDone] = useState2(false);
  const toggle = t => setTools(ts => ts.includes(t) ? ts.filter(x => x !== t) : [...ts, t]);
  useEffect2(() => {
    const esc = e => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', esc);
    if (window.lucide) window.lucide.createIcons();
    return () => window.removeEventListener('keydown', esc);
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "scrim",
    onMouseDown: e => {
      if (e.target === e.currentTarget) onClose();
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "drawer"
  }, !done ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "drawer-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "b-av"
  }, /*#__PURE__*/React.createElement("img", {
    src: ASSETS + "logo-mark-gold.svg"
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "t"
  }, "Design a Buddha"), /*#__PURE__*/React.createElement("div", {
    className: "s"
  }, "Shape a role \xB7 give it tools \xB7 employ it")), /*#__PURE__*/React.createElement("button", {
    className: "drawer-x",
    onClick: onClose
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "x",
    size: 18
  }))), /*#__PURE__*/React.createElement("div", {
    className: "drawer-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Role name"), /*#__PURE__*/React.createElement("div", {
    className: "hint"
  }, "What should this employee be called?"), /*#__PURE__*/React.createElement("input", {
    value: name,
    onChange: e => setName(e.target.value),
    placeholder: "e.g. Operations Buddha"
  })), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Goal"), /*#__PURE__*/React.createElement("div", {
    className: "hint"
  }, "Describe the outcome it owns, end to end."), /*#__PURE__*/React.createElement("textarea", {
    rows: 3,
    value: goal,
    onChange: e => setGoal(e.target.value),
    placeholder: "Close the books every month with under 0.1% variance, and brief me weekly."
  })), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Tools it can use"), /*#__PURE__*/React.createElement("div", {
    className: "hint"
  }, "It onboards itself to whatever you grant."), /*#__PURE__*/React.createElement("div", {
    className: "tool-toggle"
  }, ALL_TOOLS.map(t => /*#__PURE__*/React.createElement("button", {
    key: t,
    className: "tool" + (tools.includes(t) ? " on" : ""),
    onClick: () => toggle(t)
  }, tools.includes(t) && /*#__PURE__*/React.createElement(Icon, {
    name: "check",
    size: 12
  }), t)))), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Model"), /*#__PURE__*/React.createElement("div", {
    className: "hint"
  }, "The mind that powers it."), MODELS.map(m => /*#__PURE__*/React.createElement("div", {
    key: m.id,
    className: "model-opt" + (model === m.id ? " on" : ""),
    onClick: () => setModel(m.id)
  }, /*#__PURE__*/React.createElement("span", {
    className: "radio"
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "mn"
  }, m.name), /*#__PURE__*/React.createElement("div", {
    className: "md"
  }, m.desc)))))), /*#__PURE__*/React.createElement("div", {
    className: "drawer-foot"
  }, /*#__PURE__*/React.createElement("span", {
    className: "mono",
    style: {
      fontSize: 12,
      color: 'var(--fg-subtle)'
    }
  }, tools.length, " tool", tools.length !== 1 ? 's' : '', " \xB7 ", model), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-metal",
    onClick: () => setDone(true),
    disabled: !name
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "badge-check",
    size: 16
  }), " Employ this Buddha"))) : /*#__PURE__*/React.createElement("div", {
    className: "dsuccess"
  }, /*#__PURE__*/React.createElement("div", {
    className: "mark"
  }, /*#__PURE__*/React.createElement("img", {
    src: ASSETS + "logo-mark-black.svg"
  })), /*#__PURE__*/React.createElement("h3", null, name || 'Your Buddha', " is employed."), /*#__PURE__*/React.createElement("p", null, "It\u2019s onboarding to ", tools.length, " tool", tools.length !== 1 ? 's' : '', " now and will start its first tasks in moments. You\u2019ll get a brief when it\u2019s done."), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: () => onEmploy({
      name,
      goal,
      tools,
      model
    })
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "arrow-left",
    size: 15
  }), " Back to workforce"))));
}
Object.assign(window, {
  AgentDetail,
  ActivityView,
  InboxView,
  SimpleView,
  DesignDrawer
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/app-views.jsx", error: String((e && e.message) || e) }); }

// ui_kits/app/tweaks-panel.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)

/* BEGIN USAGE */
// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
// Exports (to window): useTweaks, TweaksPanel, TweakSection, TweakRow, TweakSlider,
//   TweakToggle, TweakRadio, TweakSelect, TweakText, TweakNumber, TweakColor, TweakButton.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// TweakRadio is the segmented control for 2–3 short options (auto-falls-back to
// TweakSelect past ~16/~10 chars per label); reach for TweakSelect directly when
// options are many or long. For color tweaks always curate 3-4 options rather than
// a free picker; an option can also be a whole 2–5 color palette (the stored value
// is the array). The Tweak* controls are a floor, not a ceiling — build custom
// controls inside the panel if a tweak calls for UI they don't cover.
/* END USAGE */
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;box-sizing:border-box;width:100%;min-width:0;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;box-sizing:border-box;min-width:0;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null ? keyOrEdits : {
      [keyOrEdits]: val
    };
    setValues(prev => ({
      ...prev,
      ...edits
    }));
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits
    }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', {
      detail: edits
    }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({
  title = 'Tweaks',
  children
}) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  const offsetRef = React.useRef({
    x: 16,
    y: 16
  });
  const PAD = 16;
  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth,
      h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y))
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);
  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);
  React.useEffect(() => {
    const onMsg = e => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({
      type: '__edit_mode_available'
    }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);
  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({
      type: '__edit_mode_dismissed'
    }, '*');
  };
  const onDragStart = e => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX,
      sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = ev => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy)
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };
  if (!open) return null;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("style", null, __TWEAKS_STYLE), /*#__PURE__*/React.createElement("div", {
    ref: dragRef,
    className: "twk-panel",
    "data-omelette-chrome": "",
    style: {
      right: offsetRef.current.x,
      bottom: offsetRef.current.y
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-hd",
    onMouseDown: onDragStart
  }, /*#__PURE__*/React.createElement("b", null, title), /*#__PURE__*/React.createElement("button", {
    className: "twk-x",
    "aria-label": "Close tweaks",
    onMouseDown: e => e.stopPropagation(),
    onClick: dismiss
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    className: "twk-body"
  }, children)));
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({
  label,
  children
}) {
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "twk-sect"
  }, label), children);
}
function TweakRow({
  label,
  value,
  children,
  inline = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: inline ? 'twk-row twk-row-h' : 'twk-row'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label), value != null && /*#__PURE__*/React.createElement("span", {
    className: "twk-val"
  }, value)), children);
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label,
    value: `${value}${unit}`
  }, /*#__PURE__*/React.createElement("input", {
    type: "range",
    className: "twk-slider",
    min: min,
    max: max,
    step: step,
    value: value,
    onChange: e => onChange(Number(e.target.value))
  }));
}
function TweakToggle({
  label,
  value,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-row twk-row-h"
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "twk-toggle",
    "data-on": value ? '1' : '0',
    role: "switch",
    "aria-checked": !!value,
    onClick: () => onChange(!value)
  }, /*#__PURE__*/React.createElement("i", null)));
}
function TweakRadio({
  label,
  value,
  options,
  onChange
}) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = o => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({
    2: 16,
    3: 10
  }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = s => {
      const m = options.find(o => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return /*#__PURE__*/React.createElement(TweakSelect, {
      label: label,
      value: value,
      options: options,
      onChange: s => onChange(resolve(s))
    });
  }
  const opts = options.map(o => typeof o === 'object' ? o : {
    value: o,
    label: o
  });
  const idx = Math.max(0, opts.findIndex(o => o.value === value));
  const n = opts.length;
  const segAt = clientX => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor((clientX - r.left - 2) / inner * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };
  const onPointerDown = e => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = ev => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    ref: trackRef,
    role: "radiogroup",
    onPointerDown: onPointerDown,
    className: dragging ? 'twk-seg dragging' : 'twk-seg'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-seg-thumb",
    style: {
      left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
      width: `calc((100% - 4px) / ${n})`
    }
  }), opts.map(o => /*#__PURE__*/React.createElement("button", {
    key: o.value,
    type: "button",
    role: "radio",
    "aria-checked": o.value === value
  }, o.label))));
}
function TweakSelect({
  label,
  value,
  options,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("select", {
    className: "twk-field",
    value: value,
    onChange: e => onChange(e.target.value)
  }, options.map(o => {
    const v = typeof o === 'object' ? o.value : o;
    const l = typeof o === 'object' ? o.label : o;
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    }, l);
  })));
}
function TweakText({
  label,
  value,
  placeholder,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("input", {
    className: "twk-field",
    type: "text",
    value: value,
    placeholder: placeholder,
    onChange: e => onChange(e.target.value)
  }));
}
function TweakNumber({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange
}) {
  const clamp = n => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({
    x: 0,
    val: 0
  });
  const onScrubStart = e => {
    e.preventDefault();
    startRef.current = {
      x: e.clientX,
      val: value
    };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = ev => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-num"
  }, /*#__PURE__*/React.createElement("span", {
    className: "twk-num-lbl",
    onPointerDown: onScrubStart
  }, label), /*#__PURE__*/React.createElement("input", {
    type: "number",
    value: value,
    min: min,
    max: max,
    step: step,
    onChange: e => onChange(clamp(Number(e.target.value)))
  }), unit && /*#__PURE__*/React.createElement("span", {
    className: "twk-num-unit"
  }, unit));
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, c => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = n >> 16 & 255,
    g = n >> 8 & 255,
    b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}
const __TwkCheck = ({
  light
}) => /*#__PURE__*/React.createElement("svg", {
  viewBox: "0 0 14 14",
  "aria-hidden": "true"
}, /*#__PURE__*/React.createElement("path", {
  d: "M3 7.2 5.8 10 11 4.2",
  fill: "none",
  strokeWidth: "2.2",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  stroke: light ? 'rgba(0,0,0,.78)' : '#fff'
}));

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({
  label,
  value,
  options,
  onChange
}) {
  if (!options || !options.length) {
    return /*#__PURE__*/React.createElement("div", {
      className: "twk-row twk-row-h"
    }, /*#__PURE__*/React.createElement("div", {
      className: "twk-lbl"
    }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("input", {
      type: "color",
      className: "twk-swatch",
      value: value,
      onChange: e => onChange(e.target.value)
    }));
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = o => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-chips",
    role: "radiogroup"
  }, options.map((o, i) => {
    const colors = Array.isArray(o) ? o : [o];
    const [hero, ...rest] = colors;
    const sup = rest.slice(0, 4);
    const on = key(o) === cur;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      type: "button",
      className: "twk-chip",
      role: "radio",
      "aria-checked": on,
      "data-on": on ? '1' : '0',
      "aria-label": colors.join(', '),
      title: colors.join(' · '),
      style: {
        background: hero
      },
      onClick: () => onChange(o)
    }, sup.length > 0 && /*#__PURE__*/React.createElement("span", null, sup.map((c, j) => /*#__PURE__*/React.createElement("i", {
      key: j,
      style: {
        background: c
      }
    }))), on && /*#__PURE__*/React.createElement(__TwkCheck, {
      light: __twkIsLight(hero)
    }));
  })));
}
function TweakButton({
  label,
  onClick,
  secondary = false
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: secondary ? 'twk-btn secondary' : 'twk-btn',
    onClick: onClick
  }, label);
}
Object.assign(window, {
  useTweaks,
  TweaksPanel,
  TweakSection,
  TweakRow,
  TweakSlider,
  TweakToggle,
  TweakRadio,
  TweakSelect,
  TweakText,
  TweakNumber,
  TweakColor,
  TweakButton
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/app/tweaks-panel.jsx", error: String((e && e.message) || e) }); }

// ui_kits/docs/docs-app.jsx
try { (() => {
/* ============================================================
   Buddha Cognitive Lab — Docs & Blog app (components + mount)
   ============================================================ */
const {
  useState,
  useEffect
} = React;

/* ---- code block renderer ---- */
function CodeBlock({
  block
}) {
  const [copied, setCopied] = useState(false);
  const text = block.lines.map(line => line.map(([, t]) => t).join('')).join('\n');
  const copy = () => {
    try {
      navigator.clipboard.writeText(text);
    } catch (e) {}
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "cb"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cb-bar"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "file-code",
    size: 13
  }), /*#__PURE__*/React.createElement("span", null, block.file), /*#__PURE__*/React.createElement("span", {
    className: "lang"
  }, "\xB7 ", block.lang), /*#__PURE__*/React.createElement("span", {
    className: "copy",
    onClick: copy
  }, /*#__PURE__*/React.createElement(Icon, {
    name: copied ? 'check' : 'copy',
    size: 13
  }), copied ? 'copied' : 'copy')), /*#__PURE__*/React.createElement("pre", null, block.lines.map((line, i) => /*#__PURE__*/React.createElement("div", {
    key: i
  }, line.length === 0 ? '\u00A0' : line.map(([cls, t], j) => /*#__PURE__*/React.createElement("span", {
    key: j,
    className: cls
  }, t))))));
}

/* ---- article block dispatcher ---- */
function Block({
  b
}) {
  if (b.t === 'h2') return /*#__PURE__*/React.createElement("h2", {
    id: b.id
  }, b.tx);
  if (b.t === 'h3') return /*#__PURE__*/React.createElement("h3", null, b.tx);
  if (b.t === 'p') return /*#__PURE__*/React.createElement("p", {
    dangerouslySetInnerHTML: {
      __html: b.html
    }
  });
  if (b.t === 'code') return /*#__PURE__*/React.createElement(CodeBlock, {
    block: b
  });
  if (b.t === 'callout') return /*#__PURE__*/React.createElement("div", {
    className: "callout " + (b.cls || '')
  }, /*#__PURE__*/React.createElement(Icon, {
    name: b.ic,
    size: 18,
    className: "ic"
  }), /*#__PURE__*/React.createElement("div", {
    className: "ct",
    dangerouslySetInnerHTML: {
      __html: b.html
    }
  }));
  if (b.t === 'params') return /*#__PURE__*/React.createElement("table", {
    className: "ptable"
  }, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, /*#__PURE__*/React.createElement("th", null, "Parameter"), /*#__PURE__*/React.createElement("th", null, "Type"), /*#__PURE__*/React.createElement("th", null, "Description"))), /*#__PURE__*/React.createElement("tbody", null, b.rows.map(r => /*#__PURE__*/React.createElement("tr", {
    key: r.n
  }, /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    className: "pn"
  }, r.n), r.req && /*#__PURE__*/React.createElement("div", {
    className: "pt",
    style: {
      color: 'var(--gold-600)'
    }
  }, "required")), /*#__PURE__*/React.createElement("td", null, /*#__PURE__*/React.createElement("span", {
    className: "pt"
  }, r.ty)), /*#__PURE__*/React.createElement("td", null, r.d)))));
  return null;
}

/* ---- Header ---- */
function Header({
  tab,
  setTab
}) {
  return /*#__PURE__*/React.createElement("header", {
    className: "hdr"
  }, /*#__PURE__*/React.createElement("div", {
    className: "hdr-in"
  }, /*#__PURE__*/React.createElement("img", {
    className: "hdr-logo",
    src: DASSETS + "logo-buddha-cognitive-lab-onblack.svg",
    alt: "Buddha Cognitive Lab"
  }), /*#__PURE__*/React.createElement("div", {
    className: "hdr-tabs"
  }, ['Docs', 'Blog', 'Research'].map(t => /*#__PURE__*/React.createElement("div", {
    key: t,
    className: "hdr-tab" + (tab === t ? " on" : ""),
    onClick: () => setTab(t)
  }, t))), /*#__PURE__*/React.createElement("div", {
    className: "hdr-search"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "search",
    size: 14
  }), /*#__PURE__*/React.createElement("input", {
    placeholder: "Search docs\u2026"
  }), /*#__PURE__*/React.createElement("span", {
    className: "k"
  }, "/")), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    style: {
      marginLeft: 14
    }
  }, "Console ", /*#__PURE__*/React.createElement(Icon, {
    name: "arrow-up-right",
    size: 14
  }))));
}

/* ---- Docs view ---- */
function DocsView() {
  const [active, setActive] = useState('quickstart');
  const [toc, setToc] = useState(ARTICLE.toc[0].id);
  return /*#__PURE__*/React.createElement("div", {
    className: "docs fade-in"
  }, /*#__PURE__*/React.createElement("nav", {
    className: "doc-nav"
  }, DOC_NAV.map(g => /*#__PURE__*/React.createElement("div", {
    className: "dn-group",
    key: g.group
  }, /*#__PURE__*/React.createElement("h4", null, g.group), g.items.map(it => /*#__PURE__*/React.createElement("div", {
    key: it.id,
    className: "dn-item" + (active === it.id ? " on" : ""),
    onClick: () => setActive(it.id)
  }, it.label, it.tag && /*#__PURE__*/React.createElement("span", {
    className: "tag"
  }, it.tag)))))), /*#__PURE__*/React.createElement("article", {
    className: "article"
  }, /*#__PURE__*/React.createElement("div", {
    className: "art-crumb"
  }, ARTICLE.crumb.map((c, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: i
  }, i > 0 && /*#__PURE__*/React.createElement(Icon, {
    name: "chevron-right",
    size: 12
  }), /*#__PURE__*/React.createElement("span", {
    className: i === ARTICLE.crumb.length - 1 ? 'gold' : ''
  }, c)))), /*#__PURE__*/React.createElement("h1", null, ARTICLE.title), /*#__PURE__*/React.createElement("p", {
    className: "art-lead"
  }, ARTICLE.lead), ARTICLE.blocks.map((b, i) => /*#__PURE__*/React.createElement(Block, {
    key: i,
    b: b
  })), /*#__PURE__*/React.createElement("div", {
    className: "art-foot"
  }, /*#__PURE__*/React.createElement("a", null, /*#__PURE__*/React.createElement("div", {
    className: "dir"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "arrow-left",
    size: 12,
    style: {
      verticalAlign: '-1px'
    }
  }), " ", ARTICLE.prev.dir), /*#__PURE__*/React.createElement("div", {
    className: "ti"
  }, ARTICLE.prev.ti)), /*#__PURE__*/React.createElement("a", {
    className: "next"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dir"
  }, ARTICLE.next.dir, " ", /*#__PURE__*/React.createElement(Icon, {
    name: "arrow-right",
    size: 12,
    style: {
      verticalAlign: '-1px'
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "ti"
  }, ARTICLE.next.ti)))), /*#__PURE__*/React.createElement("aside", {
    className: "otp"
  }, /*#__PURE__*/React.createElement("h5", null, "On this page"), ARTICLE.toc.map(t => /*#__PURE__*/React.createElement("a", {
    key: t.id,
    className: toc === t.id ? 'on' : '',
    onClick: () => {
      setToc(t.id);
      const el = document.getElementById(t.id);
      if (el) {
        const y = el.getBoundingClientRect().top + window.scrollY - 80;
        window.scrollTo({
          top: y,
          behavior: 'smooth'
        });
      }
    }
  }, t.label))));
}

/* ---- Blog index ---- */
function BlogIndex({
  onOpen
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "blog fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blog-hero"
  }, /*#__PURE__*/React.createElement("div", {
    className: "eyebrow"
  }, "// From the lab"), /*#__PURE__*/React.createElement("h1", null, "Research & notes"), /*#__PURE__*/React.createElement("p", null, "How we build frontier minds that do real work \u2014 and what we learn watching them run.")), /*#__PURE__*/React.createElement("div", {
    className: "posts"
  }, POSTS.map(p => /*#__PURE__*/React.createElement("div", {
    key: p.id,
    className: "post" + (p.feat ? " feat" : ""),
    onClick: () => onOpen(p)
  }, /*#__PURE__*/React.createElement("div", {
    className: "post-art"
  }, /*#__PURE__*/React.createElement("div", {
    className: "glow"
  }), /*#__PURE__*/React.createElement("img", {
    src: DASSETS + "logo-mark-gold.svg"
  }), /*#__PURE__*/React.createElement("img", {
    className: "wm",
    src: DASSETS + "logo-mark-white.svg"
  })), /*#__PURE__*/React.createElement("div", {
    className: "post-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cat"
  }, p.cat), /*#__PURE__*/React.createElement("h3", null, p.title), /*#__PURE__*/React.createElement("p", null, p.excerpt), /*#__PURE__*/React.createElement("div", {
    className: "post-meta"
  }, /*#__PURE__*/React.createElement("span", {
    className: "av"
  }, p.author), p.who, /*#__PURE__*/React.createElement("span", null, "\xB7"), p.date, /*#__PURE__*/React.createElement("span", null, "\xB7"), p.read))))));
}

/* ---- Blog post read ---- */
function BlogPost({
  onBack
}) {
  const b = POST_BODY;
  return /*#__PURE__*/React.createElement("div", {
    className: "read fade-in"
  }, /*#__PURE__*/React.createElement("div", {
    className: "read-back",
    onClick: onBack
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "arrow-left",
    size: 13
  }), " All posts"), /*#__PURE__*/React.createElement("div", {
    className: "cat"
  }, b.cat), /*#__PURE__*/React.createElement("h1", null, b.title), /*#__PURE__*/React.createElement("div", {
    className: "read-meta"
  }, /*#__PURE__*/React.createElement("span", {
    className: "av"
  }, b.av), b.who, /*#__PURE__*/React.createElement("span", null, "\xB7"), b.date, /*#__PURE__*/React.createElement("span", null, "\xB7"), b.read), b.blocks.map((x, i) => {
    if (x.t === 'h2') return /*#__PURE__*/React.createElement("h2", {
      key: i
    }, x.tx);
    if (x.t === 'quote') return /*#__PURE__*/React.createElement("blockquote", {
      key: i
    }, x.tx);
    return /*#__PURE__*/React.createElement("p", {
      key: i,
      dangerouslySetInnerHTML: {
        __html: x.html
      }
    });
  }));
}
function Footer() {
  return /*#__PURE__*/React.createElement("footer", {
    className: "foot"
  }, /*#__PURE__*/React.createElement("div", {
    className: "foot-in"
  }, /*#__PURE__*/React.createElement("img", {
    src: DASSETS + "logo-buddha-cognitive-lab-onblack.svg",
    alt: "Buddha Cognitive Lab"
  }), /*#__PURE__*/React.createElement("span", null, "\xA9 2026 Buddha Cognitive Lab \xB7 Towards digital enlightenment"), /*#__PURE__*/React.createElement("div", {
    className: "social"
  }, /*#__PURE__*/React.createElement("a", {
    href: "https://buddhalab.in"
  }, "buddhalab.in"), /*#__PURE__*/React.createElement("a", {
    href: "#"
  }, "@buddhalab"))));
}

/* ---- App ---- */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "theme": "dark"
} /*EDITMODE-END*/;
function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [tab, setTab] = useState('Docs');
  const [post, setPost] = useState(null);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', t.theme);
  }, [t.theme]);
  useEffect(() => {
    if (window.lucide) window.lucide.createIcons();
  });
  let body;
  if (tab === 'Docs') body = /*#__PURE__*/React.createElement(DocsView, null);else if (tab === 'Blog' || tab === 'Research') body = post ? /*#__PURE__*/React.createElement(BlogPost, {
    onBack: () => setPost(null)
  }) : /*#__PURE__*/React.createElement(BlogIndex, {
    onOpen: p => setPost(p)
  });
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Header, {
    tab: tab,
    setTab: x => {
      setTab(x);
      setPost(null);
    }
  }), body, /*#__PURE__*/React.createElement(Footer, null), /*#__PURE__*/React.createElement(TweaksPanel, null, /*#__PURE__*/React.createElement(TweakSection, {
    label: "Theme"
  }), /*#__PURE__*/React.createElement(TweakRadio, {
    label: "Surface",
    value: t.theme,
    options: ['dark', 'light'],
    onChange: v => setTweak('theme', v)
  })));
}
ReactDOM.createRoot(document.getElementById('root')).render(/*#__PURE__*/React.createElement(App, null));
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/docs/docs-app.jsx", error: String((e && e.message) || e) }); }

// ui_kits/docs/docs-content.jsx
try { (() => {
/* ============================================================
   Buddha Cognitive Lab — Docs & Blog content/data
   Exports: Icon, DASSETS, DOC_NAV, ARTICLE, POSTS
   ============================================================ */
const {
  useState: dUseState,
  useEffect: dUseEffect,
  useRef: dUseRef
} = React;
const DASSETS = "../../assets/";
function Icon({
  name,
  size = 18,
  stroke = 1.75,
  style,
  className
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": name,
    className: className,
    style: {
      width: size,
      height: size,
      strokeWidth: stroke,
      display: 'inline-flex',
      flex: 'none',
      ...style
    }
  });
}
const DOC_NAV = [{
  group: 'Get started',
  items: [{
    id: 'intro',
    label: 'Introduction'
  }, {
    id: 'quickstart',
    label: 'Quickstart',
    on: true
  }, {
    id: 'concepts',
    label: 'Core concepts'
  }]
}, {
  group: 'Building Buddhas',
  items: [{
    id: 'design',
    label: 'Designing a role'
  }, {
    id: 'tools',
    label: 'Connecting tools'
  }, {
    id: 'goals',
    label: 'Goals & guardrails'
  }, {
    id: 'memory',
    label: 'Memory & context'
  }]
}, {
  group: 'Models',
  items: [{
    id: 'frontier',
    label: 'buddha-frontier-1'
  }, {
    id: 'swift',
    label: 'buddha-swift-1'
  }, {
    id: 'deep',
    label: 'buddha-deep-1'
  }]
}, {
  group: 'Reference',
  items: [{
    id: 'api',
    label: 'REST API',
    tag: 'v1'
  }, {
    id: 'sdk',
    label: 'Python SDK'
  }, {
    id: 'webhooks',
    label: 'Webhooks'
  }]
}];

/* The currently-open article (Quickstart). Blocks render in order. */
const ARTICLE = {
  crumb: ['Docs', 'Get started', 'Quickstart'],
  title: 'Quickstart',
  lead: 'Design, employ, and observe your first autonomous Buddha in under five minutes — from the dashboard or the API.',
  toc: [{
    id: 'before',
    label: 'Before you begin'
  }, {
    id: 'design',
    label: '1 · Design the role'
  }, {
    id: 'employ',
    label: '2 · Employ it'
  }, {
    id: 'observe',
    label: '3 · Observe & delegate'
  }, {
    id: 'next',
    label: 'Where to next'
  }],
  blocks: [{
    t: 'callout',
    cls: '',
    ic: 'sparkles',
    html: 'A <b>Buddha</b> is an autonomous AI employee: a role you shape, grant tools, and hold to an outcome. It works end-to-end while you rest.'
  }, {
    t: 'h2',
    id: 'before',
    tx: 'Before you begin'
  }, {
    t: 'p',
    html: 'You’ll need a Buddha Cognitive Lab workspace and an API key. Create a key under <b>Settings → API keys</b>, then export it:'
  }, {
    t: 'code',
    lang: 'bash',
    file: 'terminal',
    lines: [[['cm', '# Authenticate the CLI']], [['kw', 'export '], ['nm', 'BUDDHA_API_KEY'], ['pu', '='], ['st', '"sk-buddha-…"']], [['fn', 'buddha '], ['nm', 'login']]]
  }, {
    t: 'h2',
    id: 'design',
    tx: '1 · Design the role'
  }, {
    t: 'p',
    html: 'Describe the employee you want. Give it a name, a goal stated as an outcome, the tools it may use, and the model that powers it.'
  }, {
    t: 'code',
    lang: 'python',
    file: 'hire_ops.py',
    lines: [[['kw', 'from '], ['nm', 'buddha '], ['kw', 'import '], ['nm', 'Lab']], [], [['nm', 'lab '], ['pu', '= '], ['fn', 'Lab'], ['pu', '()']], [], [['cm', '# Shape an autonomous Operations employee']], [['nm', 'ops '], ['pu', '= '], ['nm', 'lab'], ['pu', '.'], ['fn', 'hire'], ['pu', '(']], [['pu', '    '], ['nm', 'name'], ['pu', '='], ['st', '"Operations Buddha"'], ['pu', ',']], [['pu', '    '], ['nm', 'goal'], ['pu', '='], ['st', '"Close the books monthly, < 0.1% variance"'], ['pu', ',']], [['pu', '    '], ['nm', 'tools'], ['pu', '='], ['pu', '['], ['st', '"stripe"'], ['pu', ', '], ['st', '"quickbooks"'], ['pu', ', '], ['st', '"gmail"'], ['pu', '],']], [['pu', '    '], ['nm', 'model'], ['pu', '='], ['st', '"buddha-frontier-1"'], ['pu', ',']], [['pu', ')']]]
  }, {
    t: 'callout',
    cls: 'note',
    ic: 'info',
    html: 'Goals are <b>outcomes</b>, not task lists. State what “done” looks like; the Buddha plans the steps and adapts as reality changes.'
  }, {
    t: 'h2',
    id: 'employ',
    tx: '2 · Employ it'
  }, {
    t: 'p',
    html: 'Employing a Buddha onboards it to your connected tools and starts its first run. The call returns immediately with a handle you can poll or subscribe to.'
  }, {
    t: 'code',
    lang: 'python',
    file: 'hire_ops.py',
    lines: [[['nm', 'ops'], ['pu', '.'], ['fn', 'employ'], ['pu', '()']], [['fn', 'print'], ['pu', '('], ['nm', 'ops'], ['pu', '.'], ['nm', 'status'], ['pu', ')  '], ['cm', '# → "running"']]]
  }, {
    t: 'params',
    rows: [{
      n: 'name',
      ty: 'string',
      req: true,
      d: 'Human-readable role name, e.g. “Support Buddha”.'
    }, {
      n: 'goal',
      ty: 'string',
      req: true,
      d: 'The outcome the employee owns, in plain language.'
    }, {
      n: 'tools',
      ty: 'string[]',
      req: false,
      d: 'Integrations the Buddha may use. It onboards itself to each.'
    }, {
      n: 'model',
      ty: 'enum',
      req: false,
      d: 'frontier-1 · swift-1 · deep-1. Defaults to frontier-1.'
    }]
  }, {
    t: 'h2',
    id: 'observe',
    tx: '3 · Observe & delegate'
  }, {
    t: 'p',
    html: 'Every action a Buddha takes is traced. Watch the live timeline in the console, or stream events. When it needs a human decision, it lands in your <b>Inbox</b> — nothing else interrupts you.'
  }, {
    t: 'code',
    lang: 'python',
    file: 'watch.py',
    lines: [[['kw', 'for '], ['nm', 'event '], ['kw', 'in '], ['nm', 'ops'], ['pu', '.'], ['fn', 'stream'], ['pu', '():']], [['pu', '    '], ['fn', 'print'], ['pu', '('], ['nm', 'event'], ['pu', '.'], ['nm', 'summary'], ['pu', ')']]]
  }, {
    t: 'callout',
    cls: '',
    ic: 'shield-check',
    html: '<b>Guardrails first.</b> Buddhas ask before irreversible actions — refunds, sends, deletions — unless you grant explicit autonomy per tool.'
  }, {
    t: 'h2',
    id: 'next',
    tx: 'Where to next'
  }, {
    t: 'p',
    html: 'You’ve employed your first autonomous teammate. Go deeper on shaping roles, wiring tools, and the guardrail model.'
  }],
  prev: {
    dir: 'Previous',
    ti: 'Introduction'
  },
  next: {
    dir: 'Next',
    ti: 'Core concepts'
  }
};
const POSTS = [{
  id: 'p1',
  feat: true,
  cat: 'Research',
  title: 'Long-horizon autonomy: how buddha-frontier-1 stays on task for days',
  excerpt: 'A look at the memory architecture and self-checking loops that let a single agent own a multi-week outcome without drift.',
  author: 'R',
  who: 'Rahul',
  date: 'May 28, 2026',
  read: '9 min'
}, {
  id: 'p2',
  cat: 'Engineering',
  title: 'Designing guardrails that don’t get in the way',
  excerpt: 'Permissioning irreversible actions per tool — and why “ask first” beats “undo later”.',
  author: 'A',
  who: 'Aisha',
  date: 'May 14, 2026',
  read: '6 min'
}, {
  id: 'p3',
  cat: 'Product',
  title: 'The one-person company is already here',
  excerpt: 'What we learned watching solo founders run six-figure operations with a workforce of Buddhas.',
  author: 'M',
  who: 'Marco',
  date: 'Apr 30, 2026',
  read: '7 min'
}, {
  id: 'p4',
  cat: 'Research',
  title: 'Evaluating practical intelligence, not benchmarks',
  excerpt: 'Why we measure our models on real, messy business work — and how we score it.',
  author: 'R',
  who: 'Rahul',
  date: 'Apr 12, 2026',
  read: '8 min'
}, {
  id: 'p5',
  cat: 'Safety',
  title: 'A calm interface for powerful agents',
  excerpt: 'Design principles for keeping a human serenely in control of autonomous systems.',
  author: 'A',
  who: 'Aisha',
  date: 'Mar 27, 2026',
  read: '5 min'
}];
const POST_BODY = {
  cat: 'Research',
  title: 'Long-horizon autonomy: how buddha-frontier-1 stays on task for days',
  who: 'Rahul',
  av: 'R',
  date: 'May 28, 2026',
  read: '9 min',
  blocks: [{
    t: 'p',
    html: 'Most agents are sprinters. They do well on a single prompt and unravel over a long, branching task. The work that actually runs a business — closing books, nurturing a pipeline, shipping a research brief — is a <b>marathon</b>, measured in days, not turns.'
  }, {
    t: 'p',
    html: '<b>buddha-frontier-1</b> is built for the marathon. Three ideas do most of the work: durable memory, periodic self-checks, and an explicit goal it can always return to.'
  }, {
    t: 'h2',
    tx: 'Memory that survives the context window'
  }, {
    t: 'p',
    html: 'Rather than cramming everything into one prompt, a Buddha writes structured notes to durable memory as it goes — decisions, open questions, and a running model of the world it’s acting in. When it resumes, it reads the goal and the notes, not the entire history.'
  }, {
    t: 'quote',
    tx: 'A long task is not a long prompt. It is a short prompt, held steady against a goal, many times over.'
  }, {
    t: 'h2',
    tx: 'Self-checks instead of drift'
  }, {
    t: 'p',
    html: 'Every few steps the agent stops and asks a plain question: <b>am I still serving the outcome?</b> If reality has changed — a payment failed, a lead went cold — it re-plans rather than barreling ahead. Drift is caught in minutes, not discovered in a weekly review.'
  }, {
    t: 'p',
    html: 'The result is an employee you can trust with an outcome and leave alone. That, more than any benchmark, is what “frontier” means to us.'
  }]
};
Object.assign(window, {
  Icon,
  DASSETS,
  DOC_NAV,
  ARTICLE,
  POSTS,
  POST_BODY
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/docs/docs-content.jsx", error: String((e && e.message) || e) }); }

// ui_kits/docs/tweaks-panel.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)

/* BEGIN USAGE */
// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
// Exports (to window): useTweaks, TweaksPanel, TweakSection, TweakRow, TweakSlider,
//   TweakToggle, TweakRadio, TweakSelect, TweakText, TweakNumber, TweakColor, TweakButton.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// TweakRadio is the segmented control for 2–3 short options (auto-falls-back to
// TweakSelect past ~16/~10 chars per label); reach for TweakSelect directly when
// options are many or long. For color tweaks always curate 3-4 options rather than
// a free picker; an option can also be a whole 2–5 color palette (the stored value
// is the array). The Tweak* controls are a floor, not a ceiling — build custom
// controls inside the panel if a tweak calls for UI they don't cover.
/* END USAGE */
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;box-sizing:border-box;width:100%;min-width:0;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;box-sizing:border-box;min-width:0;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null ? keyOrEdits : {
      [keyOrEdits]: val
    };
    setValues(prev => ({
      ...prev,
      ...edits
    }));
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits
    }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', {
      detail: edits
    }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({
  title = 'Tweaks',
  children
}) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  const offsetRef = React.useRef({
    x: 16,
    y: 16
  });
  const PAD = 16;
  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth,
      h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y))
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);
  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);
  React.useEffect(() => {
    const onMsg = e => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({
      type: '__edit_mode_available'
    }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);
  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({
      type: '__edit_mode_dismissed'
    }, '*');
  };
  const onDragStart = e => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX,
      sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = ev => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy)
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };
  if (!open) return null;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("style", null, __TWEAKS_STYLE), /*#__PURE__*/React.createElement("div", {
    ref: dragRef,
    className: "twk-panel",
    "data-omelette-chrome": "",
    style: {
      right: offsetRef.current.x,
      bottom: offsetRef.current.y
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-hd",
    onMouseDown: onDragStart
  }, /*#__PURE__*/React.createElement("b", null, title), /*#__PURE__*/React.createElement("button", {
    className: "twk-x",
    "aria-label": "Close tweaks",
    onMouseDown: e => e.stopPropagation(),
    onClick: dismiss
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    className: "twk-body"
  }, children)));
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({
  label,
  children
}) {
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "twk-sect"
  }, label), children);
}
function TweakRow({
  label,
  value,
  children,
  inline = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: inline ? 'twk-row twk-row-h' : 'twk-row'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label), value != null && /*#__PURE__*/React.createElement("span", {
    className: "twk-val"
  }, value)), children);
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label,
    value: `${value}${unit}`
  }, /*#__PURE__*/React.createElement("input", {
    type: "range",
    className: "twk-slider",
    min: min,
    max: max,
    step: step,
    value: value,
    onChange: e => onChange(Number(e.target.value))
  }));
}
function TweakToggle({
  label,
  value,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-row twk-row-h"
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "twk-toggle",
    "data-on": value ? '1' : '0',
    role: "switch",
    "aria-checked": !!value,
    onClick: () => onChange(!value)
  }, /*#__PURE__*/React.createElement("i", null)));
}
function TweakRadio({
  label,
  value,
  options,
  onChange
}) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = o => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({
    2: 16,
    3: 10
  }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = s => {
      const m = options.find(o => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return /*#__PURE__*/React.createElement(TweakSelect, {
      label: label,
      value: value,
      options: options,
      onChange: s => onChange(resolve(s))
    });
  }
  const opts = options.map(o => typeof o === 'object' ? o : {
    value: o,
    label: o
  });
  const idx = Math.max(0, opts.findIndex(o => o.value === value));
  const n = opts.length;
  const segAt = clientX => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor((clientX - r.left - 2) / inner * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };
  const onPointerDown = e => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = ev => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    ref: trackRef,
    role: "radiogroup",
    onPointerDown: onPointerDown,
    className: dragging ? 'twk-seg dragging' : 'twk-seg'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-seg-thumb",
    style: {
      left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
      width: `calc((100% - 4px) / ${n})`
    }
  }), opts.map(o => /*#__PURE__*/React.createElement("button", {
    key: o.value,
    type: "button",
    role: "radio",
    "aria-checked": o.value === value
  }, o.label))));
}
function TweakSelect({
  label,
  value,
  options,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("select", {
    className: "twk-field",
    value: value,
    onChange: e => onChange(e.target.value)
  }, options.map(o => {
    const v = typeof o === 'object' ? o.value : o;
    const l = typeof o === 'object' ? o.label : o;
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    }, l);
  })));
}
function TweakText({
  label,
  value,
  placeholder,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("input", {
    className: "twk-field",
    type: "text",
    value: value,
    placeholder: placeholder,
    onChange: e => onChange(e.target.value)
  }));
}
function TweakNumber({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange
}) {
  const clamp = n => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({
    x: 0,
    val: 0
  });
  const onScrubStart = e => {
    e.preventDefault();
    startRef.current = {
      x: e.clientX,
      val: value
    };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = ev => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-num"
  }, /*#__PURE__*/React.createElement("span", {
    className: "twk-num-lbl",
    onPointerDown: onScrubStart
  }, label), /*#__PURE__*/React.createElement("input", {
    type: "number",
    value: value,
    min: min,
    max: max,
    step: step,
    onChange: e => onChange(clamp(Number(e.target.value)))
  }), unit && /*#__PURE__*/React.createElement("span", {
    className: "twk-num-unit"
  }, unit));
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, c => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = n >> 16 & 255,
    g = n >> 8 & 255,
    b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}
const __TwkCheck = ({
  light
}) => /*#__PURE__*/React.createElement("svg", {
  viewBox: "0 0 14 14",
  "aria-hidden": "true"
}, /*#__PURE__*/React.createElement("path", {
  d: "M3 7.2 5.8 10 11 4.2",
  fill: "none",
  strokeWidth: "2.2",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  stroke: light ? 'rgba(0,0,0,.78)' : '#fff'
}));

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({
  label,
  value,
  options,
  onChange
}) {
  if (!options || !options.length) {
    return /*#__PURE__*/React.createElement("div", {
      className: "twk-row twk-row-h"
    }, /*#__PURE__*/React.createElement("div", {
      className: "twk-lbl"
    }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("input", {
      type: "color",
      className: "twk-swatch",
      value: value,
      onChange: e => onChange(e.target.value)
    }));
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = o => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-chips",
    role: "radiogroup"
  }, options.map((o, i) => {
    const colors = Array.isArray(o) ? o : [o];
    const [hero, ...rest] = colors;
    const sup = rest.slice(0, 4);
    const on = key(o) === cur;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      type: "button",
      className: "twk-chip",
      role: "radio",
      "aria-checked": on,
      "data-on": on ? '1' : '0',
      "aria-label": colors.join(', '),
      title: colors.join(' · '),
      style: {
        background: hero
      },
      onClick: () => onChange(o)
    }, sup.length > 0 && /*#__PURE__*/React.createElement("span", null, sup.map((c, j) => /*#__PURE__*/React.createElement("i", {
      key: j,
      style: {
        background: c
      }
    }))), on && /*#__PURE__*/React.createElement(__TwkCheck, {
      light: __twkIsLight(hero)
    }));
  })));
}
function TweakButton({
  label,
  onClick,
  secondary = false
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: secondary ? 'twk-btn secondary' : 'twk-btn',
    onClick: onClick
  }, label);
}
Object.assign(window, {
  useTweaks,
  TweaksPanel,
  TweakSection,
  TweakRow,
  TweakSlider,
  TweakToggle,
  TweakRadio,
  TweakSelect,
  TweakText,
  TweakNumber,
  TweakColor,
  TweakButton
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/docs/tweaks-panel.jsx", error: String((e && e.message) || e) }); }

// ui_kits/marketing/app.jsx
try { (() => {
/* ============================================================
   Hire Buddha — Marketing app (mount + tweaks + reveal)
   ============================================================ */
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "heroVariant": "centered",
  "accent": "metallic",
  "theme": "dark"
} /*EDITMODE-END*/;
function useReveal(dep) {
  useEffect(() => {
    const els = [...document.querySelectorAll('.reveal')];
    const io = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) {
          e.target.classList.add('in');
          io.unobserve(e.target);
        }
      });
    }, {
      threshold: 0.12
    });
    els.forEach(el => io.observe(el));
    return () => io.disconnect();
  }, [dep]);
}
function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [preset, setPreset] = useState(undefined); // undefined = closed
  const [open, setOpen] = useState(false);
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', t.theme);
  }, [t.theme]);

  // Render Lucide icons after every render (step + agent + modal icons)
  useEffect(() => {
    if (window.lucide) window.lucide.createIcons();
  });
  useReveal(t.heroVariant);
  const openBlank = () => {
    setPreset(null);
    setOpen(true);
  };
  const openWith = a => {
    setPreset(a);
    setOpen(true);
  };
  const metallic = t.accent === 'metallic';
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Nav, {
    onDesign: openBlank
  }), /*#__PURE__*/React.createElement(Hero, {
    variant: t.heroVariant,
    metallic: metallic,
    onDesign: openBlank
  }), /*#__PURE__*/React.createElement(HowItWorks, null), /*#__PURE__*/React.createElement(AgentGallery, {
    onHire: openWith
  }), /*#__PURE__*/React.createElement(Closing, {
    metallic: metallic,
    onDesign: openBlank
  }), /*#__PURE__*/React.createElement(Footer, null), open && /*#__PURE__*/React.createElement(DesignModal, {
    preset: preset,
    onClose: () => setOpen(false)
  }), /*#__PURE__*/React.createElement(TweaksPanel, null, /*#__PURE__*/React.createElement(TweakSection, {
    label: "Hero"
  }), /*#__PURE__*/React.createElement(TweakRadio, {
    label: "Direction",
    value: t.heroVariant,
    options: ['centered', 'split', 'mark'],
    onChange: v => setTweak('heroVariant', v)
  }), /*#__PURE__*/React.createElement(TweakSection, {
    label: "Accent"
  }), /*#__PURE__*/React.createElement(TweakRadio, {
    label: "Gold style",
    value: t.accent,
    options: ['solid', 'metallic'],
    onChange: v => setTweak('accent', v)
  }), /*#__PURE__*/React.createElement(TweakSection, {
    label: "Theme"
  }), /*#__PURE__*/React.createElement(TweakRadio, {
    label: "Surface",
    value: t.theme,
    options: ['dark', 'light'],
    onChange: v => setTweak('theme', v)
  })));
}
ReactDOM.createRoot(document.getElementById('root')).render(/*#__PURE__*/React.createElement(App, null));
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/marketing/app.jsx", error: String((e && e.message) || e) }); }

// ui_kits/marketing/marketing-components.jsx
try { (() => {
/* ============================================================
   Hire Buddha — Marketing components
   Exports to window: Icon, Nav, Hero, HowItWorks, AgentGallery,
   Closing, Footer, DesignModal, AGENTS
   ============================================================ */
const {
  useState,
  useEffect,
  useRef
} = React;

/* Lucide icon wrapper — SVG is created centrally by App (see refreshIcons) */
function Icon({
  name,
  size = 20,
  stroke = 1.75,
  style
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": name,
    style: {
      width: size,
      height: size,
      strokeWidth: stroke,
      display: 'inline-flex',
      ...style
    }
  });
}
const LOGO = "../../assets/";
const AGENTS = [{
  id: 'ops',
  name: 'Operations Buddha',
  role: 'OPS · AUTONOMOUS',
  icon: 'workflow',
  desc: 'Runs billing, invoicing and reconciliation end-to-end. Reports to you weekly.',
  tools: ['stripe', 'quickbooks', 'gmail']
}, {
  id: 'support',
  name: 'Support Buddha',
  role: 'SUPPORT · AUTONOMOUS',
  icon: 'life-buoy',
  desc: 'Answers tickets across email and chat. Escalates only what truly needs you.',
  tools: ['zendesk', 'slack', 'notion']
}, {
  id: 'sales',
  name: 'Sales Buddha',
  role: 'GROWTH · AUTONOMOUS',
  icon: 'trending-up',
  desc: 'Researches leads, drafts tailored outreach, and books meetings on your calendar.',
  tools: ['hubspot', 'gmail', 'calendar']
}, {
  id: 'research',
  name: 'Research Buddha',
  role: 'RESEARCH · AUTONOMOUS',
  icon: 'flask-conical',
  desc: 'Reads, synthesizes, and briefs you on any topic — with citations, not vibes.',
  tools: ['web', 'arxiv', 'docs']
}, {
  id: 'finance',
  name: 'Finance Buddha',
  role: 'FINANCE · AUTONOMOUS',
  icon: 'landmark',
  desc: 'Tracks spend, forecasts runway, and files clean reports every month.',
  tools: ['ramp', 'stripe', 'sheets']
}, {
  id: 'recruit',
  name: 'Recruiting Buddha',
  role: 'PEOPLE · AUTONOMOUS',
  icon: 'users-round',
  desc: 'Sources candidates, screens for fit, and schedules — you just meet the best.',
  tools: ['linkedin', 'gmail', 'calendar']
}];
const ALL_TOOLS = ['gmail', 'slack', 'stripe', 'notion', 'hubspot', 'quickbooks', 'calendar', 'sheets', 'zendesk', 'ramp', 'linkedin', 'web'];

/* ---------------- Nav ---------------- */
function Nav({
  onDesign
}) {
  return /*#__PURE__*/React.createElement("nav", {
    className: "nav"
  }, /*#__PURE__*/React.createElement("div", {
    className: "wrap nav-inner"
  }, /*#__PURE__*/React.createElement("a", {
    href: "#top"
  }, /*#__PURE__*/React.createElement("img", {
    className: "nav-logo",
    src: LOGO + "logo-hire-buddha-onblack.svg",
    alt: "Hire Buddha"
  })), /*#__PURE__*/React.createElement("div", {
    className: "nav-links"
  }, /*#__PURE__*/React.createElement("a", {
    href: "#how"
  }, "Product"), /*#__PURE__*/React.createElement("a", {
    href: "#agents"
  }, "Agents"), /*#__PURE__*/React.createElement("a", {
    href: "#research"
  }, "Research"), /*#__PURE__*/React.createElement("a", {
    href: "#docs"
  }, "Docs"), /*#__PURE__*/React.createElement("a", {
    href: "#pricing"
  }, "Pricing")), /*#__PURE__*/React.createElement("div", {
    className: "nav-right"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn btn-ghost"
  }, "Sign in"), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: onDesign
  }, "Design your Buddha ", /*#__PURE__*/React.createElement("span", {
    "aria-hidden": true
  }, "\u2192")))));
}

/* ---------------- Console preview ---------------- */
function ConsolePreview() {
  return /*#__PURE__*/React.createElement("div", {
    className: "console reveal"
  }, /*#__PURE__*/React.createElement("div", {
    className: "console-bar"
  }, /*#__PURE__*/React.createElement("span", {
    className: "console-dot"
  }), /*#__PURE__*/React.createElement("span", {
    className: "console-dot"
  }), /*#__PURE__*/React.createElement("span", {
    className: "console-dot"
  }), /*#__PURE__*/React.createElement("span", {
    className: "console-title"
  }, "workforce \xB7 4 employed")), /*#__PURE__*/React.createElement("div", {
    className: "console-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "crow sel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cav"
  }, /*#__PURE__*/React.createElement("img", {
    src: LOGO + "logo-mark-gold.svg"
  })), /*#__PURE__*/React.createElement("div", {
    className: "cmeta"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cnm"
  }, "Operations Buddha"), /*#__PURE__*/React.createElement("div", {
    className: "csub"
  }, "stripe \xB7 quickbooks \xB7 gmail")), /*#__PURE__*/React.createElement("div", {
    className: "cstat"
  }, /*#__PURE__*/React.createElement("span", {
    className: "d"
  }), "running")), /*#__PURE__*/React.createElement("div", {
    className: "crow"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cav"
  }, /*#__PURE__*/React.createElement("img", {
    src: LOGO + "logo-mark-white.svg",
    style: {
      opacity: .75
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "cmeta"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cnm"
  }, "Support Buddha"), /*#__PURE__*/React.createElement("div", {
    className: "csub"
  }, "zendesk \xB7 slack")), /*#__PURE__*/React.createElement("div", {
    className: "cstat",
    style: {
      color: 'var(--positive)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "d",
    style: {
      background: 'var(--positive)'
    }
  }), "idle")), /*#__PURE__*/React.createElement("div", {
    className: "crow"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cav"
  }, /*#__PURE__*/React.createElement("img", {
    src: LOGO + "logo-mark-white.svg",
    style: {
      opacity: .75
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "cmeta"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cnm"
  }, "Research Buddha"), /*#__PURE__*/React.createElement("div", {
    className: "csub"
  }, "web \xB7 arxiv \xB7 docs")), /*#__PURE__*/React.createElement("div", {
    className: "cstat"
  }, /*#__PURE__*/React.createElement("span", {
    className: "d"
  }), "running"))));
}

/* ---------------- Hero ---------------- */
function Hero({
  variant,
  metallic,
  onDesign
}) {
  const cta = /*#__PURE__*/React.createElement("div", {
    className: "hero-cta"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn btn-lg " + (metallic ? "metallic" : "btn-primary"),
    onClick: onDesign
  }, "Design your Buddha ", /*#__PURE__*/React.createElement("span", {
    "aria-hidden": true
  }, "\u2192")), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-lg btn-secondary"
  }, "See it work"));
  const eyebrow = /*#__PURE__*/React.createElement("div", {
    className: "eyebrow hero-eyebrow"
  }, "// Buddha Cognitive Lab");
  const sub = /*#__PURE__*/React.createElement("p", {
    className: "hero-sub"
  }, "Design an autonomous AI employee \u2014 give it your tools and your goals \u2014 and let it run your business, end to end.");
  const note = /*#__PURE__*/React.createElement("div", {
    className: "hero-note"
  }, "No headcount. No onboarding. One mind, fully employed.");
  if (variant === 'split') {
    return /*#__PURE__*/React.createElement("header", {
      className: "hero split",
      id: "top"
    }, /*#__PURE__*/React.createElement("div", {
      className: "hero-glow",
      style: {
        left: '-200px',
        top: '-160px'
      }
    }), /*#__PURE__*/React.createElement("div", {
      className: "wrap"
    }, /*#__PURE__*/React.createElement("div", {
      className: "hero-grid"
    }, /*#__PURE__*/React.createElement("div", null, eyebrow, /*#__PURE__*/React.createElement("h1", null, "HIRE MINDS,", /*#__PURE__*/React.createElement("br", null), "NOT HEADCOUNT"), sub, cta, note), /*#__PURE__*/React.createElement(ConsolePreview, null))));
  }
  if (variant === 'mark') {
    return /*#__PURE__*/React.createElement("header", {
      className: "hero mark",
      id: "top"
    }, /*#__PURE__*/React.createElement("div", {
      className: "hero-glow",
      style: {
        left: '-160px',
        top: '-120px'
      }
    }), /*#__PURE__*/React.createElement("div", {
      className: "wrap"
    }, /*#__PURE__*/React.createElement("div", {
      className: "hero-grid"
    }, /*#__PURE__*/React.createElement("div", {
      className: "hero-medallion"
    }, /*#__PURE__*/React.createElement("img", {
      src: LOGO + "logo-mark-black.svg"
    })), /*#__PURE__*/React.createElement("div", null, eyebrow, /*#__PURE__*/React.createElement("h1", null, "HIRE MINDS,", /*#__PURE__*/React.createElement("br", null), "NOT HEADCOUNT"), sub, cta, note))));
  }
  // centered (default)
  return /*#__PURE__*/React.createElement("header", {
    className: "hero centered",
    id: "top"
  }, /*#__PURE__*/React.createElement("div", {
    className: "hero-glow",
    style: {
      left: '50%',
      top: '-120px',
      transform: 'translateX(-50%)'
    }
  }), /*#__PURE__*/React.createElement("img", {
    className: "hero-watermark",
    src: LOGO + "logo-mark-gold.svg"
  }), /*#__PURE__*/React.createElement("div", {
    className: "wrap"
  }, eyebrow, /*#__PURE__*/React.createElement("h1", null, "HIRE MINDS,", /*#__PURE__*/React.createElement("br", null), "NOT HEADCOUNT"), sub, cta, note));
}

/* ---------------- How it works ---------------- */
const STEPS = [{
  n: '01',
  ico: 'wand-2',
  t: 'Design',
  d: 'Shape a role. Name it, set a goal, choose its tools and the model that powers it.'
}, {
  n: '02',
  ico: 'badge-check',
  t: 'Employ',
  d: 'Hire your Buddha with one click. It onboards itself to your systems and learns your way.'
}, {
  n: '03',
  ico: 'workflow',
  t: 'Automate',
  d: 'It runs the work end-to-end — quietly, precisely, while you do what only you can.'
}];
function HowItWorks() {
  return /*#__PURE__*/React.createElement("section", {
    className: "section",
    id: "how"
  }, /*#__PURE__*/React.createElement("div", {
    className: "wrap"
  }, /*#__PURE__*/React.createElement("div", {
    className: "section-head reveal"
  }, /*#__PURE__*/React.createElement("div", {
    className: "eyebrow"
  }, "// How it works"), /*#__PURE__*/React.createElement("h2", null, "Three steps to your", /*#__PURE__*/React.createElement("br", null), "first autonomous employee.")), /*#__PURE__*/React.createElement("div", {
    className: "steps"
  }, STEPS.map(s => /*#__PURE__*/React.createElement("div", {
    className: "step reveal",
    key: s.n
  }, /*#__PURE__*/React.createElement("div", {
    className: "step-num"
  }, s.n), /*#__PURE__*/React.createElement("div", {
    className: "step-ico"
  }, /*#__PURE__*/React.createElement(Icon, {
    name: s.ico,
    size: 22
  })), /*#__PURE__*/React.createElement("h3", null, s.t), /*#__PURE__*/React.createElement("p", null, s.d))))));
}

/* ---------------- Agent gallery ---------------- */
function AgentGallery({
  onHire
}) {
  return /*#__PURE__*/React.createElement("section", {
    className: "section",
    id: "agents",
    style: {
      paddingTop: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "wrap"
  }, /*#__PURE__*/React.createElement("div", {
    className: "section-head center reveal"
  }, /*#__PURE__*/React.createElement("div", {
    className: "eyebrow"
  }, "// Pre-trained Buddhas"), /*#__PURE__*/React.createElement("h2", null, "Start with a role. Make it yours."), /*#__PURE__*/React.createElement("p", {
    className: "section-lead"
  }, "Each Buddha arrives trained for the work. Hire one as-is, or open it up and design every detail.")), /*#__PURE__*/React.createElement("div", {
    className: "agents"
  }, AGENTS.map(a => /*#__PURE__*/React.createElement("div", {
    className: "agent reveal",
    key: a.id,
    onClick: () => onHire(a)
  }, /*#__PURE__*/React.createElement("div", {
    className: "agent-top"
  }, /*#__PURE__*/React.createElement("div", {
    className: "agent-av"
  }, /*#__PURE__*/React.createElement("img", {
    src: LOGO + "logo-mark-gold.svg"
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h3", null, a.name), /*#__PURE__*/React.createElement("div", {
    className: "role"
  }, a.role))), /*#__PURE__*/React.createElement("p", null, a.desc), /*#__PURE__*/React.createElement("div", {
    className: "chips"
  }, a.tools.map(t => /*#__PURE__*/React.createElement("span", {
    className: "chip",
    key: t
  }, t))), /*#__PURE__*/React.createElement("div", {
    className: "agent-foot"
  }, /*#__PURE__*/React.createElement("span", {
    className: "agent-hire"
  }, "Hire this Buddha ", /*#__PURE__*/React.createElement("span", {
    "aria-hidden": true
  }, "\u2192")), /*#__PURE__*/React.createElement(Icon, {
    name: a.icon,
    size: 18,
    style: {
      color: 'var(--fg-faint)'
    }
  })))))));
}

/* ---------------- Closing CTA ---------------- */
function Closing({
  metallic,
  onDesign
}) {
  return /*#__PURE__*/React.createElement("section", {
    className: "closing",
    id: "pricing"
  }, /*#__PURE__*/React.createElement("div", {
    className: "closing-glow"
  }), /*#__PURE__*/React.createElement("img", {
    className: "closing-mark",
    src: LOGO + "logo-mark-gold.svg"
  }), /*#__PURE__*/React.createElement("div", {
    className: "wrap"
  }, /*#__PURE__*/React.createElement("div", {
    className: "eyebrow",
    style: {
      marginBottom: '22px'
    }
  }, "// Begin"), /*#__PURE__*/React.createElement("h2", {
    className: "reveal"
  }, "TOWARDS DIGITAL", /*#__PURE__*/React.createElement("br", null), "ENLIGHTENMENT"), /*#__PURE__*/React.createElement("p", {
    className: "reveal"
  }, "Your workforce begins with one. Design it now \u2014 it\u2019s working before your coffee\u2019s cold."), /*#__PURE__*/React.createElement("button", {
    className: "btn btn-lg " + (metallic ? "metallic" : "btn-primary"),
    onClick: onDesign
  }, "Design your Buddha ", /*#__PURE__*/React.createElement("span", {
    "aria-hidden": true
  }, "\u2192"))));
}

/* ---------------- Footer ---------------- */
const FOOT = [{
  h: 'Product',
  items: ['Overview', 'Agents', 'Pricing', 'Changelog']
}, {
  h: 'Lab',
  items: ['Research', 'Models', 'Safety', 'Publications']
}, {
  h: 'Company',
  items: ['About', 'Careers', 'Blog', 'Contact']
}];
function Footer() {
  return /*#__PURE__*/React.createElement("footer", {
    className: "footer",
    id: "docs"
  }, /*#__PURE__*/React.createElement("div", {
    className: "wrap"
  }, /*#__PURE__*/React.createElement("div", {
    className: "footer-grid"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("img", {
    className: "footer-logo",
    src: LOGO + "logo-buddha-cognitive-lab-onblack.svg",
    alt: "Buddha Cognitive Lab"
  }), /*#__PURE__*/React.createElement("div", {
    className: "footer-tag"
  }, "A frontier AI research lab. Building minds with practical applicability.")), FOOT.map(col => /*#__PURE__*/React.createElement("div", {
    key: col.h
  }, /*#__PURE__*/React.createElement("h4", null, col.h), /*#__PURE__*/React.createElement("ul", null, col.items.map(i => /*#__PURE__*/React.createElement("li", {
    key: i
  }, /*#__PURE__*/React.createElement("a", {
    href: "#"
  }, i))))))), /*#__PURE__*/React.createElement("div", {
    className: "footer-bottom"
  }, /*#__PURE__*/React.createElement("span", null, "\xA9 2026 Buddha Cognitive Lab \xB7 Towards digital enlightenment"), /*#__PURE__*/React.createElement("div", {
    className: "social"
  }, /*#__PURE__*/React.createElement("a", {
    href: "https://buddhalab.in"
  }, "buddhalab.in"), /*#__PURE__*/React.createElement("a", {
    href: "#"
  }, "@buddhalab")))));
}

/* ---------------- Design modal ---------------- */
function DesignModal({
  preset,
  onClose
}) {
  const [name, setName] = useState(preset ? preset.name : 'Operations Buddha');
  const [goal, setGoal] = useState(preset ? preset.desc : '');
  const [tools, setTools] = useState(preset ? preset.tools : ['gmail']);
  const [model, setModel] = useState('buddha-frontier-1');
  const [hired, setHired] = useState(false);
  const toggle = t => setTools(ts => ts.includes(t) ? ts.filter(x => x !== t) : [...ts, t]);
  useEffect(() => {
    const esc = e => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, []);
  return /*#__PURE__*/React.createElement("div", {
    className: "scrim",
    onMouseDown: e => {
      if (e.target === e.currentTarget) onClose();
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "modal"
  }, !hired ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "modal-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "agent-av"
  }, /*#__PURE__*/React.createElement("img", {
    src: LOGO + "logo-mark-gold.svg"
  })), /*#__PURE__*/React.createElement("div", {
    className: "modal-title"
  }, "Design your Buddha"), /*#__PURE__*/React.createElement("button", {
    className: "modal-x",
    onClick: onClose
  }, /*#__PURE__*/React.createElement(Icon, {
    name: "x",
    size: 18
  }))), /*#__PURE__*/React.createElement("div", {
    className: "modal-body"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Role name"), /*#__PURE__*/React.createElement("input", {
    value: name,
    onChange: e => setName(e.target.value),
    placeholder: "e.g. Operations Buddha"
  })), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Goal \u2014 what should it own?"), /*#__PURE__*/React.createElement("input", {
    value: goal,
    onChange: e => setGoal(e.target.value),
    placeholder: "Close the books every month, end to end"
  })), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Tools it can use"), /*#__PURE__*/React.createElement("div", {
    className: "tool-toggle"
  }, ALL_TOOLS.map(t => /*#__PURE__*/React.createElement("button", {
    key: t,
    className: "tool" + (tools.includes(t) ? " on" : ""),
    onClick: () => toggle(t)
  }, t)))), /*#__PURE__*/React.createElement("div", {
    className: "field"
  }, /*#__PURE__*/React.createElement("label", null, "Model"), /*#__PURE__*/React.createElement("select", {
    value: model,
    onChange: e => setModel(e.target.value)
  }, /*#__PURE__*/React.createElement("option", {
    value: "buddha-frontier-1"
  }, "buddha-frontier-1 \xB7 most capable"), /*#__PURE__*/React.createElement("option", {
    value: "buddha-swift-1"
  }, "buddha-swift-1 \xB7 fast & economical"), /*#__PURE__*/React.createElement("option", {
    value: "buddha-deep-1"
  }, "buddha-deep-1 \xB7 long-horizon reasoning")))), /*#__PURE__*/React.createElement("div", {
    className: "modal-foot"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn btn-ghost",
    onClick: onClose
  }, "Cancel"), /*#__PURE__*/React.createElement("button", {
    className: "btn metallic",
    onClick: () => setHired(true)
  }, "Hire this Buddha ", /*#__PURE__*/React.createElement("span", {
    "aria-hidden": true
  }, "\u2192")))) : /*#__PURE__*/React.createElement("div", {
    className: "success"
  }, /*#__PURE__*/React.createElement("div", {
    className: "success-mark"
  }, /*#__PURE__*/React.createElement("img", {
    src: LOGO + "logo-mark-black.svg"
  })), /*#__PURE__*/React.createElement("h3", null, name, " is employed."), /*#__PURE__*/React.createElement("p", null, "It\u2019s onboarding to ", tools.length, " tool", tools.length !== 1 ? 's' : '', " now and will start its first tasks in moments. You\u2019ll get a brief when it\u2019s done."), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: '26px'
    }
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn btn-primary",
    onClick: onClose
  }, "Back to workforce")))));
}
Object.assign(window, {
  Icon,
  Nav,
  Hero,
  ConsolePreview,
  HowItWorks,
  AgentGallery,
  Closing,
  Footer,
  DesignModal,
  AGENTS
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/marketing/marketing-components.jsx", error: String((e && e.message) || e) }); }

// ui_kits/marketing/tweaks-panel.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)

/* BEGIN USAGE */
// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
// Exports (to window): useTweaks, TweaksPanel, TweakSection, TweakRow, TweakSlider,
//   TweakToggle, TweakRadio, TweakSelect, TweakText, TweakNumber, TweakColor, TweakButton.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// TweakRadio is the segmented control for 2–3 short options (auto-falls-back to
// TweakSelect past ~16/~10 chars per label); reach for TweakSelect directly when
// options are many or long. For color tweaks always curate 3-4 options rather than
// a free picker; an option can also be a whole 2–5 color palette (the stored value
// is the array). The Tweak* controls are a floor, not a ceiling — build custom
// controls inside the panel if a tweak calls for UI they don't cover.
/* END USAGE */
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;box-sizing:border-box;width:100%;min-width:0;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;box-sizing:border-box;min-width:0;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null ? keyOrEdits : {
      [keyOrEdits]: val
    };
    setValues(prev => ({
      ...prev,
      ...edits
    }));
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits
    }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', {
      detail: edits
    }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({
  title = 'Tweaks',
  children
}) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  const offsetRef = React.useRef({
    x: 16,
    y: 16
  });
  const PAD = 16;
  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth,
      h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y))
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);
  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);
  React.useEffect(() => {
    const onMsg = e => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({
      type: '__edit_mode_available'
    }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);
  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({
      type: '__edit_mode_dismissed'
    }, '*');
  };
  const onDragStart = e => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX,
      sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = ev => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy)
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };
  if (!open) return null;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("style", null, __TWEAKS_STYLE), /*#__PURE__*/React.createElement("div", {
    ref: dragRef,
    className: "twk-panel",
    "data-omelette-chrome": "",
    style: {
      right: offsetRef.current.x,
      bottom: offsetRef.current.y
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-hd",
    onMouseDown: onDragStart
  }, /*#__PURE__*/React.createElement("b", null, title), /*#__PURE__*/React.createElement("button", {
    className: "twk-x",
    "aria-label": "Close tweaks",
    onMouseDown: e => e.stopPropagation(),
    onClick: dismiss
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    className: "twk-body"
  }, children)));
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({
  label,
  children
}) {
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "twk-sect"
  }, label), children);
}
function TweakRow({
  label,
  value,
  children,
  inline = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: inline ? 'twk-row twk-row-h' : 'twk-row'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label), value != null && /*#__PURE__*/React.createElement("span", {
    className: "twk-val"
  }, value)), children);
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label,
    value: `${value}${unit}`
  }, /*#__PURE__*/React.createElement("input", {
    type: "range",
    className: "twk-slider",
    min: min,
    max: max,
    step: step,
    value: value,
    onChange: e => onChange(Number(e.target.value))
  }));
}
function TweakToggle({
  label,
  value,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-row twk-row-h"
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "twk-toggle",
    "data-on": value ? '1' : '0',
    role: "switch",
    "aria-checked": !!value,
    onClick: () => onChange(!value)
  }, /*#__PURE__*/React.createElement("i", null)));
}
function TweakRadio({
  label,
  value,
  options,
  onChange
}) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = o => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({
    2: 16,
    3: 10
  }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = s => {
      const m = options.find(o => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return /*#__PURE__*/React.createElement(TweakSelect, {
      label: label,
      value: value,
      options: options,
      onChange: s => onChange(resolve(s))
    });
  }
  const opts = options.map(o => typeof o === 'object' ? o : {
    value: o,
    label: o
  });
  const idx = Math.max(0, opts.findIndex(o => o.value === value));
  const n = opts.length;
  const segAt = clientX => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor((clientX - r.left - 2) / inner * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };
  const onPointerDown = e => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = ev => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    ref: trackRef,
    role: "radiogroup",
    onPointerDown: onPointerDown,
    className: dragging ? 'twk-seg dragging' : 'twk-seg'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-seg-thumb",
    style: {
      left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
      width: `calc((100% - 4px) / ${n})`
    }
  }), opts.map(o => /*#__PURE__*/React.createElement("button", {
    key: o.value,
    type: "button",
    role: "radio",
    "aria-checked": o.value === value
  }, o.label))));
}
function TweakSelect({
  label,
  value,
  options,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("select", {
    className: "twk-field",
    value: value,
    onChange: e => onChange(e.target.value)
  }, options.map(o => {
    const v = typeof o === 'object' ? o.value : o;
    const l = typeof o === 'object' ? o.label : o;
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    }, l);
  })));
}
function TweakText({
  label,
  value,
  placeholder,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("input", {
    className: "twk-field",
    type: "text",
    value: value,
    placeholder: placeholder,
    onChange: e => onChange(e.target.value)
  }));
}
function TweakNumber({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange
}) {
  const clamp = n => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({
    x: 0,
    val: 0
  });
  const onScrubStart = e => {
    e.preventDefault();
    startRef.current = {
      x: e.clientX,
      val: value
    };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = ev => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-num"
  }, /*#__PURE__*/React.createElement("span", {
    className: "twk-num-lbl",
    onPointerDown: onScrubStart
  }, label), /*#__PURE__*/React.createElement("input", {
    type: "number",
    value: value,
    min: min,
    max: max,
    step: step,
    onChange: e => onChange(clamp(Number(e.target.value)))
  }), unit && /*#__PURE__*/React.createElement("span", {
    className: "twk-num-unit"
  }, unit));
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, c => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = n >> 16 & 255,
    g = n >> 8 & 255,
    b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}
const __TwkCheck = ({
  light
}) => /*#__PURE__*/React.createElement("svg", {
  viewBox: "0 0 14 14",
  "aria-hidden": "true"
}, /*#__PURE__*/React.createElement("path", {
  d: "M3 7.2 5.8 10 11 4.2",
  fill: "none",
  strokeWidth: "2.2",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  stroke: light ? 'rgba(0,0,0,.78)' : '#fff'
}));

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({
  label,
  value,
  options,
  onChange
}) {
  if (!options || !options.length) {
    return /*#__PURE__*/React.createElement("div", {
      className: "twk-row twk-row-h"
    }, /*#__PURE__*/React.createElement("div", {
      className: "twk-lbl"
    }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("input", {
      type: "color",
      className: "twk-swatch",
      value: value,
      onChange: e => onChange(e.target.value)
    }));
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = o => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-chips",
    role: "radiogroup"
  }, options.map((o, i) => {
    const colors = Array.isArray(o) ? o : [o];
    const [hero, ...rest] = colors;
    const sup = rest.slice(0, 4);
    const on = key(o) === cur;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      type: "button",
      className: "twk-chip",
      role: "radio",
      "aria-checked": on,
      "data-on": on ? '1' : '0',
      "aria-label": colors.join(', '),
      title: colors.join(' · '),
      style: {
        background: hero
      },
      onClick: () => onChange(o)
    }, sup.length > 0 && /*#__PURE__*/React.createElement("span", null, sup.map((c, j) => /*#__PURE__*/React.createElement("i", {
      key: j,
      style: {
        background: c
      }
    }))), on && /*#__PURE__*/React.createElement(__TwkCheck, {
      light: __twkIsLight(hero)
    }));
  })));
}
function TweakButton({
  label,
  onClick,
  secondary = false
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: secondary ? 'twk-btn secondary' : 'twk-btn',
    onClick: onClick
  }, label);
}
Object.assign(window, {
  useTweaks,
  TweaksPanel,
  TweakSection,
  TweakRow,
  TweakSlider,
  TweakToggle,
  TweakRadio,
  TweakSelect,
  TweakText,
  TweakNumber,
  TweakColor,
  TweakButton
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/marketing/tweaks-panel.jsx", error: String((e && e.message) || e) }); }

})();
