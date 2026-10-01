/**
 * Single source of truth for the API base URL.
 *
 * `VITE_API_BASE_URL` is only defined when a `.env` file (gitignored) or an
 * explicit env var is present at build/dev-server start. Reading
 * `import.meta.env.VITE_API_BASE_URL` directly means every raw `fetch()` builds
 * a URL like `undefined/ai/entities`, which the dev server answers with the SPA
 * index.html — the request silently "succeeds" and the caller gets no data.
 * Always import API_BASE_URL (or API_ORIGIN) from here instead.
 *
 * Without the variable the app talks to a local API and says so on the console
 * (FE-04). It used to fall back to the production gateway, so a clone run
 * without a `.env` wrote to production.
 */
const LOCAL_API = 'http://localhost:8000/api/v1';

const configured: string | undefined = import.meta.env.VITE_API_BASE_URL;
if (!configured) {
    console.warn(
        `VITE_API_BASE_URL is not set; using ${LOCAL_API}. ` +
        'Set it in frontend/.env (see .env.example) to point the app at another API.',
    );
}

export const API_BASE_URL: string = configured || LOCAL_API;

/** The API's origin (no `/api/v1`), for URLs built outside apiClient — downloads, previews. */
export const API_ORIGIN: string = API_BASE_URL.replace(/\/api\/v1\/?$/, '');
