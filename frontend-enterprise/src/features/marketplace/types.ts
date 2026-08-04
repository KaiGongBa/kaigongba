export type MarketplaceVerification = 'verified' | 'official' | 'pending';

export type ServiceVersion = {
  version: string;
  releasedAt: string;
  current?: boolean;
  summary: string;
};

export type AiService = {
  id: string;
  name: string;
  category: string;
  provider: string;
  providerSlug: string;
  providerVerified: boolean;
  avatar: string;
  description: string;
  verified: boolean;
  online: boolean;
  price: number;
  priceUnit: string;
  averageMinutes: number;
  includedRevisions: number;
  rating: number | null;
  completedOrders: number;
  onTimeRate: number;
  responseMinutes: number;
  reviewCount?: number;
  performanceMetricsAvailable?: boolean;
  subscribed?: boolean;
  mine?: boolean;
  deliveryFormat: '文档' | '表格' | '报告' | '工作流';
  serviceScope: string[];
  exclusions: string[];
  deliverables: Array<{ name: string; format: string; size: string }>;
  process: Array<{ title: string; description: string }>;
  acceptanceCriteria: string[];
  versions: ServiceVersion[];
};

export type SkillPermission = {
  key: string;
  label: string;
  level: 'allow' | 'deny' | 'review';
  detail: string;
};

export type SkillSchemaField = {
  name: string;
  type: string;
  required: boolean;
  description: string;
  example: string;
};

export type MarketplaceSkill = {
  id: string;
  name: string;
  provider: string;
  providerSlug: string;
  description: string;
  category: string;
  version: string;
  verification: MarketplaceVerification;
  runtime: '平台托管' | '外部 Agent' | '远程 API';
  language: string;
  weight: '轻量' | '标准';
  price: number;
  priceUnit: string;
  installs: number;
  rating: number | null;
  reviewCount?: number;
  installCountVerified?: boolean;
  icon: 'document' | 'robot' | 'sheet' | 'search' | 'people' | 'tag';
  iconTone: 'violet' | 'blue' | 'green' | 'orange';
  permissionTags: string[];
  installed?: boolean;
  private?: boolean;
  mine?: boolean;
  scenarios: string[];
  inputs: SkillSchemaField[];
  outputs: SkillSchemaField[];
  permissions: SkillPermission[];
  networkPolicy: string;
  retentionPolicy: string;
  digest: string;
  auditedAt: string;
  auditor: string;
  versions: ServiceVersion[];
};

export type AiServiceQuery = {
  keyword?: string;
  category?: string;
  deliveryFormat?: string;
  price?: string;
  verified?: boolean;
  scope?: 'all' | 'subscribed' | 'mine';
  organizationId?: string;
};

export type SkillQuery = {
  keyword?: string;
  category?: string;
  runtime?: string;
  verification?: string;
  price?: string;
  permission?: string;
  scope?: 'all' | 'installed' | 'private' | 'mine';
  organizationId?: string;
};

export type MarketplaceList<T> = {
  items: T[];
  total: number;
};

export type MarketplaceInstallTarget = {
  id: string;
  name: string;
  description?: string;
};

export type MarketplaceSkillInstallation = {
  installed: true;
  installationId: string;
  status: string;
};

export type MarketplaceOrganization = {
  id: string;
  name: string;
  slug: string;
  role: string;
};

export type OrganizationMember = {
  id: string;
  userId: string;
  username: string;
  displayName: string;
  roles: string[];
  dataScope: Record<string, unknown>;
  status: string;
  joinedAt: string;
};

export type OrganizationInvitation = {
  id: string;
  inviteeEmail: string;
  roles: string[];
  dataScope: Record<string, unknown>;
  status: string;
  invitedBy: string;
  expiresAt: string;
  createdAt: string;
  acceptanceCode?: string;
};

export type ProviderApplication = {
  id: string;
  organizationId: string;
  status: string;
  profile: Record<string, unknown>;
  cases: Array<Record<string, unknown>>;
  reviewComment?: string;
  submittedAt?: string;
  reviewedAt?: string;
};

export type OrganizationDetail = {
  id: string;
  name: string;
  slug: string;
  legalName?: string;
  organizationType: string;
  unifiedCreditCode?: string;
  contactName?: string;
  contactPhone?: string;
  contactEmail?: string;
  verificationStatus: string;
  ownerUserId: string;
  currentUserRoles: string[];
  members: OrganizationMember[];
  invitations: OrganizationInvitation[];
  provider?: {
    id: string;
    displayName: string;
    verificationStatus: string;
    status: string;
  };
  providerApplication?: ProviderApplication;
};

export type PublishingItem = {
  id: string;
  itemType: 'ai_service' | 'skill';
  name: string;
  description: string;
  version: string;
  status: string;
  verificationStatus: string;
  visibility: string;
  price: number;
  priceUnit: string;
  usageCount: number;
  updatedAt: string;
  reviewComment?: string;
};

export type PublishingOverview = {
  providerStatus: string;
  items: PublishingItem[];
  counts: {
    published: number;
    pending_review: number;
    draft: number;
    attention: number;
  };
};

export type AIServiceDraftInput = {
  organization_id: string;
  agent_profile_id: string;
  name: string;
  category: string;
  description: string;
  version: string;
  visibility: 'public' | 'private';
  price: number;
  price_unit: string;
  average_minutes: number;
  included_revisions: number;
  delivery_format: AiService['deliveryFormat'];
  service_scope: string[];
  exclusions: string[];
  deliverables: Array<Record<string, string>>;
  acceptance_criteria: string[];
  cases: Array<Record<string, string>>;
  sop_version?: string;
  data_permissions: string[];
  change_summary: string;
};

export type SkillDraftInput = {
  organization_id: string;
  name: string;
  category: string;
  description: string;
  version: string;
  visibility: 'public' | 'private';
  runtime: MarketplaceSkill['runtime'];
  language: string;
  weight: MarketplaceSkill['weight'];
  price: number;
  price_unit: string;
  source_uri: string;
  package_digest: string;
  package_version_id?: string;
  entrypoint: string;
  input_schema: Array<Record<string, unknown>>;
  output_schema: Array<Record<string, unknown>>;
  permissions: Array<Record<string, unknown>>;
  network_policy: string;
  retention_policy: string;
  webhook_url?: string;
  change_summary: string;
};

export type SkillPackageVersion = {
  id: string;
  providerOrganizationId?: string;
  slug: string;
  name: string;
  version: string;
  digest: string;
  sourceUri: string;
  runtime: 'python' | 'node' | 'remote_api';
  entrypoint: string;
  status: string;
  manifest: Record<string, unknown>;
  permissions: Record<string, unknown>;
  storageProvider: string;
  originalFilename: string;
  sizeBytes: number;
  scanStatus: string;
  scanReport: Record<string, unknown>;
  riskLevel: 'low' | 'medium' | 'high';
  executionPolicy: 'metadata_only' | 'external' | 'hosted';
  immutable: boolean;
  reviewedAt?: string;
  createdAt: string;
};

export type PublicationDraft = {
  id: string;
  itemType: 'ai_service' | 'skill';
  status: string;
  versionId: string;
  version: string;
};

export type PublicationEditor = PublicationDraft & {
  data: Record<string, unknown>;
};

export type MarketplaceReview = {
  id: string;
  organizationId: string;
  organizationName: string;
  targetType: 'provider_application' | 'ai_service' | 'skill';
  targetId: string;
  targetName: string;
  versionId?: string;
  version: string;
  status: string;
  riskLevel: string;
  submittedBy: string;
  reviewer?: string;
  reviewerComment?: string;
  snapshot: Record<string, unknown>;
  submittedAt: string;
  reviewedAt?: string;
};

export type RequirementSummary = {
  id: string;
  code: string;
  title: string;
  category: string;
  status: string;
  buyerOrganizationId: string;
  buyerOrganizationName: string;
  budgetMinAmount: string;
  budgetMaxAmount: string;
  currency: string;
  desiredDeliveryAt?: string;
  quoteCount: number;
  invitationCount: number;
  updatedAt: string;
};

export type RequirementVersion = {
  id: string;
  version: number;
  status: string;
  description: string;
  deliverables: Array<Record<string, unknown>>;
  acceptanceCriteria: string[];
  attachments: Array<Record<string, unknown>>;
  changeSummary: string;
  snapshotDigest: string;
  createdBy: string;
  createdAt: string;
};

export type MatchRecommendation = {
  id: string;
  serviceId: string;
  serviceName: string;
  providerOrganizationId: string;
  providerName: string;
  score: number;
  reasons: string[];
  riskFlags: string[];
  status: string;
  invitationStatus?: string;
  generatedAt: string;
};

export type Clarification = {
  id: string;
  providerOrganizationId?: string;
  providerName?: string;
  askedByOrganizationId?: string;
  askedByName: string;
  askedByUser: string;
  question: string;
  responsibleParty: string;
  visibility: string;
  status: string;
  dueAt?: string;
  attachments: Array<Record<string, unknown>>;
  answer?: string;
  answerAttachments: Array<Record<string, unknown>>;
  answeredBy?: string;
  answeredAt?: string;
  createdAt: string;
};

export type RequirementDetail = RequirementSummary & {
  visibility: string;
  currentVersion: RequirementVersion;
  matches: MatchRecommendation[];
  clarifications: Clarification[];
  selectedQuoteId?: string;
  agreementId?: string;
  canEdit: boolean;
  canRunMatch: boolean;
  canQuote: boolean;
};

export type RequirementInput = {
  organization_id: string;
  title: string;
  category_id?: string;
  category: string;
  description: string;
  budget_min_amount: string;
  budget_max_amount: string;
  desired_delivery_at: string;
  visibility: 'public' | 'enterprise' | 'invited_providers';
  confidentiality_level: 'standard' | 'confidential' | 'highly_confidential';
  invite_limit: number;
  deliverables: Array<Record<string, unknown>>;
  acceptance_criteria: string[];
  attachments: Array<Record<string, unknown>>;
  change_summary?: string;
};

export type AssistantRequirementDraftFieldSource = {
  source: 'user_message' | 'user_choice' | 'user_edit' | 'attachment_extraction' | 'existing_record' | 'ai_expansion' | 'system_default';
  source_ref?: string | null;
  confirmed: boolean;
};

export type AssistantRequirementFormSeed = {
  organization_id?: string | null;
  title?: string | null;
  category_id?: string | null;
  category?: string | null;
  description?: string | null;
  budget_min_amount?: string | null;
  budget_max_amount?: string | null;
  desired_delivery_at?: string | null;
  visibility?: RequirementInput['visibility'] | null;
  confidentiality_level?: RequirementInput['confidentiality_level'] | null;
  invite_limit?: number | null;
  deliverables?: Array<Record<string, unknown>> | null;
  acceptance_criteria?: string[] | null;
  attachments?: Array<Record<string, unknown>> | null;
};

export type ServiceCategory = {
  id: string;
  name: string;
  parentId: string | null;
  description: string;
  aliases: string[];
  exampleTasks: string[];
  requiredFacets: string[];
  status: 'active' | 'inactive';
  version: number;
  sortOrder: number;
  createdAt: string;
  updatedAt: string;
};

export type AssistantRequirementDraftResponse = {
  protocol_version: '1.0';
  draft: {
    draft_id: string;
    draft_version: number;
    missing_fields: string[];
    [key: string]: unknown;
  };
  draft_meta: {
    row_version: number;
    status: string;
    updated_at: string;
  };
  field_sources: Record<string, AssistantRequirementDraftFieldSource>;
  form_seed: AssistantRequirementFormSeed;
  warnings: Array<{ field: string; code: string; message: string }>;
  handoff: {
    can_handoff: boolean;
    blockers: Array<{ field: string; code: string; message: string }>;
  };
};

export type AssistantRequirementHandoffInput = {
  protocol_version: '1.0';
  draft_version: number;
  transaction_requirement_id: string;
  requirement_write: RequirementInput;
  idempotency_key: string;
};

export type QuoteVersion = {
  id: string;
  version: number;
  status: string;
  totalAmount: string;
  currency: string;
  validUntil: string;
  deliveryDays: number;
  includedRevisions: number;
  serviceScope: string[];
  exclusions: string[];
  milestones: Array<{
    name: string;
    description: string;
    input_materials: string[];
    deliverables: string[];
    duration_days: number;
    acceptance_criteria: string[];
    amount: string;
  }>;
  acceptanceCriteria: string[];
  additionalTerms: string;
  generationMethod: string;
  generatorSkillId?: string;
  generatorSkillVersion?: string;
  generationBasis: Record<string, unknown>;
  createdBy: string;
  createdAt: string;
};

export type Quote = {
  id: string;
  requirementId: string;
  requirementCode: string;
  requirementTitle: string;
  requirementVersion: number;
  buyerOrganizationId: string;
  buyerName: string;
  providerOrganizationId: string;
  providerName: string;
  serviceId: string;
  serviceName: string;
  status: string;
  currentVersion: QuoteVersion;
  versions: QuoteVersion[];
  confirmedBy?: string;
  confirmedAt?: string;
  sentAt?: string;
  selectedAt?: string;
  createdAt: string;
  canEdit: boolean;
  canConfirm: boolean;
  canSelect: boolean;
};

export type ProviderWorkbench = {
  organizationId: string;
  providerStatus: string;
  pendingInvitations: RequirementSummary[];
  quoteDrafts: Quote[];
  sentQuotes: Quote[];
  counts: Record<string, number>;
};

export type AgreementConfirmation = {
  id: string;
  organizationId: string;
  organizationName: string;
  partyRole: 'buyer' | 'provider';
  confirmedBy: string;
  confirmationStatement: string;
  authMethod: string;
  confirmedAt: string;
};

export type Agreement = {
  id: string;
  code: string;
  requirementId: string;
  requirementCode: string;
  selectedQuoteId: string;
  buyerOrganizationId: string;
  buyerName: string;
  providerOrganizationId: string;
  providerName: string;
  version: number;
  title: string;
  status: string;
  snapshot: {
    transaction?: {
      mode?: 'demand_quote' | 'direct_service_checkout';
      quantity?: number;
      unit_price?: string;
    };
    requirement: Record<string, unknown>;
    quote: Record<string, unknown>;
    service: Record<string, unknown>;
    terms: Record<string, unknown>;
  };
  snapshotDigest: string;
  legalReviewStatus: string;
  legalReviewedAt?: string;
  confirmations: AgreementConfirmation[];
  currentPartyRole: 'buyer' | 'provider' | 'platform';
  currentOrganizationConfirmed: boolean;
  allPartiesConfirmed: boolean;
  activatedAt?: string;
  createdAt: string;
  paymentOrderId?: string;
  paymentStatus?: string;
  orderId?: string;
};

export type PaymentMilestone = {
  sequence: number;
  name: string;
  amount: string;
};

export type PaymentEvent = {
  id: string;
  eventType: string;
  resultStatus?: string;
  idempotencyKey: string;
  signatureValid: boolean;
  createdAt: string;
};

export type PaymentOrder = {
  id: string;
  code: string;
  agreementId: string;
  agreementCode: string;
  requirementId: string;
  requirementCode: string;
  buyerOrganizationId: string;
  buyerName: string;
  providerOrganizationId: string;
  providerName: string;
  serviceName: string;
  serviceVersion?: string;
  attempt: number;
  channel: 'demo' | string;
  status: string;
  amount: string;
  currency: string;
  idempotencyKey: string;
  callbackPreview: Record<string, unknown>;
  milestones: PaymentMilestone[];
  events: PaymentEvent[];
  orderId?: string;
  orderCode?: string;
  paidAt?: string;
  createdAt: string;
  currentPartyRole: 'buyer' | 'provider';
  canSimulate: boolean;
};

export type OrderMilestone = {
  id: string;
  sequence: number;
  name: string;
  description: string;
  amount: string;
  durationDays: number;
  status: string;
  inputMaterials: string[];
  deliverables: string[];
  acceptanceCriteria: string[];
};

export type TransactionOrder = {
  id: string;
  code: string;
  agreementId: string;
  paymentOrderId: string;
  requirementId: string;
  requirementCode: string;
  title: string;
  serviceId: string;
  serviceName: string;
  buyerOrganizationId: string;
  buyerName: string;
  providerOrganizationId: string;
  providerName: string;
  currentRole: 'buyer' | 'provider' | 'platform';
  status: string;
  paymentStatus: string;
  settlementStatus: string;
  totalAmount: string;
  heldAmount: string;
  currency: string;
  currentMilestoneSequence: number;
  currentMilestoneName: string;
  milestoneCount: number;
  progressPercent: number;
  expectedDeliveryAt?: string;
  paidAt: string;
  createdAt: string;
  snapshot?: Record<string, unknown>;
  snapshotDigest?: string;
  milestones?: OrderMilestone[];
};

export type OrderFile = {
  id: string;
  orderId: string;
  milestoneId?: string;
  purpose: 'material' | 'deliverable' | 'revision_evidence' | 'message' | 'dispute_evidence';
  filename: string;
  contentType: string;
  sizeBytes: number;
  sha256Digest: string;
  uploadedByOrganizationId: string;
  uploadedBy: string;
  createdAt: string;
  downloadUrl: string;
};

export type MaterialSubmission = {
  id: string;
  version: number;
  note: string;
  files: OrderFile[];
  submittedBy: string;
  createdAt: string;
};

export type MaterialRequest = {
  id: string;
  orderId: string;
  milestoneId: string;
  title: string;
  description: string;
  status: string;
  dueAt?: string;
  requestedBy: string;
  requestedFromOrganizationId: string;
  submissions: MaterialSubmission[];
  createdAt: string;
  updatedAt: string;
};

export type DeliverableVersion = {
  id: string;
  version: number;
  status: string;
  changeSummary: string;
  file: OrderFile;
  submittedBy: string;
  submittedAt: string;
};

export type RevisionRequest = {
  id: string;
  targetVersionId: string;
  reasonCategory: string;
  requirements: string;
  status: string;
  expectedResubmitAt?: string;
  requestedBy: string;
  resolvedByVersionId?: string;
  createdAt: string;
  resolvedAt?: string;
};

export type Deliverable = {
  id: string;
  orderId: string;
  milestoneId: string;
  name: string;
  description: string;
  kind: string;
  status: string;
  currentVersionId?: string;
  acceptedVersionId?: string;
  versions: DeliverableVersion[];
  revisionRequests: RevisionRequest[];
  createdAt: string;
  updatedAt: string;
};

export type OrderEvent = {
  id: string;
  milestoneId?: string;
  eventType: string;
  partyRole: 'buyer' | 'provider' | 'platform';
  organizationId?: string;
  actor: string;
  summary: string;
  payload: Record<string, unknown>;
  createdAt: string;
};

export type ExecutionNode = {
  id: string;
  nodeKey: string;
  sequence: number;
  attempt: number;
  name: string;
  status: string;
  executionMode: 'agent' | 'human';
  publicSummary: string;
  result: Record<string, unknown>;
  internalDetail?: Record<string, unknown>;
  claimedBy?: string;
  startedAt?: string;
  completedAt?: string;
};

export type ExecutionEvent = {
  eventId: string;
  sequence: number;
  eventType: string;
  publicSummary: string;
  payload: Record<string, unknown>;
  actorType: string;
  createdAt: string;
};

export type ExecutionRun = {
  id: string;
  orderId: string;
  milestoneId: string;
  status: string;
  progressPercent: number;
  currentNodeKey?: string;
  agentProfileId?: string;
  skillPackageVersionId?: string;
  skillPackageDigest?: string;
  sopSnapshot: {
    id: string;
    sourceSkillId?: string;
    sourceSkillVersion?: string;
    definitionDigest: string;
    summary: {
      name?: string;
      version?: string;
      nodeCount?: number;
      nodes?: Array<{ key: string; sequence: number; name: string; description: string }>;
      privacyNotice?: string;
    };
    frozenAt: string;
  };
  nodes: ExecutionNode[];
  events: ExecutionEvent[];
  capabilities: {
    canStart: boolean;
    canPause: boolean;
    canResume: boolean;
    canCancel: boolean;
    canRetry: boolean;
    canTakeover: boolean;
    canCompleteNode: boolean;
  };
  startedAt: string;
  pausedAt?: string;
  completedAt?: string;
};

export type OrderExecution = {
  perspective: 'buyer' | 'provider';
  current?: ExecutionRun;
  history: ExecutionRun[];
  canStart: boolean;
};

export type OrderWorkspace = {
  order: TransactionOrder & {
    snapshot: Record<string, unknown>;
    snapshotDigest: string;
    milestones: OrderMilestone[];
  };
  perspective: 'buyer' | 'provider';
  capabilities: {
    canStartMilestone: boolean;
    canRequestMaterial: boolean;
    canSubmitMaterial: boolean;
    canSubmitDeliverable: boolean;
    canAccept: boolean;
  };
  materialRequests: MaterialRequest[];
  deliverables: Deliverable[];
  events: OrderEvent[];
  execution: OrderExecution;
};

export type OrderMessage = {
  id: string;
  orderId: string;
  milestoneId?: string;
  messageType: 'text' | 'attachment' | 'system';
  content: string;
  attachments: Array<Pick<OrderFile, 'id' | 'filename' | 'contentType' | 'sizeBytes' | 'sha256Digest' | 'downloadUrl'>>;
  replyToMessageId?: string;
  senderOrganizationId?: string;
  senderName: string;
  senderRole: 'buyer' | 'provider' | 'platform' | 'system';
  mine: boolean;
  readByCurrentUser: boolean;
  createdAt: string;
};

export type OrderMessageList = {
  items: OrderMessage[];
  unreadCount: number;
};

export type OrderChange = {
  id: string;
  orderId: string;
  milestoneId?: string;
  version: number;
  status: string;
  title: string;
  reason: string;
  scopeChanges: string[];
  deliverableChanges: string[];
  amountDelta: string;
  durationDeltaDays: number;
  requestedByOrganizationId: string;
  requestedBy: string;
  counterpartyOrganizationId: string;
  counterpartyDecision?: string;
  counterpartyComment: string;
  financeStatus: string;
  canDecide: boolean;
  canApplyAdjustment: boolean;
  createdAt: string;
  updatedAt: string;
};

export type OrderCancellation = {
  id: string;
  orderId: string;
  status: string;
  reasonCategory: string;
  reason: string;
  requestedRefundAmount: string;
  requestedByOrganizationId: string;
  requestedBy: string;
  counterpartyOrganizationId: string;
  counterpartyDecision?: string;
  counterpartyComment: string;
  platformDecision?: string;
  platformComment: string;
  canDecide: boolean;
  canPlatformDecide: boolean;
  createdAt: string;
  updatedAt: string;
};

export type ActionItem = {
  id: string;
  organizationId: string;
  orderId?: string;
  category: string;
  targetType: string;
  targetId: string;
  title: string;
  summary: string;
  actingRole: string;
  riskLevel: 'normal' | 'medium' | 'high';
  status: string;
  route: string;
  payload: Record<string, unknown>;
  dueAt?: string;
  createdAt: string;
};

export type ActionItemList = {
  items: ActionItem[];
  counts: Record<string, number>;
};

export type CollaborationNotification = {
  id: string;
  organizationId: string;
  orderId?: string;
  notificationType: string;
  title: string;
  body: string;
  riskLevel: string;
  status: 'unread' | 'read';
  route: string;
  payload: Record<string, unknown>;
  dueAt?: string;
  readAt?: string;
  createdAt: string;
};

export type CollaborationNotificationList = {
  items: CollaborationNotification[];
  unreadCount: number;
};

export type CollaborationDashboardOrder = {
  id: string;
  code: string;
  title: string;
  serviceName: string;
  buyerName: string;
  providerName: string;
  status: string;
  paymentStatus: string;
  settlementStatus: string;
  totalAmount: string;
  currency: string;
  progressPercent: number;
  currentMilestone: string;
  executionStatus?: string;
  executionHealth: string;
  pendingActionCount: number;
  unreadMessageCount: number;
  riskLevel: 'normal' | 'medium' | 'high';
  expectedDeliveryAt?: string;
  updatedAt: string;
};

export type CollaborationDashboard = {
  perspective: 'buyer' | 'provider' | 'platform';
  counts: Record<string, number>;
  orders: CollaborationDashboardOrder[];
  recentActions: ActionItem[];
};

export type DisputeEvidence = {
  id: string;
  evidenceType: string;
  sourceType: string;
  sourceId?: string;
  title: string;
  description: string;
  fileId?: string;
  filename?: string;
  downloadUrl?: string;
  snapshotDigest: string;
  submittedByOrganizationId?: string;
  submittedBy: string;
  submittedRole: string;
  visibility: 'case_parties' | 'platform_only';
  isAutoArchived: boolean;
  evidenceRequestId?: string;
  createdAt: string;
};

export type DisputeEvidenceRequest = {
  id: string;
  requestedFromOrganizationId: string;
  requestedFrom: string;
  title: string;
  description: string;
  status: string;
  dueAt: string;
  createdAt: string;
};

export type DisputeTimelineEvent = {
  id: string;
  eventType: string;
  summary: string;
  actorRole: string;
  actor: string;
  visibility: string;
  payload: Record<string, unknown>;
  createdAt: string;
};

export type DisputeMediation = {
  id: string;
  version: number;
  proposal: string;
  proposedRefundAmount: string;
  proposedReleaseAmount: string;
  status: string;
  buyerResponse?: string;
  providerResponse?: string;
  createdBy: string;
  createdAt: string;
};

export type DisputeDecision = {
  id: string;
  version: number;
  status: string;
  outcome: string;
  refundAmount: string;
  releaseAmount: string;
  rationale: string;
  submittedBy: string;
  submittedAt: string;
  reviewedBy?: string;
  reviewComment: string;
  reviewedAt?: string;
  appealDueAt?: string;
  appliedAt?: string;
};

export type DisputeAppeal = {
  id: string;
  decisionId: string;
  organizationId: string;
  organizationName: string;
  reason: string;
  newEvidenceDescription: string;
  status: string;
  submittedBy: string;
  reviewedBy?: string;
  reviewComment: string;
  reviewedAt?: string;
  createdAt: string;
};

export type DisputeFundOperation = {
  id: string;
  operationType: string;
  amount: string;
  channel: string;
  status: string;
  operatedBy: string;
  createdAt: string;
};

export type DisputeCapabilities = {
  canRespond: boolean;
  canSubmitEvidence: boolean;
  canRespondMediation: boolean;
  canAppeal: boolean;
  canWaiveAppeal: boolean;
  canAssign: boolean;
  canRequestEvidence: boolean;
  canMediate: boolean;
  canSubmitDecision: boolean;
  canReviewDecision: boolean;
  canReviewAppeal: boolean;
  canFinalize: boolean;
};

export type DisputeSummary = {
  id: string;
  code: string;
  orderId: string;
  orderCode: string;
  orderTitle: string;
  buyerName: string;
  providerName: string;
  status: string;
  disputeType: string;
  disputedAmount: string;
  claim: string;
  requestedBy: string;
  respondentName: string;
  assignedTo?: string;
  evidenceDueAt: string;
  appealDueAt?: string;
  riskLevel: string;
  evidenceCount: number;
  closedAt?: string;
  createdAt: string;
  updatedAt: string;
};

export type DisputeDetail = DisputeSummary & {
  milestoneId?: string;
  statement: string;
  requestedByOrganizationId: string;
  respondentOrganizationId: string;
  responseStatement: string;
  respondedBy?: string;
  respondedAt?: string;
  previousOrderStatus: string;
  previousSettlementStatus: string;
  aiSummary: Record<string, unknown>;
  buyerAppealWaivedAt?: string;
  providerAppealWaivedAt?: string;
  evidence: DisputeEvidence[];
  evidenceRequests: DisputeEvidenceRequest[];
  timeline: DisputeTimelineEvent[];
  mediations: DisputeMediation[];
  decisions: DisputeDecision[];
  appeals: DisputeAppeal[];
  fundOperations: DisputeFundOperation[];
  capabilities: DisputeCapabilities;
};

export type DisputeOrderProjection = {
  activeCase?: DisputeSummary;
  history: DisputeSummary[];
  canCreate: boolean;
};

export type DisputePlatformDashboard = {
  counts: Record<string, number>;
  cases: DisputeSummary[];
};
