/**
 * Helpers for saving an entity from the builder without losing what the
 * builder does not show (FE-25).
 */

const isPlainObject = (v: unknown): v is Record<string, any> =>
    !!v && typeof v === 'object' && !Array.isArray(v);

/**
 * `built` laid over `loaded`: every key the builder sets wins — an `undefined`
 * value clears it, as the field was cleared in the form — and every key the
 * builder does not know is kept from the stored entity. Objects merge key by
 * key; arrays and scalars are replaced.
 *
 * Before FE-25 the builder sent only what it rebuilt from its form, and the
 * update replaces each config column, so a setting made through the API (say
 * `governance.meta_review_interval`) vanished on the next unchanged save.
 */
export function overlayConfig<T = any>(loaded: unknown, built: T): T {
    if (!isPlainObject(built) || !isPlainObject(loaded)) return built;
    const out: Record<string, any> = { ...loaded };
    for (const [key, value] of Object.entries(built)) {
        out[key] = isPlainObject(value) && isPlainObject(loaded[key])
            ? overlayConfig(loaded[key], value)
            : value;
    }
    return out as T;
}

const UNKNOWN_KEYS_PREFIX = 'Unknown configuration key(s), which would be ignored: ';

/** The dotted paths a PO-09 "unknown configuration key(s)" 422 names, or []. */
export function unknownKeyPaths(detail: unknown): string[] {
    const messages: string[] = Array.isArray(detail)
        ? detail.map((d: any) => String(d?.msg ?? ''))
        : [String(detail ?? '')];
    for (const message of messages) {
        const at = message.indexOf(UNKNOWN_KEYS_PREFIX);
        if (at === -1) continue;
        const rest = message.slice(at + UNKNOWN_KEYS_PREFIX.length);
        return rest.split('. Check')[0].split(',').map(p => p.trim()).filter(Boolean);
    }
    return [];
}

/** `steps[1].target.tool` → ['steps', 1, 'target', 'tool']. */
const pathParts = (path: string): (string | number)[] =>
    path.split('.').flatMap(part => {
        const m = part.match(/^([^[]+)((?:\[\d+\])*)$/);
        if (!m) return [part];
        const indexes = [...m[2].matchAll(/\[(\d+)\]/g)].map(i => Number(i[1]));
        return [m[1], ...indexes];
    });

/** Whether `path` names something present in `obj`. */
export function hasPath(obj: unknown, path: string): boolean {
    let cur: any = obj;
    for (const part of pathParts(path)) {
        if (cur === null || typeof cur !== 'object' || !(part in cur)) return false;
        cur = cur[part];
    }
    return true;
}

/** A copy of `obj` without the keys at `paths`. */
export function withoutPaths<T>(obj: T, paths: string[]): T {
    const copy: any = structuredClone(obj);
    for (const path of paths) {
        const parts = pathParts(path);
        let cur: any = copy;
        for (const part of parts.slice(0, -1)) {
            if (cur === null || typeof cur !== 'object') { cur = null; break; }
            cur = cur[part];
        }
        if (cur && typeof cur === 'object') delete cur[parts[parts.length - 1]];
    }
    return copy;
}
