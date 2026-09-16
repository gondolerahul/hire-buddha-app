/**
 * Single source of truth for the API base URL.
 *
 * `VITE_API_BASE_URL` is only defined when a `.env` file (gitignored) or an
 * explicit env var is present at build/dev-server start. Reading
 * `import.meta.env.VITE_API_BASE_URL` directly means every raw `fetch()` builds
 * a URL like `undefined/ai/entities`, which the dev server answers with the SPA
 * index.html — the request silently "succeeds" and the caller gets no data.
 * Always import API_BASE_URL from here instead.
 */
export const API_BASE_URL: string =
    import.meta.env.VITE_API_BASE_URL || 'https://gateway.hirebuddha.com/api/v1';
