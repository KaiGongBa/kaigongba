import type { AgentProfileRead } from '@/types';
import type { ExecutionRun, OrderWorkspace } from '@/features/marketplace/types';

export type ProjectCenterView = 'agents' | 'projects';
export type ProjectWorkFilter = 'all' | 'working' | 'waiting' | 'idle';
export type ProjectWorkState = Exclude<ProjectWorkFilter, 'all'>;

export type ProjectConnectionState = {
  key: 'enabled' | 'disabled' | 'online' | 'degraded' | 'offline' | 'unknown' | 'revoked';
  label: string;
};

export type ProjectCenterProject = {
  order: OrderWorkspace['order'];
  workspace: OrderWorkspace;
  agentId?: string;
  executionId?: string;
  execution?: ExecutionRun;
  currentNodeName: string;
  openMaterialCount: number;
  deliverableCount: number;
  todoCount: number;
  active: boolean;
};

export type ProjectCenterEmployee = {
  agent: AgentProfileRead;
  projects: ProjectCenterProject[];
  activeProjects: ProjectCenterProject[];
  connection: ProjectConnectionState;
  work: { key: ProjectWorkState; label: string };
  todoCount: number;
};

export type ProjectCenterModel = {
  employees: ProjectCenterEmployee[];
  projects: ProjectCenterProject[];
  stats: {
    employeeCount: number;
    workingCount: number;
    activeProjectCount: number;
    todoCount: number;
  };
};

const TERMINAL_ORDER_STATUSES = new Set(['completed', 'cancelled', 'refunded']);
const OPEN_MATERIAL_STATUSES = new Set(['pending', 'requested', 'open', 'waiting', 'submitted']);
const WAITING_EXECUTION_STATUSES = new Set(['waiting_confirmation', 'waiting_input', 'waiting_material']);

export function buildProjectCenterModel(
  agents: AgentProfileRead[],
  workspaces: OrderWorkspace[],
  connectionHealthByAgentId: Record<string, string> = {},
): ProjectCenterModel {
  const projects = workspaces.map(projectFromWorkspace);
  const employees = agents
    .filter((agent) => !agent.is_overall)
    .map((agent) => {
      const employeeProjects = projects.filter((project) => project.agentId === agent.id);
      const activeProjects = employeeProjects.filter((project) => project.active);
      const waiting = activeProjects.some((project) => (
        project.openMaterialCount > 0
        || Boolean(project.execution && WAITING_EXECUTION_STATUSES.has(project.execution.status))
      ));
      const work = waiting
        ? { key: 'waiting' as const, label: '等待材料' }
        : activeProjects.length > 0
          ? { key: 'working' as const, label: '工作中' }
          : { key: 'idle' as const, label: '空闲' };
      return {
        agent,
        projects: employeeProjects,
        activeProjects,
        connection: connectionState(agent, connectionHealthByAgentId[agent.id]),
        work,
        todoCount: activeProjects.reduce((total, project) => total + project.todoCount, 0),
      };
    });

  return {
    employees,
    projects,
    stats: {
      employeeCount: employees.length,
      workingCount: employees.filter((employee) => employee.work.key !== 'idle').length,
      activeProjectCount: projects.filter((project) => project.active).length,
      todoCount: projects.reduce((total, project) => total + project.todoCount, 0),
    },
  };
}

export function projectCenterView(searchParams: URLSearchParams): ProjectCenterView {
  return searchParams.get('view') === 'projects' ? 'projects' : 'agents';
}

export function projectCenterWork(searchParams: URLSearchParams): ProjectWorkFilter {
  const value = searchParams.get('work');
  return value === 'working' || value === 'waiting' || value === 'idle' ? value : 'all';
}

export function projectCenterSearch(
  current: URLSearchParams,
  patch: { view?: ProjectCenterView; query?: string; work?: ProjectWorkFilter },
): URLSearchParams {
  const next = new URLSearchParams(current);
  if (patch.view) next.set('view', patch.view);
  if (patch.query !== undefined) setOrDelete(next, 'q', patch.query.trim());
  if (patch.work !== undefined) setOrDelete(next, 'work', patch.work === 'all' ? '' : patch.work);
  return next;
}

function projectFromWorkspace(workspace: OrderWorkspace): ProjectCenterProject {
  const execution = workspace.execution.current;
  const agentId = cleanString(execution?.agentProfileId) || snapshotAgentId(workspace.order.snapshot);
  const currentNode = execution?.nodes.find((node) => node.nodeKey === execution.currentNodeKey);
  const openMaterialCount = workspace.materialRequests.filter((item) => OPEN_MATERIAL_STATUSES.has(item.status)).length;
  const active = !TERMINAL_ORDER_STATUSES.has(workspace.order.status);
  const needsAcceptance = ['pending_acceptance', 'submitted'].includes(workspace.order.status) ? 1 : 0;
  return {
    order: workspace.order,
    workspace,
    agentId: agentId || undefined,
    executionId: cleanString(execution?.id) || undefined,
    execution,
    currentNodeName: currentNode?.name || workspace.order.currentMilestoneName || '待开始',
    openMaterialCount,
    deliverableCount: workspace.deliverables.length,
    todoCount: active ? openMaterialCount + needsAcceptance : 0,
    active,
  };
}

function snapshotAgentId(snapshot: Record<string, unknown>): string {
  const service = snapshot.service;
  if (!service || typeof service !== 'object' || Array.isArray(service)) return '';
  const value = (service as Record<string, unknown>).agent_profile_id;
  return cleanString(value);
}

function connectionState(agent: AgentProfileRead, liveHealth?: string): ProjectConnectionState {
  const metadata = agent.metadata || {};
  const external = metadata.source_mode === 'external';
  if (!external) {
    return agent.status === 'active'
      ? { key: 'enabled', label: '已启用' }
      : { key: 'disabled', label: '未启用' };
  }
  const raw = cleanString(
    liveHealth
      || metadata.connection_health_status
      || metadata.external_health_status
      || metadata.health_status,
  );
  const key = raw === 'online'
    || raw === 'degraded'
    || raw === 'offline'
    || raw === 'revoked'
    ? raw
    : 'unknown';
  return {
    key,
    label: ({
      online: '在线',
      degraded: '连接异常',
      offline: '离线',
      unknown: '待心跳',
      revoked: '已撤销',
    } as const)[key],
  };
}

function cleanString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function setOrDelete(params: URLSearchParams, key: string, value: string) {
  if (value) params.set(key, value);
  else params.delete(key);
}
