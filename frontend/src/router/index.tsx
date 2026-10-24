/**
 * router — every page of the three workspaces, and where every old route went (Phase 15 T9-1, T9-11; 07 §4, §9).
 *
 * Routes are a table: a path, its page, and whether the navigation rules guard
 * it (`Guarded`: the route belongs to the person's workspace and to an item
 * they see; a feature the plan lacks shows a locked page). `REDIRECTS` keeps
 * every old bookmark working.
 */
import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';

import { MainLayout } from '@/components/layout';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { useAuth } from '@/hooks/useAuth';
import { UserRole } from '@/types';

import { Guarded, homeOf, PageLoader, Protected } from './guards';

const page = <T extends React.ComponentType<any>>(load: () => Promise<{ default: T }>) => lazy(load);
const named = <K extends string>(load: () => Promise<Record<K, React.ComponentType<any>>>, name: K) =>
    lazy(() => load().then(m => ({ default: m[name] })));

// ── public ──
const LoginPage = named(() => import('@/pages/auth'), 'LoginPage');
const RegisterPage = named(() => import('@/pages/auth'), 'RegisterPage');
const ForgotPasswordPage = named(() => import('@/pages/auth/PasswordReset'), 'ForgotPasswordPage');
const ResetPasswordPage = named(() => import('@/pages/auth/PasswordReset'), 'ResetPasswordPage');
const VerifyEmailPage = named(() => import('@/pages/auth/VerifyEmail'), 'VerifyEmailPage');
const OAuthCallbackPage = named(() => import('@/pages/auth/OAuthCallback'), 'OAuthCallbackPage');
const PartnerApplyPage = page(() => import('@/pages/partner/PartnerApplyPage'));
const OnboardingWizard = page(() => import('@/pages/OnboardingWizard'));

// ── shared ──
const UserSettings = named(() => import('@/pages/UserSettings'), 'UserSettings');
const ReportLibrary = page(() => import('@/pages/reports/ReportLibrary'));
const ReportPage = page(() => import('@/pages/reports/ReportPage'));
const TeamPage = page(() => import('@/pages/settings/TeamPage'));

// ── Business Workspace ──
const BusinessHome = page(() => import('@/pages/business/BusinessHome'));
const EntityLibrary = named(() => import('@/pages/ai/EntityLibrary'), 'EntityLibrary');
const EntityBuilder = named(() => import('@/pages/ai/EntityBuilder'), 'EntityBuilder');
const ExecutionPage = named(() => import('@/pages/ai/ExecutionPage'), 'ExecutionPage');
const ExecutionHistory = named(() => import('@/pages/ai/ExecutionHistory'), 'ExecutionHistory');
const ExecutionDetail = named(() => import('@/pages/ai/ExecutionDetail'), 'ExecutionDetail');
const HITLPanel = named(() => import('@/pages/ai/HITLPanel'), 'HITLPanel');
const TemplateMarketplace = named(() => import('@/pages/ai/TemplateMarketplace'), 'TemplateMarketplace');
const KnowledgeBase = named(() => import('@/pages/KnowledgeBase'), 'KnowledgeBase');
const CortexExplorer = named(() => import('@/pages/ai/CortexExplorer'), 'CortexExplorer');
const CortexTreeDetail = named(() => import('@/pages/ai/CortexTreeDetail'), 'CortexTreeDetail');
const ControlRoom = page(() => import('@/pages/automation/ControlRoom'));
const AutomationSettings = page(() => import('@/pages/automation/AutomationSettings'));
const StreamingSessionsPage = named(() => import('@/pages/streaming'), 'StreamingSessionsPage');
const CampaignsPage = named(() => import('@/pages/streaming'), 'CampaignsPage');
const CampaignDetailPage = named(() => import('@/pages/streaming'), 'CampaignDetailPage');
const CallDetailPage = named(() => import('@/pages/streaming'), 'CallDetailPage');
const PhonePool = page(() => import('@/pages/PhonePool'));
const RecordsPage = page(() => import('@/pages/records/RecordsPage'));
const SchemaPage = page(() => import('@/pages/records/SchemaPage'));
const DataKeysPage = page(() => import('@/pages/records/DataKeysPage'));
const ConnectionsPage = page(() => import('@/pages/connections/ConnectionsPage'));
const ConnectionDetail = page(() => import('@/pages/connections/ConnectionDetail'));
const AppsPage = page(() => import('@/pages/apps/AppsPage'));
const AppDetail = page(() => import('@/pages/apps/AppDetail'));
const CodePage = page(() => import('@/pages/apps/CodePage'));
const Artifacts = named(() => import('@/pages/artifacts/Artifacts'), 'Artifacts');
const WalletPage = named(() => import('@/pages/billing/WalletPage'), 'WalletPage');
const PlanPage = page(() => import('@/pages/billing/PlanPage'));
const InvoicesPage = page(() => import('@/pages/billing/InvoicesPage'));
const ChargesPage = page(() => import('@/pages/billing/ChargesPage'));
const SpendControlsPage = page(() => import('@/pages/billing/SpendControlsPage'));
const TenantSettings = page(() => import('@/pages/settings/TenantSettings'));
const PartnerAccessPage = page(() => import('@/pages/settings/PartnerAccessPage'));

// ── Partner Portal ──
const PartnerHome = page(() => import('@/pages/partner/PartnerHome'));
const PartnerDashboard = page(() => import('@/pages/PartnerDashboard'));
const PartnerCustomers = page(() => import('@/pages/partner/PartnerCustomers'));
const PartnerLeads = page(() => import('@/pages/partner/PartnerLeads'));
const PartnerCharges = page(() => import('@/pages/partner/PartnerCharges'));
const PartnerNetwork = page(() => import('@/pages/partner/PartnerNetwork'));
const PartnerEarnings = page(() => import('@/pages/partner/PartnerEarnings'));
const PartnerPartnership = page(() => import('@/pages/partner/PartnerPartnership'));
const PartnerGuidePage = page(() => import('@/pages/partner/PartnerGuidePage'));
const PartnerAccessGrantsPage = page(() => import('@/pages/partner/PartnerAccessGrantsPage'));

// ── Platform Console ──
const ConsoleHome = page(() => import('@/pages/console/ConsoleHome'));
const CompaniesPage = page(() => import('@/pages/console/CompaniesPage'));
const Company360Page = page(() => import('@/pages/console/Company360Page'));
const AuditLogPage = page(() => import('@/pages/console/AuditLogPage'));
const PlatformManagement = named(() => import('@/pages/PlatformManagement'), 'PlatformManagement');
const TenantsPage = page(() => import('@/pages/admin/TenantsPage'));
const PartnersAdminPage = page(() => import('@/pages/admin/partners/PartnersAdminPage'));
const PartnerDetailPage = page(() => import('@/pages/admin/partners/PartnerDetailPage'));
const PartnerRulesPage = page(() => import('@/pages/admin/partners/PartnerRulesPage'));
const PartnerPayoutsPage = page(() => import('@/pages/admin/partners/PartnerPayoutsPage'));
const PlansAdminPage = page(() => import('@/pages/admin/PlansAdminPage'));
const PricingPage = page(() => import('@/pages/admin/PricingPage'));
const BillingSettings = named(() => import('@/pages/billing/BillingSettings'), 'BillingSettings');
const DailyCreditsPage = page(() => import('@/pages/admin/DailyCreditsPage'));
const CurrencyPage = page(() => import('@/pages/admin/CurrencyPage'));
const MoneySettingsPage = page(() => import('@/pages/admin/MoneySettingsPage'));
const WalletsAdminPage = page(() => import('@/pages/admin/WalletsAdminPage'));
const PaymentsAdminPage = page(() => import('@/pages/admin/PaymentsAdminPage'));
const BillingShadowPage = page(() => import('@/pages/admin/BillingShadowPage'));
const AutomationPlatformPage = page(() => import('@/pages/admin/AutomationPlatformPage'));
const IntegrationsPage = named(() => import('@/pages/IntegrationsPage'), 'IntegrationsPage');
const AIModelConfigPage = named(() => import('@/pages/ai-config/AIModelConfigPage'), 'AIModelConfigPage');
const ToolManagement = named(() => import('@/pages/ai/ToolManagement'), 'ToolManagement');
const ConnectorApprovalsPage = page(() => import('@/pages/admin/ConnectorApprovalsPage'));
const KPIDashboard = page(() => import('@/pages/dashboards/KPIDashboard'));
const MetaIntelligencePage = page(() => import('@/pages/admin/MetaIntelligencePage'));
const CostAttributionDashboard = page(() => import('@/pages/admin/CostAttributionDashboard'));
const FeatureFlagsPage = page(() => import('@/pages/admin/FeatureFlagsPage'));
const RiskAndExitPage = page(() => import('@/pages/admin/RiskAndExitPage'));

const A = UserRole.APP_ADMIN;

/** [path, page, roles?]: guarded by the navigation rules; `roles` narrows further where no menu item covers it. */
type RouteRow = [string, React.ReactNode, UserRole[]?];

export const ROUTES: RouteRow[] = [
    // Business Workspace (07 §4.5–4.6)
    ['/home', <BusinessHome />],
    ['/agents', <EntityLibrary />],
    ['/agents/new', <EntityBuilder />],
    ['/agents/templates', <TemplateMarketplace />],
    ['/agents/:id/run', <ExecutionPage />],
    ['/agents/:id', <EntityBuilder />],
    ['/knowledge', <KnowledgeBase />],
    ['/knowledge/memory', <CortexExplorer />],
    ['/knowledge/memory/:treeId', <CortexTreeDetail />],
    ['/work', <ExecutionHistory />],
    ['/work/:id', <ExecutionDetail />],
    ['/approvals', <HITLPanel />],
    ['/automation', <ControlRoom />],
    ['/calls', <StreamingSessionsPage />],
    ['/calls/campaigns', <CampaignsPage />],
    ['/calls/campaigns/:campaignId', <CampaignDetailPage />],
    ['/calls/numbers', <PhonePool />],
    ['/calls/:sessionId', <CallDetailPage />],
    ['/records', <RecordsPage />],
    ['/records/schema', <SchemaPage />],
    ['/records/keys', <DataKeysPage />],
    ['/apps', <AppsPage />],
    ['/apps/:id', <AppDetail />],
    ['/code', <CodePage />],
    ['/connections', <ConnectionsPage />],
    ['/connections/:id', <ConnectionDetail />],
    ['/files', <Artifacts />],
    ['/billing', <WalletPage />],
    ['/billing/plan', <PlanPage />],
    ['/billing/usage', <ReportPage reportId="R-T02" />],
    ['/billing/invoices', <InvoicesPage />],
    ['/billing/charges', <ChargesPage />],
    ['/billing/controls', <SpendControlsPage />],
    ['/reports', <ReportLibrary workspace="business" />],
    ['/reports/:reportId', <ReportPage />],
    ['/settings', <TenantSettings />],
    ['/settings/team', <TeamPage />],
    ['/settings/automation', <AutomationSettings />],
    ['/settings/partner-access', <PartnerAccessPage />],

    // Partner Portal (07 §4.3–4.4)
    ['/partner', <PartnerHome />],
    ['/partner/tenants', <PartnerDashboard />],
    ['/partner/customers', <PartnerCustomers />],
    ['/partner/leads', <PartnerLeads />],
    ['/partner/charges', <PartnerCharges />],
    ['/partner/network', <PartnerNetwork />],
    ['/partner/earnings', <PartnerEarnings />],
    ['/partner/statements', <Navigate to="/partner/earnings?tab=statements" replace />],
    ['/partner/partnership', <PartnerPartnership />],
    ['/partner/guide', <PartnerGuidePage />],
    ['/partner/reports', <ReportLibrary workspace="partner" />],
    ['/partner/reports/:reportId', <ReportPage />],
    ['/partner/team', <TeamPage />],
    ['/partner/access', <PartnerAccessGrantsPage />],

    // Platform Console (07 §4.1–4.2)
    ['/console', <ConsoleHome />],
    ['/console/companies', <CompaniesPage />],
    ['/console/companies/:id', <Company360Page />],
    ['/console/users', <PlatformManagement />],
    ['/console/workspaces', <TenantsPage />],
    ['/console/partners', <PartnersAdminPage />],
    ['/console/partners/applications', <Navigate to="/console/partners?tab=applications" replace />],
    ['/console/partners/rules', <PartnerRulesPage />],
    ['/console/partners/:id', <PartnerDetailPage />],
    ['/console/leads', <PartnersAdminPage defaultTab="leads" />],
    ['/console/plans', <PlansAdminPage />],
    ['/console/pricing', <PricingPage />],
    ['/console/formula', <BillingSettings />],
    ['/console/daily-credits', <DailyCreditsPage />],
    ['/console/currency', <CurrencyPage />],
    ['/console/wallet-policy', <MoneySettingsPage groups={['wallet', 'admission', 'payments', 'alerts', 'billing']} />],
    ['/console/tax', <MoneySettingsPage groups={['tax']} />],
    ['/console/finance/revenue', <ReportPage reportId="R-A02" />],
    ['/console/finance/receivables', <WalletsAdminPage />],
    ['/console/finance/payments', <PaymentsAdminPage />],
    ['/console/finance/payouts', <PartnerPayoutsPage />],
    ['/console/finance/liability', <ReportPage reportId="R-A05" />],
    ['/console/finance/shadow', <BillingShadowPage />],
    ['/console/ops/runs', <ExecutionHistory />],
    ['/console/ops/runs/:id', <ExecutionDetail />],
    ['/console/ops/approvals', <HITLPanel />],
    ['/console/ops/calls', <StreamingSessionsPage />],
    ['/console/ops/numbers', <PhonePool />],
    ['/console/ops/apps', <ReportPage reportId="R-A17" />],
    ['/console/ops/automation', <AutomationPlatformPage />],
    ['/console/ops/health', <ReportPage reportId="R-A21" />],
    ['/console/ai/skus', <IntegrationsPage />],
    ['/console/ai/routing', <AIModelConfigPage />],
    ['/console/ai/tools', <ToolManagement />],
    ['/console/ai/templates', <TemplateMarketplace />],
    ['/console/ai/connectors', <ConnectorApprovalsPage />],
    ['/console/ai/kernel/kpi', <KPIDashboard />],
    ['/console/ai/kernel/meta', <MetaIntelligencePage />],
    ['/console/ai/kernel/cost', <CostAttributionDashboard />],
    ['/console/ai/kernel/flags', <FeatureFlagsPage />, [A]],
    ['/console/ai/kernel/risks', <RiskAndExitPage />],
    ['/console/reports', <ReportLibrary workspace="console" />],
    ['/console/reports/:reportId', <ReportPage />],
    ['/console/settings', <MoneySettingsPage />],
    ['/console/audit', <AuditLogPage />],
];

/** Every old route and where it went (07 §9). `:params` carry over. */
export const REDIRECTS: Array<[string, string]> = [
    ['/', '/dashboard'],
    ['/ai/entities', '/agents'],
    ['/ai/entities/create', '/agents/new'],
    ['/ai/entities/edit/:id', '/agents/:id'],
    ['/agents/create', '/agents/new'],
    ['/workflows', '/agents'],
    ['/workflows/create', '/agents/new'],
    ['/workflows/:id', '/agents/:id'],
    ['/ai/execute/:id', '/agents/:id/run'],
    ['/execute/:type/:id', '/agents/:id/run'],
    ['/ai/executions', '/work'],
    ['/ai/executions/:id', '/work/:id'],
    ['/executions', '/work'],
    ['/executions/:id', '/work/:id'],
    ['/ai/approvals', '/approvals'],
    ['/ai/templates', '/agents/templates'],
    ['/ai/tool-registry', '/console/ai/tools'],
    ['/ai-config', '/console/ai/routing'],
    ['/integrations', '/console/ai/skus'],
    ['/cortex', '/knowledge/memory'],
    ['/cortex/trees/:treeId', '/knowledge/memory/:treeId'],
    ['/streaming/sessions', '/calls'],
    ['/streaming/calls/:sessionId', '/calls/:sessionId'],
    ['/streaming/campaigns', '/calls/campaigns'],
    ['/streaming/campaigns/:campaignId', '/calls/campaigns/:campaignId'],
    ['/streaming/phone-numbers', '/calls/numbers'],
    ['/phone-numbers', '/calls/numbers'],
    ['/phone-pool', '/calls/numbers'],
    ['/artifacts', '/files'],
    ['/assets', '/files'],
    ['/wallet', '/billing'],
    ['/settings/tenant', '/settings'],
    ['/settings/billing', '/console/formula'],
    ['/reports/costing', '/console/reports/R-A02'],
    ['/reports/analytics/app-admin', '/console/reports'],
    ['/reports/analytics/app-user', '/console/reports'],
    ['/reports/analytics/partner-admin', '/partner/reports'],
    ['/reports/analytics/partner-user', '/partner/reports'],
    ['/reports/analytics/tenant-admin', '/reports'],
    ['/reports/analytics/tenant-user', '/reports'],
    ['/admin/agent-kernel/kpi', '/console/ai/kernel/kpi'],
    ['/admin/agent-kernel/meta-intelligence', '/console/ai/kernel/meta'],
    ['/admin/agent-kernel/cost', '/console/ai/kernel/cost'],
    ['/admin/agent-kernel/feature-flags', '/console/ai/kernel/flags'],
    ['/admin/agent-kernel/risks', '/console/ai/kernel/risks'],
    ['/admin/automation', '/console/ops/automation'],
    ['/admin/tenants', '/console/workspaces'],
    ['/admin/connectors', '/console/ai/connectors'],
    ['/admin/currency', '/console/currency'],
    ['/admin/billing-shadow', '/console/finance/shadow'],
    ['/admin/wallets', '/console/finance/receivables'],
    ['/admin/daily-credits', '/console/daily-credits'],
    ['/admin/pricing', '/console/pricing'],
    ['/admin/money-settings', '/console/settings'],
    ['/admin/plans', '/console/plans'],
    ['/admin/payments', '/console/finance/payments'],
    ['/admin/partners', '/console/partners'],
    ['/admin/partners/rules', '/console/partners/rules'],
    ['/admin/partners/payouts', '/console/finance/payouts'],
    ['/admin/partners/:id', '/console/partners/:id'],
    ['/partners', '/console/partners'],
    ['/tenants', '/console/companies'],
    ['/users', '/console/users'],
];

const ParamRedirect: React.FC<{ to: string }> = ({ to }) => {
    const params = useParams();
    const target = to.replace(/:(\w+)/g, (_, name: string) => encodeURIComponent(params[name] ?? ''));
    return <Navigate to={target} replace />;
};

/** `/dashboard` and `/platform-management`: each workspace has its own home and directory now (07 §9). */
const HomeRedirect: React.FC = () => {
    const { user, loading } = useAuth();
    if (loading) return <PageLoader />;
    return <Navigate to={user ? homeOf(user.role) : '/login'} replace />;
};

const DirectoryRedirect: React.FC = () => {
    const { user } = useAuth();
    const to = user?.role === 'app_admin' || user?.role === 'app_user' ? '/console/companies'
        : user?.role === 'partner_admin' ? '/partner/tenants' : '/settings/team';
    return <Navigate to={to} replace />;
};

const PublicRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const { isAuthenticated, loading } = useAuth();
    if (loading) return <PageLoader />;
    return !isAuthenticated ? <>{children}</> : <HomeRedirect />;
};

export const AppRouter: React.FC = () => (
    <BrowserRouter>
        <ErrorBoundary scope="The application">
            <Suspense fallback={<PageLoader />}>
                <Routes>
                    <Route path="/login" element={<PublicRoute><LoginPage /></PublicRoute>} />
                    <Route path="/register" element={<PublicRoute><RegisterPage /></PublicRoute>} />
                    <Route path="/forgot-password" element={<PublicRoute><ForgotPasswordPage /></PublicRoute>} />
                    <Route path="/reset-password" element={<PublicRoute><ResetPasswordPage /></PublicRoute>} />
                    <Route path="/verify-email" element={<PublicRoute><VerifyEmailPage /></PublicRoute>} />
                    <Route path="/auth/callback" element={<OAuthCallbackPage />} />
                    <Route path="/partners/apply" element={<PartnerApplyPage />} />
                    <Route path="/onboarding" element={<Protected><OnboardingWizard /></Protected>} />

                    <Route path="/dashboard" element={<HomeRedirect />} />
                    <Route path="/platform-management" element={<DirectoryRedirect />} />
                    <Route path="/profile" element={<Protected><MainLayout><UserSettings /></MainLayout></Protected>} />

                    {ROUTES.map(([path, element, roles]) => (
                        <Route key={path} path={path} element={
                            <Protected roles={roles}><MainLayout><Guarded>{element}</Guarded></MainLayout></Protected>
                        } />
                    ))}
                    {REDIRECTS.map(([from, to]) => (
                        <Route key={from} path={from} element={from === '/' ? <HomeRedirect /> : <ParamRedirect to={to} />} />
                    ))}

                    <Route path="*" element={<HomeRedirect />} />
                </Routes>
            </Suspense>
        </ErrorBoundary>
    </BrowserRouter>
);
