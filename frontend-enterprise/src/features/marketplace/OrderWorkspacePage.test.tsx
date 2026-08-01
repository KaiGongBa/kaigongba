// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { OrderWorkspace } from './types';

let workspaceState = orderWorkspace('buyer');

vi.mock('./useMarketplaceOrganization', () => ({
  useMarketplaceOrganization: () => ({
    organizations: [{ id: 'org_current', name: '当前企业' }],
    selected: { id: 'org_current', name: '当前企业' },
    selectOrganization: vi.fn(),
    loading: false,
    error: '',
  }),
}));

vi.mock('./useMarketplaceResource', () => ({
  useMarketplaceResource: () => ({ data: workspaceState, loading: false, error: '', reload: vi.fn() }),
}));

vi.mock('./MarketplaceNotifications', () => ({ default: () => null }));
vi.mock('./OrderCollaborationPanels', () => ({
  OrderCommunicationPanel: () => <section>真实订单沟通面板</section>,
  OrderChangePanel: () => <section>真实变更与取消面板</section>,
}));
vi.mock('./OrderDisputePanel', () => ({ default: () => <section>真实平台争议处理面板</section> }));

import OrderWorkspacePage, { ORDER_WORKSPACE_TABS } from './OrderWorkspacePage';

afterEach(() => {
  cleanup();
  workspaceState = orderWorkspace('buyer');
});

describe('order workspace target UI', () => {
  it('keeps all eight panels and synchronizes selection with URL history', () => {
    renderPage('/enterprise/orders/order_real?from=projects');

    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(8);
    expect(tabs.map((tab) => tab.getAttribute('aria-label'))).toEqual(ORDER_WORKSPACE_TABS.map((tab) => tab.label));
    expect(screen.getByRole('tab', { name: '项目总览' }).getAttribute('aria-selected')).toBe('true');

    fireEvent.click(screen.getByRole('tab', { name: '材料' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_real?from=projects&tab=materials');
    expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe('order-tab-materials');

    fireEvent.click(screen.getByRole('tab', { name: '执行记录' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_real?from=projects&tab=events');
    fireEvent.click(screen.getByRole('button', { name: '浏览器返回' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_real?from=projects&tab=materials');
    expect(screen.getByRole('tab', { name: '材料' }).getAttribute('aria-selected')).toBe('true');
  });

  it('preserves real agreement, payment, deliverable and relationship-aware return routes', () => {
    workspaceState = orderWorkspace('provider', { withDeliverable: true });
    renderPage('/enterprise/orders/order_real?tab=deliverables');

    expect(screen.getByRole('button', { name: '查看合作协议' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '查看支付单' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '查看版本' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_real/deliverables/deliverable_real');

    cleanup();
    renderPage('/enterprise/orders/order_real');
    fireEvent.click(screen.getByRole('button', { name: '我的订单 / KGB-REAL-001' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders?perspective=provider');

    cleanup();
    renderPage('/enterprise/orders/order_real');
    fireEvent.click(screen.getByRole('button', { name: '查看合作协议' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/agreements/agreement_real');
  });

  it('shows only public execution data to buyers and keeps provider controls capability-driven', () => {
    workspaceState = orderWorkspace('buyer', { executionStatus: 'failed' });
    renderPage('/enterprise/orders/order_real?tab=execution');

    expect(screen.getByText('公开失败摘要')).toBeTruthy();
    expect(screen.queryByText('PRIVATE_PROMPT_SECRET')).toBeNull();
    expect(screen.queryByRole('button', { name: '重试节点' })).toBeNull();
    expect(screen.queryByRole('button', { name: '人工接管' })).toBeNull();

    cleanup();
    workspaceState = orderWorkspace('provider', { executionStatus: 'failed' });
    renderPage('/enterprise/orders/order_real?tab=execution');
    expect(screen.getByRole('button', { name: '重试节点' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '人工接管' })).toBeTruthy();
    expect(screen.queryByText('PRIVATE_PROMPT_SECRET')).toBeNull();
  });

  it('renders completed no-SOP and disputed failed-execution boundary states without local state overrides', () => {
    workspaceState = orderWorkspace('buyer', { orderStatus: 'completed', noExecution: true });
    renderPage('/enterprise/orders/order_real?tab=execution');
    expect(screen.getByText('订单结案前未启动 SOP')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '冻结并启动 SOP' })).toBeNull();

    cleanup();
    workspaceState = orderWorkspace('provider', { orderStatus: 'disputed', executionStatus: 'failed' });
    renderPage('/enterprise/orders/order_real?tab=execution');
    expect(screen.getByText('平台争议处理中')).toBeTruthy();
    expect(screen.getByText('失败')).toBeTruthy();
    expect(screen.getByRole('button', { name: '重试节点' })).toBeTruthy();
  });
});

function renderPage(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/enterprise/orders/:orderId" element={<OrderWorkspacePage />} />
      </Routes>
      <TestNavigation />
    </MemoryRouter>,
  );
}

function TestNavigation() {
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output data-testid="location">{location.pathname}{location.search}</output>
      <button type="button" onClick={() => navigate(-1)}>浏览器返回</button>
    </>
  );
}

function orderWorkspace(
  perspective: 'buyer' | 'provider',
  options: {
    withDeliverable?: boolean;
    orderStatus?: string;
    executionStatus?: string;
    noExecution?: boolean;
  } = {},
): OrderWorkspace {
  const milestone = {
    id: 'milestone_real',
    sequence: 1,
    name: '合同审查与交付',
    description: '按冻结范围交付',
    amount: '8800.00',
    durationDays: 5,
    status: options.orderStatus === 'completed' ? 'accepted' : 'in_progress',
    inputMaterials: ['采购合同'],
    deliverables: ['风险清单'],
    acceptanceCriteria: ['风险完整'],
  };
  const file = {
    id: 'file_real', orderId: 'order_real', milestoneId: milestone.id, purpose: 'deliverable' as const,
    filename: '风险清单.docx', contentType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    sizeBytes: 1024, sha256Digest: 'digest', uploadedByOrganizationId: 'org_provider', uploadedBy: '服务方',
    createdAt: '2026-08-01T10:00:00Z', downloadUrl: '/download/file_real',
  };
  const execution = options.noExecution ? undefined : {
    id: 'execution_real',
    orderId: 'order_real',
    milestoneId: milestone.id,
    status: options.executionStatus || 'running',
    progressPercent: options.executionStatus === 'failed' ? 40 : 60,
    currentNodeKey: 'review',
    agentProfileId: 'agent_real',
    skillPackageVersionId: 'skill_version_real',
    skillPackageDigest: 'skill-digest',
    sopSnapshot: {
      id: 'snapshot_real',
      sourceSkillId: 'skill_real',
      sourceSkillVersion: '2.3',
      definitionDigest: '1234567890abcdef1234567890abcdef',
      summary: { name: '合同审查 SOP', version: '2.3', nodeCount: 1, privacyNotice: '采购方只查看公开进度与结果摘要。' },
      frozenAt: '2026-08-01T09:00:00Z',
    },
    nodes: [{
      id: 'node_real', nodeKey: 'review', sequence: 1, attempt: 1, name: '人工复核',
      status: options.executionStatus === 'failed' ? 'failed' : 'running', executionMode: 'agent' as const,
      publicSummary: options.executionStatus === 'failed' ? '公开失败摘要' : '公开执行摘要',
      result: {}, internalDetail: { prompt: 'PRIVATE_PROMPT_SECRET' }, startedAt: '2026-08-01T09:10:00Z',
    }],
    events: [],
    capabilities: {
      canStart: false,
      canPause: true,
      canResume: false,
      canCancel: true,
      canRetry: true,
      canTakeover: true,
      canCompleteNode: false,
    },
    startedAt: '2026-08-01T09:00:00Z',
  };

  return {
    order: {
      id: 'order_real', code: 'KGB-REAL-001', agreementId: 'agreement_real', paymentOrderId: 'payment_real',
      requirementId: 'requirement_real', requirementCode: 'REQ-REAL-001', title: '软件采购合同审查',
      serviceId: 'service_real', serviceName: '合同审查服务', buyerOrganizationId: 'org_buyer', buyerName: '采购企业',
      providerOrganizationId: 'org_provider', providerName: '服务企业', currentRole: perspective,
      status: options.orderStatus || 'in_progress', paymentStatus: 'paid', settlementStatus: 'held_demo',
      totalAmount: '8800.00', heldAmount: '8800.00', currency: 'CNY', currentMilestoneSequence: 1,
      currentMilestoneName: milestone.name, milestoneCount: 1, progressPercent: options.orderStatus === 'completed' ? 100 : 60,
      expectedDeliveryAt: '2026-08-05T18:00:00Z', paidAt: '2026-08-01T08:00:00Z', createdAt: '2026-08-01T07:00:00Z',
      snapshot: { service: 'frozen' }, snapshotDigest: 'snapshot-digest', milestones: [milestone],
    },
    perspective,
    capabilities: {
      canStartMilestone: perspective === 'provider' && options.orderStatus !== 'completed',
      canRequestMaterial: perspective === 'provider' && options.orderStatus !== 'completed',
      canSubmitMaterial: perspective === 'buyer' && options.orderStatus !== 'completed',
      canSubmitDeliverable: perspective === 'provider' && options.orderStatus !== 'completed',
      canAccept: perspective === 'buyer' && options.orderStatus !== 'completed',
    },
    materialRequests: [],
    deliverables: options.withDeliverable ? [{
      id: 'deliverable_real', orderId: 'order_real', milestoneId: milestone.id, name: '合同风险清单', description: '风险说明',
      kind: 'file', status: 'submitted', currentVersionId: 'version_real', versions: [{
        id: 'version_real', version: 1, status: 'submitted', changeSummary: '首稿', file,
        submittedBy: '服务方', submittedAt: '2026-08-01T10:00:00Z',
      }], revisionRequests: [], createdAt: '2026-08-01T10:00:00Z', updatedAt: '2026-08-01T10:00:00Z',
    }] : [],
    events: [{
      id: 'event_real', milestoneId: milestone.id, eventType: 'order.created', partyRole: 'platform',
      actor: '系统', summary: '订单已创建', payload: {}, createdAt: '2026-08-01T07:00:00Z',
    }],
    execution: { perspective, current: execution, history: execution ? [execution] : [], canStart: perspective === 'provider' && !options.noExecution },
  };
}
