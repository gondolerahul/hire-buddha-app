/**
 * A readable message from an API error.
 *
 * FastAPI answers most errors with `detail: string`, but a validation error
 * (422) with `detail: [{loc, msg}, ...]` — an array React cannot render.
 */
export function apiErrorMessage(err: any, fallback: string): string {
    const detail = err?.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
        return detail
            .map((d: any) => {
                const field = Array.isArray(d?.loc) ? d.loc.filter((p: any) => p !== 'body').join('.') : '';
                return field ? `${field}: ${d?.msg}` : String(d?.msg ?? d);
            })
            .join('; ');
    }
    return fallback;
}
