import { api } from '@/api/client';
import avatarAfterSales from '@/assets/staffdeck/staffdeck-avatar-after-sales.png';
import avatarCommerce from '@/assets/staffdeck/staffdeck-avatar-commerce.png';
import avatarDefault from '@/assets/staffdeck/staffdeck-avatar-default.png';
import avatarOps from '@/assets/staffdeck/staffdeck-avatar-ops.png';
import avatarQuality from '@/assets/staffdeck/staffdeck-avatar-quality.png';
import avatarService from '@/assets/staffdeck/staffdeck-avatar-service.png';
import { aiServiceFixtures, skillFixtures } from './fixtures';
import type {
  AIServiceDraftInput,
  ActionItemList,
  Deliverable,
  DisputeDetail,
  DisputeOrderProjection,
  DisputePlatformDashboard,
  Agreement,
  AiService,
  AiServiceQuery,
  Clarification,
  CollaborationDashboard,
  CollaborationNotificationList,
  MarketplaceInstallTarget,
  MarketplaceList,
  MarketplaceOrganization,
  MarketplaceReview,
  MarketplaceSkill,
  MarketplaceSkillInstallation,
  MaterialRequest,
  OrderCancellation,
  OrderChange,
  OrderFile,
  OrderMessage,
  OrderMessageList,
  ExecutionRun,
  OrderWorkspace,
  PaymentOrder,
  OrganizationDetail,
  OrganizationInvitation,
  ProviderApplication,
  PublicationDraft,
  PublicationEditor,
  PublishingOverview,
  ProviderWorkbench,
  Quote,
  RequirementDetail,
  RequirementInput,
  RequirementSummary,
  TransactionOrder,
  SkillDraftInput,
  SkillPackageVersion,
  SkillQuery,
} from './types';

const useFixtures =
  (import.meta.env.MODE === 'test' && import.meta.env.VITE_MARKETPLACE_FIXTURES !== 'false')
  || (import.meta.env.DEV && import.meta.env.VITE_MARKETPLACE_FIXTURES === 'true');

const installedSkillIds = new Set(
  skillFixtures.filter((skill) => skill.installed).map((skill) => skill.id),
);
const fixtureInstallTargets: MarketplaceInstallTarget[] = [
  { id: 'agent_demo_it_ops', name: 'IT运维工程师' },
  { id: 'agent_demo_contract_review', name: '合同审查专员' },
  { id: 'agent_demo_finance_report', name: '财务报表分析师' },
];
const serviceAvatars: Record<string, string> = {
  'asset://staffdeck/after-sales': avatarAfterSales,
  'asset://staffdeck/commerce': avatarCommerce,
  'asset://staffdeck/default': avatarDefault,
  'asset://staffdeck/ops': avatarOps,
  'asset://staffdeck/quality': avatarQuality,
  'asset://staffdeck/service': avatarService,
};

function includesKeyword(values: Array<string | undefined>, keyword?: string) {
  if (!keyword?.trim()) return true;
  const needle = keyword.trim().toLocaleLowerCase();
  return values.some((value) => value?.toLocaleLowerCase().includes(needle));
}

function priceMatches(price: number, filter?: string) {
  if (!filter || filter === 'all') return true;
  if (filter === 'free') return price === 0;
  if (filter === 'under-100') return price > 0 && price < 100;
  if (filter === '100-200') return price >= 100 && price <= 200;
  if (filter === 'over-200') return price > 200;
  return true;
}

export function filterAiServices(items: AiService[], query: AiServiceQuery) {
  return items.filter((item) => {
    if (!includesKeyword([item.name, item.category, item.provider, item.description], query.keyword)) return false;
    if (query.category && query.category !== 'all' && item.category !== query.category) return false;
    if (query.deliveryFormat && query.deliveryFormat !== 'all' && item.deliveryFormat !== query.deliveryFormat) return false;
    if (!priceMatches(item.price, query.price)) return false;
    if (query.verified && !item.verified) return false;
    if (query.scope === 'subscribed' && !item.subscribed) return false;
    if (query.scope === 'mine' && !item.mine) return false;
    return true;
  });
}

export function filterSkills(items: MarketplaceSkill[], query: SkillQuery) {
  return items
    .map((item) => ({ ...item, installed: item.installed || installedSkillIds.has(item.id) }))
    .filter((item) => {
      if (!includesKeyword([item.name, item.category, item.provider, item.description], query.keyword)) return false;
      if (query.category && query.category !== 'all' && item.category !== query.category) return false;
      if (query.runtime && query.runtime !== 'all' && item.runtime !== query.runtime) return false;
      if (query.verification && query.verification !== 'all' && item.verification !== query.verification) return false;
      if (!priceMatches(item.price, query.price)) return false;
      if (query.permission && query.permission !== 'all' && !item.permissionTags.includes(query.permission)) return false;
      if (query.scope === 'installed' && !item.installed) return false;
      if (query.scope === 'private' && !item.private) return false;
      if (query.scope === 'mine' && !item.mine) return false;
      return true;
    });
}

function queryString(values: Record<string, string | boolean | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== '' && value !== 'all') params.set(key, String(value));
  });
  const text = params.toString();
  return text ? `?${text}` : '';
}

async function fixtureDelay() {
  await new Promise((resolve) => window.setTimeout(resolve, 120));
}

export const marketplaceRepository = {
  async listAiServices(query: AiServiceQuery = {}): Promise<MarketplaceList<AiService>> {
    if (!useFixtures) {
      const result = await api.get<MarketplaceList<AiService>>(`/api/marketplace/ai-services${queryString(query)}`);
      return { ...result, items: result.items.map(hydrateServiceAssets) };
    }
    await fixtureDelay();
    const items = filterAiServices(aiServiceFixtures, query);
    return { items, total: items.length };
  },

  async getAiService(id: string, organizationId?: string): Promise<AiService> {
    if (!useFixtures) {
      const result = await api.get<AiService>(
        `/api/marketplace/ai-services/${encodeURIComponent(id)}${queryString({ organizationId })}`,
      );
      return hydrateServiceAssets(result);
    }
    await fixtureDelay();
    const item = aiServiceFixtures.find((service) => service.id === id);
    if (!item) throw new Error('服务不存在或已下架');
    return item;
  },

  async listSkills(query: SkillQuery = {}): Promise<MarketplaceList<MarketplaceSkill>> {
    if (!useFixtures) {
      return api.get<MarketplaceList<MarketplaceSkill>>(`/api/marketplace/skills${queryString(query)}`);
    }
    await fixtureDelay();
    const items = filterSkills(skillFixtures, query);
    return { items, total: items.length };
  },

  async getSkill(id: string, organizationId?: string): Promise<MarketplaceSkill> {
    if (!useFixtures) {
      return api.get<MarketplaceSkill>(
        `/api/marketplace/skills/${encodeURIComponent(id)}${queryString({ organizationId })}`,
      );
    }
    await fixtureDelay();
    const item = skillFixtures.find((skill) => skill.id === id);
    if (!item) throw new Error('Skill 不存在或已下架');
    return { ...item, installed: installedSkillIds.has(item.id) };
  },

  async listInstallTargets(organizationId: string): Promise<MarketplaceInstallTarget[]> {
    if (!organizationId) return [];
    if (!useFixtures) {
      return api.get<MarketplaceInstallTarget[]>(
        `/api/marketplace/install-targets${queryString({ organizationId })}`,
      );
    }
    await fixtureDelay();
    return fixtureInstallTargets;
  },

  async listOrganizations(): Promise<MarketplaceOrganization[]> {
    if (!useFixtures) {
      return api.get<MarketplaceOrganization[]>('/api/marketplace/organizations');
    }
    await fixtureDelay();
    return [
      { id: 'org_demo_buyer', name: '开工吧演示企业', slug: 'demo-buyer', role: 'owner' },
      { id: 'org_youfu', name: '优服智能', slug: 'youfu', role: 'owner' },
      { id: 'org_cloud_ops', name: '云维科技', slug: 'cloud-ops', role: 'owner' },
    ];
  },

  async getOrganization(organizationId: string): Promise<OrganizationDetail> {
    return api.get<OrganizationDetail>(
      `/api/marketplace/organizations/${encodeURIComponent(organizationId)}`,
    );
  },

  async updateOrganization(
    organizationId: string,
    input: Record<string, unknown>,
  ): Promise<OrganizationDetail> {
    return api.put<OrganizationDetail>(
      `/api/marketplace/organizations/${encodeURIComponent(organizationId)}`,
      input,
    );
  },

  async createInvitation(
    organizationId: string,
    input: {
      invitee_email: string;
      roles: string[];
      data_scope: Record<string, unknown>;
    },
  ): Promise<OrganizationInvitation> {
    return api.post<OrganizationInvitation>(
      `/api/marketplace/organizations/${encodeURIComponent(organizationId)}/invitations`,
      input,
    );
  },

  async cancelInvitation(organizationId: string, invitationId: string): Promise<void> {
    await api.delete(
      `/api/marketplace/organizations/${encodeURIComponent(organizationId)}/invitations/${encodeURIComponent(invitationId)}`,
    );
  },

  async updateOrganizationMember(
    organizationId: string,
    memberId: string,
    input: { roles: string[]; data_scope: Record<string, unknown> },
  ): Promise<OrganizationDetail> {
    return api.put<OrganizationDetail>(
      `/api/marketplace/organizations/${encodeURIComponent(organizationId)}/members/${encodeURIComponent(memberId)}`,
      input,
    );
  },

  async removeOrganizationMember(organizationId: string, memberId: string): Promise<void> {
    await api.delete(
      `/api/marketplace/organizations/${encodeURIComponent(organizationId)}/members/${encodeURIComponent(memberId)}`,
    );
  },

  async submitProviderApplication(
    organizationId: string,
    input: Record<string, unknown>,
  ): Promise<ProviderApplication> {
    return api.post<ProviderApplication>(
      `/api/marketplace/organizations/${encodeURIComponent(organizationId)}/provider-application`,
      input,
    );
  },

  async getPublishingOverview(organizationId: string): Promise<PublishingOverview> {
    return api.get<PublishingOverview>(
      `/api/marketplace/publishing${queryString({ organizationId })}`,
    );
  },

  async createAIServiceDraft(input: AIServiceDraftInput): Promise<PublicationDraft> {
    return api.post<PublicationDraft>('/api/marketplace/publishing/ai-services', input);
  },

  async getAIServiceEditor(
    serviceId: string,
    organizationId: string,
  ): Promise<PublicationEditor> {
    return api.get<PublicationEditor>(
      `/api/marketplace/publishing/ai-services/${encodeURIComponent(serviceId)}${queryString({ organizationId })}`,
    );
  },

  async updateAIServiceDraft(
    serviceId: string,
    input: AIServiceDraftInput,
  ): Promise<PublicationDraft> {
    return api.put<PublicationDraft>(
      `/api/marketplace/publishing/ai-services/${encodeURIComponent(serviceId)}`,
      input,
    );
  },

  async submitAIServiceReview(
    serviceId: string,
    organizationId: string,
  ): Promise<MarketplaceReview> {
    return api.post<MarketplaceReview>(
      `/api/marketplace/publishing/ai-services/${encodeURIComponent(serviceId)}/submit-review${queryString({ organizationId })}`,
    );
  },

  async createSkillDraft(input: SkillDraftInput): Promise<PublicationDraft> {
    return api.post<PublicationDraft>('/api/marketplace/publishing/skills', input);
  },

  async getSkillEditor(
    skillId: string,
    organizationId: string,
  ): Promise<PublicationEditor> {
    return api.get<PublicationEditor>(
      `/api/marketplace/publishing/skills/${encodeURIComponent(skillId)}${queryString({ organizationId })}`,
    );
  },

  async updateSkillDraft(
    skillId: string,
    input: SkillDraftInput,
  ): Promise<PublicationDraft> {
    return api.put<PublicationDraft>(
      `/api/marketplace/publishing/skills/${encodeURIComponent(skillId)}`,
      input,
    );
  },

  async submitSkillReview(
    skillId: string,
    organizationId: string,
  ): Promise<MarketplaceReview> {
    return api.post<MarketplaceReview>(
      `/api/marketplace/publishing/skills/${encodeURIComponent(skillId)}/submit-review${queryString({ organizationId })}`,
    );
  },

  async uploadSkillPackage(input: {
    organizationId: string;
    slug: string;
    name: string;
    version: string;
    runtime: 'python' | 'node';
    entrypoint: string;
    manifest: Record<string, unknown>;
    permissions: Record<string, unknown>;
    executionPolicy: 'external' | 'hosted';
    file: File;
  }): Promise<SkillPackageVersion> {
    const form = new FormData();
    form.append('organizationId', input.organizationId);
    form.append('slug', input.slug);
    form.append('name', input.name);
    form.append('version', input.version);
    form.append('runtime', input.runtime);
    form.append('entrypoint', input.entrypoint);
    form.append('manifest', JSON.stringify(input.manifest));
    form.append('permissions', JSON.stringify(input.permissions));
    form.append('executionPolicy', input.executionPolicy);
    form.append('file', input.file);
    return api.postForm<SkillPackageVersion>('/api/executions/skill-packages/upload', form);
  },

  async listSkillPackages(): Promise<SkillPackageVersion[]> {
    return api.get<SkillPackageVersion[]>('/api/executions/skill-packages');
  },

  async reviewSkillPackage(
    packageId: string,
    stage: 'security' | 'platform',
    decision: 'approved' | 'rejected',
    comment: string,
  ): Promise<SkillPackageVersion> {
    return api.post<SkillPackageVersion>(
      `/api/executions/skill-packages/${encodeURIComponent(packageId)}/review`,
      {
        review_stage: stage,
        decision,
        reviewer_comment: comment,
        security_checks: { reviewed_in_console: true },
      },
    );
  },

  async listMarketReviews(
    status?: string,
    targetType?: string,
  ): Promise<MarketplaceReview[]> {
    return api.get<MarketplaceReview[]>(
      `/api/marketplace/reviews${queryString({ status, targetType })}`,
    );
  },

  async decideMarketReview(
    reviewId: string,
    action: 'approve' | 'request_changes' | 'reject' | 'disable',
    comment: string,
  ): Promise<MarketplaceReview> {
    return api.post<MarketplaceReview>(
      `/api/marketplace/reviews/${encodeURIComponent(reviewId)}/decision`,
      { action, comment },
    );
  },

  async listRequirements(
    organizationId: string,
    perspective: 'buyer' | 'provider' = 'buyer',
  ): Promise<RequirementSummary[]> {
    return api.get<RequirementSummary[]>(
      `/api/transactions/requirements${queryString({ organizationId, perspective })}`,
    );
  },

  async createRequirement(input: RequirementInput): Promise<RequirementDetail> {
    return api.post<RequirementDetail>('/api/transactions/requirements', input);
  },

  async updateRequirement(
    requirementId: string,
    input: RequirementInput,
  ): Promise<RequirementDetail> {
    return api.put<RequirementDetail>(
      `/api/transactions/requirements/${encodeURIComponent(requirementId)}`,
      input,
    );
  },

  async publishRequirement(
    requirementId: string,
    organizationId: string,
  ): Promise<RequirementDetail> {
    return api.post<RequirementDetail>(
      `/api/transactions/requirements/${encodeURIComponent(requirementId)}/publish${queryString({ organizationId })}`,
    );
  },

  async getRequirement(
    requirementId: string,
    organizationId: string,
  ): Promise<RequirementDetail> {
    return api.get<RequirementDetail>(
      `/api/transactions/requirements/${encodeURIComponent(requirementId)}${queryString({ organizationId })}`,
    );
  },

  async runRequirementMatch(
    requirementId: string,
    organizationId: string,
    inviteLimit?: number,
  ): Promise<RequirementDetail> {
    return api.post<RequirementDetail>(
      `/api/transactions/requirements/${encodeURIComponent(requirementId)}/match`,
      { organization_id: organizationId, invite_limit: inviteLimit },
    );
  },

  async createClarification(
    requirementId: string,
    input: Record<string, unknown>,
  ): Promise<Clarification> {
    return api.post<Clarification>(
      `/api/transactions/requirements/${encodeURIComponent(requirementId)}/clarifications`,
      input,
    );
  },

  async answerClarification(
    clarificationId: string,
    organizationId: string,
    answer: string,
  ): Promise<Clarification> {
    return api.post<Clarification>(
      `/api/transactions/clarifications/${encodeURIComponent(clarificationId)}/answer`,
      { acting_organization_id: organizationId, answer, attachments: [] },
    );
  },

  async getProviderWorkbench(organizationId: string): Promise<ProviderWorkbench> {
    return api.get<ProviderWorkbench>(
      `/api/transactions/provider/workbench${queryString({ organizationId })}`,
    );
  },

  async generateQuote(
    requirementId: string,
    organizationId: string,
    serviceId: string,
    generatorSkillId?: string,
    generatorSkillVersion?: string,
  ): Promise<Quote> {
    return api.post<Quote>(
      `/api/transactions/requirements/${encodeURIComponent(requirementId)}/quotes/generate`,
      {
        organization_id: organizationId,
        service_id: serviceId,
        generator_skill_id: generatorSkillId,
        generator_skill_version: generatorSkillVersion,
      },
    );
  },

  async getQuote(quoteId: string, organizationId: string): Promise<Quote> {
    return api.get<Quote>(
      `/api/transactions/quotes/${encodeURIComponent(quoteId)}${queryString({ organizationId })}`,
    );
  },

  async updateQuote(
    quoteId: string,
    input: Record<string, unknown>,
  ): Promise<Quote> {
    return api.put<Quote>(
      `/api/transactions/quotes/${encodeURIComponent(quoteId)}`,
      input,
    );
  },

  async confirmAndSendQuote(quoteId: string, organizationId: string): Promise<Quote> {
    return api.post<Quote>(
      `/api/transactions/quotes/${encodeURIComponent(quoteId)}/confirm-send${queryString({ organizationId })}`,
    );
  },

  async withdrawQuote(quoteId: string, organizationId: string): Promise<Quote> {
    return api.post<Quote>(
      `/api/transactions/quotes/${encodeURIComponent(quoteId)}/withdraw${queryString({ organizationId })}`,
    );
  },

  async listRequirementQuotes(
    requirementId: string,
    organizationId: string,
  ): Promise<Quote[]> {
    return api.get<Quote[]>(
      `/api/transactions/requirements/${encodeURIComponent(requirementId)}/quotes${queryString({ organizationId })}`,
    );
  },

  async selectQuote(
    requirementId: string,
    organizationId: string,
    quoteId: string,
    buyerNote: string,
  ): Promise<Agreement> {
    return api.post<Agreement>(
      `/api/transactions/requirements/${encodeURIComponent(requirementId)}/select-quote`,
      {
        organization_id: organizationId,
        quote_id: quoteId,
        buyer_note: buyerNote,
      },
    );
  },

  async getAgreement(agreementId: string, organizationId: string): Promise<Agreement> {
    return api.get<Agreement>(
      `/api/transactions/agreements/${encodeURIComponent(agreementId)}${queryString({ organizationId })}`,
    );
  },

  async confirmAgreement(
    agreementId: string,
    organizationId: string,
    confirmationStatement: string,
  ): Promise<Agreement> {
    return api.post<Agreement>(
      `/api/transactions/agreements/${encodeURIComponent(agreementId)}/confirm`,
      {
        organization_id: organizationId,
        confirmation_statement: confirmationStatement,
      },
    );
  },

  async requestAgreementChange(
    agreementId: string,
    organizationId: string,
    reason: string,
  ): Promise<Agreement> {
    return api.post<Agreement>(
      `/api/transactions/agreements/${encodeURIComponent(agreementId)}/request-change`,
      { organization_id: organizationId, reason },
    );
  },

  async createPaymentOrder(
    agreementId: string,
    organizationId: string,
  ): Promise<PaymentOrder> {
    return api.post<PaymentOrder>(
      `/api/transactions/agreements/${encodeURIComponent(agreementId)}/payment-orders`,
      { organization_id: organizationId },
    );
  },

  async getPaymentOrder(
    paymentOrderId: string,
    organizationId: string,
  ): Promise<PaymentOrder> {
    return api.get<PaymentOrder>(
      `/api/transactions/payment-orders/${encodeURIComponent(paymentOrderId)}${queryString({ organizationId })}`,
    );
  },

  async simulateDemoPayment(
    paymentOrderId: string,
    input: {
      organization_id: string;
      result: 'success' | 'failed' | 'cancelled' | 'timeout';
      confirmation_code: string;
      callback_id: string;
      acknowledged_demo: boolean;
    },
  ): Promise<PaymentOrder> {
    return api.post<PaymentOrder>(
      `/api/transactions/payment-orders/${encodeURIComponent(paymentOrderId)}/demo-simulate`,
      input,
    );
  },

  async listOrders(
    organizationId: string,
    perspective: 'buyer' | 'provider' | 'all',
  ): Promise<TransactionOrder[]> {
    return api.get<TransactionOrder[]>(
      `/api/transactions/orders${queryString({ organizationId, perspective })}`,
    );
  },

  async getOrder(
    orderId: string,
    organizationId: string,
  ): Promise<TransactionOrder> {
    return api.get<TransactionOrder>(
      `/api/transactions/orders/${encodeURIComponent(orderId)}${queryString({ organizationId })}`,
    );
  },

  async getOrderWorkspace(orderId: string, organizationId: string): Promise<OrderWorkspace> {
    return api.get<OrderWorkspace>(
      `/api/transactions/orders/${encodeURIComponent(orderId)}/workspace${queryString({ organizationId })}`,
    );
  },

  async startMilestone(
    orderId: string,
    milestoneId: string,
    organizationId: string,
  ): Promise<OrderWorkspace> {
    return api.post<OrderWorkspace>(
      `/api/transactions/orders/${encodeURIComponent(orderId)}/milestones/${encodeURIComponent(milestoneId)}/actions`,
      { organization_id: organizationId, action: 'start' },
    );
  },

  async startExecution(
    orderId: string,
    organizationId: string,
    milestoneId: string,
    commandId: string,
    skillPackageVersionId?: string,
  ): Promise<ExecutionRun> {
    return api.post<ExecutionRun>(
      `/api/executions/orders/${encodeURIComponent(orderId)}/runs`,
      {
        organization_id: organizationId,
        milestone_id: milestoneId,
        command_id: commandId,
        skill_package_version_id: skillPackageVersionId,
      },
    );
  },

  async commandExecution(
    runId: string,
    organizationId: string,
    action: 'pause' | 'resume' | 'cancel' | 'retry_node' | 'takeover' | 'complete_node',
    commandId: string,
    nodeRunId?: string,
    summary?: string,
  ): Promise<ExecutionRun> {
    return api.post<ExecutionRun>(
      `/api/executions/runs/${encodeURIComponent(runId)}/commands`,
      {
        organization_id: organizationId,
        action,
        command_id: commandId,
        node_run_id: nodeRunId,
        summary: summary || '',
      },
    );
  },

  async uploadOrderFile(
    orderId: string,
    organizationId: string,
    milestoneId: string | undefined,
    purpose: OrderFile['purpose'],
    file: File,
  ): Promise<OrderFile> {
    const form = new FormData();
    form.append('organizationId', organizationId);
    if (milestoneId) form.append('milestoneId', milestoneId);
    form.append('purpose', purpose);
    form.append('file', file);
    return api.postForm<OrderFile>(
      `/api/transactions/orders/${encodeURIComponent(orderId)}/files`,
      form,
    );
  },

  async createMaterialRequest(
    orderId: string,
    organizationId: string,
    milestoneId: string,
    title: string,
    description: string,
    dueAt?: string,
  ): Promise<MaterialRequest> {
    return api.post<MaterialRequest>(
      `/api/transactions/orders/${encodeURIComponent(orderId)}/material-requests`,
      {
        organization_id: organizationId,
        milestone_id: milestoneId,
        title,
        description,
        due_at: dueAt || undefined,
      },
    );
  },

  async submitMaterial(
    materialRequestId: string,
    organizationId: string,
    fileIds: string[],
    note: string,
  ): Promise<MaterialRequest> {
    return api.post<MaterialRequest>(
      `/api/transactions/material-requests/${encodeURIComponent(materialRequestId)}/submit`,
      { organization_id: organizationId, file_ids: fileIds, note },
    );
  },

  async createDeliverable(
    orderId: string,
    organizationId: string,
    milestoneId: string,
    name: string,
    description: string,
  ): Promise<Deliverable> {
    return api.post<Deliverable>(
      `/api/transactions/orders/${encodeURIComponent(orderId)}/deliverables`,
      {
        organization_id: organizationId,
        milestone_id: milestoneId,
        name,
        description,
        kind: 'file',
      },
    );
  },

  async submitDeliverableVersion(
    deliverableId: string,
    organizationId: string,
    fileId: string,
    changeSummary: string,
  ): Promise<Deliverable> {
    return api.post<Deliverable>(
      `/api/transactions/deliverables/${encodeURIComponent(deliverableId)}/versions`,
      {
        organization_id: organizationId,
        file_id: fileId,
        change_summary: changeSummary,
      },
    );
  },

  async decideAcceptance(
    deliverableId: string,
    input: {
      organization_id: string;
      action: 'accept' | 'request_revision' | 'request_dispute';
      comments: string;
      idempotency_key: string;
      reason_category?: string;
      requested_changes?: string;
      expected_resubmit_at?: string;
    },
  ): Promise<Deliverable> {
    return api.post<Deliverable>(
      `/api/transactions/deliverables/${encodeURIComponent(deliverableId)}/acceptance`,
      input,
    );
  },

  async downloadOrderFile(fileId: string, organizationId: string): Promise<Blob> {
    return api.blob(
      `/api/transactions/files/${encodeURIComponent(fileId)}/download${queryString({ organizationId })}`,
    );
  },

  async getOrderDisputes(orderId: string, organizationId: string): Promise<DisputeOrderProjection> {
    return api.get<DisputeOrderProjection>(
      `/api/disputes/orders/${encodeURIComponent(orderId)}${queryString({ organizationId })}`,
    );
  },

  async createDispute(orderId: string, input: {
    organizationId: string;
    milestoneId?: string;
    disputeType: string;
    disputedAmount: string;
    claim: string;
    statement: string;
    evidenceDueDays: number;
  }): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/orders/${encodeURIComponent(orderId)}`, {
      organization_id: input.organizationId,
      milestone_id: input.milestoneId,
      dispute_type: input.disputeType,
      disputed_amount: input.disputedAmount,
      claim: input.claim,
      statement: input.statement,
      evidence_due_days: input.evidenceDueDays,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async getDispute(caseId: string, organizationId?: string): Promise<DisputeDetail> {
    return api.get<DisputeDetail>(
      `/api/disputes/cases/${encodeURIComponent(caseId)}${queryString({ organizationId })}`,
    );
  },

  async respondDispute(caseId: string, organizationId: string, statement: string): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/cases/${encodeURIComponent(caseId)}/response`, {
      organization_id: organizationId,
      statement,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async submitDisputeEvidence(caseId: string, input: {
    organizationId: string;
    title: string;
    description: string;
    fileId?: string;
    evidenceRequestId?: string;
    visibility: 'case_parties' | 'platform_only';
  }): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/cases/${encodeURIComponent(caseId)}/evidence`, {
      organization_id: input.organizationId,
      title: input.title,
      description: input.description,
      file_id: input.fileId,
      evidence_request_id: input.evidenceRequestId,
      visibility: input.visibility,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async getPlatformDisputes(): Promise<DisputePlatformDashboard> {
    return api.get<DisputePlatformDashboard>('/api/disputes/platform/dashboard');
  },

  async downloadPlatformDisputeFile(fileId: string): Promise<Blob> {
    return api.blob(`/api/disputes/platform/files/${encodeURIComponent(fileId)}/download`);
  },

  async assignDispute(caseId: string, assigneeUserId = 'self'): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/cases/${encodeURIComponent(caseId)}/assignment`, {
      assignee_user_id: assigneeUserId,
      comment: '平台处理人员领取案件',
      idempotency_key: crypto.randomUUID(),
    });
  },

  async generateDisputeSummary(caseId: string): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/cases/${encodeURIComponent(caseId)}/ai-summary`, {});
  },

  async requestDisputeEvidence(caseId: string, input: {
    organizationId: string;
    title: string;
    description: string;
    dueAt: string;
  }): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/cases/${encodeURIComponent(caseId)}/evidence-requests`, {
      requested_from_organization_id: input.organizationId,
      title: input.title,
      description: input.description,
      due_at: input.dueAt,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async createDisputeMediation(caseId: string, input: {
    proposal: string;
    refundAmount: string;
    releaseAmount: string;
  }): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/cases/${encodeURIComponent(caseId)}/mediations`, {
      proposal: input.proposal,
      proposed_refund_amount: input.refundAmount,
      proposed_release_amount: input.releaseAmount,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async respondDisputeMediation(
    mediationId: string,
    organizationId: string,
    response: 'accepted' | 'rejected',
    comment: string,
  ): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/mediations/${encodeURIComponent(mediationId)}/response`, {
      organization_id: organizationId,
      response,
      comment,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async createDisputeDecision(caseId: string, input: {
    outcome: string;
    refundAmount: string;
    releaseAmount: string;
    rationale: string;
    appealDays: number;
  }): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/cases/${encodeURIComponent(caseId)}/decisions`, {
      outcome: input.outcome,
      refund_amount: input.refundAmount,
      release_amount: input.releaseAmount,
      rationale: input.rationale,
      appeal_days: input.appealDays,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async reviewDisputeDecision(
    decisionId: string,
    decision: 'approved' | 'rejected',
    comment: string,
  ): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/decisions/${encodeURIComponent(decisionId)}/review`, {
      decision,
      comment,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async appealDispute(caseId: string, organizationId: string, reason: string, newEvidenceDescription: string): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/cases/${encodeURIComponent(caseId)}/appeals`, {
      organization_id: organizationId,
      reason,
      new_evidence_description: newEvidenceDescription,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async reviewDisputeAppeal(appealId: string, decision: 'accepted' | 'rejected', comment: string): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/appeals/${encodeURIComponent(appealId)}/review`, {
      decision,
      comment,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async waiveDisputeAppeal(caseId: string, organizationId: string): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/cases/${encodeURIComponent(caseId)}/appeal-waiver`, {
      organization_id: organizationId,
      acknowledged: true,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async finalizeDispute(caseId: string, comment: string): Promise<DisputeDetail> {
    return api.post<DisputeDetail>(`/api/disputes/cases/${encodeURIComponent(caseId)}/finalize`, {
      comment,
      idempotency_key: crypto.randomUUID(),
    });
  },

  async listOrderMessages(orderId: string, organizationId: string): Promise<OrderMessageList> {
    return api.get<OrderMessageList>(
      `/api/collaboration/orders/${encodeURIComponent(orderId)}/messages${queryString({ organizationId })}`,
    );
  },

  async createOrderMessage(
    orderId: string,
    organizationId: string,
    input: { content: string; attachmentFileIds: string[]; milestoneId?: string },
  ): Promise<OrderMessage> {
    return api.post<OrderMessage>(
      `/api/collaboration/orders/${encodeURIComponent(orderId)}/messages`,
      {
        organization_id: organizationId,
        milestone_id: input.milestoneId,
        content: input.content,
        attachment_file_ids: input.attachmentFileIds,
        idempotency_key: crypto.randomUUID(),
      },
    );
  },

  async markOrderMessagesRead(orderId: string, organizationId: string, messageId: string): Promise<OrderMessageList> {
    return api.post<OrderMessageList>(
      `/api/collaboration/orders/${encodeURIComponent(orderId)}/messages/read`,
      { organization_id: organizationId, message_id: messageId },
    );
  },

  async listOrderChanges(orderId: string, organizationId: string): Promise<OrderChange[]> {
    return api.get<OrderChange[]>(
      `/api/collaboration/orders/${encodeURIComponent(orderId)}/changes${queryString({ organizationId })}`,
    );
  },

  async createOrderChange(
    orderId: string,
    input: {
      organizationId: string;
      milestoneId?: string;
      title: string;
      reason: string;
      scopeChanges: string[];
      deliverableChanges: string[];
      amountDelta: string;
      durationDeltaDays: number;
    },
  ): Promise<OrderChange> {
    return api.post<OrderChange>(
      `/api/collaboration/orders/${encodeURIComponent(orderId)}/changes`,
      {
        organization_id: input.organizationId,
        milestone_id: input.milestoneId,
        title: input.title,
        reason: input.reason,
        scope_changes: input.scopeChanges,
        deliverable_changes: input.deliverableChanges,
        amount_delta: input.amountDelta,
        duration_delta_days: input.durationDeltaDays,
        idempotency_key: crypto.randomUUID(),
      },
    );
  },

  async decideOrderChange(changeId: string, organizationId: string, decision: 'approved' | 'rejected', comment: string): Promise<OrderChange> {
    return api.post<OrderChange>(
      `/api/collaboration/changes/${encodeURIComponent(changeId)}/decision`,
      { organization_id: organizationId, decision, comment, idempotency_key: crypto.randomUUID() },
    );
  },

  async applyOrderChangeDemoAdjustment(changeId: string, decision: 'apply_demo_adjustment' | 'reject', comment: string): Promise<OrderChange> {
    return api.post<OrderChange>(
      `/api/collaboration/changes/${encodeURIComponent(changeId)}/platform-adjustment`,
      { decision, comment, idempotency_key: crypto.randomUUID() },
    );
  },

  async listOrderCancellations(orderId: string, organizationId: string): Promise<OrderCancellation[]> {
    return api.get<OrderCancellation[]>(
      `/api/collaboration/orders/${encodeURIComponent(orderId)}/cancellations${queryString({ organizationId })}`,
    );
  },

  async createOrderCancellation(orderId: string, organizationId: string, reasonCategory: string, reason: string, requestedRefundAmount: string): Promise<OrderCancellation> {
    return api.post<OrderCancellation>(
      `/api/collaboration/orders/${encodeURIComponent(orderId)}/cancellations`,
      { organization_id: organizationId, reason_category: reasonCategory, reason, requested_refund_amount: requestedRefundAmount, idempotency_key: crypto.randomUUID() },
    );
  },

  async decideOrderCancellation(cancellationId: string, organizationId: string, decision: 'approved' | 'rejected', comment: string): Promise<OrderCancellation> {
    return api.post<OrderCancellation>(
      `/api/collaboration/cancellations/${encodeURIComponent(cancellationId)}/decision`,
      { organization_id: organizationId, decision, comment, idempotency_key: crypto.randomUUID() },
    );
  },

  async decidePlatformCancellation(cancellationId: string, decision: 'cancel_and_demo_refund' | 'reject', comment: string): Promise<OrderCancellation> {
    return api.post<OrderCancellation>(
      `/api/collaboration/cancellations/${encodeURIComponent(cancellationId)}/platform-decision`,
      { decision, comment, idempotency_key: crypto.randomUUID() },
    );
  },

  async listActionItems(organizationId: string): Promise<ActionItemList> {
    return api.get<ActionItemList>(
      `/api/collaboration/action-items${queryString({ organizationId })}`,
    );
  },

  async getCollaborationDashboard(organizationId: string, perspective: 'buyer' | 'provider'): Promise<CollaborationDashboard> {
    return api.get<CollaborationDashboard>(
      `/api/collaboration/dashboard${queryString({ organizationId, perspective })}`,
    );
  },

  async getPlatformDashboard(): Promise<CollaborationDashboard> {
    return api.get<CollaborationDashboard>('/api/collaboration/platform/dashboard');
  },

  async listCollaborationNotifications(organizationId?: string): Promise<CollaborationNotificationList> {
    return api.get<CollaborationNotificationList>(
      `/api/collaboration/notifications${queryString({ organizationId })}`,
    );
  },

  async markCollaborationNotificationsRead(notificationIds: string[] = [], markAll = false): Promise<CollaborationNotificationList> {
    return api.post<CollaborationNotificationList>(
      '/api/collaboration/notifications/read',
      { notification_ids: notificationIds, mark_all: markAll },
    );
  },

  async installSkill(
    id: string,
    agentId: string,
    version: string,
    organizationId: string,
  ): Promise<MarketplaceSkillInstallation> {
    if (!useFixtures) {
      return api.post<MarketplaceSkillInstallation>(`/api/marketplace/skills/${encodeURIComponent(id)}/install`, {
        agent_id: agentId,
        version,
        organization_id: organizationId,
      });
    }
    await fixtureDelay();
    installedSkillIds.add(id);
    return { installed: true, installationId: `fixture-${id}-${agentId}`, status: 'active' };
  },
};

function hydrateServiceAssets(service: AiService): AiService {
  return {
    ...service,
    avatar: serviceAvatars[service.avatar] || service.avatar || avatarDefault,
  };
}
