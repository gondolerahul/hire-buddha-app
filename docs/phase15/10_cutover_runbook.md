# Phase 15 — Cutover runbook

> **Tasks:** T10-1 (migration and dry runs), T10-3 (shadow review and switch-on), T10-4 (customer notices). Plan: 08 §4 (migration order), §6 (switches), §7 (risks).
> **Tools:** `python -m src.billing.cutover` (readiness and reconciliation), `python -m src.billing.wallet_cutover` (buckets → lots), `python -m src.billing.unit_codes_report` (registry units), `python -m src.billing.cutover_notices` (customer notices). All run from `backend/` against the database in `DATABASE_URL`.
> **Status:** built and rehearsed on the local stack only. The dry run on a production copy, the production shadow period and the switch-on have not happened (09 §7).

---

## 1. Who and when

| Role | Does |
|---|---|
| Release owner | Runs the steps, keeps the log (time, command, output) in the release ticket |
| Finance sign-off | Reads the per-company reconciliation (step 6) and signs it before the window closes |
| Support lead | Watches the support inbox for 48 h after each switch; owns customer replies |
| Product owner | Approves the notice dates (§5) and each switch-on (§4) |

The production migration runs in **one maintenance window** (about 60 min for the migration, 30 min for checks), on a weekday morning IST, with a **full database backup** taken at its start. Step 6 (the wallet) cannot be undone except by restoring that backup.

---

## 2. Dry run on a production copy (do this at least twice)

1. Restore last night's production backup into a scratch server (the same Postgres major version, pgvector installed). Point a shell's `DATABASE_URL` at it; never at production.
2. Before migrating, take the "before" reports:
   ```
   python -m src.billing.unit_codes_report            # every registry unit maps (exit 1 if one does not)
   python -m src.billing.wallet_cutover --json > before_wallets.json
   ```
   An unmapped unit stops the migration (step 3): extend the unit mapping in `control_0007_registry_unit_codes.plan()` or fix the registry row, then start again.
3. Migrate: `python -m src.common.tenancy.migrate control`, then `python -m src.common.tenancy.migrate tenants` (every tenant database).
4. Reconcile:
   ```
   python -m src.billing.wallet_cutover                # lots = buckets × rate, per company
   python -m src.billing.cutover --markdown dryrun.md  # the whole readiness report
   ```
5. Compare `before_wallets.json` with the lots company by company. Every difference must be explained (an expired bucket, a rate) or fixed in the migration, then the dry run is repeated from step 1.
6. Time each step: the window in §3 must hold it with a margin.

A dry run passes when `wallet_cutover` exits 0 and the readiness report's blockers are only those expected before the shadow period (step 9: no shadow rows yet).

---

## 3. The production migration (the window)

Order of 08 §4. Each step is a migration of the control tree unless noted; `migrate control` runs them in order, so the window is one command plus the checks between.

| Step | Migration | Check after it | If it fails |
|---|---|---|---|
| 0 | — | Backup taken and restorable (`pg_restore --list` on it); workers and the scheduler stopped (`stop_services` / scale to 0); the API in read-only maintenance | Do not start |
| 1 | `control_0005` … `control_0010`: audit, cost units, currencies, FX, settings | readiness step 1 ok | downgrade to `control_0004` |
| 2 | `control_0011_company_geography` | readiness step 2 ok (every company IN/INR unless set) | downgrade |
| 3 | `control_0007_registry_unit_codes` (in the chain) | readiness step 3 ok; the migration itself aborts on an unmapped unit | fix the map, rerun |
| 4 | `control_0012_billing_formulas` | readiness step 4 ok; golden prices equal (`pytest tests/golden`) | downgrade |
| 5 | `control_0013_usage_rating`, `control_0014_billing_lines` | readiness step 5: open rows rated; historical rows marked settled | downgrade |
| 6 | `control_0015_wallet_lots` (**one-way**), `control_0016_money_controls` | `python -m src.billing.wallet_cutover` exits 0; readiness "Wallets equal their ledgers" ok; **finance signs the per-company report** | restore the backup (the only undo) |
| 7 | `control_0017_plans`, `control_0018_invoices` | readiness step 7 ok | downgrade |
| 8 | `control_0019_number_rentals`, `control_0020_partners`, `control_0021_staff_functions` | readiness step 8 ok | downgrade |
| 9 | tenant tree (`migrate tenants`): agent budgets in billed amounts | `migrate tenants` reports every tenant at head | rerun for the failed tenant |
| 10 | — | Start workers, scheduler and API; `GET /api/v1/health` ok; one run and one call on the internal test company billed in INR | roll forward; restore only if billing is wrong |

**Between step 9 and step 10** (the migration done, nothing started yet), set the rollout switches **off** (they default on, the behaviour as built), so the release changes billing but nothing customers feel yet:

```sql
INSERT INTO platform_settings (key, scope, scope_id, value_json) VALUES
  ('billing.enforcement_enabled', 'platform', NULL, 'false'), ('billing.apps_stop_enabled', 'platform', NULL, 'false'),
  ('entitlements.enforced', 'platform', NULL, 'false'), ('partners.programme_enabled', 'platform', NULL, 'false'),
  ('billing.v2_mode', 'platform', NULL, '"shadow"')
ON CONFLICT (key, scope, scope_id) DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = now();
```

Once the API runs, the switches are changed on **Console → Settings → Rollout** (`/console/settings`) or with `PUT /api/v1/admin/billing-settings/{key}` and a reason — every change is audited.

**Step 10 drops nothing.** The old tables and columns (`billing_config`, the wallet bucket columns, `subscription_tiers`, `billing_events`, the registry `cost_unit` text, `companies.default_daily_credits`) stay for one release and are dropped by a later migration (08 §4 step 10), after `billing.v2_mode` has been `on` for that release.

---

## 4. Shadow period and switch-on (T10-3)

### 4.1 Shadow

`billing.v2_mode = shadow` (the default) records every settled run and call priced both ways in `billing_shadow_diffs`. Run it **2 weeks in dev, 1 week in production**. Each working day:

1. **Console → Finance → Billing shadow** (or `GET /api/v1/admin/billing-shadow?days=1`): settlements compared, how many differ, the largest difference.
2. Explain every difference over USD 0.01: a row rated with another formula version, a row written after the run settled (the hourly job charges it), a failed rating. Record the explanation in the release ticket. An unexplained difference stops the switch-on.
3. `python -m src.billing.cutover` — the blockers left must be zero by the end of the period.

### 4.2 Switch-on order

Each switch is a staff setting (Console → Settings → Rollout), changed with a reason, in this order, a few days apart, each only after its notice (§5) has gone out:

| # | Switch | Precondition | Watch for 48 h |
|---|---|---|---|
| 1 | `billing.v2_mode` → `on` | The readiness report has no blocker — the API refuses otherwise (409 with the blockers) | Shadow rows stop; settlements keep flowing (`R-A21 Billing exceptions`) |
| 2 | `entitlements.enforced` → on | Notice `plans` sent; every company on a plan (readiness step 7) | `feature_locked` refusals in the API log; support tickets |
| 3 | `billing.enforcement_enabled` → on | Notices `enforcement`, `billing_currency`, `recharge_validity`, `per_second_calls` sent ≥ 7 days before | Companies in debt (`R-A06`), refusals per day, approvals waiting |
| 4 | `billing.apps_stop_enabled` → on | Enforcement on for ≥ 7 days | Apps stopped (`R-A17`), restarts after recharge |
| 5 | `partners.programme_enabled` → on | Notice `partner_programme` sent; partner agreements signed | Applications, the first commissions (`R-A10`) |

**Rolling back a switch** is setting it off again (with a reason); nothing it did is undone (debt stays recorded, commissions accrued stay accrued). `billing.v2_mode` back to `shadow` resumes the comparison.

The new UI has **no per-workspace switch** (`ui.workspaces` in 08 §6): it replaced the old shell outright and every old route redirects (09 §6). Staff learn the console on dev first.

---

## 5. Customer notices (T10-4)

`python -m src.billing.cutover_notices list` shows the templates; each is filled per company (its currency, rate, plan, call rate, number rent) and sent to its admins in the app and by e-mail.

| Template | Who | When |
|---|---|---|
| `billing_currency` | businesses | 14 days before the release |
| `recharge_validity` | businesses | 14 days before the release (existing balances keep their expiry) |
| `per_second_calls` | businesses | 14 days before the release |
| `number_rent` | businesses with numbers | 30 days before rent starts |
| `plans` | businesses | 7 days before `entitlements.enforced` |
| `enforcement` | businesses | 7 days before `billing.enforcement_enabled` |
| `partner_programme` | partners | 7 days before `partners.programme_enabled` |

```
python -m src.billing.cutover_notices preview billing_currency --company "Acme Pvt Ltd" --date "1 December 2026"
python -m src.billing.cutover_notices send billing_currency --date "1 December 2026"          # counts only
python -m src.billing.cutover_notices send billing_currency --date "1 December 2026" --yes    # sends
```

A notice goes to each person once (its dedupe key `phase15:<template>:v1`); a send that stopped half-way is run again. Changing a template's wording for a second send needs a new `VERSION` in `cutover_notices.py`.

---

## 6. After the release

- Day 1, 2, 7: `python -m src.billing.cutover`, `R-A21 Billing exceptions`, `R-A06 Receivables`, the wallet ledger check (the nightly job logs any wallet that does not equal its ledger).
- One release later: the drop migration (08 §4 step 10), and removal of the old pages left unrouted (09 §6).
- Runbooks for day-to-day money operations (FX change, refunds, payouts, suspension): [11_operations_runbooks.md](11_operations_runbooks.md).
