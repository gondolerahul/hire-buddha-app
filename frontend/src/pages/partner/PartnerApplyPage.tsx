/**
 * pages/partner/PartnerApplyPage — apply to be a HireBuddha partner (Phase 15 T8-5). No sign-in.
 *
 * With an invitation link (``?token=``) the recruiting partner is named; it
 * has no say in the type, which HireBuddha sets after review.
 */
import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { partnerBusiness } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';

import '@/pages/admin/MoneyConsole.css';
import './Partner.css';

const EMPTY = {
    company_name: '', contact_name: '', email: '', phone: '', country_code: 'IN', requested_type: '', pan: '',
    gstin: '', website: '', address: '', territory: '', verticals: '', notes: '',
};

export const PartnerApplyPage: React.FC = () => {
    const [params] = useSearchParams();
    const token = params.get('token');
    const [recruiter, setRecruiter] = useState<string | null>(null);
    const [form, setForm] = useState(EMPTY);
    const [done, setDone] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!token) return;
        partnerBusiness.invite(token)
            .then(res => { setRecruiter(res.recruiter); if (res.email) setForm(f => ({ ...f, email: res.email ?? '' })); })
            .catch(err => setError(apiErrorMessage(err, 'That invitation is not valid')));
    }, [token]);

    const field = (key: keyof typeof EMPTY, label: string, extra: React.InputHTMLAttributes<HTMLInputElement> = {}) => (
        <label>{label}
            <input type="text" value={form[key]} onChange={e => setForm({ ...form, [key]: e.target.value })} {...extra} />
        </label>
    );

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        try {
            const body = Object.fromEntries(Object.entries({ ...form, token }).filter(([, v]) => v));
            const res = await partnerBusiness.apply(body);
            setDone(res.message);
        } catch (err) {
            setError(apiErrorMessage(err, 'The application was not sent'));
        }
    };

    return (
        <div className="apply-page">
            <div className="money-console apply-card">
                <h1 className="page-title">Become a HireBuddha partner</h1>
                <p className="page-subtitle">
                    {recruiter ? `Invited by ${recruiter}. ` : ''}Silver partners refer customers; Gold partners sell,
                    set up and support them. HireBuddha reviews every application and decides the type.
                </p>
                {error && <div className="error-banner">{error}</div>}
                {done ? <div className="success-banner">{done}</div> : (
                    <form className="money-form money-card glass" onSubmit={submit}>
                        {field('company_name', 'Company', { required: true, minLength: 2 })}
                        {field('contact_name', 'Your name', { required: true, minLength: 2 })}
                        {field('email', 'E-mail', { required: true, type: 'email' })}
                        {field('phone', 'Phone')}
                        {field('country_code', 'Country (two letters)', { maxLength: 2 })}
                        <label>You would like to be
                            <select value={form.requested_type} onChange={e => setForm({ ...form, requested_type: e.target.value })}>
                                <option value="">Not sure</option><option value="SILVER">Silver (referral)</option>
                                <option value="GOLD">Gold (resell and deliver)</option>
                            </select>
                        </label>
                        {field('pan', 'PAN', { maxLength: 10 })}
                        {field('gstin', 'GSTIN', { maxLength: 15 })}
                        {field('website', 'Website')}
                        {field('territory', 'Territory')}
                        {field('verticals', 'Industries you serve')}
                        <label className="grow">About you
                            <input type="text" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} />
                        </label>
                        <button type="submit" className="btn-primary">Apply</button>
                    </form>
                )}
            </div>
        </div>
    );
};

export default PartnerApplyPage;
