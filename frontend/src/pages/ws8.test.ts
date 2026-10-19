/**
 * The WS8 screens' own logic (Phase 14): names from labels, schema proposals,
 * what a key may do, a connection's health, what stops when it goes, app names.
 */
import { describe, expect, it } from 'vitest';

import { impactLines } from './connections/ConnectionDetail';
import { healthOf } from './connections/ConnectionsPage';
import { canDo } from './records/DataKeysPage';
import { searchFieldOf, toValue } from './records/RecordsPage';
import { nameFrom, operationsFor } from './records/SchemaPage';
import { statusTone } from './apps/AppsPage';
import { suggestAppName } from '@/services/apps.service';
import { actorLabel } from '@/services/records.service';
import type { Connection } from '@/services/connections.service';
import type { DataKey } from '@/services/records.service';

describe('schema proposals', () => {
    it('names come from labels', () => {
        expect(nameFrom('Shipments')).toBe('shipments');
        expect(nameFrom('  ETA (days) ')).toBe('eta_days');
        expect(nameFrom('2nd address')).toBe('f_2nd_address');
    });

    it('a new table carries its fields; fields on a table are one operation each', () => {
        const fields = [
            { label: 'Carrier', type: 'text' as const, required: true, values: '', to: '' },
            { label: 'Status', type: 'enum' as const, required: false, values: 'in transit, delivered', to: '' },
            { label: 'Order', type: 'ref' as const, required: false, values: '', to: 'order' },
            { label: '', type: 'text' as const, required: false, values: '', to: '' },
        ];
        const [table] = operationsFor('table', '', 'Shipments', fields);
        expect(table).toEqual({ op: 'add_object', object: 'shipments', definition: { label: 'Shipments', fields: {
            carrier: { type: 'text', label: 'Carrier', required: true },
            status: { type: 'enum', label: 'Status', values: ['in transit', 'delivered'] },
            order: { type: 'ref', label: 'Order', to: 'order' },
        } } });
        const ops = operationsFor('field', 'contact', '', fields);
        expect(ops.map(o => o.op)).toEqual(['add_field', 'add_field', 'add_relation']);
        expect(ops[0]).toMatchObject({ object: 'contact', field: 'carrier' });
    });
});

describe('records', () => {
    it('form values are what the Data API takes', () => {
        expect(toValue({ type: 'integer' }, '42')).toBe(42);
        expect(toValue({ type: 'text' }, '')).toBeNull();
        expect(toValue({ type: 'boolean' }, true)).toBe(true);
        expect(toValue({ type: 'decimal' }, '1.50')).toBe('1.50');
    });

    it('search looks in a name-like field first', () => {
        const object = { label: 'Account', plural: 'Accounts', fields: {
            city: { type: 'text' as const }, name: { type: 'text' as const }, phone: { type: 'phone' as const } } };
        expect(searchFieldOf(object)).toBe('name');
        expect(searchFieldOf({ ...object, fields: { city: { type: 'text' as const } } })).toBe('city');
        expect(searchFieldOf({ ...object, fields: { amount: { type: 'integer' as const } } })).toBeUndefined();
    });

    it('who changed a record, in words', () => {
        expect(actorLabel('user:1')).toBe('a person');
        expect(actorLabel('run:9')).toBe('an agent');
        expect(actorLabel('app_user:3')).toBe('an app user');
        expect(actorLabel(null)).toBe('unknown');
    });

    it('a key says what it may do', () => {
        const key = { scopes: { objects: { contact: ['read', 'create'], '*': ['read', 'create', 'update', 'delete'] } } } as unknown as DataKey;
        expect(canDo(key)).toBe('contact: read/create · Everything: read/write/delete');
    });
});

describe('connections', () => {
    const base = { status: 'active', health: {}, token_expires_at: null } as unknown as Connection;

    it('health reads the status, the last error and the expiry', () => {
        expect(healthOf(base)).toEqual({ label: 'Healthy', tone: 'active' });
        expect(healthOf({ ...base, status: 'needs_reconnect' }).label).toBe('Needs reconnect');
        expect(healthOf({ ...base, health: { last_error: 'boom' } }).tone).toBe('dead');
        // eslint-disable-next-line no-restricted-syntax -- a number of milliseconds, not a server timestamp
        const soon = new Date(Date.now() + 5 * 86_400_000 + 3_600_000).toISOString().replace('Z', '');
        expect(healthOf({ ...base, status: 'expiring', token_expires_at: soon }).label).toBe('Expires in 5 days');
    });

    it('disconnecting says what stops', () => {
        expect(impactLines({ all_agents: false, agents: [{ id: 'a', name: 'Community Manager' }], apps: ['x'],
                             triggers: [{ id: 't', name: 'New comment', enabled: true }, { id: 'u', name: 'Old', enabled: false }] }))
            .toEqual(['1 agent loses it: Community Manager', '1 app loses it', '1 trigger will pause: New comment']);
        expect(impactLines({ all_agents: true, agents: [], apps: [], triggers: [] })).toEqual(['Every agent loses it']);
    });
});

describe('apps', () => {
    it('a web name from the display name', () => {
        expect(suggestAppName('Sales CRM')).toBe('sales-crm');
        expect(suggestAppName('  2024 Shop!! ')).toBe('shop');
        expect(suggestAppName('a'.repeat(40))).toHaveLength(30);
    });

    it('states have tones', () => {
        expect(statusTone('published')).toBe('active');
        expect(statusTone('failed')).toBe('dead');
        expect(statusTone('building')).toBe('paused');
    });
});
