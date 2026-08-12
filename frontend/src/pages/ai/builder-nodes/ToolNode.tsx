import { memo } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { Wrench, CheckCircle2, AlertTriangle } from 'lucide-react';
import './nodes.css';

export const ToolNode = memo(({ data, selected }: NodeProps) => {
    const hasToolRef = !!data.toolRef;
    const hasValidationError = !!data.validationError;

    return (
        <div className={`entity-node glass tool-node ${selected ? 'selected' : ''} ${hasToolRef ? 'linked' : ''} ${hasValidationError ? 'has-error' : ''}`}>
            <Handle type="target" position={Position.Top} className="node-handle" />

            {/* Execution order badge */}
            {data.executionOrder != null && (
                <div className="execution-order-badge" title={`Execution order: ${data.executionOrder}`}>
                    {data.executionOrder}
                </div>
            )}

            <div className="node-header">
                <div className="node-icon tool-icon">
                    <Wrench size={16} />
                </div>
                <div className="node-title-area">
                    <div className="node-label">{data.label || 'Tool'}</div>
                    <div className="node-type">TOOL_CALL</div>
                </div>
                {hasToolRef && (
                    <div className="node-status-icon" title="Linked to tool">
                        <CheckCircle2 size={14} />
                    </div>
                )}
                {hasValidationError && (
                    <div className="node-validation-icon" title={data.validationError}>
                        <AlertTriangle size={14} />
                    </div>
                )}
            </div>

            {data.description && (
                <div className="node-description">{data.description}</div>
            )}

            {hasToolRef && (
                <div className="node-footer">
                    <span className="node-ref-label tool-ref">🔧 {data.toolRef.name}</span>
                </div>
            )}

            <Handle type="source" position={Position.Bottom} className="node-handle" />
        </div>
    );
});
