import React, { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import { GlassCard, GlassInput, JellyButton } from './ui';
import { UserRole, Company, User } from '../types';
import { companyService } from '../services/company.service';

interface CreateUserModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSubmit: (id: string | undefined, data: any) => Promise<void>;
    currentUser: User | null;
    initialData?: User;
}

export const CreateUserModal: React.FC<CreateUserModalProps> = ({
    isOpen,
    onClose,
    onSubmit,
    currentUser,
    initialData
}) => {
    const [formData, setFormData] = useState({
        email: '',
        password: '',
        full_name: '',
        company_id: '',
        role: '' as UserRole
    });
    const [companies, setCompanies] = useState<Company[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen) {
            if (initialData) {
                setFormData({
                    email: initialData.email,
                    password: '',
                    full_name: initialData.full_name,
                    company_id: initialData.company_id,
                    role: initialData.role
                });
            } else if (currentUser) {
                setFormData({
                    email: '',
                    password: '',
                    full_name: '',
                    company_id: currentUser.company_id,
                    role: '' as UserRole
                });
            }
            if (currentUser) {
                fetchAvailableCompanies();
            }
            setError(null);
        }
    }, [isOpen, currentUser, initialData]);

    const fetchAvailableCompanies = async () => {
        try {
            if (currentUser?.role === 'app_admin') {
                const partners = await companyService.getPartners();
                const tenants = await companyService.getTenants();
                setCompanies([...partners, ...tenants]);
            } else if (currentUser?.role === 'partner_admin') {
                const tenants = await companyService.getTenants();
                setCompanies(tenants);
            }
        } catch (err) {
            console.error('Failed to fetch companies', err);
        }
    };

    if (!isOpen) return null;

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        setLoading(true);

        try {
            const data = { ...formData };
            if (initialData && !data.password) {
                delete (data as any).password;
            }

            await onSubmit(initialData?.id, data);

            if (!initialData) {
                setFormData({
                    email: '',
                    password: '',
                    full_name: '',
                    company_id: currentUser?.company_id || '',
                    role: '' as UserRole
                });
            }
            onClose();
        } catch (err: any) {
            setError(err.response?.data?.detail || `Failed to ${initialData ? 'update' : 'create'} user`);
        } finally {
            setLoading(false);
        }
    };

    const getAvailableRoles = () => {
        if (currentUser?.role === 'app_admin') {
            return [
                UserRole.APP_ADMIN,
                UserRole.PARTNER_ADMIN,
                UserRole.TENANT_ADMIN,
                UserRole.APP_USER,
                UserRole.PARTNER_USER,
                UserRole.TENANT_USER
            ];
        }
        if (currentUser?.role === 'partner_admin') {
            return [
                UserRole.PARTNER_ADMIN,
                UserRole.PARTNER_USER,
                UserRole.TENANT_ADMIN,
                UserRole.TENANT_USER
            ];
        }
        if (currentUser?.role === 'tenant_admin') {
            return [
                UserRole.TENANT_ADMIN,
                UserRole.TENANT_USER
            ];
        }
        return [];
    };

    return (
        <div className="modal-overlay">
            <GlassCard className="w-full max-w-lg p-8 relative">
                <button
                    onClick={onClose}
                    className="absolute top-6 right-6 p-2 text-tertiary hover:text-white transition-colors"
                >
                    <X size={20} />
                </button>

                <h2 className="text-xl font-bold text-white mb-8">
                    {initialData ? 'Update Identity' : 'Establish Identity'}
                </h2>

                <form onSubmit={handleSubmit} className="space-y-6">
                    <div className="grid grid-cols-1 gap-6">
                        <GlassInput
                            label="Full Name"
                            value={formData.full_name}
                            onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                            placeholder="John Doe"
                            required
                        />
                        <GlassInput
                            label="Email"
                            type="email"
                            value={formData.email}
                            onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                            placeholder="john@example.com"
                            required
                        />
                    </div>

                    <GlassInput
                        label="Password"
                        type="password"
                        value={formData.password}
                        onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                        placeholder={initialData ? "Leave blank to keep current" : "••••••••"}
                        required={!initialData}
                    />

                    <div className="grid grid-cols-1 gap-6">
                        <div className="form-group">
                            <label>Company</label>
                            <select
                                value={formData.company_id}
                                onChange={(e) => setFormData({ ...formData, company_id: e.target.value })}
                                required
                            >
                                <option value={currentUser?.company_id}>My Company</option>
                                {companies.map(c => (
                                    <option key={c.id} value={c.id}>{c.name}</option>
                                ))}
                            </select>
                        </div>

                        <div className="form-group">
                            <label>Role</label>
                            <select
                                value={formData.role}
                                onChange={(e) => setFormData({ ...formData, role: e.target.value as UserRole })}
                                required
                            >
                                <option value="" disabled>Select Role</option>
                                {getAvailableRoles().map(role => (
                                    <option key={role} value={role}>{role.replace('_', ' ').toUpperCase()}</option>
                                ))}
                            </select>
                        </div>
                    </div>

                    {error && (
                        <div className="error-toast glass">
                            {error}
                        </div>
                    )}

                    <div className="flex justify-end gap-4 pt-4">
                        <JellyButton type="button" onClick={onClose} variant="ghost">
                            Cancel
                        </JellyButton>
                        <JellyButton
                            type="submit"
                            disabled={loading || !formData.email || (!initialData && !formData.password) || !formData.role}
                            roseGold
                        >
                            {loading ? 'Synthesizing...' : (initialData ? 'Update Identity' : 'Calibrate Identity')}
                        </JellyButton>
                    </div>
                </form>
            </GlassCard>
        </div>
    );
};
