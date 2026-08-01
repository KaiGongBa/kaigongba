// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AgentProfileRead } from '@/types';
import type { OrderWorkspace } from '@/features/marketplace/types';

const workspaces = [
  projectWorkspace('order_alpha', '合同智能审查', 'agent_working', 'execution_alpha', 'running', 55),
];

const projectTestState = vi.hoisted(() => ({
  organization: 'ready' as 'ready' | 'none' | 'loading',
  resource: 'ready' as 'ready' | 'loading' | 'error' | 'empty',
}));

vi.mock('@/features/marketplace/useMarketplaceOrganization', () => ({
  useMarketplaceOrganization: () => ({
    organizations: projectTestState.organization === 'none' ? [] : [{ id: 'org_demo', name: '开工吧测试企业' }],
    selected: projectTestState.organization === 'ready' ? { id: 'org_demo', name: '开工吧测试企业' } : null,
    selectOrganization: vi.fn(),
    loading: projectTestState.organization === 'loading',
    error: '',
  }),
}));

vi.mock('@/features/marketplace/useMarketplaceResource', () => ({
  useMarketplaceResource: () => ({
    data: {
      workspaces: projectTestState.resource === 'empty' ? [] : workspaces,
      connectionHealthByAgentId: {},
    },
    loading: projectTestState.resource === 'loading',
    error: projectTestState.resource === 'error' ? '订单聚合接口无权访问' : '',
    reload: vi.fn(),
  }),
}));

vi.mock('@/features/marketplace/MarketplaceNotifications', () => ({
  default: () => null,
}));

vi.mock('@/components/EmployeeAvatar', () => ({
  default: ({ agent }: { agent: AgentProfileRead }) => <span data-testid={`avatar-${agent.id}`} />,
}));

import ProjectCenterPage from './ProjectCenterPage';

const agents: AgentProfileRead[] = [
  employee('agent_working', '合同审查专员', 'active'),
  employee('agent_idle', '财务助理', 'archived'),
];

afterEach(() => {
  cleanup();
  projectTestState.organization = 'ready';
  projectTestState.resource = 'ready';
});

describe('project center page', () => {
  it('switches real views, keeps URL filter state and opens a unique order route by keyboard', () => {
    renderProjectCenter('/workspace/gallery?source=qa');

    expect(screen.getByRole('heading', { name: '项目中心' })).toBeTruthy();
    expect(screen.getAllByText('合同审查专员').length).toBeGreaterThan(0);
    expect(screen.getAllByText('财务助理').length).toBeGreaterThan(0);
    expect(screen.getByText('已启用')).toBeTruthy();
    expect(screen.getAllByText('工作中').length).toBeGreaterThan(0);
    expect(screen.getByText('未启用')).toBeTruthy();
    expect(screen.getAllByText('空闲').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('tab', { name: '按项目查看' }));
    expect(screen.getByTestId('location').textContent).toContain('source=qa');
    expect(screen.getByTestId('location').textContent).toContain('view=projects');

    const project = screen.getByRole('button', { name: /打开项目：合同智能审查/ });
    project.focus();
    fireEvent.keyDown(project, { key: 'Enter' });
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_alpha');
  });

  it('opens an employee project page and preserves search/filter state when returning', () => {
    renderProjectCenter('/workspace/gallery?q=合同&work=working');

    fireEvent.click(screen.getByRole('button', { name: /查看员工项目：合同审查专员/ }));
    expect(screen.getByTestId('location').textContent).toContain('/workspace/projects/agents/agent_working');
    expect(screen.getByTestId('location').textContent).toContain('q=合同');
    expect(screen.getByRole('heading', { name: '合同审查专员' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '返回项目中心' }));
    expect(screen.getByTestId('location').textContent).toContain('/workspace/gallery');
    expect(screen.getByTestId('location').textContent).toContain('work=working');
  });

  it('renders loading, error, no-permission and empty states without inventing data', () => {
    projectTestState.resource = 'loading';
    const loading = renderProjectCenter('/workspace/gallery');
    expect(screen.getByText('正在加载市场数据…')).toBeTruthy();
    loading.unmount();

    projectTestState.resource = 'error';
    const error = renderProjectCenter('/workspace/gallery');
    expect(screen.getByRole('alert').textContent).toContain('订单聚合接口无权访问');
    error.unmount();

    projectTestState.resource = 'ready';
    projectTestState.organization = 'none';
    const denied = renderProjectCenter('/workspace/gallery');
    expect(screen.getByText('当前账号未加入可访问企业')).toBeTruthy();
    denied.unmount();

    projectTestState.organization = 'ready';
    projectTestState.resource = 'empty';
    renderProjectCenter('/workspace/gallery?view=projects');
    expect(screen.getByText('当前企业还没有项目')).toBeTruthy();
  });
});

function renderProjectCenter(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="*" element={<TestRoute />} />
      </Routes>
    </MemoryRouter>,
  );
}

function TestRoute() {
  const location = useLocation();
  const match = location.pathname.match(/^\/workspace\/projects\/agents\/([^/]+)$/);
  return (
    <>
      {location.pathname.startsWith('/workspace') && (
        <ProjectCenterPage agents={agents} selectedAgentId={match?.[1]} onOpenChat={vi.fn()} />
      )}
      <output data-testid="location">{location.pathname}{location.search}</output>
    </>
  );
}

function employee(id: string, name: string, status: string): AgentProfileRead {
  return {
    id,
    tenant_id: 'tenant_demo',
    name,
    description: `${name}负责真实业务交付。`,
    is_overall: false,
    status,
    metadata: { role_name: name },
    resources: [],
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  };
}

function projectWorkspace(
  id: string,
  title: string,
  agentId: string,
  executionId: string,
  status: string,
  progressPercent: number,
): OrderWorkspace {
  return {
    order: {
      id,
      code: `KGB-${id}`,
      agreementId: `agreement_${id}`,
      paymentOrderId: `payment_${id}`,
      requirementId: `requirement_${id}`,
      requirementCode: `REQ-${id}`,
      title,
      serviceId: `service_${id}`,
      serviceName: `${title}服务`,
      buyerOrganizationId: 'org_buyer',
      buyerName: '甲方企业',
      providerOrganizationId: 'org_demo',
      providerName: '开工吧测试企业',
      currentRole: 'provider',
      status: 'in_progress',
      paymentStatus: 'paid',
      settlementStatus: 'pending',
      totalAmount: '10000.00',
      heldAmount: '10000.00',
      currency: 'CNY',
      currentMilestoneSequence: 1,
      currentMilestoneName: '方案执行',
      milestoneCount: 2,
      progressPercent,
      expectedDeliveryAt: '2026-08-20T00:00:00Z',
      paidAt: '2026-08-01T00:00:00Z',
      createdAt: '2026-08-01T00:00:00Z',
      snapshot: {},
      snapshotDigest: 'digest',
      milestones: [],
    },
    perspective: 'provider',
    capabilities: {
      canStartMilestone: false,
      canRequestMaterial: false,
      canSubmitMaterial: false,
      canSubmitDeliverable: false,
      canAccept: false,
    },
    materialRequests: [],
    deliverables: [],
    events: [],
    execution: {
      perspective: 'provider',
      current: {
        id: executionId,
        orderId: id,
        milestoneId: 'milestone_1',
        status,
        progressPercent,
        currentNodeKey: 'node_review',
        agentProfileId: agentId,
        sopSnapshot: {
          id: 'sop_snapshot_1',
          definitionDigest: 'digest',
          summary: { name: '标准交付 SOP', version: 'v1', nodeCount: 3 },
          frozenAt: '2026-08-01T00:00:00Z',
        },
        nodes: [{ id: 'node_1', nodeKey: 'node_review', sequence: 1, attempt: 1, name: '智能审查', status, executionMode: 'agent', publicSummary: '正在审查', result: {} }],
        events: [],
        capabilities: { canStart: false, canPause: false, canResume: false, canCancel: false, canRetry: false, canTakeover: false, canCompleteNode: false },
        startedAt: '2026-08-01T00:00:00Z',
      },
      history: [],
      canStart: false,
    },
  };
}
