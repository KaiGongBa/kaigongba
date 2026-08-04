import { describe, expect, it } from 'vitest';

import type { AgentProfileRead } from '@/types';
import type { OrderWorkspace, TransactionOrder } from '@/features/marketplace/types';

import {
  buildProjectCenterModel,
  projectCenterSearch,
  projectCenterView,
} from './projectCenterModel';

const agents: AgentProfileRead[] = [
  agent('agent_working', '合同审查专员', 'active'),
  agent('agent_waiting', '招聘流程专员', 'active'),
  agent('agent_idle', '财务助理', 'archived'),
  { ...agent('agent_overall', '公司广场', 'active'), is_overall: true },
  { ...agent('agent_external', '外部数据分析师', 'active'), metadata: { source_mode: 'external', external_connection_id: 'connection_1' } },
];

const orderA = order('order_alpha', '合同智能审查', 'in_progress', 55);
const orderB = order('order_beta', '招聘流程搭建', 'paid', 20);
const orderUnassigned = order('order_unassigned', '未绑定员工项目', 'pending_acceptance', 90);

describe('project center model', () => {
  it('projects real agents, execution ids, order ids and separate connection/work states', () => {
    const result = buildProjectCenterModel(agents, [
      workspace(orderA, 'agent_working', 'execution_alpha', 'running'),
      {
        ...workspace(orderB, 'agent_waiting', 'execution_beta', 'waiting_confirmation'),
        materialRequests: [{ id: 'material_1', status: 'pending' } as OrderWorkspace['materialRequests'][number]],
      },
      workspace(orderUnassigned, '', 'execution_unassigned', 'running'),
    ], { agent_external: 'online' });

    expect(result.employees).toHaveLength(4);
    expect(result.employees.find((item) => item.agent.id === 'agent_working')).toMatchObject({
      connection: { key: 'enabled', label: '已启用' },
      work: { key: 'working', label: '工作中' },
    });
    expect(result.employees.find((item) => item.agent.id === 'agent_waiting')?.work.key).toBe('waiting');
    expect(result.employees.find((item) => item.agent.id === 'agent_idle')).toMatchObject({
      connection: { key: 'disabled', label: '未启用' },
      work: { key: 'idle', label: '空闲' },
    });
    expect(result.employees.find((item) => item.agent.id === 'agent_external')?.connection).toEqual({
      key: 'online',
      label: '在线',
    });
    expect(result.projects.find((item) => item.order.id === 'order_alpha')).toMatchObject({
      agentId: 'agent_working',
      executionId: 'execution_alpha',
    });
    expect(result.projects.find((item) => item.order.id === 'order_unassigned')).toMatchObject({
      agentId: undefined,
      executionId: 'execution_unassigned',
    });
  });

  it('uses a frozen service snapshot only as the fallback agent relation', () => {
    const fallback = workspace(orderA, '', '', 'pending');
    fallback.order.snapshot = { service: { agent_profile_id: 'agent_working' } };
    fallback.execution.current = undefined;

    const result = buildProjectCenterModel(agents, [fallback]);

    expect(result.projects[0].agentId).toBe('agent_working');
    expect(result.projects[0].executionId).toBeUndefined();
  });

  it('reads and writes project-center state without losing unrelated query parameters', () => {
    expect(projectCenterView(new URLSearchParams('view=projects'))).toBe('projects');
    expect(projectCenterView(new URLSearchParams('view=unknown'))).toBe('agents');

    const next = projectCenterSearch(
      new URLSearchParams('source=notification&view=agents&q=旧值'),
      { view: 'projects', query: '合同', work: 'working' },
    );

    expect(next.get('source')).toBe('notification');
    expect(next.get('view')).toBe('projects');
    expect(next.get('q')).toBe('合同');
    expect(next.get('work')).toBe('working');
  });
});

function agent(id: string, name: string, status: string): AgentProfileRead {
  return {
    id,
    tenant_id: 'tenant_demo',
    name,
    description: `${name}描述`,
    is_overall: false,
    status,
    metadata: {},
    resources: [],
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  };
}

function order(id: string, title: string, status: string, progressPercent: number): TransactionOrder {
  return {
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
    providerOrganizationId: 'org_provider',
    providerName: '乙方企业',
    currentRole: 'provider',
    status,
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
  };
}

function workspace(
  row: TransactionOrder,
  agentProfileId: string,
  executionId: string,
  executionStatus: string,
): OrderWorkspace {
  return {
    order: { ...row, snapshot: {}, snapshotDigest: 'digest', milestones: [] },
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
        orderId: row.id,
        milestoneId: 'milestone_1',
        status: executionStatus,
        progressPercent: row.progressPercent,
        currentNodeKey: 'node_review',
        agentProfileId: agentProfileId || undefined,
        sopSnapshot: {
          id: 'sop_snapshot_1',
          definitionDigest: 'digest',
          summary: { name: '标准交付 SOP', version: 'v1', nodeCount: 3 },
          frozenAt: '2026-08-01T00:00:00Z',
        },
        nodes: [{
          id: 'node_1',
          nodeKey: 'node_review',
          sequence: 1,
          attempt: 1,
          name: '智能审查',
          status: executionStatus,
          executionMode: 'agent',
          publicSummary: '正在审查',
          result: {},
        }],
        events: [],
        capabilities: {
          canStart: false,
          canPause: false,
          canResume: false,
          canCancel: false,
          canRetry: false,
          canTakeover: false,
          canCompleteNode: false,
        },
        startedAt: '2026-08-01T00:00:00Z',
      },
      history: [],
      canStart: false,
    },
  };
}
