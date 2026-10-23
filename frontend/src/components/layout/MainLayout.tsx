import React, { useState, useEffect, Suspense } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { useTheme } from '@/hooks/useTheme';
import { NotificationBell } from '@/components/notifications/NotificationBell';
import { WorkspaceGate } from './WorkspaceGate';
import { ActingCompanyBanner, ActingCompanySwitcher } from './ActingCompany';
import {
    Menu,
    X,
    LogOut,
    User,
    Moon,
    Sun,
    LayoutGrid,
    Server,
    Bot,
    BrainCircuit,
    ShieldCheck,
    TerminalSquare,
    Radio,
    PhoneCall,
    Activity,
    Megaphone,
    FolderTree,
    BookOpen,
    Blocks,
    Archive,
    LineChart,
    PieChart,
    TrendingUp,
    CreditCard,
    Wallet,
    PiggyBank,
    Settings,
    Route,
    ChevronDown,
    Brain,
    Wrench,
    Layers,
    Users,
    Gauge,
    Sparkles,
    Receipt,
    Flag,
    ShieldAlert,
    Timer,
    Database,
    Plug,
    AppWindow,
    Code2,
    Building2,
} from 'lucide-react';
import { UserRole } from '@/types';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import logo from '@/assets/logo.png';
import './MainLayout.css';

interface MainLayoutProps {
    children: React.ReactNode;
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [userMenuOpen, setUserMenuOpen] = useState(false);
    const [openSubmenus, setOpenSubmenus] = useState<Record<string, boolean>>({});
    const { logout, user } = useAuth();
    // Partners and platform staff may work in another company's data (Phase 14 M2-4).
    const canActForOthers = [UserRole.APP_ADMIN, UserRole.APP_USER, UserRole.PARTNER_ADMIN, UserRole.PARTNER_USER]
        .includes(user?.role as UserRole);
    const { theme, toggleTheme } = useTheme();
    const location = useLocation();

    const menuGroups = [
        {
            isStandalone: true,
            path: '/dashboard',
            label: 'Dashboard',
            icon: LayoutGrid,
        },
        ...(([UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN].includes(user?.role as UserRole)) ? [{
            isStandalone: true,
            path: '/platform-management',
            label: 'Platform Hub',
            icon: Server,
        }] : []),
        ...(([UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN].includes(user?.role as UserRole)) ? [{
            isStandalone: true,
            path: '/partner',
            label: 'Partner Dashboard',
            icon: Users,
        }] : []),
        {
            title: 'AI Workspace',
            icon: Bot,
            items: [
                { path: '/ai/entities', label: 'Entity Library', icon: BrainCircuit },
                { path: '/ai/templates', label: 'Template Marketplace', icon: Layers },
                { path: '/ai/approvals', label: 'Guardian Oversight', icon: ShieldCheck },
                { path: '/ai/executions', label: 'Executions', icon: TerminalSquare },
                { path: '/automation', label: 'Control Room', icon: Timer },
                { path: '/records', label: 'Records', icon: Database },
                { path: '/apps', label: 'Apps', icon: AppWindow },
                { path: '/code', label: 'Code', icon: Code2 },
                { path: '/cortex', label: 'Memory Trees', icon: Brain },
                ...(([UserRole.APP_ADMIN].includes(user?.role as UserRole)) ? [{ path: '/ai/tool-registry', label: 'Tool Registry', icon: Wrench }] : []),
            ]
        },
        {
            title: 'Communications',
            icon: Radio,
            items: [
                { path: '/phone-numbers', label: 'Phone Numbers', icon: PhoneCall },
                { path: '/streaming/sessions', label: 'Streaming Sessions', icon: Activity },
                { path: '/streaming/campaigns', label: 'Campaigns', icon: Megaphone },
            ]
        },
        {
            title: 'Assets & Connections',
            icon: FolderTree,
            items: [
                { path: '/knowledge', label: 'Knowledge Base', icon: BookOpen },
                { path: '/connections', label: 'Connections', icon: Plug },
                // System integrations are HireBuddha staff's (D40); businesses' own keys move to
                // Connections with WS7's conversion (REGISTRY_PLATFORM_ONLY), until then they stay here.
                { path: '/integrations', label: user?.role === UserRole.APP_ADMIN ? 'System Integrations' : 'Integrations',
                  icon: Blocks },
                ...(([UserRole.APP_ADMIN].includes(user?.role as UserRole)) ? [{ path: '/ai-config', label: 'AI Configuration', icon: Route }] : []),
                { path: '/artifacts', label: 'Artifacts', icon: Archive },
            ]
        },
        {
            title: 'Analytics & Reports',
            icon: LineChart,
            items: [
                ...(user?.role === UserRole.APP_ADMIN ? [{ path: '/reports/analytics/app-admin', label: 'Platform Analytics', icon: PieChart }] : []),
                ...(([UserRole.APP_ADMIN, UserRole.APP_USER].includes(user?.role as UserRole)) ? [{ path: '/reports/analytics/app-user', label: 'Ops & Incidents', icon: TrendingUp }] : []),
                ...(([UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN].includes(user?.role as UserRole)) ? [{ path: '/reports/analytics/partner-admin', label: 'Portfolio Analytics', icon: PieChart }] : []),
                ...(([UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.PARTNER_USER].includes(user?.role as UserRole)) ? [{ path: '/reports/analytics/partner-user', label: 'Tenant Support', icon: Activity }] : []),
                ...(([UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN].includes(user?.role as UserRole)) ? [{ path: '/reports/analytics/tenant-admin', label: 'Operations Analytics', icon: PieChart }] : []),
                { path: '/reports/analytics/tenant-user', label: 'My Analytics', icon: TrendingUp },
            ]
        },
        {
            title: 'Finance & Administration',
            icon: CreditCard,
            items: [
                { path: '/wallet', label: 'Wallet & Credits', icon: Wallet },
                { path: '/settings/tenant', label: 'Business Settings', icon: Settings },
                { path: '/settings/automation', label: 'Automation Settings', icon: Timer },
                ...(([UserRole.APP_ADMIN].includes(user?.role as UserRole)) ? [{ path: '/admin/automation', label: 'Platform Automation', icon: Timer }] : []),
                ...(([UserRole.APP_ADMIN].includes(user?.role as UserRole)) ? [{ path: '/admin/tenants', label: 'Tenants', icon: Building2 }] : []),
                ...(([UserRole.APP_ADMIN].includes(user?.role as UserRole)) ? [{ path: '/admin/connectors', label: 'Connector Approvals', icon: Plug }] : []),
                ...(([UserRole.APP_ADMIN].includes(user?.role as UserRole)) ? [{ path: '/reports/costing', label: 'Costing Report', icon: PiggyBank }] : []),
                ...(([UserRole.APP_ADMIN].includes(user?.role as UserRole)) ? [{ path: '/settings/billing', label: 'Billing Settings', icon: Settings }] : []),
            ]
        },
        // Phase 11 — Agent Kernel observability + admin. Admin-only.
        ...(([UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN].includes(user?.role as UserRole)) ? [{
            title: 'Agent Kernel',
            icon: BrainCircuit,
            items: [
                { path: '/admin/agent-kernel/kpi', label: 'KPI Dashboard', icon: Gauge },
                { path: '/admin/agent-kernel/meta-intelligence', label: 'Meta-Agent Intelligence', icon: Sparkles },
                { path: '/admin/agent-kernel/cost', label: 'Cost Attribution', icon: Receipt },
                // Engineering switches: staff only (Phase 15 Q6, T0-1).
                ...(user?.role === UserRole.APP_ADMIN ? [{ path: '/admin/agent-kernel/feature-flags', label: 'Feature Flags', icon: Flag }] : []),
                { path: '/admin/agent-kernel/risks', label: 'Risk & Exit', icon: ShieldAlert },
            ]
        }] : [])
    ];

    const isActive = (path: string) => location.pathname.startsWith(path);

    const toggleSubmenu = (title: string) => {
        setOpenSubmenus(prev => ({ ...prev, [title]: !prev[title] }));
    };

    // The groups holding the current page, opened when you navigate into them.
    const activeGroupKey = menuGroups
        .filter(group => !group.isStandalone && group.items?.some(item => isActive(item.path)))
        .map(group => group.title!)
        .join('|');

    useEffect(() => {
        if (!activeGroupKey) return;
        // An updater: the effect used to copy `openSubmenus` from the render it
        // was created in, so a submenu toggled since could be reverted (FE-08).
        setOpenSubmenus(prev => {
            const titles = activeGroupKey.split('|');
            if (titles.every(title => prev[title])) return prev;
            return { ...prev, ...Object.fromEntries(titles.map(title => [title, true])) };
        });
    }, [activeGroupKey]);

    return (
        <div className="main-layout">

            {/* Sidebar */}
            <aside className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
                <div className="sidebar-header">
                    <div className="logo-container">
                        <img src={logo} alt="HireBuddha" className="sidebar-logo-img" />
                        {sidebarOpen && <h2 className="text-rose-gold">HireBuddha</h2>}
                    </div>
                    <button
                        className="sidebar-toggle"
                        onClick={() => setSidebarOpen(!sidebarOpen)}
                        aria-expanded={sidebarOpen}
                        aria-label={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
                    >
                        {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
                    </button>
                </div>

                <nav className="sidebar-nav">
                    <div className="sidebar-nav-links">
                        {menuGroups.map((group, index) => {
                            if (group.isStandalone) {
                                const Icon = group.icon;
                                return (
                                    <Link
                                        key={group.path || index}
                                        to={group.path!}
                                        className={`nav-item ${isActive(group.path!) ? 'active' : ''}`}
                                        title={!sidebarOpen ? group.label : ''}
                                    >
                                        <div className="nav-item-icon">
                                            <Icon size={20} />
                                        </div>
                                        {sidebarOpen && <span className="nav-item-label">{group.label}</span>}
                                    </Link>
                                );
                            }

                            const Icon = group.icon;
                            const isExpanded = openSubmenus[group.title!];
                            const hasActiveChild = group.items?.some(item => isActive(item.path));

                            return (
                                <div key={group.title} className={`nav-group ${hasActiveChild ? 'has-active-child' : ''}`}>
                                    <button
                                        className={`nav-group-header ${isExpanded ? 'expanded' : ''} ${hasActiveChild && !isExpanded ? 'active-collapsed' : ''}`}
                                        onClick={() => {
                                            if (!sidebarOpen) setSidebarOpen(true);
                                            toggleSubmenu(group.title!);
                                        }}
                                        title={!sidebarOpen ? group.title : ''}
                                    >
                                        <div className="nav-item-icon">
                                            <Icon size={20} />
                                        </div>
                                        {sidebarOpen && (
                                            <>
                                                <span className="nav-item-label">{group.title}</span>
                                                <ChevronDown
                                                    size={16}
                                                    className={`nav-group-chevron ${isExpanded ? 'rotated' : ''}`}
                                                />
                                            </>
                                        )}
                                    </button>

                                    <div className={`nav-group-items ${isExpanded && sidebarOpen ? 'expanded' : ''}`}>
                                        {group.items?.map(item => {
                                            const ItemIcon = item.icon;
                                            return (
                                                <Link
                                                    key={item.path}
                                                    to={item.path}
                                                    className={`nav-item sub-item ${isActive(item.path) ? 'active' : ''}`}
                                                    title={!sidebarOpen ? item.label : ''}
                                                >
                                                    <div className="nav-item-icon">
                                                        <ItemIcon size={18} />
                                                    </div>
                                                    {sidebarOpen && <span className="nav-item-label">{item.label}</span>}
                                                </Link>
                                            )
                                        })}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                    <div className="sidebar-footer pt-4 border-t border-white/5 mt-4 space-y-2">
                        {canActForOthers && <ActingCompanySwitcher expanded={sidebarOpen} ownCompanyId={user?.company_id} />}
                        <NotificationBell expanded={sidebarOpen} />
                        <button
                            className="theme-toggle-button w-full"
                            onClick={toggleTheme}
                            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
                        >
                            <div className="nav-item-icon">
                                {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
                            </div>
                            {sidebarOpen && <span>{theme === 'dark' ? 'Luminescence' : 'Eclipse'} Mode</span>}
                        </button>

                        <div className="user-menu">
                            <button
                                className="user-menu-button w-full"
                                onClick={() => setUserMenuOpen(!userMenuOpen)}
                            >
                                <div className="nav-item-icon">
                                    <User size={20} />
                                </div>
                                {sidebarOpen && <span className="truncate flex-1 text-left">{user?.full_name || user?.email}</span>}
                            </button>

                            {userMenuOpen && (
                                <div className={`user-menu-dropdown glass ${sidebarOpen ? 'open' : 'closed-compact'}`}>
                                    <Link
                                        to="/profile"
                                        className="user-menu-item"
                                        onClick={() => setUserMenuOpen(false)}
                                    >
                                        <User size={16} />
                                        {sidebarOpen && <span>Profile Settings</span>}
                                    </Link>
                                    <button className="user-menu-item" onClick={logout}>
                                        <LogOut size={16} />
                                        {sidebarOpen && <span>Logout</span>}
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                </nav>
            </aside>

            {/* Main Content */}
            <div className="main-content">
                {/* A page that throws, or whose chunk is still loading, takes
                    only this area — the sidebar stays (FE-01). Navigating away
                    clears the error. */}
                <main>
                    <ErrorBoundary scope="This page" resetKey={location.pathname}>
                        <Suspense fallback={<div className="page-loading">Loading…</div>}>
                            {canActForOthers && <ActingCompanyBanner />}
                            <WorkspaceGate>{children}</WorkspaceGate>
                        </Suspense>
                    </ErrorBoundary>
                </main>
            </div>
        </div>
    );
};
