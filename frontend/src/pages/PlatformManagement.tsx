import { parseServerDate } from '@/utils/datetime';
import React, { useEffect, useState } from 'react';
import { GlassCard, JellyButton } from '@/components/ui';
import { companyService } from '@/services/company.service';
import { userService } from '@/services/user.service';
import { authService } from '@/services/auth.service';
import { Company, User, UserRole } from '@/types';
import {
    AlertTriangle,
    CheckCircle,
    Ban,
    RefreshCw,
    Plus,
    Building,
    Users,
    User as UserIcon,
    Shield,
    Mail,
    Edit,
    Layers
} from 'lucide-react';
import { CreateCompanyModal } from '@/components/CreateCompanyModal';
import { CreateUserModal } from '@/components/CreateUserModal';
import './PlatformManagement.css';

type ManagementTab = 'ALL' | 'PARTNERS' | 'TENANTS' | 'USERS';

export const PlatformManagement: React.FC = () => {
    const [activeTab, setActiveTab] = useState<ManagementTab>('ALL');
    const [partners, setPartners] = useState<Company[]>([]);
    const [tenants, setTenants] = useState<Company[]>([]);
    const [users, setUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [currentUser, setCurrentUser] = useState<User | null>(null);

    // Modal states
    const [isCompanyModalOpen, setIsCompanyModalOpen] = useState(false);
    const [isUserModalOpen, setIsUserModalOpen] = useState(false);
    const [editingCompany, setEditingCompany] = useState<Company | undefined>(undefined);
    const [editingUser, setEditingUser] = useState<User | undefined>(undefined);

    const fetchData = async () => {
        setLoading(true);
        setError(null);
        try {
            const user = await authService.getCurrentUser();
            setCurrentUser(user);

            if (activeTab === 'ALL') {
                const [pData, tData, uData] = await Promise.all([
                    companyService.getPartners(),
                    companyService.getTenants(),
                    userService.getUsers()
                ]);
                setPartners(pData);
                setTenants(tData);
                setUsers(uData);
            } else if (activeTab === 'PARTNERS') {
                const data = await companyService.getPartners();
                setPartners(data);
            } else if (activeTab === 'TENANTS') {
                const data = await companyService.getTenants();
                setTenants(data);
            } else if (activeTab === 'USERS') {
                const data = await userService.getUsers();
                setUsers(data);
            }
        } catch (err) {
            console.error(`Failed to fetch ${activeTab.toLowerCase()}`, err);
            setError(`Failed to load ${activeTab.toLowerCase()}`);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
    }, [activeTab]);

    const handleToggleCompanyStatus = async (company: Company) => {
        try {
            const newStatus = company.status === 'active' ? 'suspended' : 'active';
            await companyService.updateCompany(company.id, { status: newStatus });

            if (activeTab === 'PARTNERS' || activeTab === 'ALL') {
                setPartners(partners.map(p => p.id === company.id ? { ...p, status: newStatus } : p));
            }
            if (activeTab === 'TENANTS' || activeTab === 'ALL') {
                setTenants(tenants.map(t => t.id === company.id ? { ...t, status: newStatus } : t));
            }
        } catch (err) {
            console.error('Failed to update company status', err);
            setError('Failed to update status');
        }
    };

    const handleToggleUserStatus = async (user: User) => {
        try {
            const newStatus = !user.is_active;
            await userService.updateUser(user.id, { is_active: newStatus });
            setUsers(users.map(u => u.id === user.id ? { ...u, is_active: newStatus } : u));
        } catch (err) {
            console.error('Failed to update user status', err);
            setError('Failed to update status');
        }
    };

    const handleCompanySubmit = async (id: string | undefined, data: any) => {
        if (id) {
            await companyService.updateCompany(id, data);
        } else {
            await companyService.createCompany(data);
        }
        fetchData();
    };

    const handleUserSubmit = async (id: string | undefined, data: any) => {
        if (id) {
            await userService.updateUser(id, data);
        } else {
            await userService.createUser(data);
        }
        fetchData();
    };

    const openEditCompany = (company: Company) => {
        setEditingCompany(company);
        setIsCompanyModalOpen(true);
    };

    const openEditUser = (user: User) => {
        setEditingUser(user);
        setIsUserModalOpen(true);
    };

    const openCreate = () => {
        if (activeTab === 'USERS') {
            setEditingUser(undefined);
            setIsUserModalOpen(true);
        } else {
            setEditingCompany(undefined);
            setIsCompanyModalOpen(true);
        }
    };

    const getRoleBadgeColor = (role: string) => {
        switch (role) {
            case UserRole.APP_ADMIN: return 'badge-purple';
            case UserRole.PARTNER_ADMIN: return 'badge-blue';
            case UserRole.TENANT_ADMIN: return 'badge-green';
            default: return 'badge-gray';
        }
    };

    const renderTabs = () => {
        const tabs: ManagementTab[] = ['ALL'];
        if (currentUser?.role === UserRole.APP_ADMIN) tabs.push('PARTNERS');
        if ([UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN].includes(currentUser?.role as UserRole)) tabs.push('TENANTS');
        if ([UserRole.APP_ADMIN, UserRole.PARTNER_ADMIN, UserRole.TENANT_ADMIN].includes(currentUser?.role as UserRole)) tabs.push('USERS');

        return (
            <div className="filter-tabs">
                {tabs.map(tab => (
                    <button
                        key={tab}
                        className={`filter-tab ${activeTab === tab ? 'active' : ''}`}
                        onClick={() => setActiveTab(tab)}
                    >
                        {tab}
                    </button>
                ))}
            </div>
        );
    };

    return (
        <div className="platform-management-page">
            <div className="page-header">
                <div>
                    <h1>Platform Management</h1>
                    <p>Orchestrate Partners, Tenants, and User Access Control</p>
                </div>
                <div className="header-actions">
                    <JellyButton onClick={fetchData} variant="ghost" className="mr-2">
                        <RefreshCw size={20} className={loading ? 'spin' : ''} />
                    </JellyButton>
                    <JellyButton onClick={openCreate} roseGold disabled={activeTab === 'ALL'}>
                        <Plus size={20} />
                        Add {activeTab === 'ALL' ? 'Item' : activeTab.slice(0, -1)}
                    </JellyButton>
                </div>
            </div>

            {renderTabs()}

            {error && (
                <div className="error-banner glass mb-8 p-4 flex items-center gap-3">
                    <AlertTriangle className="text-error" size={20} />
                    <span className="text-error">{error}</span>
                </div>
            )}

            <div className="entities-grid">
                {loading ? (
                    <div className="loading-container col-span-full">
                        <Layers size={48} className="pulse" color="var(--color-rose-gold)" />
                        <div className="loading">Calibrating Nexus...</div>
                    </div>
                ) : (
                    <>
                        {(activeTab === 'ALL' || activeTab === 'PARTNERS') && partners.map(partner => (
                            <GlassCard key={partner.id} hover className="management-card">
                                <div className="card-header">
                                    <div className="card-icon-wrapper partner-icon">
                                        <Building size={24} />
                                    </div>
                                    <div className="info">
                                        <div className="flex items-center gap-2">
                                            <h3>{partner.name}</h3>
                                            <span className="type-indicator partner">PARTNER</span>
                                        </div>
                                        <div className={`badge ${partner.status === 'active' ? 'badge-ready' : 'badge-failed'}`}>
                                            {partner.status === 'active' ? <CheckCircle size={14} /> : <Ban size={14} />}
                                            {partner.status.toUpperCase()}
                                        </div>
                                    </div>
                                </div>
                                <div className="meta-info">
                                    <div className="meta-row">
                                        <span className="label">ID</span>
                                        <span className="value font-mono">{partner.id.slice(0, 8)}...</span>
                                    </div>
                                    <div className="meta-row">
                                        <span className="label">REGISTERED</span>
                                        <span className="value">{partner.created_at ? parseServerDate(partner.created_at).toLocaleDateString() : 'N/A'}</span>
                                    </div>
                                </div>
                                <div className="card-actions">
                                    <JellyButton variant="secondary" onClick={() => openEditCompany(partner)} className="flex-1">
                                        <Edit size={16} /> Edit
                                    </JellyButton>
                                    <JellyButton
                                        variant={partner.status === 'active' ? 'danger' : 'primary'}
                                        onClick={() => handleToggleCompanyStatus(partner)}
                                        className="flex-1"
                                    >
                                        {partner.status === 'active' ? 'Suspend' : 'Activate'}
                                    </JellyButton>
                                </div>
                            </GlassCard>
                        ))}
                        {(activeTab === 'ALL' || activeTab === 'TENANTS') && tenants.map(tenant => (
                            <GlassCard key={tenant.id} hover className="management-card">
                                <div className="card-header">
                                    <div className="card-icon-wrapper tenant-icon">
                                        <Building size={24} />
                                    </div>
                                    <div className="info">
                                        <div className="flex items-center gap-2">
                                            <h3>{tenant.name}</h3>
                                            <span className="type-indicator tenant">TENANT</span>
                                        </div>
                                        <div className={`badge ${tenant.status === 'active' ? 'badge-ready' : 'badge-failed'}`}>
                                            {tenant.status === 'active' ? <CheckCircle size={14} /> : <Ban size={14} />}
                                            {tenant.status.toUpperCase()}
                                        </div>
                                    </div>
                                </div>
                                <div className="meta-info">
                                    <div className="meta-row">
                                        <span className="label">ID</span>
                                        <span className="value font-mono">{tenant.id.slice(0, 8)}...</span>
                                    </div>
                                    <div className="meta-row">
                                        <span className="label">REGISTERED</span>
                                        <span className="value">{tenant.created_at ? parseServerDate(tenant.created_at).toLocaleDateString() : 'N/A'}</span>
                                    </div>
                                </div>
                                <div className="card-actions">
                                    <JellyButton variant="secondary" onClick={() => openEditCompany(tenant)} className="flex-1">
                                        <Edit size={16} /> Edit
                                    </JellyButton>
                                    <JellyButton
                                        variant={tenant.status === 'active' ? 'danger' : 'primary'}
                                        onClick={() => handleToggleCompanyStatus(tenant)}
                                        className="flex-1"
                                    >
                                        {tenant.status === 'active' ? 'Suspend' : 'Activate'}
                                    </JellyButton>
                                </div>
                            </GlassCard>
                        ))}
                        {(activeTab === 'ALL' || activeTab === 'USERS') && users.map(user => (
                            <GlassCard key={user.id} hover className="management-card">
                                <div className="card-header">
                                    <div className="user-avatar-circle">
                                        {user.full_name.charAt(0)}
                                    </div>
                                    <div className="info">
                                        <div className="flex items-center gap-2">
                                            <h3>{user.full_name}</h3>
                                            <span className="type-indicator user">USER</span>
                                        </div>
                                        <div className="badge-row">
                                            <div className={`badge ${getRoleBadgeColor(user.role)}`}>
                                                <Shield size={12} />
                                                {user.role.split('_')[0].toUpperCase()}
                                            </div>
                                            <div className={`badge ${user.is_active ? 'badge-ready' : 'badge-failed'}`}>
                                                {user.is_active ? <CheckCircle size={12} /> : <Ban size={12} />}
                                                {user.is_active ? 'ACTIVE' : 'SUSPENDED'}
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div className="meta-info">
                                    <div className="meta-row-compact">
                                        <Mail size={14} className="text-tertiary" />
                                        <span className="truncate">{user.email}</span>
                                    </div>
                                    <div className="meta-row-compact">
                                        <Building size={14} className="text-tertiary" />
                                        <span className="truncate">Org: {user.company_id.slice(0, 12)}...</span>
                                    </div>
                                </div>
                                <div className="card-actions">
                                    <JellyButton variant="secondary" onClick={() => openEditUser(user)} className="flex-1">
                                        <Edit size={16} /> Edit
                                    </JellyButton>
                                    <JellyButton
                                        variant={user.is_active ? 'danger' : 'primary'}
                                        onClick={() => handleToggleUserStatus(user)}
                                        className="flex-1"
                                    >
                                        {user.is_active ? 'Suspend' : 'Activate'}
                                    </JellyButton>
                                </div>
                            </GlassCard>
                        ))}

                        {activeTab === 'ALL' && partners.length === 0 && tenants.length === 0 && users.length === 0 && (
                            <GlassCard className="empty-state col-span-full">
                                <Layers size={64} color="var(--color-text-tertiary)" />
                                <h3>Nexus Empty</h3>
                                <p>No entities or identities detected in current scope</p>
                            </GlassCard>
                        )}
                        {activeTab === 'PARTNERS' && partners.length === 0 && (
                            <GlassCard className="empty-state col-span-full">
                                <Users size={64} color="var(--color-text-tertiary)" />
                                <h3>No Partners Found</h3>
                                <p>Register your first partner entity to begin</p>
                            </GlassCard>
                        )}
                        {activeTab === 'TENANTS' && tenants.length === 0 && (
                            <GlassCard className="empty-state col-span-full">
                                <Building size={64} color="var(--color-text-tertiary)" />
                                <h3>No Tenants Found</h3>
                                <p>Establish logic isolation with your first tenant</p>
                            </GlassCard>
                        )}
                        {activeTab === 'USERS' && users.length === 0 && (
                            <GlassCard className="empty-state col-span-full">
                                <UserIcon size={64} color="var(--color-text-tertiary)" />
                                <h3>No Users Found</h3>
                                <p>Provision the first identity in this nexus</p>
                            </GlassCard>
                        )}
                    </>
                )}
            </div>

            <CreateCompanyModal
                isOpen={isCompanyModalOpen}
                onClose={() => setIsCompanyModalOpen(false)}
                onSubmit={handleCompanySubmit}
                type={activeTab === 'PARTNERS' ? 'PARTNER' : 'TENANT'}
                parentId={activeTab === 'TENANTS' ? currentUser?.company_id : undefined}
                initialData={editingCompany}
            />

            <CreateUserModal
                isOpen={isUserModalOpen}
                onClose={() => setIsUserModalOpen(false)}
                onSubmit={handleUserSubmit}
                currentUser={currentUser}
                initialData={editingUser}
            />
        </div>
    );
};

export default PlatformManagement;
