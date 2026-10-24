/**
 * pages/admin/partners/PartnerRulesPage — the programme's rules and the simulator (Phase 15 T8-7, T8-8,
 * T8-13, T8-14; 07 §5.10).
 *
 * Commission rules (type × revenue × level: rate, the level-0 pool cap, an
 * optional end in months) and fee rules (range, split with a 100 % check) —
 * each change a new version, audited; agreements keep their snapshot. Payout
 * and network policy are money settings (Money settings, group "partners").
 * The simulator runs a sample chain on today's or proposed rates.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Scale, Play } from 'lucide-react';

import { CommissionRuleRow, FeeRuleRow, partnerAdmin, REVENUE_LABEL, Simulation } from '@/services/partners.service';
import { apiErrorMessage } from '@/utils/apiError';
import { formatMoney } from '@/utils/money';

import '@/pages/admin/MoneyConsole.css';
import '@/pages/partner/Partner.css';

export const PartnerRulesPage: React.FC = () => {
    const [commission, setCommission] = useState<CommissionRuleRow[]>([]);
    const [fees, setFees] = useState<FeeRuleRow[]>([]);
    const [policy, setPolicy] = useState<Record<string, string>>({});
    const [error, setError] = useState<string | null>(null);
    const [notice, setNotice] = useState<string | null>(null);

    const load = useCallback(async () => {
        try {
            const res = await partnerAdmin.rules();
            setCommission(res.commission_rules);
            setFees(res.fee_rules);
            setPolicy(res.policy);
        } catch (err) {
            setError(apiErrorMessage(err, 'The rules could not be loaded'));
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const editRate = async (r: CommissionRuleRow) => {
        const rate = prompt(`${r.partner_type} ${REVENUE_LABEL[r.revenue_kind]} level ${r.level}: rate %`, r.rate_pct);
        if (rate === null) return;
        const cap = r.level === 0 ? prompt('Pool cap % of the payment', r.cap_pct ?? '') : null;
        const reason = prompt('Reason (kept with the version):') ?? undefined;
        try {
            await partnerAdmin.putCommission({ partner_type: r.partner_type, revenue_kind: r.revenue_kind, level: r.level,
                                               rate_pct: rate, cap_pct: cap || null, months: r.months, reason });
            setNotice('A new version is in force for new payments.');
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'Not saved'));
        }
    };

    const editFee = async (f: FeeRuleRow) => {
        const range = prompt(`${f.partner_type} ${f.fee_kind}: minimum and maximum USD, e.g. "100 10000"`, `${Number(f.min_usd)} ${Number(f.max_usd)}`);
        if (range === null) return;
        const split = prompt('Split %: originator level1 level2 platform (adds to 100)',
                             ['originator', 'level1', 'level2', 'platform'].map(k => f.split[k] ?? 0).join(' '));
        if (split === null) return;
        const [min, max] = range.trim().split(/\s+/);
        const [o, l1, l2, pl] = split.trim().split(/\s+/).map(Number);
        try {
            await partnerAdmin.putFee({ partner_type: f.partner_type, fee_kind: f.fee_kind, min_usd: min, max_usd: max,
                                        split: { originator: o, level1: l1, level2: l2, platform: pl } });
            setNotice('A new fee rule version is in force.');
            load();
        } catch (err) {
            setError(apiErrorMessage(err, 'Not saved'));
        }
    };

    return (
        <div className="money-console">
            <div className="page-header">
                <div>
                    <h1 className="page-title"><Scale size={22} /> Programme rules</h1>
                    <p className="page-subtitle">
                        Commission on customer payments only — never on recruiting or partnership fees. Payout and network
                        policy are <Link to="/console/settings">money settings</Link> (partners).
                    </p>
                </div>
            </div>
            {error && <div className="error-banner">{error}</div>}
            {notice && <div className="success-banner">{notice}</div>}
            <section className="money-card glass">
                <h2>Commission rules</h2>
                <table className="money-table">
                    <thead><tr><th>Type</th><th>On</th><th>Level</th><th>Rate</th><th>Pool cap</th><th>Ends after</th><th>Version</th><th /></tr></thead>
                    <tbody>
                        {commission.map(r => (
                            <tr key={r.id}>
                                <td>{r.partner_type}</td><td>{REVENUE_LABEL[r.revenue_kind] ?? r.revenue_kind}</td>
                                <td>{r.level === 0 ? 'the partner' : `upline ${r.level}`}</td><td>{Number(r.rate_pct)} %</td>
                                <td>{r.cap_pct ? `${Number(r.cap_pct)} %` : '—'}</td><td>{r.months ? `${r.months} months` : 'no end'}</td>
                                <td>v{r.version}</td><td><button className="btn-secondary" onClick={() => editRate(r)}>Edit</button></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </section>
            <section className="money-card glass">
                <h2>Setup and customisation fees</h2>
                <table className="money-table">
                    <thead><tr><th>Type</th><th>Fee</th><th>Range</th><th>Split</th><th>Version</th><th /></tr></thead>
                    <tbody>
                        {fees.map(f => (
                            <tr key={f.id}>
                                <td>{f.partner_type}</td><td>{f.fee_kind}</td>
                                <td>{formatMoney(f.min_usd, 'USD')} – {formatMoney(f.max_usd, 'USD')}</td>
                                <td>{Object.entries(f.split).map(([k, v]) => `${k} ${v} %`).join(' · ')}</td>
                                <td>v{f.version}</td><td><button className="btn-secondary" onClick={() => editFee(f)}>Edit</button></td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </section>
            <section className="money-card glass">
                <h2>Policy</h2>
                <table className="money-table"><tbody>
                    {Object.entries(policy).map(([k, v]) => <tr key={k}><td>{k.replace('partners.', '')}</td><td>{v}</td></tr>)}
                </tbody></table>
            </section>
            <Simulator />
        </div>
    );
};

const Simulator: React.FC = () => {
    const [form, setForm] = useState({ revenue_kind: 'usage_topup', base: '100000', billed: '100000', cost: '40000' });
    const [chain, setChain] = useState([
        { type: 'GOLD', status: 'active', own_revenue_usd: 0, months_since_below_joined: 0 },
        { type: 'GOLD', status: 'active', own_revenue_usd: 500, months_since_below_joined: 6 },
        { type: 'SILVER', status: 'active', own_revenue_usd: 0, months_since_below_joined: 6 },
    ]);
    const [result, setResult] = useState<Simulation | null>(null);
    const [error, setError] = useState<string | null>(null);

    const run = async () => {
        setError(null);
        try {
            setResult(await partnerAdmin.simulate({ ...form, chain }));
        } catch (err) {
            setError(apiErrorMessage(err, 'The simulation failed'));
        }
    };

    return (
        <section className="money-card glass">
            <h2>Simulator</h2>
            {error && <div className="error-banner">{error}</div>}
            <div className="money-form" style={{ marginTop: 0 }}>
                <label>Revenue
                    <select value={form.revenue_kind} onChange={e => setForm({ ...form, revenue_kind: e.target.value })}>
                        {Object.entries(REVENUE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </select>
                </label>
                <label>Payment (net)<input type="text" value={form.base} onChange={e => setForm({ ...form, base: e.target.value })} /></label>
                <label>Month billed<input type="text" value={form.billed} onChange={e => setForm({ ...form, billed: e.target.value })} /></label>
                <label>Month cost<input type="text" value={form.cost} onChange={e => setForm({ ...form, cost: e.target.value })} /></label>
            </div>
            <table className="money-table" style={{ marginTop: '1rem' }}>
                <thead><tr><th>Level</th><th>Type</th><th>Status</th><th>Own revenue (USD, month)</th><th>Months since the one below joined</th></tr></thead>
                <tbody>
                    {chain.map((c, i) => (
                        <tr key={i}>
                            <td>{i === 0 ? 'the partner' : `upline ${i}`}</td>
                            <td><select value={c.type} onChange={e => setChain(chain.map((x, j) => j === i ? { ...x, type: e.target.value } : x))}>
                                <option>GOLD</option><option>SILVER</option></select></td>
                            <td><select value={c.status} onChange={e => setChain(chain.map((x, j) => j === i ? { ...x, status: e.target.value } : x))}>
                                {['active', 'renewal_due', 'lapsed', 'suspended'].map(s => <option key={s}>{s}</option>)}</select></td>
                            <td><input type="number" value={c.own_revenue_usd} onChange={e => setChain(chain.map((x, j) => j === i ? { ...x, own_revenue_usd: Number(e.target.value) } : x))} /></td>
                            <td><input type="number" value={c.months_since_below_joined} onChange={e => setChain(chain.map((x, j) => j === i ? { ...x, months_since_below_joined: Number(e.target.value) } : x))} /></td>
                        </tr>
                    ))}
                </tbody>
            </table>
            <div className="money-form"><button className="btn-primary" onClick={run}><Play size={14} /> Run</button></div>
            {result && (
                <table className="money-table" style={{ marginTop: '1rem' }}>
                    <thead><tr><th>Level</th><th>Rate</th><th>Earns</th><th>Status</th><th>Why not</th></tr></thead>
                    <tbody>
                        {result.shares.map(s => (
                            <tr key={s.level}><td>{s.level}</td><td>{Number(s.rate_pct)} %</td><td>{Number(s.amount).toLocaleString()}</td>
                                <td>{s.status}</td><td className="muted">{s.why ?? ''}</td></tr>
                        ))}
                        <tr><td colSpan={2}>Platform</td><td>{Number(result.platform).toLocaleString()}</td>
                            <td colSpan={2}>{result.capped ? `cut to the pool cap (${Number(result.pool_cap).toLocaleString()})` : ''}</td></tr>
                        {result.margin_guard && (
                            <tr><td colSpan={2}>Margin guard</td><td>allows {Number(result.margin_guard.allowed).toLocaleString()}</td>
                                <td colSpan={2}>{Number(result.margin_guard.held) > 0 ? `${Number(result.margin_guard.held).toLocaleString()} would be held` : 'within the margin'}</td></tr>
                        )}
                    </tbody>
                </table>
            )}
        </section>
    );
};

export default PartnerRulesPage;
