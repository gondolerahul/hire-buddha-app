/**
 * router/guards — who may open a page (Phase 15 T9-1; 07 §2.5, §10).
 *
 * `Protected` needs a sign-in (and, optionally, roles). `Guarded` adds the
 * navigation rules: a route of another workspace, or of an item the person does
 * not see (role, partner type, staff function), sends them to their own home;
 * a feature their plan lacks shows a locked page — never a bare 403.
 */
import React from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { Lock } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { HOME, itemForRoute, routeAccess, WORKSPACE_OF } from '@/nav/config';
import { useEntitlements } from '@/queries/hooks';
import { getActingCompany } from '@/services/actingCompany';
import type { UserRole } from '@/types';

export const PageLoader: React.FC = () => (
    <div className="loading-container">
        <div className="pulse"><div className="loading">Initializing...</div></div>
    </div>
);

export function homeOf(role?: string): string {
    return HOME[WORKSPACE_OF[role ?? ''] ?? 'business'];
}

export const Protected: React.FC<{ children: React.ReactNode; roles?: UserRole[] }> = ({ children, roles }) => {
    const { isAuthenticated, user, loading } = useAuth();
    if (loading) return <PageLoader />;
    if (!isAuthenticated) return <Navigate to="/login" replace />;
    if (roles && user && !roles.includes(user.role)) return <Navigate to={homeOf(user.role)} replace />;
    return <>{children}</>;
};

export const LockedPage: React.FC<{ label?: string }> = ({ label }) => (
    <div className="money-console" style={{ maxWidth: 640 }}>
        <div className="money-card glass">
            <h2><Lock size={18} /> {label ?? 'This feature'} is not in your plan</h2>
            <p className="card-desc">
                Your plan does not include it. Compare the plans and change yours on the <Link to="/billing/plan">Plan</Link> page.
            </p>
        </div>
    </div>
);

/** A page under the navigation rules (on top of `Protected`). */
export const Guarded: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const { user } = useAuth();
    const location = useLocation();
    const staff = user?.role === 'app_admin' || user?.role === 'app_user';
    const entitlements = useEntitlements(!!user && !staff);
    if (!user) return <>{children}</>;
    if (!staff && entitlements.isLoading) return <PageLoader />;
    const access = routeAccess(location.pathname, {
        role: user.role,
        acting: !!getActingCompany(),
        partnerType: user.partner_type ?? null,
        staffFunctions: user.staff_functions ?? [],
        entitlements: entitlements.data
            ? Object.fromEntries(Object.entries(entitlements.data.entitlements).map(([k, v]) => [k, v.enabled]))
            : undefined,
    });
    if (access === 'forbidden') return <Navigate to={homeOf(user.role)} replace />;
    if (access === 'locked') return <LockedPage label={itemForRoute(location.pathname)?.label} />;
    return <>{children}</>;
};
