import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  ClipboardCheck,
  FileBox,
  FolderKanban,
  MessageCircle,
  RefreshCw,
  Users,
} from 'lucide-react';
import { useMemo } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '@/api/client';
import EmployeeAvatar from '@/components/EmployeeAvatar';
import { employeeDisplayName, employeeProfile } from '@/employee';
import { MarketplaceHeader, MarketplaceState } from '@/features/marketplace/components';
import { marketplaceRepository } from '@/features/marketplace/repository';
import { useMarketplaceOrganization } from '@/features/marketplace/useMarketplaceOrganization';
import { useMarketplaceResource } from '@/features/marketplace/useMarketplaceResource';
import type { AgentProfileRead } from '@/types';

import {
  buildProjectCenterModel,
  projectCenterSearch,
  projectCenterView,
  projectCenterWork,
  type ProjectCenterEmployee,
  type ProjectCenterProject,
  type ProjectCenterView,
  type ProjectWorkFilter,
} from './projectCenterModel';
import './project-center.css';

export type ProjectCenterPageProps = {
  agents: AgentProfileRead[];
  selectedAgentId?: string;
  onOpenChat: (agent: AgentProfileRead) => void;
};

type ProjectCenterResourceData = {
  workspaces: Awaited<ReturnType<typeof marketplaceRepository.getOrderWorkspace>>[];
  connectionHealthByAgentId: Record<string, string>;
};

type ExternalAgentOperationsSummary = {
  connection: { healthStatus: string };
};

export default function ProjectCenterPage({
  agents,
  selectedAgentId,
  onOpenChat,
}: ProjectCenterPageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const organization = useMarketplaceOrganization();
  const resource = useMarketplaceResource(
    async () => {
      if (!organization.selected) return { workspaces: [], connectionHealthByAgentId: {} };
      const orders = await marketplaceRepository.listOrders(organization.selected.id, 'all');
      const workspaces = await Promise.all(
        orders.map((order) => marketplaceRepository.getOrderWorkspace(order.id, organization.selected!.id)),
      );
      const externalAgents = agents.filter((agent) => (
        agent.metadata?.source_mode === 'external'
        && typeof agent.metadata.external_connection_id === 'string'
        && agent.metadata.external_connection_id
      ));
      const healthEntries = await Promise.all(externalAgents.map(async (agent) => {
        const connectionId = String(agent.metadata.external_connection_id);
        try {
          const operations = await api.get<ExternalAgentOperationsSummary>(
            `/api/enterprise/external-agents/${encodeURIComponent(connectionId)}/operations`,
          );
          return [agent.id, operations.connection.healthStatus] as const;
        } catch {
          return [agent.id, 'unknown'] as const;
        }
      }));
      return { workspaces, connectionHealthByAgentId: Object.fromEntries(healthEntries) };
    },
    `project-center:${organization.selected?.id || 'none'}:${externalConnectionDependency(agents)}`,
  );
  const model = useMemo(
    () => buildProjectCenterModel(
      agents,
      resource.data?.workspaces || [],
      resource.data?.connectionHealthByAgentId || {},
    ),
    [agents, resource.data],
  );
  const selectedEmployee = selectedAgentId
    ? model.employees.find((employee) => employee.agent.id === selectedAgentId)
    : undefined;

  if (selectedAgentId) {
    return (
      <main className="project-center-page">
        <MarketplaceHeader
          breadcrumb={(
            <button
              type="button"
              className="project-center-back"
              onClick={() => navigate({ pathname: '/workspace/gallery', search: location.search })}
            >
              <ArrowLeft />返回项目中心
            </button>
          )}
          organizations={organization.organizations}
          selectedOrganizationId={organization.selected?.id}
          organizationLoading={organization.loading}
          onOrganizationChange={organization.selectOrganization}
        />
        <ProjectCenterLoadState
          organizationReady={Boolean(organization.selected)}
          organizationLoading={organization.loading}
          loading={resource.loading}
          error={organization.error || resource.error}
          onRetry={resource.reload}
        />
        {!resource.loading && !resource.error && organization.selected && (
          selectedEmployee
            ? <EmployeeProjectsDetail employee={selectedEmployee} onOpenChat={onOpenChat} onOpenOrder={openOrder} />
            : <ProjectCenterNotFound />
        )}
      </main>
    );
  }

  const view = projectCenterView(searchParams);
  const work = projectCenterWork(searchParams);
  const query = searchParams.get('q') || '';
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const visibleEmployees = model.employees.filter((employee) => {
    const matchesStatus = work === 'all' || employee.work.key === work;
    const values = [
      employeeDisplayName(employee.agent),
      employee.agent.description || '',
      employeeProfile(employee.agent).roleName,
      ...employee.projects.map((project) => project.order.title),
    ];
    return matchesStatus && values.some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
  });
  const visibleProjects = model.projects.filter((project) => {
    const employee = model.employees.find((item) => item.agent.id === project.agentId);
    return [
      project.order.title,
      project.order.code,
      project.order.serviceName,
      project.order.buyerName,
      project.order.providerName,
      employee ? employeeDisplayName(employee.agent) : '',
    ].some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
  });

  function updateState(patch: { view?: ProjectCenterView; query?: string; work?: ProjectWorkFilter }) {
    setSearchParams(projectCenterSearch(searchParams, patch));
  }

  function openOrder(project: ProjectCenterProject) {
    navigate(`/enterprise/orders/${encodeURIComponent(project.order.id)}`);
  }

  return (
    <main className="project-center-page">
      <MarketplaceHeader
        title="项目中心"
        searchValue={query}
        searchPlaceholder="搜索员工、项目、订单或服务"
        onSearchChange={(value) => updateState({ query: value })}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={(
          <button type="button" className="project-center-refresh" onClick={resource.reload} aria-label="刷新项目中心">
            <RefreshCw />刷新
          </button>
        )}
      />

      <div className="project-center-heading">
        <div>
          <h2>员工与项目运行看板</h2>
          <p>项目来自真实订单；SOP 进度、待办和交付物随订单执行记录更新。</p>
        </div>
        <div className="project-center-tabs" role="tablist" aria-label="项目中心视图">
          <button type="button" role="tab" aria-selected={view === 'agents'} className={view === 'agents' ? 'is-active' : ''} onClick={() => updateState({ view: 'agents' })}>按员工查看</button>
          <button type="button" role="tab" aria-selected={view === 'projects'} className={view === 'projects' ? 'is-active' : ''} onClick={() => updateState({ view: 'projects' })}>按项目查看</button>
        </div>
      </div>

      <ProjectCenterLoadState
        organizationReady={Boolean(organization.selected)}
        organizationLoading={organization.loading}
        loading={resource.loading}
        error={organization.error || resource.error}
        onRetry={resource.reload}
      />

      {!resource.loading && !resource.error && organization.selected && (
        <>
          <ProjectStats model={model} />
          {view === 'agents' ? (
            <section className="project-center-section" aria-label="员工项目状态">
              <div className="project-center-section__header">
                <div><h3>数字员工</h3><span>{visibleEmployees.length} 位</span></div>
                <label className="project-center-filter">
                  <span>工作状态</span>
                  <select value={work} onChange={(event) => updateState({ work: event.target.value as ProjectWorkFilter })}>
                    <option value="all">全部状态</option>
                    <option value="working">工作中</option>
                    <option value="waiting">等待材料</option>
                    <option value="idle">空闲</option>
                  </select>
                </label>
              </div>
              {visibleEmployees.length ? (
                <div className="project-employee-grid">
                  {visibleEmployees.map((employee) => (
                    <EmployeeProjectCard
                      key={employee.agent.id}
                      employee={employee}
                      onOpen={() => navigate({
                        pathname: `/workspace/projects/agents/${encodeURIComponent(employee.agent.id)}`,
                        search: location.search,
                      })}
                    />
                  ))}
                </div>
              ) : <ProjectCenterEmpty title="没有符合条件的员工" detail="调整搜索词或工作状态筛选后重试。" />}
            </section>
          ) : (
            <section className="project-center-section" aria-label="项目运行状态">
              <div className="project-center-section__header">
                <div><h3>真实订单项目</h3><span>{visibleProjects.length} 个</span></div>
                <p>未绑定数字员工的订单仍会展示，并明确标记“未绑定员工”。</p>
              </div>
              {visibleProjects.length ? (
                <div className="project-list">
                  {visibleProjects.map((project) => (
                    <ProjectRow
                      key={project.order.id}
                      project={project}
                      employee={model.employees.find((item) => item.agent.id === project.agentId)}
                      onOpen={() => openOrder(project)}
                    />
                  ))}
                </div>
              ) : <ProjectCenterEmpty title="当前企业还没有项目" detail="合同确认并完成支付后，真实订单会自动进入项目中心。" />}
            </section>
          )}
        </>
      )}
    </main>
  );
}

function ProjectCenterLoadState({
  organizationReady,
  organizationLoading,
  loading,
  error,
  onRetry,
}: {
  organizationReady: boolean;
  organizationLoading: boolean;
  loading: boolean;
  error: string;
  onRetry: () => void;
}) {
  if (!organizationLoading && !organizationReady && !error) {
    return <ProjectCenterEmpty title="当前账号未加入可访问企业" detail="请先在管理端的账号管理中加入企业与团队。" />;
  }
  return <MarketplaceState loading={organizationLoading || loading} error={error} onRetry={onRetry} />;
}

function ProjectStats({ model }: { model: ReturnType<typeof buildProjectCenterModel> }) {
  const items = [
    { label: '数字员工', value: model.stats.employeeCount, detail: '当前账号可用', Icon: Users },
    { label: '正在工作', value: model.stats.workingCount, detail: '含等待材料', Icon: Bot },
    { label: '进行中项目', value: model.stats.activeProjectCount, detail: '来自真实订单', Icon: FolderKanban },
    { label: '待处理事项', value: model.stats.todoCount, detail: '材料与验收', Icon: ClipboardCheck },
  ];
  return (
    <section className="project-center-stats" aria-label="项目中心统计">
      {items.map(({ label, value, detail, Icon }) => (
        <article key={label}>
          <span><Icon /></span>
          <div><small>{label}</small><strong>{value}</strong><em>{detail}</em></div>
        </article>
      ))}
    </section>
  );
}

function EmployeeProjectCard({ employee, onOpen }: { employee: ProjectCenterEmployee; onOpen: () => void }) {
  const profile = employeeProfile(employee.agent);
  const displayName = employeeDisplayName(employee.agent);
  const primaryProject = employee.activeProjects[0] || employee.projects[0];
  return (
    <button
      type="button"
      className="project-employee-card"
      aria-label={`查看员工项目：${displayName}`}
      onClick={onOpen}
    >
      <header>
        <EmployeeAvatar agent={employee.agent} width={72} height={80} fit="contain" objectPosition="center bottom" radius={16} />
        <div className="project-employee-card__identity">
          <strong data-i18n-ignore>{displayName}</strong>
          <span data-i18n-ignore>{profile.roleName}</span>
          <div>
            <i className={`is-${employee.connection.key}`}><CircleDot />{employee.connection.label}</i>
            <i className={`is-${employee.work.key}`}>{employee.work.label}</i>
          </div>
        </div>
        <ChevronRight className="project-card-arrow" />
      </header>
      {primaryProject ? (
        <div className="project-employee-card__project">
          <div><span>当前项目</span><em>{primaryProject.order.code}</em></div>
          <strong data-i18n-ignore>{primaryProject.order.title}</strong>
          <p><span>{primaryProject.currentNodeName}</span><em>{primaryProject.order.progressPercent}%</em></p>
          <div className="project-progress"><i style={{ width: `${primaryProject.order.progressPercent}%` }} /></div>
          <footer>
            <span><FileBox />{primaryProject.deliverableCount} 份交付物</span>
            <span><CalendarClock />{expectedDate(primaryProject.order.expectedDeliveryAt)}</span>
          </footer>
        </div>
      ) : (
        <div className="project-employee-card__idle">
          <CheckCircle2 />
          <strong>当前没有进行中的项目</strong>
          <span>员工处于空闲状态，可承接新任务。</span>
        </div>
      )}
      <footer className="project-employee-card__footer">
        <span>{employee.activeProjects.length} 个进行中</span>
        <span>{employee.todoCount} 项待处理</span>
        <em>查看项目 <ArrowRight /></em>
      </footer>
    </button>
  );
}

function ProjectRow({
  project,
  employee,
  onOpen,
}: {
  project: ProjectCenterProject;
  employee?: ProjectCenterEmployee;
  onOpen: () => void;
}) {
  const name = employee ? employeeDisplayName(employee.agent) : '';
  return (
    <button
      type="button"
      className="project-row"
      aria-label={`打开项目：${project.order.title}`}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <span className="project-row__status"><i className={project.active ? 'is-active' : 'is-finished'} /><em>{orderStatus(project.order.status)}</em></span>
      <span className="project-row__main"><small>{project.order.code}</small><strong data-i18n-ignore>{project.order.title}</strong><em data-i18n-ignore>{project.order.serviceName}</em></span>
      <span className="project-row__employee">
        {employee ? <EmployeeAvatar agent={employee.agent} size={38} radius={12} /> : <i><Bot /></i>}
        <span><small>负责员工</small><strong data-i18n-ignore>{name || '未绑定员工'}</strong></span>
      </span>
      <span className="project-row__node"><small>当前节点</small><strong>{project.currentNodeName}</strong><em>{project.executionId ? `执行 ${shortId(project.executionId)}` : '尚未启动 SOP'}</em></span>
      <span className="project-row__progress"><small>整体进度 <em>{project.order.progressPercent}%</em></small><i><b style={{ width: `${project.order.progressPercent}%` }} /></i><strong>{expectedDate(project.order.expectedDeliveryAt)}</strong></span>
      <ChevronRight />
    </button>
  );
}

function EmployeeProjectsDetail({
  employee,
  onOpenChat,
  onOpenOrder,
}: {
  employee: ProjectCenterEmployee;
  onOpenChat: (agent: AgentProfileRead) => void;
  onOpenOrder: (project: ProjectCenterProject) => void;
}) {
  const profile = employeeProfile(employee.agent);
  const name = employeeDisplayName(employee.agent);
  return (
    <div className="employee-project-detail">
      <section className="employee-project-hero">
        <EmployeeAvatar agent={employee.agent} width={104} height={116} fit="contain" objectPosition="center bottom" radius={22} />
        <div>
          <span data-i18n-ignore>{profile.roleName}</span>
          <h1 data-i18n-ignore>{name}</h1>
          <p data-i18n-ignore>{employee.agent.description || '暂无员工说明'}</p>
          <div><i className={`is-${employee.connection.key}`}>{employee.connection.label}</i><i className={`is-${employee.work.key}`}>{employee.work.label}</i></div>
        </div>
        <button type="button" onClick={() => onOpenChat(employee.agent)}><MessageCircle />与员工对话</button>
      </section>
      <section className="employee-project-metrics">
        <article><small>全部项目</small><strong>{employee.projects.length}</strong></article>
        <article><small>进行中</small><strong>{employee.activeProjects.length}</strong></article>
        <article><small>待处理事项</small><strong>{employee.todoCount}</strong></article>
        <article><small>累计交付物</small><strong>{employee.projects.reduce((sum, project) => sum + project.deliverableCount, 0)}</strong></article>
      </section>
      <section className="project-center-section">
        <div className="project-center-section__header"><div><h3>负责项目</h3><span>{employee.projects.length} 个</span></div><p>点击项目进入真实订单工作区。</p></div>
        {employee.projects.length ? (
          <div className="project-list">
            {employee.projects.map((project) => <ProjectRow key={project.order.id} project={project} employee={employee} onOpen={() => onOpenOrder(project)} />)}
          </div>
        ) : <ProjectCenterEmpty title="该员工还没有项目" detail="员工承接的真实订单将在这里展示。" />}
      </section>
    </div>
  );
}

function ProjectCenterNotFound() {
  return <ProjectCenterEmpty title="员工不存在或无权访问" detail="请返回项目中心，选择当前账号可见的员工。" />;
}

function ProjectCenterEmpty({ title, detail }: { title: string; detail: string }) {
  return <section className="project-center-empty"><FolderKanban /><strong>{title}</strong><span>{detail}</span></section>;
}

function expectedDate(value?: string) {
  if (!value) return '待排期';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '待排期';
  return `${date.getMonth() + 1}月${date.getDate()}日预计完成`;
}

function shortId(value: string) {
  return value.length > 16 ? `${value.slice(0, 14)}…` : value;
}

function orderStatus(value: string) {
  return ({
    pending: '待开始',
    paid: '待开始',
    in_progress: '进行中',
    running: '进行中',
    pending_acceptance: '待验收',
    submitted: '待验收',
    completed: '已完成',
    disputed: '争议处理中',
    cancelled: '已取消',
  } as Record<string, string>)[value] || value;
}

function externalConnectionDependency(agents: AgentProfileRead[]) {
  return agents
    .filter((agent) => agent.metadata?.source_mode === 'external')
    .map((agent) => `${agent.id}:${String(agent.metadata.external_connection_id || '')}`)
    .sort()
    .join(',');
}
