/**
 * services/pagination.ts — the one page contract every list endpoint answers (API-16).
 *
 * `GET /ai/entities`, `/ai/executions`, `/config/integrations` and `/artifacts`
 * take `?limit=` (at most 200) and `?cursor=` and answer
 * `{ items, next_cursor, limit }`, newest first; `next_cursor` is null on the
 * last page. A picker that needs every row follows the cursor with
 * `fetchAllPages`; a long list shows a page and a "Load more" button.
 */
import { apiClient } from './api.client';

export interface Page<T> {
    items: T[];
    next_cursor: string | null;
    limit: number;
}

export const MAX_PAGE_SIZE = 200;

/** One page of `path`, after `cursor` when given. */
export async function fetchPage<T>(
    path: string,
    params: Record<string, unknown> = {},
    cursor: string | null = null,
    limit: number = 50,
): Promise<Page<T>> {
    const { data } = await apiClient.get<Page<T>>(path, {
        params: { ...params, limit, ...(cursor ? { cursor } : {}) },
    });
    return data;
}

/**
 * Every row of `path`, page by page, up to `maxPages` pages (a guard against a
 * list that never ends; 10,000 rows at the largest page size).
 */
export async function fetchAllPages<T>(
    path: string,
    params: Record<string, unknown> = {},
    maxPages: number = 50,
): Promise<T[]> {
    const rows: T[] = [];
    let cursor: string | null = null;
    for (let n = 0; n < maxPages; n += 1) {
        const page: Page<T> = await fetchPage<T>(path, params, cursor, MAX_PAGE_SIZE);
        rows.push(...page.items);
        cursor = page.next_cursor;
        if (!cursor) break;
    }
    return rows;
}
