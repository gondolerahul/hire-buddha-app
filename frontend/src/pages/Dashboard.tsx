import React from 'react';
import { useAuth } from '@/hooks/useAuth';
import { UserRole } from '@/types';
import { AppAdminDashboard } from './dashboards/AppAdminDashboard';
import { AppUserDashboard } from './dashboards/AppUserDashboard';
import { PartnerAdminDashboard } from './dashboards/PartnerAdminDashboard';
import { PartnerUserDashboard } from './dashboards/PartnerUserDashboard';
import { TenantAdminDashboard } from './dashboards/TenantAdminDashboard';
import { TenantUserDashboard } from './dashboards/TenantUserDashboard';
import { Navigate } from 'react-router-dom';

export const Dashboard: React.FC = () => {
    const { user } = useAuth();

    if (!user) {
        return <Navigate to="/auth/login" />;
    }

    const renderDashboard = () => {
        switch (user.role) {
            case UserRole.APP_ADMIN:
                return <AppAdminDashboard />;
            case UserRole.APP_USER:
                return <AppUserDashboard />;
            case UserRole.PARTNER_ADMIN:
                return <PartnerAdminDashboard />;
            case UserRole.PARTNER_USER:
                return <PartnerUserDashboard />;
            case UserRole.TENANT_ADMIN:
                return <TenantAdminDashboard />;
            case UserRole.TENANT_USER:
                return <TenantUserDashboard />;
            default:
                return (
                    <div>
                        <h1>Dashboard Unavailable</h1>
                        <p>No specific dashboard defined for your role.</p>
                    </div>
                );
        }
    };

    return (
        <div className="page-container dashboard">
            {renderDashboard()}
        </div>
    );
};
