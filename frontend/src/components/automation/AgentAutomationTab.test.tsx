// @vitest-environment jsdom
/**
 * AgentAutomationTab — the agent's Automation tab: whether triggers may run it,
 * and the tool grants and targets for scheduling and signals.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { EntityStatus, EntityType } from '@/types';

import { AgentAutomationTab, automationOf, SCHEDULE_TOOLS, type AgentAutomation } from './AgentAutomationTab';

const AGENTS = [
    { id: 'self', name: 'Sales Assistant', type: EntityType.AGENT, status: EntityStatus.ACTIVE },
    { id: 'cm', name: 'Community Manager', type: EntityType.AGENT, status: EntityStatus.ACTIVE },
];

function setup(value: AgentAutomation, grantedTools: string[] = []) {
    const onChange = vi.fn();
    const onToolsChange = vi.fn();
    render(
        <QueryClientProvider client={new QueryClient()}>
            <AgentAutomationTab entityId="self" value={value} onChange={onChange} grantedTools={grantedTools}
                                onToolsChange={onToolsChange} agents={AGENTS} />
        </QueryClientProvider>,
    );
    return { onChange, onToolsChange };
}

afterEach(cleanup);

describe('AgentAutomationTab', () => {
    it('reads stored settings, defaulting to runnable with no extra targets', () => {
        expect(automationOf(undefined)).toEqual({ triggerable: true, can_schedule: [] });
        expect(automationOf({ automation: { triggerable: false } })).toEqual({ triggerable: false, can_schedule: [] });
    });

    it('turns automatic runs off', () => {
        const { onChange } = setup({ triggerable: true, can_schedule: [] });
        fireEvent.click(screen.getByLabelText('Runs from triggers'));
        expect(onChange).toHaveBeenLastCalledWith({ triggerable: false, can_schedule: [] });
    });

    it('grants the scheduling tools together, and the signal tool on its own', () => {
        const { onToolsChange } = setup({ triggerable: true, can_schedule: [] });
        fireEvent.click(screen.getByLabelText('May schedule work'));
        expect(onToolsChange).toHaveBeenLastCalledWith(SCHEDULE_TOOLS, true);
        fireEvent.click(screen.getByLabelText('May send signals'));
        expect(onToolsChange).toHaveBeenLastCalledWith(['emit_event'], true);
        fireEvent.click(screen.getByLabelText('May wait for events'));
        expect(onToolsChange).toHaveBeenLastCalledWith(['wait_for_event'], true);
    });

    it('lists the other agents it may schedule once scheduling is granted', () => {
        expect(screen.queryByLabelText('May schedule Community Manager')).toBeNull();
        cleanup();
        const { onChange } = setup({ triggerable: true, can_schedule: [] }, SCHEDULE_TOOLS);
        expect(screen.queryByLabelText('May schedule Sales Assistant')).toBeNull();  // itself: always allowed
        fireEvent.click(screen.getByLabelText('May schedule Community Manager'));
        expect(onChange).toHaveBeenLastCalledWith({ triggerable: true, can_schedule: ['cm'] });
    });
});
