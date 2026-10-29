/**
 * nav/config — every menu entry of the three workspaces, declared once (Phase 15 T9-1; 07 §2, §4).
 *
 * An item names its route and who sees it: roles, a partner type (Gold or
 * Silver), an app_user's staff function, and the plan entitlement it needs
 * (shown locked, never hidden, when the plan lacks it — 07 §2.5). `menuFor`
 * resolves the menu for one person; the layout renders exactly that, and a
 * test snapshots it per role.
 */
import type { StaffFunction, UserRole } from '@/types';

export type Workspace = 'console' | 'partner' | 'business';
export type PartnerTypeCode = 'SILVER' | 'GOLD';

export interface NavItem {
    id: string;
    label: string;
    route: string;
    icon: string;                       // a lucide icon name (nav/icons.ts)
    roles?: UserRole[];                 // default: every role of the workspace
    partnerTypes?: PartnerTypeCode[];
    staffFunctions?: StaffFunction[];   // app_user needs one of these; app_admin always passes
    entitlement?: string;               // feature.* key; locked when the plan lacks it
}

export interface NavGroup {
    id: string;
    label: string;
    icon: string;
    items: NavItem[];
}

const A = 'app_admin' as UserRole;
const U = 'app_user' as UserRole;
const PA = 'partner_admin' as UserRole;
const PU = 'partner_user' as UserRole;
const TA = 'tenant_admin' as UserRole;
const TU = 'tenant_user' as UserRole;

export const WORKSPACE_OF: Record<string, Workspace> = {
    app_admin: 'console', app_user: 'console', partner_admin: 'partner', partner_user: 'partner',
    tenant_admin: 'business', tenant_user: 'business',
};

export const HOME: Record<Workspace, string> = { console: '/console', partner: '/partner', business: '/home' };

/** 07 §4.1–4.2: the Platform Console. Staff functions: support, sales, finance, ops. */
const CONSOLE: NavGroup[] = [
    { id: 'home', label: 'Home', icon: 'LayoutGrid', items: [
        { id: 'console-home', label: 'Platform overview', route: '/console', icon: 'LayoutGrid' },
    ] },
    { id: 'customers', label: 'Customers', icon: 'Building2', items: [
        { id: 'companies', label: 'Companies', route: '/console/companies', icon: 'Building2', staffFunctions: ['support', 'sales', 'finance'] },
        { id: 'users', label: 'Users', route: '/console/users', icon: 'Users', staffFunctions: ['support'] },
        { id: 'workspaces', label: 'Workspaces', route: '/console/workspaces', icon: 'Database', roles: [A] },
    ] },
    { id: 'partners', label: 'Partners', icon: 'HeartHandshake', items: [
        { id: 'partner-network', label: 'Partner network', route: '/console/partners', icon: 'HeartHandshake', staffFunctions: ['sales'] },
        { id: 'applications', label: 'Applications', route: '/console/partners/applications', icon: 'ClipboardCheck', roles: [A] },
        { id: 'leads', label: 'Leads', route: '/console/leads', icon: 'Target', staffFunctions: ['sales'] },
        { id: 'programme-rules', label: 'Programme rules', route: '/console/partners/rules', icon: 'Scale', roles: [A] },
    ] },
    { id: 'commercial', label: 'Commercial', icon: 'Coins', items: [
        { id: 'plans', label: 'Plans & entitlements', route: '/console/plans', icon: 'Layers', roles: [A] },
        { id: 'pricing', label: 'Pricing', route: '/console/pricing', icon: 'Tag', roles: [A] },
        { id: 'formula', label: 'Billing formula', route: '/console/formula', icon: 'Sigma', roles: [A] },
        { id: 'daily-credits', label: 'Daily credits', route: '/console/daily-credits', icon: 'Timer', roles: [A] },
        { id: 'currency', label: 'Currency & FX', route: '/console/currency', icon: 'Coins', roles: [A] },
        { id: 'wallet-policy', label: 'Wallet & admission', route: '/console/wallet-policy', icon: 'Wallet', roles: [A] },
        { id: 'tax', label: 'Tax & invoicing', route: '/console/tax', icon: 'Receipt', roles: [A] },
    ] },
    { id: 'finance', label: 'Finance', icon: 'PiggyBank', items: [
        { id: 'revenue', label: 'Revenue & margin', route: '/console/finance/revenue', icon: 'TrendingUp', staffFunctions: ['finance'] },
        { id: 'receivables', label: 'Receivables', route: '/console/finance/receivables', icon: 'AlertTriangle', staffFunctions: ['finance'] },
        { id: 'payments', label: 'Payments & invoices', route: '/console/finance/payments', icon: 'Receipt', staffFunctions: ['finance'] },
        { id: 'payouts', label: 'Partner payouts', route: '/console/finance/payouts', icon: 'Wallet', staffFunctions: ['finance'] },
        { id: 'liability', label: 'Wallet liability', route: '/console/finance/liability', icon: 'PiggyBank', staffFunctions: ['finance'] },
        { id: 'shadow', label: 'Billing shadow', route: '/console/finance/shadow', icon: 'Scale', roles: [A] },
    ] },
    { id: 'operations', label: 'Operations', icon: 'Activity', items: [
        { id: 'runs', label: 'Runs', route: '/console/ops/runs', icon: 'TerminalSquare', staffFunctions: ['ops', 'support'] },
        { id: 'ops-approvals', label: 'Approvals oversight', route: '/console/ops/approvals', icon: 'ShieldCheck', staffFunctions: ['ops', 'support'] },
        { id: 'ops-calls', label: 'Calls & campaigns', route: '/console/ops/calls', icon: 'PhoneCall', staffFunctions: ['ops', 'support'] },
        { id: 'ops-numbers', label: 'Phone number pool', route: '/console/ops/numbers', icon: 'Phone', staffFunctions: ['ops'] },
        { id: 'ops-apps', label: 'Apps & hosting', route: '/console/ops/apps', icon: 'AppWindow', staffFunctions: ['ops'] },
        { id: 'ops-automation', label: 'Automation', route: '/console/ops/automation', icon: 'Timer', staffFunctions: ['ops'] },
        { id: 'ops-health', label: 'Health & incidents', route: '/console/ops/health', icon: 'Gauge', staffFunctions: ['ops'] },
    ] },
    { id: 'ai', label: 'AI platform', icon: 'BrainCircuit', items: [
        { id: 'skus', label: 'Models & SKUs', route: '/console/ai/skus', icon: 'Blocks', roles: [A] },
        { id: 'routing', label: 'Model routing', route: '/console/ai/routing', icon: 'Route', roles: [A] },
        { id: 'tools', label: 'Tools', route: '/console/ai/tools', icon: 'Wrench', roles: [A] },
        { id: 'templates', label: 'Templates', route: '/console/ai/templates', icon: 'Layers', roles: [A] },
        { id: 'connectors', label: 'Connectors', route: '/console/ai/connectors', icon: 'Plug', roles: [A] },
        { id: 'kernel-kpi', label: 'Kernel KPIs', route: '/console/ai/kernel/kpi', icon: 'Gauge', staffFunctions: ['ops'] },
        { id: 'kernel-meta', label: 'Meta-agent', route: '/console/ai/kernel/meta', icon: 'Sparkles', staffFunctions: ['ops'] },
        { id: 'kernel-cost', label: 'Cost attribution', route: '/console/ai/kernel/cost', icon: 'Receipt', staffFunctions: ['ops', 'finance'] },
        { id: 'kernel-flags', label: 'Feature flags', route: '/console/ai/kernel/flags', icon: 'Flag', roles: [A] },
        { id: 'kernel-risks', label: 'Risk & exit', route: '/console/ai/kernel/risks', icon: 'ShieldAlert', staffFunctions: ['ops'] },
    ] },
    { id: 'reports', label: 'Reports', icon: 'LineChart', items: [
        { id: 'console-reports', label: 'Report library', route: '/console/reports', icon: 'LineChart' },
    ] },
    { id: 'settings', label: 'Settings', icon: 'Settings', items: [
        { id: 'platform-settings', label: 'Platform settings', route: '/console/settings', icon: 'Settings', roles: [A] },
        { id: 'audit', label: 'Audit log', route: '/console/audit', icon: 'ScrollText', roles: [A] },
    ] },
];

/** 07 §4.3–4.4: the Partner Portal. */
const PARTNER: NavGroup[] = [
    { id: 'home', label: 'Home', icon: 'LayoutGrid', items: [
        { id: 'partner-home', label: 'Overview', route: '/partner', icon: 'LayoutGrid' },
    ] },
    { id: 'customers', label: 'Customers', icon: 'Users', items: [
        { id: 'my-tenants', label: 'My tenants', route: '/partner/tenants', icon: 'Building2', partnerTypes: ['GOLD'] },
        { id: 'referred', label: 'Referred customers', route: '/partner/customers', icon: 'Users', partnerTypes: ['SILVER'] },
        { id: 'partner-leads', label: 'Leads', route: '/partner/leads', icon: 'Target' },
        { id: 'charges', label: 'Setup & customisation fees', route: '/partner/charges', icon: 'Receipt', roles: [PA], partnerTypes: ['GOLD'] },
    ] },
    { id: 'network', label: 'Network', icon: 'Network', items: [
        { id: 'my-partners', label: 'My partners', route: '/partner/network', icon: 'Network', roles: [PA] },
    ] },
    { id: 'earnings', label: 'Earnings', icon: 'PiggyBank', items: [
        { id: 'earnings', label: 'Earnings', route: '/partner/earnings', icon: 'PiggyBank', roles: [PA] },
        { id: 'statements', label: 'Statements & payouts', route: '/partner/statements', icon: 'FileText', roles: [PA] },
    ] },
    { id: 'partnership', label: 'Partnership', icon: 'BadgeCheck', items: [
        { id: 'partnership', label: 'Partnership', route: '/partner/partnership', icon: 'BadgeCheck', roles: [PA] },
        { id: 'guide', label: 'Programme guide', route: '/partner/guide', icon: 'BookOpen' },
    ] },
    { id: 'reports', label: 'Reports', icon: 'LineChart', items: [
        { id: 'partner-reports', label: 'Reports', route: '/partner/reports', icon: 'LineChart' },
    ] },
    { id: 'team', label: 'Team', icon: 'Users', items: [
        { id: 'partner-team', label: 'Team', route: '/partner/team', icon: 'Users', roles: [PA] },
        { id: 'partner-access', label: 'Access grants', route: '/partner/access', icon: 'KeyRound', roles: [PA], partnerTypes: ['GOLD'] },
    ] },
];

/** 07 §4.5–4.6: the Business Workspace. */
const BUSINESS: NavGroup[] = [
    { id: 'home', label: 'Home', icon: 'LayoutGrid', items: [
        { id: 'business-home', label: 'Overview', route: '/home', icon: 'LayoutGrid' },
    ] },
    { id: 'employees', label: 'AI employees', icon: 'Bot', items: [
        { id: 'agents', label: 'Employees', route: '/agents', icon: 'Bot', entitlement: 'feature.agents.builder' },
        { id: 'templates', label: 'Templates', route: '/agents/templates', icon: 'Layers', roles: [TA], entitlement: 'feature.agents.templates' },
        { id: 'knowledge', label: 'Knowledge', route: '/knowledge', icon: 'BookOpen', entitlement: 'feature.knowledge.base' },
    ] },
    { id: 'work', label: 'Work', icon: 'TerminalSquare', items: [
        { id: 'work-history', label: 'Work history', route: '/work', icon: 'TerminalSquare' },
        { id: 'approvals', label: 'Approvals', route: '/approvals', icon: 'ShieldCheck', entitlement: 'feature.agents.hitl' },
        { id: 'automation', label: 'Automation', route: '/automation', icon: 'Timer', roles: [TA], entitlement: 'feature.automation.triggers' },
    ] },
    { id: 'calls', label: 'Customers & calls', icon: 'PhoneCall', items: [
        { id: 'campaigns', label: 'Campaigns', route: '/calls/campaigns', icon: 'Megaphone', entitlement: 'feature.voice.outbound_campaigns' },
        { id: 'calls', label: 'Calls', route: '/calls', icon: 'PhoneCall', entitlement: 'feature.voice.inbound' },
        { id: 'conversations', label: 'Conversations', route: '/conversations', icon: 'MessagesSquare' },
        { id: 'numbers', label: 'Phone numbers', route: '/calls/numbers', icon: 'Phone', roles: [TA], entitlement: 'feature.phone_numbers' },
    ] },
    { id: 'data', label: 'Data & apps', icon: 'Database', items: [
        { id: 'records', label: 'Records', route: '/records', icon: 'Database', roles: [TA], entitlement: 'feature.records' },
        { id: 'apps', label: 'Apps', route: '/apps', icon: 'AppWindow', roles: [TA], entitlement: 'feature.apps.hosting' },
        { id: 'code', label: 'Code', route: '/code', icon: 'Code2', roles: [TA], entitlement: 'feature.code.lanes' },
        { id: 'connections', label: 'Connections', route: '/connections', icon: 'Plug', roles: [TA] },
        { id: 'files', label: 'Files', route: '/files', icon: 'Archive' },
    ] },
    { id: 'billing', label: 'Billing', icon: 'Wallet', items: [
        { id: 'wallet', label: 'Wallet', route: '/billing', icon: 'Wallet', roles: [TA] },
        { id: 'plan', label: 'Plan', route: '/billing/plan', icon: 'Star', roles: [TA] },
        { id: 'usage', label: 'Usage & charges', route: '/billing/usage', icon: 'BarChart3', roles: [TA] },
        { id: 'invoices', label: 'Invoices', route: '/billing/invoices', icon: 'FileText', roles: [TA] },
        { id: 'fees', label: 'Fees to pay', route: '/billing/charges', icon: 'Receipt', roles: [TA] },
        { id: 'controls', label: 'Spend controls', route: '/billing/controls', icon: 'Gauge', roles: [TA] },
    ] },
    { id: 'reports', label: 'Reports', icon: 'LineChart', items: [
        { id: 'business-reports', label: 'Reports', route: '/reports', icon: 'LineChart' },
    ] },
    { id: 'settings', label: 'Settings', icon: 'Settings', items: [
        { id: 'business-profile', label: 'Business profile', route: '/settings', icon: 'Building2', roles: [TA] },
        { id: 'team', label: 'Team', route: '/settings/team', icon: 'Users', roles: [TA] },
        { id: 'automation-settings', label: 'Automation & data', route: '/settings/automation', icon: 'Timer', roles: [TA] },
        { id: 'partner-access', label: 'Partner access', route: '/settings/partner-access', icon: 'KeyRound', roles: [TA] },
        { id: 'support-access', label: 'Support access', route: '/settings/support-access', icon: 'LifeBuoy', roles: [TA] },
        { id: 'data-closing', label: 'Data & closing', route: '/settings/data', icon: 'ShieldAlert', roles: [TA] },
    ] },
];

export const NAV: Record<Workspace, NavGroup[]> = { console: CONSOLE, partner: PARTNER, business: BUSINESS };

export interface Viewer {
    role: string;
    /** Working inside a tenant (staff, or a Gold partner under a grant): the tenant's menu and pages (07 §2.7). */
    acting?: boolean;
    partnerType?: PartnerTypeCode | null;
    staffFunctions?: StaffFunction[];
    /** feature key → enabled; absent keys are enabled (everything is on at launch). */
    entitlements?: Record<string, boolean>;
}

export interface ResolvedItem extends NavItem {
    locked: boolean;
}

export interface ResolvedGroup extends Omit<NavGroup, 'items'> {
    items: ResolvedItem[];
}

export function itemVisible(item: NavItem, viewer: Viewer): boolean {
    const role = viewer.role as UserRole;
    if (item.roles && !item.roles.includes(role)) return false;
    if (item.partnerTypes && !(viewer.partnerType && item.partnerTypes.includes(viewer.partnerType))) {
        // A partner without a known type (before the programme) is treated as Gold (06 §11.9, I-38).
        if (!(viewer.partnerType == null && item.partnerTypes.includes('GOLD'))) return false;
    }
    if (item.staffFunctions && role === U) {
        const mine = viewer.staffFunctions ?? [];
        if (!item.staffFunctions.some(f => mine.includes(f))) return false;
    }
    return true;
}

/** Who a person is inside a tenant they act in: an admin, or — a partner_user — a user (07 §4.4). */
export function actingAs(viewer: Viewer): Viewer {
    if (!viewer.acting || WORKSPACE_OF[viewer.role] === 'business') return viewer;
    return { ...viewer, role: viewer.role === PU ? TU : TA, entitlements: undefined };
}

/** The menu one person sees: their workspace's groups, the items they may see, locked where the plan lacks it. */
export function menuFor(original: Viewer): ResolvedGroup[] {
    const viewer = actingAs(original);
    const workspace = WORKSPACE_OF[viewer.role] ?? 'business';
    const staffLike = viewer.role === A || viewer.role === U;
    return NAV[workspace]
        .map(group => ({
            ...group,
            items: group.items.filter(item => itemVisible(item, viewer)).map(item => ({
                ...item,
                locked: !staffLike && !!item.entitlement && viewer.entitlements?.[item.entitlement] === false,
            })),
        }))
        .filter(group => group.items.length > 0);
}

/** The item a route belongs to (longest matching prefix), for guards and the active state. */
export function itemForRoute(path: string, workspace?: Workspace): NavItem | undefined {
    const groups = workspace ? NAV[workspace] : [...CONSOLE, ...PARTNER, ...BUSINESS];
    let best: NavItem | undefined;
    for (const item of groups.flatMap(g => g.items)) {
        const match = path === item.route || path.startsWith(item.route.endsWith('/') ? item.route : `${item.route}/`);
        if (match && (!best || item.route.length > best.route.length)) best = item;
    }
    return best;
}

export const ROLES = { A, U, PA, PU, TA, TU };

export type Access = 'ok' | 'locked' | 'forbidden';

/**
 * Whether a viewer may open a route: a route that belongs to another workspace,
 * or to an item the viewer does not see, is forbidden; one whose entitlement the
 * plan lacks is locked (a locked page, not a 403 — 07 §2.5). A route no menu item
 * covers (a profile, a run's page) is left to its own guard.
 */
export function routeAccess(path: string, original: Viewer): Access {
    // Staff open a business's pages (their lists span every company); others only while acting in one.
    const staff = original.role === A || original.role === U;
    const viewer = staff && !original.acting && businessRoute(path) ? { ...original, role: TA } : actingAs(original);
    const mine = WORKSPACE_OF[viewer.role] ?? 'business';
    for (const workspace of Object.keys(NAV) as Workspace[]) {
        const item = itemForRoute(path, workspace);
        if (!item) continue;
        if (workspace !== mine) return 'forbidden';
        if (!itemVisible(item, viewer)) return 'forbidden';
        const staffLike = viewer.role === A || viewer.role === U;
        return !staffLike && item.entitlement && viewer.entitlements?.[item.entitlement] === false ? 'locked' : 'ok';
    }
    return 'ok';
}

function businessRoute(path: string): boolean {
    return !!itemForRoute(path, 'business') && !path.startsWith('/console') && !path.startsWith('/partner');
}
