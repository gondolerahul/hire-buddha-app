import { describe, expect, it } from 'vitest';
import { API_ORIGIN, apiUrl } from './api';

// Phase 14 WS1 1.3: a file link the API returns (/api/v1/files/{id}/public)
// loads from the API's origin; other URLs are left as they are.
describe('apiUrl', () => {
    it('puts API paths on the API origin', () => {
        expect(apiUrl('/api/v1/files/abc/public')).toBe(`${API_ORIGIN}/api/v1/files/abc/public`);
    });

    it('leaves full, data and legacy static URLs alone', () => {
        expect(apiUrl('https://cdn.example/x.png')).toBe('https://cdn.example/x.png');
        expect(apiUrl('data:image/png;base64,AAAA')).toBe('data:image/png;base64,AAAA');
        expect(apiUrl('/artifact/user-uploads/avatars/a.png')).toBe('/artifact/user-uploads/avatars/a.png');
    });
});
