/**
 * components/layout/MainLayout — the app shell of the three workspaces (Phase 15 T9-1; 07 §2, §3, §4).
 *
 * The menu is generated from `nav/config` for the signed-in person — their
 * workspace (Platform Console, Partner Portal, Business Workspace), role,
 * partner type, staff functions and plan entitlements (locked, not hidden).
 * The top bar names the workspace and shows a business's balance chip; the
 * acting, balance and lock banners sit above every page.
 */
import React, { useState, useEffect, useMemo, Suspense } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ChevronDown, Lock, LogOut, Menu, Moon, Sun, User, X } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { useTheme } from '@/hooks/useTheme';
import { NotificationBell } from '@/components/notifications/NotificationBell';
import { BalanceBanner, BalanceChip, LockBanner } from '@/components/billing/BalanceBar';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { menuFor, WORKSPACE_OF, type ResolvedItem } from '@/nav/config';
import { iconFor } from '@/nav/icons';
import { useEntitlements } from '@/queries/hooks';
import { getActingCompany } from '@/services/actingCompany';
import { UserRole } from '@/types';
import logo from '@/assets/logo.png';

import { WorkspaceGate } from './WorkspaceGate';
import { ActingCompanyBanner, ActingCompanySwitcher } from './ActingCompany';
import './MainLayout.css';

const WORKSPACE_LABEL = { console: 'Platform Console', partner: 'Partner Portal', business: 'Business Workspace' };

interface MainLayoutProps {
    children: React.ReactNode;
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
    const [sidebarOpen, setSidebarOpen] = useState(true);
    const [userMenuOpen, setUserMenuOpen] = useState(false);
    const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});
    const { logout, user } = useAuth();
    const { theme, toggleTheme } = useTheme();
    const location = useLocation();

    const role = (user?.role ?? 'tenant_user') as UserRole;
    const workspace = WORKSPACE_OF[role] ?? 'business';
    const isStaff = workspace === 'console';
    const isTenant = workspace === 'business';
    // Staff, and Gold partners (with grants), work inside other companies (07 §3; Silver never).
    const canActForOthers = isStaff || (workspace === 'partner' && user?.partner_type !== 'SILVER');
    const entitlements = useEntitlements(!!user && !isStaff).data?.entitlements;

    const acting = !!getActingCompany();
    const menu = useMemo(() => menuFor({
        role,
        acting,
        partnerType: user?.partner_type ?? null,
        staffFunctions: user?.staff_functions ?? [],
        entitlements: entitlements ? Object.fromEntries(Object.entries(entitlements).map(([k, v]) => [k, v.enabled])) : undefined,
    }), [role, acting, user?.partner_type, user?.staff_functions, entitlements]);

    const allRoutes = useMemo(() => menu.flatMap(g => g.items.map(i => i.route)), [menu]);
    // Active: the most specific menu route the page is under.
    const activeRoute = useMemo(() => allRoutes
        .filter(r => location.pathname === r || location.pathname.startsWith(`${r}/`))
        .sort((a, b) => b.length - a.length)[0], [allRoutes, location.pathname]);
    const activeGroup = menu.find(g => g.items.some(i => i.route === activeRoute))?.id;

    useEffect(() => {
        if (!activeGroup) return;
        setOpenGroups(prev => (prev[activeGroup] ? prev : { ...prev, [activeGroup]: true }));
    }, [activeGroup]);

    const link = (item: ResolvedItem, sub: boolean) => {
        const Icon = iconFor(item.icon);
        return (
            <Link
                key={item.id}
                to={item.locked ? '/billing/plan' : item.route}
                className={`nav-item ${sub ? 'sub-item' : ''} ${activeRoute === item.route ? 'active' : ''} ${item.locked ? 'locked' : ''}`}
                title={item.locked ? `${item.label}: not in your plan — see Plan` : !sidebarOpen ? item.label : ''}
            >
                <div className="nav-item-icon"><Icon size={sub ? 18 : 20} /></div>
                {sidebarOpen && <span className="nav-item-label">{item.label}</span>}
                {sidebarOpen && item.locked && <Lock size={12} className="nav-item-lock" aria-label="Not in your plan" />}
            </Link>
        );
    };

    return (
        <div className="main-layout">
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

                <nav className="sidebar-nav" aria-label={WORKSPACE_LABEL[workspace]}>
                    <div className="sidebar-nav-links">
                        {menu.map(group => {
                            if (group.items.length === 1 && group.id === 'home') return link(group.items[0], false);
                            const GroupIcon = iconFor(group.icon);
                            const expanded = !!openGroups[group.id];
                            const hasActive = group.id === activeGroup;
                            return (
                                <div key={group.id} className={`nav-group ${hasActive ? 'has-active-child' : ''}`}>
                                    <button
                                        className={`nav-group-header ${expanded ? 'expanded' : ''} ${hasActive && !expanded ? 'active-collapsed' : ''}`}
                                        onClick={() => {
                                            if (!sidebarOpen) setSidebarOpen(true);
                                            setOpenGroups(prev => ({ ...prev, [group.id]: !prev[group.id] }));
                                        }}
                                        aria-expanded={expanded}
                                        title={!sidebarOpen ? group.label : ''}
                                    >
                                        <div className="nav-item-icon"><GroupIcon size={20} /></div>
                                        {sidebarOpen && (
                                            <>
                                                <span className="nav-item-label">{group.label}</span>
                                                <ChevronDown size={16} className={`nav-group-chevron ${expanded ? 'rotated' : ''}`} />
                                            </>
                                        )}
                                    </button>
                                    <div className={`nav-group-items ${expanded && sidebarOpen ? 'expanded' : ''}`}>
                                        {group.items.map(item => link(item, true))}
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
                            <div className="nav-item-icon">{theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}</div>
                            {sidebarOpen && <span>{theme === 'dark' ? 'Luminescence' : 'Eclipse'} Mode</span>}
                        </button>
                        <div className="user-menu">
                            <button className="user-menu-button w-full" onClick={() => setUserMenuOpen(!userMenuOpen)}>
                                <div className="nav-item-icon"><User size={20} /></div>
                                {sidebarOpen && <span className="truncate flex-1 text-left">{user?.full_name || user?.email}</span>}
                            </button>
                            {userMenuOpen && (
                                <div className={`user-menu-dropdown glass ${sidebarOpen ? 'open' : 'closed-compact'}`}>
                                    <Link to="/profile" className="user-menu-item" onClick={() => setUserMenuOpen(false)}>
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

            <div className="main-content">
                {/* A page that throws, or whose chunk is still loading, takes only this area (FE-01). */}
                <main>
                    <ErrorBoundary scope="This page" resetKey={location.pathname}>
                        <Suspense fallback={<div className="page-loading">Loading…</div>}>
                            <div className="shell-topbar">
                                <span className="shell-workspace">{acting ? 'Business Workspace (acting)' : WORKSPACE_LABEL[workspace]}</span>
                                {isTenant && <BalanceChip enabled={!!user} isAdmin={role === UserRole.TENANT_ADMIN} />}
                            </div>
                            {canActForOthers && <ActingCompanyBanner />}
                            {isTenant && <BalanceBanner enabled={!!user} isAdmin={role === UserRole.TENANT_ADMIN} />}
                            {isTenant && <LockBanner enabled={!!user} companyId={user?.company_id} />}
                            <WorkspaceGate>{children}</WorkspaceGate>
                        </Suspense>
                    </ErrorBoundary>
                </main>
            </div>
        </div>
    );
};
