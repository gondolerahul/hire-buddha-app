/**
 * services/actingCompany — the company a partner or platform admin is working
 * in (Phase 14 M2-4, WS8).
 *
 * With split tenancy each business's agents and runs are in its own database:
 * the API reads another company's only when the request names it in
 * `X-Company-Id` (checked against what the caller may see). The API client
 * sends the header on every request while a company is chosen here; with one
 * shared database the API ignores it. Kept in this browser only, and cleared
 * at sign-out.
 */
export const ACTING_COMPANY_HEADER = 'X-Company-Id';

const STORAGE_KEY = 'acting_company';

export interface ActingCompany {
    id: string;
    name: string;
}

export function getActingCompany(): ActingCompany | null {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : null;
        return parsed && typeof parsed.id === 'string' ? { id: parsed.id, name: String(parsed.name ?? '') } : null;
    } catch {
        return null;
    }
}

export function setActingCompany(company: ActingCompany | null): void {
    try {
        if (company) {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(company));
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    } catch {
        // Storage may be blocked (private window): the choice then lasts this page only.
    }
}
