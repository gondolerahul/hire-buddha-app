/**
 * components/automation/AgentAutomationTab — an agent's Automation tab in the
 * builder (functional spec §3.3; Phase 14 WS3):
 *
 *   - Runs from triggers: schedules, events and "run now" may start it
 *   - May schedule work: grants schedule_agent, cancel_schedule, list_schedules;
 *     it may schedule itself, its own process's agents, and the agents listed here
 *   - May send signals: grants emit_event (custom.* events that wake other agents)
 *   - May wait for events: grants wait_for_event (the run pauses until an event or a deadline)
 *
 * How much an agent may do — schedules per run, shortest repeat, signals per
 * run — is the business's automation limits (Automation Settings), none unless set.
 */
import React, { useMemo } from 'react';

import { useEntityList } from '@/queries/hooks';
import type { HierarchicalEntity } from '@/types';

import './automation.css';

export interface AgentAutomation {
    triggerable: boolean;
    can_schedule: string[];
}

export const SCHEDULE_TOOLS = ['schedule_agent', 'cancel_schedule', 'list_schedules'];
export const SIGNAL_TOOLS = ['emit_event'];
export const WAIT_TOOLS = ['wait_for_event'];

export const automationOf = (capabilities: unknown): AgentAutomation => {
    const raw = (capabilities as { automation?: Partial<AgentAutomation> } | undefined)?.automation;
    return { triggerable: raw?.triggerable ?? true, can_schedule: raw?.can_schedule ?? [] };
};

interface Props {
    entityId?: string;
    value: AgentAutomation;
    onChange: (next: AgentAutomation) => void;
    grantedTools: string[];
    onToolsChange: (tools: string[], granted: boolean) => void;
    /** For tests: the agents to choose from (else the business's entities). */
    agents?: Pick<HierarchicalEntity, 'id' | 'name' | 'display_name' | 'type' | 'status'>[];
}

export const AgentAutomationTab: React.FC<Props> = ({ entityId, value, onChange, grantedTools, onToolsChange, agents }) => {
    const { data: loaded = [] } = useEntityList<HierarchicalEntity>({}, !agents);
    const others = useMemo(
        () => (agents ?? loaded)
            .filter(e => e.id !== entityId && String(e.status).toUpperCase() !== 'DELETED')
            .sort((a, b) => (a.display_name || a.name).localeCompare(b.display_name || b.name)),
        [agents, loaded, entityId]);

    const schedules = SCHEDULE_TOOLS.every(t => grantedTools.includes(t));
    const signals = SIGNAL_TOOLS.every(t => grantedTools.includes(t));
    const waiting = WAIT_TOOLS.every(t => grantedTools.includes(t));

    const toggleTarget = (id: string, on: boolean) =>
        onChange({ ...value, can_schedule: on ? [...value.can_schedule, id] : value.can_schedule.filter(x => x !== id) });

    return (
        <div className="tab-panel ar-agent-tab">
            <div className="form-section">
                <h3>Automatic runs</h3>
                <label className="ar-check">
                    <input type="checkbox" checked={value.triggerable} aria-label="Runs from triggers"
                           onChange={e => onChange({ ...value, triggerable: e.target.checked })} />
                    <span>
                        <strong>Runs from triggers</strong>
                        <small>Schedules, events and Run now in the Control Room may start this agent. Off: every
                            trigger that would start it is refused, with the reason recorded.</small>
                    </span>
                </label>
            </div>

            <div className="form-section">
                <h3>What it may do on its own</h3>
                <label className="ar-check">
                    <input type="checkbox" checked={schedules} aria-label="May schedule work"
                           onChange={e => onToolsChange(SCHEDULE_TOOLS, e.target.checked)} />
                    <span>
                        <strong>May schedule work</strong>
                        <small>"Follow up with this lead in 3 days." Its schedules appear in the Control Room as
                            made by this agent, and you can stop them.</small>
                    </span>
                </label>
                {schedules && (
                    <div className="ar-targets" aria-label="Agents it may schedule">
                        <p className="ar-note">It may always schedule itself and the agents of its own process.
                            Other agents it may schedule:</p>
                        {others.length === 0 ? <p className="ar-note">No other agents yet.</p> : others.map(a => (
                            <label key={a.id} className="ar-check ar-check--small">
                                <input type="checkbox" checked={value.can_schedule.includes(a.id)}
                                       aria-label={`May schedule ${a.display_name || a.name}`}
                                       onChange={e => toggleTarget(a.id, e.target.checked)} />
                                <span>{a.display_name || a.name} <small>({String(a.type).toLowerCase()})</small></span>
                            </label>
                        ))}
                    </div>
                )}
                <label className="ar-check">
                    <input type="checkbox" checked={signals} aria-label="May send signals"
                           onChange={e => onToolsChange(SIGNAL_TOOLS, e.target.checked)} />
                    <span>
                        <strong>May send signals</strong>
                        <small>Custom events such as custom.lead.qualified, which start the agents whose
                            triggers listen for them.</small>
                    </span>
                </label>
                <label className="ar-check">
                    <input type="checkbox" checked={waiting} aria-label="May wait for events"
                           onChange={e => onToolsChange(WAIT_TOOLS, e.target.checked)} />
                    <span>
                        <strong>May wait for events</strong>
                        <small>"Wait until the customer replies, up to 48 hours." The run pauses, using nothing,
                            and continues when the event arrives or the time is up.</small>
                    </span>
                </label>
                <p className="ar-note">Limits on how much agents may do (schedules per run, shortest repeat, signals
                    per run, longest wait) are in Automation Settings; none applies unless set.</p>
            </div>
        </div>
    );
};

export default AgentAutomationTab;
