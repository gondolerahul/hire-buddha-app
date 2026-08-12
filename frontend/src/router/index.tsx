import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { MainLayout } from '@/components/layout';
import { UserRole } from '@/types';

// Lazy load pages
const LoginPage = lazy(() => import('@/pages/auth').then(m => ({ default: m.LoginPage })));
const RegisterPage = lazy(() => import('@/pages/auth').then(m => ({ default: m.RegisterPage })));
const ForgotPasswordPage = lazy(() => import('@/pages/auth/PasswordReset').then(m => ({ default: m.ForgotPasswordPage })));
const ResetPasswordPage = lazy(() => import('@/pages/auth/PasswordReset').then(m => ({ default: m.ResetPasswordPage })));
const OAuthCallbackPage = lazy(() => import('@/pages/auth/OAuthCallback').then(m => ({ default: m.OAuthCallbackPage })));
const Dashboard = lazy(() => import('@/pages/Dashboard').then(m => ({ default: m.Dashboard })));
const EntityLibrary = lazy(() => import('@/pages/ai/EntityLibrary').then(m => ({ default: m.EntityLibrary })));
const EntityBuilder = lazy(() => import('@/pages/ai/EntityBuilder').then(m => ({ default: m.EntityBuilder })));
const ExecutionPage = lazy(() => import('@/pages/ai/ExecutionPage').then(m => ({ default: m.ExecutionPage })));
const ExecutionHistory = lazy(() => import('@/pages/ai/ExecutionHistory').then(m => ({ default: m.ExecutionHistory })));
const ExecutionDetail = lazy(() => import('@/pages/ai/ExecutionDetail').then(m => ({ default: m.ExecutionDetail })));
const HITLPanel = lazy(() => import('@/pages/ai/HITLPanel').then(m => ({ default: m.HITLPanel })));
const KnowledgeBase = lazy(() => import('@/pages/KnowledgeBase').then(m => ({ default: m.KnowledgeBase })));
const IntegrationsPage = lazy(() => import('@/pages/IntegrationsPage').then(m => ({ default: m.IntegrationsPage })));
const UserSettings = lazy(() => import('@/pages/UserSettings').then(m => ({ default: m.UserSettings })));
const PlatformManagement = lazy(() => import('@/pages/PlatformManagement').then(m => ({ default: m.PlatformManagement })));
const AIModelConfigPage = lazy(() => import('@/pages/ai-config/AIModelConfigPage').then(m => ({ default: m.AIModelConfigPage })));

// Streaming pages
const StreamingSessionsPage = lazy(() => import('@/pages/streaming').then(m => ({ default: m.StreamingSessionsPage })));
const CampaignsPage = lazy(() => import('@/pages/streaming').then(m => ({ default: m.CampaignsPage })));
const CampaignDetailPage = lazy(() => import('@/pages/streaming').then(m => ({ default: m.CampaignDetailPage })));
const CallDetailPage = lazy(() => import('@/pages/streaming').then(m => ({ default: m.CallDetailPage })));

const Artifacts = lazy(() => import('@/pages/artifacts/Artifacts').then(m => ({ default: m.Artifacts })));
const CostingReport = lazy(() => import('@/pages/reports/CostingReport').then(m => ({ default: m.CostingReport })));
const AppAdminReports = lazy(() => import('@/pages/reports/AppAdminReports').then(m => ({ default: m.AppAdminReports })));
const AppUserReports = lazy(() => import('@/pages/reports/AppUserReports').then(m => ({ default: m.AppUserReports })));
const PartnerAdminReports = lazy(() => import('@/pages/reports/PartnerAdminReports').then(m => ({ default: m.PartnerAdminReports })));
const PartnerUserReports = lazy(() => import('@/pages/reports/PartnerUserReports').then(m => ({ default: m.PartnerUserReports })));
const TenantAdminReports = lazy(() => import('@/pages/reports/TenantAdminReports').then(m => ({ default: m.TenantAdminReports })));
const TenantUserReports = lazy(() => import('@/pages/reports/TenantUserReports').then(m => ({ default: m.TenantUserReports })));
const WalletPage = lazy(() => import('@/pages/billing/WalletPage').then(m => ({ default: m.WalletPage })));
const BillingSettings = lazy(() => import('@/pages/billing/BillingSettings').then(m => ({ default: m.BillingSettings })));
// Phase 11 admin / KPI pages.
const KPIDashboard = lazy(() => import('@/pages/dashboards/KPIDashboard'));
const MetaIntelligencePage = lazy(() => import('@/pages/admin/MetaIntelligencePage'));
const CostAttributionDashboard = lazy(() => import('@/pages/admin/CostAttributionDashboard'));
const FeatureFlagsPage = lazy(() => import('@/pages/admin/FeatureFlagsPage'));
const RiskAndExitPage = lazy(() => import('@/pages/admin/RiskAndExitPage'));

// CORTEX Memory Architecture
const CortexExplorer = lazy(() => import('@/pages/ai/CortexExplorer').then(m => ({ default: m.CortexExplorer })));
const CortexTreeDetail = lazy(() => import('@/pages/ai/CortexTreeDetail').then(m => ({ default: m.CortexTreeDetail })));

// Tool Registry Management
const ToolManagement = lazy(() => import('@/pages/ai/ToolManagement').then(m => ({ default: m.ToolManagement })));
const TemplateMarketplace = lazy(() => import('@/pages/ai/TemplateMarketplace').then(m => ({ default: m.TemplateMarketplace })));

// Platform Onboarding & Management
const OnboardingWizard = lazy(() => import('@/pages/OnboardingWizard'));
const PartnerDashboard = lazy(() => import('@/pages/PartnerDashboard'));
const PhonePool = lazy(() => import('@/pages/PhonePool'));


// Loading Component for Suspense
const PageLoader = () => (
    <div className="loading-container">
        <div className="pulse">
            <div className="loading">Initializing...</div>
        </div>
    </div>
);

// Protected Route Component
interface ProtectedRouteProps {
    children: React.ReactNode;
    allowedRoles?: UserRole[];
}

const ProtectedRoute: React.FC<ProtectedRouteProps> = ({ children, allowedRoles }) => {
    const { isAuthenticated, user, loading } = useAuth();

    if (loading) {
        return <PageLoader />;
    }

    if (!isAuthenticated) {
        return <Navigate to="/login" replace />;
    }

    if (allowedRoles && user && !allowedRoles.includes(user.role)) {
        return <Navigate to="/dashboard" replace />;
    }

    return <>{children}</>;
};

// Public Route (redirect if authenticated)
const PublicRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const { isAuthenticated, loading } = useAuth();

    if (loading) {
        return <PageLoader />;
    }

    return !isAuthenticated ? <>{children}</> : <Navigate to="/dashboard" replace />;
};

// Execution Redirect component to preserve :id parameter
const ExecutionRedirect: React.FC = () => {
    const { id } = useParams();
    return <Navigate to={`/ai/executions/${id}`} replace />;
};

export const AppRouter: React.FC = () => {
    return (
        <BrowserRouter>
            <Suspense fallback={<PageLoader />}>
                <Routes>
                    {/* Public Routes */}
                    <Route path="/login" element={<PublicRoute><LoginPage /></PublicRoute>} />
                    <Route path="/register" element={<PublicRoute><RegisterPage /></PublicRoute>} />
                    <Route path="/forgot-password" element={<PublicRoute><ForgotPasswordPage /></PublicRoute>} />
                    <Route path="/reset-password" element={<PublicRoute><ResetPasswordPage /></PublicRoute>} />
                    <Route path="/auth/callback" element={<OAuthCallbackPage />} />

                    {/* Protected Routes */}
                    <Route path="/" element={<Navigate to="/dashboard" replace />} />

                    {/* Onboarding Wizard — no layout wrapper */}
                    <Route
                        path="/onboarding"
                        element={
                            <ProtectedRoute>
                                <OnboardingWizard />
                            </ProtectedRoute>
                        }
                    />

                    {/* Partner Dashboard */}
                    <Route
                        path="/partner"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <PartnerDashboard />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Unified Phone Numbers */}
                    <Route
                        path="/phone-numbers"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <PhonePool />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    {/* Legacy redirect from old pool route */}
                    <Route path="/phone-pool" element={<Navigate to="/phone-numbers" replace />} />

                    {/* Dashboard */}
                    <Route
                        path="/dashboard"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <Dashboard />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Hierarchical Entities */}
                    <Route
                        path="/ai/entities"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <EntityLibrary />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/ai/entities/create"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <EntityBuilder />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/ai/entities/edit/:id"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <EntityBuilder />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Legacy Redirects */}
                    <Route path="/agents" element={<Navigate to="/ai/entities" replace />} />
                    <Route path="/workflows" element={<Navigate to="/ai/entities" replace />} />
                    <Route path="/agents/create" element={<Navigate to="/ai/entities/create" replace />} />
                    <Route path="/workflows/create" element={<Navigate to="/ai/entities/create" replace />} />
                    <Route path="/agents/:id" element={<Navigate to="/ai/entities/edit/:id" replace />} />
                    <Route path="/workflows/:id" element={<Navigate to="/ai/entities/edit/:id" replace />} />

                    {/* Execution */}
                    <Route
                        path="/ai/execute/:id"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <ExecutionPage />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route path="/execute/:type/:id" element={<Navigate to="/ai/execute/:id" replace />} />

                    {/* Executions History */}
                    <Route
                        path="/ai/executions"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <ExecutionHistory />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Execution Detail */}
                    <Route
                        path="/ai/executions/:id"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <ExecutionDetail />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Legacy Execution Redirects */}
                    <Route path="/executions" element={<Navigate to="/ai/executions" replace />} />
                    <Route path="/executions/:id" element={<ExecutionRedirect />} />

                    {/* HITL Oversights */}
                    <Route
                        path="/ai/approvals"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <HITLPanel />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Tool Registry (App Admin) */}
                    <Route
                        path="/ai/tool-registry"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN]}>
                                <MainLayout>
                                    <ToolManagement />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Template Marketplace */}
                    <Route
                        path="/ai/templates"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <TemplateMarketplace />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Knowledge Base */}
                    <Route
                        path="/knowledge"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <KnowledgeBase />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Integrations */}
                    <Route
                        path="/integrations"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <IntegrationsPage />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* AI Configuration */}
                    <Route
                        path="/ai-config"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.TENANT_ADMIN]}>
                                <MainLayout>
                                    <AIModelConfigPage />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* User Settings */}
                    <Route
                        path="/profile"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <UserSettings />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Platform Management (Consolidated Partners, Tenants, Users) */}
                    <Route
                        path="/platform-management"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN]}>
                                <MainLayout>
                                    <PlatformManagement />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Legacy redirect from old streaming phone numbers route */}
                    <Route path="/streaming/phone-numbers" element={<Navigate to="/phone-numbers" replace />} />

                    {/* Streaming - Sessions */}
                    <Route
                        path="/streaming/sessions"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <StreamingSessionsPage />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Streaming - Campaigns */}
                    <Route
                        path="/streaming/campaigns"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <CampaignsPage />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Streaming - Campaign Detail */}
                    <Route
                        path="/streaming/campaigns/:campaignId"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <CampaignDetailPage />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Call Detail Page */}
                    <Route
                        path="/streaming/calls/:sessionId"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <CallDetailPage />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />


                    {/* Artifacts (replaces Asset Library) */}
                    <Route
                        path="/artifacts"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <Artifacts />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* CORTEX Memory Trees */}
                    <Route
                        path="/cortex"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <CortexExplorer />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/cortex/trees/:treeId"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <CortexTreeDetail />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    {/* Legacy redirect */}
                    <Route path="/assets" element={<Navigate to="/artifacts" replace />} />

                    {/* Reports - Costing */}
                    <Route
                        path="/reports/costing"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <CostingReport />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />


                    {/* Analytics Reports — Role-gated */}
                    <Route
                        path="/reports/analytics/app-admin"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN]}>
                                <MainLayout>
                                    <AppAdminReports />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/reports/analytics/app-user"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.APP_USER]}>
                                <MainLayout>
                                    <AppUserReports />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/reports/analytics/partner-admin"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN]}>
                                <MainLayout>
                                    <PartnerAdminReports />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/reports/analytics/partner-user"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.PARTNER_USER]}>
                                <MainLayout>
                                    <PartnerUserReports />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/reports/analytics/tenant-admin"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN]}>
                                <MainLayout>
                                    <TenantAdminReports />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/reports/analytics/tenant-user"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <TenantUserReports />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Wallet & Credits */}
                    <Route
                        path="/wallet"
                        element={
                            <ProtectedRoute>
                                <MainLayout>
                                    <WalletPage />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Billing Settings */}
                    <Route
                        path="/settings/billing"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN]}>
                                <MainLayout>
                                    <BillingSettings />
                                </MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* Agent kernel admin / KPI routes — admin-gated to match
                        the backend `_require_admin` check on every endpoint. */}
                    <Route
                        path="/admin/agent-kernel/kpi"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN]}>
                                <MainLayout><KPIDashboard /></MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/admin/agent-kernel/meta-intelligence"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN]}>
                                <MainLayout><MetaIntelligencePage /></MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/admin/agent-kernel/cost"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN]}>
                                <MainLayout><CostAttributionDashboard /></MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/admin/agent-kernel/feature-flags"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN]}>
                                <MainLayout><FeatureFlagsPage /></MainLayout>
                            </ProtectedRoute>
                        }
                    />
                    <Route
                        path="/admin/agent-kernel/risks"
                        element={
                            <ProtectedRoute allowedRoles={[UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN]}>
                                <MainLayout><RiskAndExitPage /></MainLayout>
                            </ProtectedRoute>
                        }
                    />

                    {/* De-prefix compat: old /admin/phase11/* bookmarks
                        redirect to /admin/agent-kernel/*. Remove after 2026-09-01. */}
                    <Route path="/admin/phase11/kpi" element={<Navigate to="/admin/agent-kernel/kpi" replace />} />
                    <Route path="/admin/phase11/meta-intelligence" element={<Navigate to="/admin/agent-kernel/meta-intelligence" replace />} />
                    <Route path="/admin/phase11/cost" element={<Navigate to="/admin/agent-kernel/cost" replace />} />
                    <Route path="/admin/phase11/feature-flags" element={<Navigate to="/admin/agent-kernel/feature-flags" replace />} />
                    <Route path="/admin/phase11/risks" element={<Navigate to="/admin/agent-kernel/risks" replace />} />

                    {/* Legacy Management Redirects */}
                    <Route path="/partners" element={<Navigate to="/platform-management" replace />} />
                    <Route path="/tenants" element={<Navigate to="/platform-management" replace />} />
                    <Route path="/users" element={<Navigate to="/platform-management" replace />} />

                    {/* 404 Route */}
                    <Route path="*" element={<Navigate to="/dashboard" replace />} />
                </Routes>
            </Suspense>
        </BrowserRouter>
    );
};
