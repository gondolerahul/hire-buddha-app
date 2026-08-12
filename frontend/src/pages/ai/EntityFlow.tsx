import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import ReactFlow, {
    addEdge, Background, Controls, MiniMap, Connection, Edge, Node,
    useNodesState, useEdgesState, Panel, EdgeLabelRenderer, BaseEdge, getSmoothStepPath,
} from 'reactflow';
import dagre from 'dagre';
import 'reactflow/dist/style.css';
import { EntityNode } from './builder-nodes/EntityNode';
import { ToolNode } from './builder-nodes/ToolNode';
import { JellyButton } from '@/components/ui';
import { Save, Layers, Trash2, Brain, Zap, Activity, Plus, Settings, Search, AlertTriangle, LayoutGrid } from 'lucide-react';
import { EntityType, HierarchicalEntity, ToolUsage } from '@/types';
import { apiClient } from '@/services/api.client';
import './EntityFlow.css';

// ── Dagre layout helper ──────────────────────────────────────────────────────
const NODE_WIDTH = 260;
const NODE_HEIGHT = 120;

const applyDagreLayout = (nodes: Node[], edges: Edge[], direction: 'TB' | 'LR' = 'TB'): { nodes: Node[]; edges: Edge[] } => {
    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: direction, nodesep: 60, ranksep: 80, marginx: 40, marginy: 40 });

    nodes.forEach(node => g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
    edges.forEach(edge => g.setEdge(edge.source, edge.target));

    dagre.layout(g);

    const layoutedNodes = nodes.map(node => {
        const pos = g.node(node.id);
        return { ...node, position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 } };
    });

    return { nodes: layoutedNodes, edges };
};

// ── Validation engine ────────────────────────────────────────────────────────
interface ValidationIssue {
    nodeId: string;
    severity: 'error' | 'warning';
    message: string;
}

const validateGraph = (nodes: Node[], edges: Edge[]): ValidationIssue[] => {
    const issues: ValidationIssue[] = [];

    // Find orphan nodes (no incoming or outgoing edges — unless it's the only node)
    if (nodes.length > 1) {
        const connectedNodes = new Set<string>();
        edges.forEach(e => { connectedNodes.add(e.source); connectedNodes.add(e.target); });
        nodes.forEach(n => {
            if (!connectedNodes.has(n.id)) {
                issues.push({ nodeId: n.id, severity: 'warning', message: 'Orphan node: not connected to any other step' });
            }
        });
    }

    // Check for CHILD_ENTITY_INVOCATION without entityRef
    nodes.forEach(n => {
        if (n.data.stepType === 'CHILD_ENTITY_INVOCATION' && !n.data.entityRef) {
            issues.push({ nodeId: n.id, severity: 'error', message: 'Sub-agent step must be linked to an entity' });
        }
        if (n.data.stepType === 'TOOL_CALL' && !n.data.toolRef) {
            issues.push({ nodeId: n.id, severity: 'error', message: 'Tool call step must be linked to a tool' });
        }
        if (!n.data.label || n.data.label === 'New Step' || n.data.label === 'Untitled') {
            issues.push({ nodeId: n.id, severity: 'warning', message: 'Step has a default name — give it a descriptive label' });
        }
    });

    return issues;
};

// ── Custom edge with clickable label + tooltip ───────────────────────────────
const RelationshipEdge = ({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, label, style, markerEnd, data }: any) => {
    const [edgePath, labelX, labelY] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 16 });

    const tooltips: Record<string, string> = {
        SEQUENTIAL: 'Steps execute one after another',
        PARALLEL: 'Steps execute simultaneously',
        CONDITIONAL: 'Step executes only if condition is met',
    };

    return (
        <>
            <BaseEdge path={edgePath} markerEnd={markerEnd} style={style} />
            <EdgeLabelRenderer>
                <div
                    style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`, pointerEvents: 'all' }}
                    className={`edge-relationship-label rel-${(label || 'SEQUENTIAL').toLowerCase()}`}
                    onClick={data?.onLabelClick}
                    title={tooltips[String(label || 'SEQUENTIAL')]}
                >
                    {label || 'SEQ'}
                </div>
            </EdgeLabelRenderer>
        </>
    );
};

const nodeTypes = { entityNode: EntityNode, toolNode: ToolNode };
const edgeTypes = { relationship: RelationshipEdge };

const STEP_TYPE_COLORS: Record<string, string> = {
    PROCESS: '#7c3aed',
    AGENT: '#2563eb',
    SKILL: '#059669',
    ACTION: '#d97706',
    TOOL_CALL: '#0891b2',
    THOUGHT: '#6b7280',
};

interface Tool { name: string; description: string; }

interface PlannedTool { tool_id: string; usage: ToolUsage; }

interface EntityFlowProps {
    initialNodes?: Node[];
    initialEdges?: Edge[];
    plannedTools?: PlannedTool[];
    onSave: (nodes: Node[], edges: Edge[]) => void;
}

export const EntityFlow: React.FC<EntityFlowProps> = ({ initialNodes = [], initialEdges = [], plannedTools = [], onSave }) => {
    const reactFlowWrapper = useRef<HTMLDivElement>(null);
    const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState(
        initialEdges.map(e => ({ ...e, type: 'relationship', animated: e.label === 'PARALLEL' }))
    );
    const [reactFlowInstance, setReactFlowInstance] = useState<any>(null);
    const [selectedNode, setSelectedNode] = useState<Node | null>(null);
    const [sidebarTab, setSidebarTab] = useState<'entities' | 'config'>('entities');
    const [layoutDirection, setLayoutDirection] = useState<'TB' | 'LR'>('TB');

    // Library data
    const [entities, setEntities] = useState<HierarchicalEntity[]>([]);
    const [tools, setTools] = useState<Tool[]>([]);
    const [loadingLibraries, setLoadingLibraries] = useState(true);
    const [entitySearch, setEntitySearch] = useState('');

    useEffect(() => { fetchLibraries(); }, []);

    const fetchLibraries = async () => {
        try {
            const [entitiesRes, toolsRes] = await Promise.all([
                apiClient.get<HierarchicalEntity[]>('/ai/entities'),
                apiClient.get<Tool[]>('/ai/tools'),
            ]);
            setEntities(entitiesRes.data);
            setTools(toolsRes.data);

            // Resolve labels for initial nodes loaded from hierarchy.children
            // (they may only have UUIDs as labels if child_name wasn't stored)
            const entityMap = new Map(entitiesRes.data.map((e: HierarchicalEntity) => [e.id, e]));
            setNodes(prevNodes => prevNodes.map(n => {
                if (n.data.entityRef?.id && entityMap.has(n.data.entityRef.id)) {
                    const resolved = entityMap.get(n.data.entityRef.id)!;
                    return {
                        ...n,
                        data: {
                            ...n.data,
                            label: resolved.display_name || resolved.name,
                            entityRef: { id: resolved.id, name: resolved.name, type: resolved.type },
                            stepType: resolved.type,
                        },
                    };
                }
                return n;
            }));

            // Auto-layout initial nodes with dagre if they came from hierarchy
            if (initialNodes.length > 0) {
                setNodes(prev => {
                    const layouted = applyDagreLayout(prev, initialEdges, 'TB');
                    return layouted.nodes;
                });
                setEdges(initialEdges.map(e => ({ ...e, type: 'relationship', animated: e.label === 'PARALLEL' })));
            }
        } catch (error) {
            console.error('Failed to fetch libraries:', error);
        } finally {
            setLoadingLibraries(false);
        }
    };

    // ── Sync PLANNED/BOTH tools onto canvas ──────────────────────────────────
    useEffect(() => {
        if (loadingLibraries) return; // Wait for tools to be fetched first

        const plannedIds = new Set(
            plannedTools
                .filter(t => t.usage === 'PLANNED' || t.usage === 'BOTH')
                .map(t => t.tool_id)
        );

        // Find tool nodes already on canvas
        const existingToolIds = new Set(
            nodes.filter(n => n.data.toolRef).map(n => n.data.toolRef.tool_id)
        );

        // Add missing planned tools
        const toAdd: Node[] = [];
        plannedIds.forEach(toolId => {
            if (!existingToolIds.has(toolId)) {
                const toolInfo = tools.find(t => t.name === toolId);
                const existingCount = nodes.length + toAdd.length;
                toAdd.push({
                    id: `tool-${toolId}`,
                    type: 'toolNode',
                    position: { x: 100 + (existingCount % 3) * 300, y: 100 + Math.floor(existingCount / 3) * 160 },
                    data: {
                        label: toolInfo?.name || toolId,
                        description: toolInfo?.description || '',
                        toolRef: { tool_id: toolId, name: toolInfo?.name || toolId },
                        stepType: 'TOOL_CALL',
                        required: true,
                    },
                });
            }
        });

        // Remove tool nodes that are no longer planned
        const toRemoveIds = nodes
            .filter(n => n.data.toolRef && !plannedIds.has(n.data.toolRef.tool_id))
            .map(n => n.id);

        if (toAdd.length > 0 || toRemoveIds.length > 0) {
            setNodes(prev => {
                let updated = prev.filter(n => !toRemoveIds.includes(n.id));
                updated = [...updated, ...toAdd];
                return updated;
            });
            // Also remove edges connected to removed nodes
            if (toRemoveIds.length > 0) {
                setEdges(prev => prev.filter(e =>
                    !toRemoveIds.includes(e.source) && !toRemoveIds.includes(e.target)
                ));
            }
        }
    }, [plannedTools, loadingLibraries, tools]);
    // ── Validation ────────────────────────────────────────────────────────────
    const validationIssues = useMemo(() => validateGraph(nodes, edges), [nodes, edges]);
    const issuesByNode = useMemo(() => {
        const map: Record<string, ValidationIssue[]> = {};
        validationIssues.forEach(issue => {
            if (!map[issue.nodeId]) map[issue.nodeId] = [];
            map[issue.nodeId].push(issue);
        });
        return map;
    }, [validationIssues]);

    // Compute execution order via topological sort
    const executionOrder = useMemo(() => {
        const order: Record<string, number> = {};
        const inDegree: Record<string, number> = {};
        const adj: Record<string, string[]> = {};
        nodes.forEach(n => { inDegree[n.id] = 0; adj[n.id] = []; });
        edges.forEach(e => { adj[e.source]?.push(e.target); inDegree[e.target] = (inDegree[e.target] || 0) + 1; });
        const queue = nodes.filter(n => inDegree[n.id] === 0).map(n => n.id);
        let idx = 1;
        while (queue.length > 0) {
            const curr = queue.shift()!;
            order[curr] = idx++;
            for (const neighbor of (adj[curr] || [])) {
                inDegree[neighbor]--;
                if (inDegree[neighbor] === 0) queue.push(neighbor);
            }
        }
        // If any nodes weren't visited (cycle), give them an order too
        nodes.forEach(n => { if (!(n.id in order)) order[n.id] = idx++; });
        return order;
    }, [nodes, edges]);

    // Inject executionOrder and validationError into node data
    const enrichedNodes = useMemo(() =>
        nodes.map(n => ({
            ...n,
            data: {
                ...n.data,
                executionOrder: executionOrder[n.id],
                validationError: issuesByNode[n.id]?.map(i => i.message).join('; ') || undefined,
            }
        }))
    , [nodes, executionOrder, issuesByNode]);

    // ── Connection / edge callbacks ───────────────────────────────────────────
    const onConnect = useCallback((params: Connection | Edge) => {
        setEdges((eds) => addEdge({ ...params, type: 'relationship', label: 'SEQUENTIAL', animated: false }, eds));
    }, [setEdges]);

    const cycleEdgeRelationship = (edgeId: string) => {
        const cycle: Record<string, string> = { SEQUENTIAL: 'PARALLEL', PARALLEL: 'CONDITIONAL', CONDITIONAL: 'SEQUENTIAL' };
        setEdges(eds => eds.map(e => e.id === edgeId
            ? { ...e, label: cycle[String(e.label || 'SEQUENTIAL')], animated: cycle[String(e.label || 'SEQUENTIAL')] === 'PARALLEL' }
            : e
        ));
    };

    // Attach onLabelClick to each edge's data
    const enrichedEdges = edges.map(e => ({
        ...e,
        data: { ...e.data, onLabelClick: () => cycleEdgeRelationship(e.id) },
    }));

    // ── Drag / drop ───────────────────────────────────────────────────────────
    const onDragOver = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
    }, []);

    const onDrop = useCallback((event: React.DragEvent) => {
        event.preventDefault();
        const bounds = reactFlowWrapper.current?.getBoundingClientRect();
        const type = event.dataTransfer.getData('application/reactflow/type');
        const payload = event.dataTransfer.getData('application/reactflow/data');
        if (!type || !bounds || !reactFlowInstance) return;

        const position = reactFlowInstance.project({ x: event.clientX - bounds.left, y: event.clientY - bounds.top });
        let nodeData: any = { label: 'New Step', description: '', stepType: 'ACTION' };

        if (payload) {
            const parsed = JSON.parse(payload);
            if (type === 'entityNode') {
                nodeData = { label: parsed.display_name || parsed.name, description: parsed.description, stepType: parsed.type, entityRef: { id: parsed.id, name: parsed.name, type: parsed.type } };
            } else if (type === 'toolNode') {
                nodeData = { label: parsed.name, description: parsed.description, stepType: 'TOOL_CALL', toolRef: { tool_id: parsed.name, name: parsed.name } };
            }
        }

        setNodes(nds => nds.concat({ id: crypto.randomUUID(), type, position, data: nodeData }));
    }, [reactFlowInstance, setNodes]);

    // ── Node selection ────────────────────────────────────────────────────────
    const onNodeClick = (_: React.MouseEvent, node: Node) => {
        setSelectedNode(node);
        setSidebarTab('config');
    };

    const onPaneClick = () => {
        setSelectedNode(null);
        if (sidebarTab === 'config') setSidebarTab('entities');
    };

    const handleNodeDataChange = (newData: any) => {
        if (!selectedNode) return;
        setNodes(nds => nds.map(n => n.id === selectedNode.id ? { ...n, data: { ...n.data, ...newData } } : n));
        setSelectedNode(prev => prev ? { ...prev, data: { ...prev.data, ...newData } } : null);
    };

    const deleteNode = () => {
        if (!selectedNode) return;
        setNodes(nds => nds.filter(n => n.id !== selectedNode.id));
        setEdges(eds => eds.filter(e => e.source !== selectedNode.id && e.target !== selectedNode.id));
        setSelectedNode(null);
        setSidebarTab('entities');
    };

    const addActionNode = () => {
        const position = reactFlowInstance?.project({ x: 400, y: 200 + nodes.length * 120 }) || { x: 400, y: 200 };
        setNodes(nds => nds.concat({ id: crypto.randomUUID(), type: 'entityNode', position, data: { label: 'New Step', description: '', stepType: 'ACTION', required: true } }));
    };

    const handleLinkEntity = (entityId: string) => {
        const entity = entities.find(e => e.id === entityId);
        if (entity) handleNodeDataChange({ label: entity.display_name || entity.name, entityRef: { id: entity.id, name: entity.name, type: entity.type }, stepType: entity.type });
    };

    const handleLinkTool = (toolName: string) => {
        const tool = tools.find(t => t.name === toolName);
        if (tool) handleNodeDataChange({ label: tool.name, toolRef: { tool_id: tool.name, name: tool.name }, stepType: 'TOOL_CALL' });
    };

    // ── Dagre auto-layout ────────────────────────────────────────────────────
    const autoLayout = () => {
        if (nodes.length === 0) return;
        const { nodes: layoutedNodes, edges: layoutedEdges } = applyDagreLayout(nodes, edges, layoutDirection);
        setNodes(layoutedNodes);
        setEdges(layoutedEdges);
        setTimeout(() => reactFlowInstance?.fitView({ padding: 0.2 }), 50);
    };

    // ── Filters ───────────────────────────────────────────────────────────────
    const filteredEntities = entities.filter(e =>
        (e.display_name || e.name).toLowerCase().includes(entitySearch.toLowerCase()) ||
        e.type.toLowerCase().includes(entitySearch.toLowerCase())
    );

    const entityTypeIcon = (type: EntityType) => {
        if (type === EntityType.AGENT) return <Layers size={13} />;
        if (type === EntityType.SKILL) return <Brain size={13} />;
        if (type === EntityType.ACTION) return <Zap size={13} />;
        return <Activity size={13} />;
    };

    const errorCount = validationIssues.filter(i => i.severity === 'error').length;
    const warningCount = validationIssues.filter(i => i.severity === 'warning').length;

    return (
        <div className="entity-flow-wrapper">
            {/* ── Sidebar ─────────────────────────────────────────────────── */}
            <div className="entity-flow-sidebar">
                <div className="sidebar-tabs" style={{ gridTemplateColumns: '1fr 1fr' }}>
                    <button className={`sidebar-tab-btn ${sidebarTab === 'entities' ? 'active' : ''}`} onClick={() => setSidebarTab('entities')}><Layers size={14} /> Entities</button>
                    <button className={`sidebar-tab-btn ${sidebarTab === 'config' ? 'active' : ''}`} onClick={() => setSidebarTab('config')}><Settings size={14} /> Config</button>
                </div>

                {/* Add manual action node */}
                <div className="sidebar-add-btn">
                    <JellyButton size="sm" onClick={addActionNode} className="w-full">
                        <Plus size={14} /> Add Action Step
                    </JellyButton>
                </div>

                {/* ──── Entities tab ──── */}
                {sidebarTab === 'entities' && (
                    <div className="sidebar-section">
                        <div className="sidebar-search">
                            <Search size={13} />
                            <input type="text" value={entitySearch} onChange={e => setEntitySearch(e.target.value)} placeholder="Search entities..." />
                        </div>
                        {loadingLibraries ? <div className="library-loading">Loading...</div> : (
                            <>
                                {filteredEntities.map(entity => (
                                    <div
                                        key={entity.id}
                                        className={`draggable-item entity-item entity-type-${entity.type.toLowerCase()}`}
                                        draggable
                                        onDragStart={(e) => {
                                            e.dataTransfer.setData('application/reactflow/type', 'entityNode');
                                            e.dataTransfer.setData('application/reactflow/data', JSON.stringify(entity));
                                        }}
                                    >
                                        <div className="item-header">
                                            {entityTypeIcon(entity.type)}
                                            <span>{entity.display_name || entity.name}</span>
                                        </div>
                                        <span className={`type-badge type-badge-${entity.type.toLowerCase()}`}>{entity.type}</span>
                                    </div>
                                ))}
                                {filteredEntities.length === 0 && <div className="library-empty">No entities found</div>}
                            </>
                        )}
                    </div>
                )}

                {/* ──── Config panel ──── */}
                {sidebarTab === 'config' && selectedNode && (
                    <div className="sidebar-section node-config-panel">
                        <div className="config-node-header">
                            <span className="step-order-badge">Step {executionOrder[selectedNode.id] || '?'}</span>
                            <span className={`type-badge type-badge-${(selectedNode.data.stepType || 'action').toLowerCase()}`}>{selectedNode.data.stepType || 'ACTION'}</span>
                        </div>
                        {issuesByNode[selectedNode.id] && (
                            <div className="config-validation-issues">
                                {issuesByNode[selectedNode.id].map((issue, i) => (
                                    <div key={i} className={`validation-issue ${issue.severity}`}>
                                        <AlertTriangle size={12} /> {issue.message}
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className="form-group">
                            <label>Step Name</label>
                            <input value={selectedNode.data.label} onChange={(e) => handleNodeDataChange({ label: e.target.value })} />
                        </div>
                        <div className="form-group">
                            <label>Description / Prompt Template</label>
                            <textarea value={selectedNode.data.description || ''} onChange={(e) => handleNodeDataChange({ description: e.target.value })} rows={3} placeholder="What should this step do?" />
                        </div>
                        <div className="form-group">
                            <label>Step Type</label>
                            <select value={selectedNode.data.stepType || 'ACTION'} onChange={(e) => handleNodeDataChange({ stepType: e.target.value, entityRef: undefined, toolRef: undefined })}>
                                <option value="ACTION">ACTION — Direct instruction</option>
                                <option value="THOUGHT">THOUGHT — Internal reasoning</option>
                                <option value="TOOL_CALL">TOOL_CALL — Tool execution</option>
                                <option value="CHILD_ENTITY_INVOCATION">CHILD_ENTITY — Sub-agent call</option>
                            </select>
                        </div>

                        {selectedNode.data.stepType === 'CHILD_ENTITY_INVOCATION' || selectedNode.data.entityRef ? (
                            <div className="form-group">
                                <label>Link to Entity</label>
                                <select value={selectedNode.data.entityRef?.id || ''} onChange={(e) => handleLinkEntity(e.target.value)}>
                                    <option value="">-- Select Entity --</option>
                                    {entities.map(e => <option key={e.id} value={e.id}>{e.display_name || e.name} ({e.type})</option>)}
                                </select>
                            </div>
                        ) : null}

                        {selectedNode.data.stepType === 'TOOL_CALL' || selectedNode.data.toolRef ? (
                            <div className="form-group">
                                <label>Link to Tool</label>
                                <select value={selectedNode.data.toolRef?.tool_id || ''} onChange={(e) => handleLinkTool(e.target.value)}>
                                    <option value="">-- Select Tool --</option>
                                    {tools.map(t => <option key={t.name} value={t.name}>{t.name}</option>)}
                                </select>
                            </div>
                        ) : null}

                        <div className="form-group">
                            <label className="checkbox-label">
                                <input type="checkbox" checked={selectedNode.data.required ?? true} onChange={(e) => handleNodeDataChange({ required: e.target.checked })} />
                                Required Step
                            </label>
                        </div>

                        <JellyButton variant="danger" size="sm" className="w-full" onClick={deleteNode}>
                            <Trash2 size={16} /> Remove Node
                        </JellyButton>
                    </div>
                )}
                {sidebarTab === 'config' && !selectedNode && (
                    <div className="sidebar-section">
                        <div className="no-selection-hint">
                            <AlertTriangle size={20} />
                            <p>Click a node on the canvas to configure it</p>
                        </div>
                    </div>
                )}
            </div>

            {/* ── Canvas ──────────────────────────────────────────────────── */}
            <div className="entity-flow-canvas" ref={reactFlowWrapper}>
                <ReactFlow
                    nodes={enrichedNodes}
                    edges={enrichedEdges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onConnect={onConnect}
                    onInit={setReactFlowInstance}
                    onDrop={onDrop}
                    onDragOver={onDragOver}
                    onNodeClick={onNodeClick}
                    onPaneClick={onPaneClick}
                    nodeTypes={nodeTypes}
                    edgeTypes={edgeTypes}
                    fitView
                >
                    <Background color="rgba(255,255,255,0.05)" gap={20} />
                    <Controls />
                    <MiniMap
                        nodeColor={(n: any) => {
                            const type = n.data?.stepType || n.data?.entityRef?.type || 'ACTION';
                            return STEP_TYPE_COLORS[type] || '#c58e7f';
                        }}
                        maskColor="rgba(0,0,0,0.5)"
                        className="glass"
                    />
                    <Panel position="top-right">
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            <select
                                className="layout-direction-select"
                                value={layoutDirection}
                                onChange={(e) => setLayoutDirection(e.target.value as 'TB' | 'LR')}
                                title="Layout direction"
                            >
                                <option value="TB">↓ Top-Down</option>
                                <option value="LR">→ Left-Right</option>
                            </select>
                            <JellyButton size="sm" onClick={autoLayout}><LayoutGrid size={14} /> Auto-Layout</JellyButton>
                            <JellyButton roseGold onClick={() => onSave(nodes, edges)}>
                                <Save size={18} /> Save Hierarchy
                            </JellyButton>
                        </div>
                    </Panel>
                    <Panel position="bottom-center">
                        <div className="edge-legend">
                            <span className="legend-item rel-sequential">SEQ</span>
                            <span className="legend-item rel-parallel">PAR</span>
                            <span className="legend-item rel-conditional">COND</span>
                            <small>Click edge labels to cycle type</small>
                            {(errorCount > 0 || warningCount > 0) && (
                                <span className="validation-summary">
                                    {errorCount > 0 && <span className="validation-error-count">⚠ {errorCount} error{errorCount !== 1 ? 's' : ''}</span>}
                                    {warningCount > 0 && <span className="validation-warning-count">⚡ {warningCount} warning{warningCount !== 1 ? 's' : ''}</span>}
                                </span>
                            )}
                        </div>
                    </Panel>
                </ReactFlow>
            </div>
        </div>
    );
};
