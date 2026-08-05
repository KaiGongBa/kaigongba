export const PLATFORM_ASSISTANT_PROTOCOL_VERSION = '1.0' as const;
export const PLATFORM_ASSISTANT_PROTOCOL_V2_VERSION = '2.0' as const;

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export type PageEntityType =
  | 'organization'
  | 'agent'
  | 'requirement'
  | 'requirement_draft'
  | 'quote'
  | 'agreement'
  | 'order'
  | 'milestone'
  | 'deliverable'
  | 'dispute'
  | 'payment_order';

export type PageEntityRef = { type: PageEntityType; id: string };

export type PageUiState = {
  active_tab?: string;
  view?: string;
  perspective?: 'buyer' | 'provider' | 'internal';
  dirty?: boolean;
};

export type PageContext<RouteId extends string = string> = {
  page_instance_id: string;
  route_id: RouteId;
  pathname: string;
  entity_refs: PageEntityRef[];
  ui_state: PageUiState;
  context_version: number;
};

export type ResolvedContext = {
  page_instance_id: string;
  route_id: string;
  resolved_pathname: string;
  organization_id: string | null;
  entity_refs: Array<{ type: string; id: string }>;
  authorization: string;
  projection_refs: string[];
  context_version: number;
  row_version: number | null;
  stale: boolean;
};

export type PlatformAssistantTurnRequest = {
  protocol_version: typeof PLATFORM_ASSISTANT_PROTOCOL_VERSION;
  client_request_id: string;
  session_id: string | null;
  message: string;
  page_context: PageContext;
};

export type PlatformAssistantTurnRequestV2 = Omit<PlatformAssistantTurnRequest, 'protocol_version'> & {
  protocol_version: typeof PLATFORM_ASSISTANT_PROTOCOL_V2_VERSION;
};

export type BlockStatus =
  | 'pending'
  | 'submitted'
  | 'reviewing'
  | 'succeeded'
  | 'failed'
  | 'blocked'
  | 'superseded'
  | 'disabled';

type BlockCommon<Type extends string, Status extends BlockStatus> = {
  schema_version: '1.0';
  block_id: string;
  block_version: number;
  type: Type;
  status: Status;
  title: string;
  description: string;
};

export type BlockOption = {
  id: string;
  label: string;
  description?: string;
  recommended?: boolean;
  disabled?: boolean;
  disabled_reason?: string;
};

export type IntentConfirmationBlock = BlockCommon<
  'intent_confirmation',
  'pending' | 'submitted' | 'superseded' | 'disabled'
> & {
  options: BlockOption[];
  allow_free_text: boolean;
};

export type QuestionInputType =
  | 'single_choice'
  | 'multi_choice'
  | 'short_text'
  | 'long_text'
  | 'money_range'
  | 'date'
  | 'duration'
  | 'date_or_duration'
  | 'attachment'
  | 'entity_picker'
  | 'boolean';

export type StructuredQuestion = {
  id: string;
  label: string;
  input_type: QuestionInputType;
  required: boolean;
  help_text?: string;
  options?: BlockOption[];
  allow_custom?: boolean;
  allow_uncertain?: boolean;
  allow_ai_suggestion?: boolean;
  max_selections?: number;
  mutually_exclusive_option_ids?: string[];
  min_length?: number;
  max_length?: number;
  entity_type?: string;
};

export type QuestionGroupBlock = BlockCommon<
  'question_group',
  'pending' | 'submitted' | 'superseded' | 'disabled'
> & {
  submit_label: string;
  questions: StructuredQuestion[];
};

export type DraftFieldSource =
  | 'user_message'
  | 'user_choice'
  | 'user_edit'
  | 'attachment_extraction'
  | 'existing_record'
  | 'ai_expansion'
  | 'system_default';

export type DraftPreviewField = {
  key: string;
  label: string;
  value: JsonValue;
  source: DraftFieldSource;
  source_ref?: string | null;
  confidence?: number | null;
  editable: boolean;
  needs_confirmation: boolean;
};

export type BlockAction = {
  id: string;
  label: string;
  style: 'primary' | 'secondary' | 'text' | 'danger';
  disabled?: boolean;
  disabled_reason?: string;
};

export type DraftPreviewBlock = BlockCommon<
  'draft_preview',
  'reviewing' | 'submitted' | 'superseded' | 'disabled'
> & {
  draft_id: string;
  draft_version: number;
  summary: string;
  sections: Array<{ id: string; title: string; fields: DraftPreviewField[] }>;
  missing_fields: Array<{
    key: string;
    label: string;
    severity: 'blocking' | 'warning' | 'info';
    reason: string;
  }>;
  actions: BlockAction[];
};

export type ActionResultBlock = BlockCommon<
  'action_result',
  'succeeded' | 'failed' | 'blocked'
> & {
  action_id: string;
  result_status: 'succeeded' | 'partial' | 'failed' | 'blocked';
  result_code: string;
  message: string;
  resource_ref?: { type: string; id: string } | null;
  actions?: BlockAction[];
};

export type EntitySummaryBlock = BlockCommon<
  'entity_summary',
  'pending' | 'succeeded' | 'disabled'
> & {
  entity_ref: { type: string; id: string };
  fields: Array<{ key: string; label: string; value: JsonValue }>;
  allowed_action_ids: string[];
};

export type DeepLinkBlock = BlockCommon<'deep_link', 'pending' | 'disabled'> & {
  route_id: string;
  route_params: Record<string, string>;
  label: string;
};

export type NoticeBlock = BlockCommon<
  'notice',
  'pending' | 'succeeded' | 'failed' | 'blocked' | 'disabled'
> & {
  tone: 'info' | 'success' | 'warning' | 'error' | 'neutral';
  code: string;
  message: string;
  actions: BlockAction[];
};

export type StructuredBlock =
  | IntentConfirmationBlock
  | QuestionGroupBlock
  | DraftPreviewBlock
  | ActionResultBlock
  | EntitySummaryBlock
  | DeepLinkBlock
  | NoticeBlock;

type BlockCommonV2<Type extends string, Status extends BlockStatus> = {
  schema_version: '2.0';
  block_id: string;
  block_version: number;
  type: Type;
  status: Status;
  title: string;
  description: string;
};

export type AdaptiveQuestionGroupBlock = BlockCommonV2<
  'question_group',
  'pending' | 'submitted' | 'superseded' | 'disabled'
> & {
  submit_label: string;
  questions: StructuredQuestion[];
  allow_free_text: boolean;
};

export type InterviewFactStatus = 'candidate' | 'confirmed' | 'conflict' | 'superseded';
export type InterviewClassificationStatus = 'matched' | 'suggested' | 'needs_confirmation' | 'unmatched';

export type InterviewFact = {
  key: string;
  label: string;
  value: JsonValue;
  source: DraftFieldSource;
  status: InterviewFactStatus;
  confidence: number;
  hard_fact: boolean;
  editable: boolean;
  edit_action_id: string | null;
};

export type InterviewClassification = {
  category_id: string | null;
  name: string | null;
  confidence: number;
  status: InterviewClassificationStatus;
};

export type InterviewMissingInformation = {
  key: string;
  label: string;
  severity: 'blocking' | 'warning' | 'info';
  reason: string;
};

export type InterviewReadiness = {
  ready: boolean;
  blocking_fields: string[];
};

export type InterviewStateBlock = BlockCommonV2<
  'interview_state',
  'pending' | 'reviewing' | 'succeeded' | 'blocked' | 'superseded'
> & {
  facts: InterviewFact[];
  classification: InterviewClassification;
  missing_information: InterviewMissingInformation[];
  readiness: InterviewReadiness;
};

/**
 * Protocol v2 deliberately carries the seven frozen v1 blocks unchanged.
 * Only adaptive question groups and interview state use block schema 2.0.
 */
export type PlatformAssistantV2StructuredBlock =
  | StructuredBlock
  | AdaptiveQuestionGroupBlock
  | InterviewStateBlock;

export type StructuredBlockParseDiagnostic = Readonly<{
  code: 'UNSUPPORTED_BLOCK' | 'INVALID_BLOCK';
  block_index: number;
  schema_version: string | null;
  block_type: string | null;
  block_id: string | null;
}>;

export type StructuredBlockParseResult = Readonly<{
  block: PlatformAssistantV2StructuredBlock;
  diagnostic: StructuredBlockParseDiagnostic | null;
}>;

export type WorkflowState =
  | 'intent_pending'
  | 'intent_confirmed'
  | 'collecting'
  | 'drafting'
  | 'reviewing'
  | 'draft_saved'
  | 'handed_off'
  | 'completed'
  | 'paused'
  | 'failed'
  | 'cancelled';

export type PlatformAssistantWorkflow = {
  capability_id: string;
  capability_version: string;
  state: WorkflowState;
  row_version: number;
  progress: { completed_required: number; total_required: number };
};

export type PlatformAssistantTurnResponse = {
  protocol_version: typeof PLATFORM_ASSISTANT_PROTOCOL_VERSION;
  request_id: string;
  server_time: string;
  session_id: string;
  run_id: string | null;
  message_id: string;
  assistant_text: string;
  ui_blocks: StructuredBlock[];
  workflow: PlatformAssistantWorkflow | null;
  context: ResolvedContext;
  usage: { request_id: string | null };
};

export type PlatformAssistantTurnResponseV2 = Omit<
  PlatformAssistantTurnResponse,
  'protocol_version' | 'ui_blocks'
> & {
  protocol_version: typeof PLATFORM_ASSISTANT_PROTOCOL_V2_VERSION;
  ui_blocks: PlatformAssistantV2StructuredBlock[];
};

export type AnyPlatformAssistantTurnResponse =
  | PlatformAssistantTurnResponse
  | PlatformAssistantTurnResponseV2;

export type PlatformAssistantErrorCode =
  | 'INVALID_REQUEST'
  | 'CONTEXT_STALE'
  | 'BLOCK_VERSION_CONFLICT'
  | 'UNAUTHORIZED_CONTEXT'
  | 'RESOURCE_NOT_FOUND'
  | 'ACTION_FORBIDDEN'
  | 'AI_UNAVAILABLE'
  | 'AI_OUTPUT_INVALID'
  | 'AI_QUOTA_EXCEEDED'
  | 'IDEMPOTENCY_CONFLICT'
  | 'INTERNAL_ERROR';

export type PlatformAssistantErrorEnvelope = {
  protocol_version: typeof PLATFORM_ASSISTANT_PROTOCOL_VERSION;
  request_id: string;
  server_time: string;
  error: {
    code: PlatformAssistantErrorCode;
    message: string;
    retryable: boolean;
    field_errors?: Array<{ field: string; code: string; message: string }>;
  };
};

export type AnswerValue =
  | { option_ids: string[]; custom_text?: string }
  | { text: string }
  | { minimum: string; maximum: string; currency: 'CNY' }
  | { date: string; timezone: string }
  | { duration: number; unit: 'hour' | 'calendar_day' | 'business_day' | 'week'; timezone: string }
  | { attachment_ids: string[] }
  | { entity_refs: Array<{ type: string; id: string }> }
  | { boolean: boolean }
  | { uncertain: true };

export type AnswerSubmission = {
  protocol_version:
    | typeof PLATFORM_ASSISTANT_PROTOCOL_VERSION
    | typeof PLATFORM_ASSISTANT_PROTOCOL_V2_VERSION;
  session_id: string;
  run_id: string;
  block_id: string;
  block_version: number;
  idempotency_key: string;
  answers: Array<{ question_id: string; value: AnswerValue; client_updated_at: string }>;
};

const BLOCK_TYPES = new Set([
  'intent_confirmation', 'question_group', 'draft_preview', 'action_result',
  'entity_summary', 'deep_link', 'notice',
]);
const V2_BLOCK_TYPES = new Set(['question_group', 'interview_state']);
const QUESTION_TYPES = new Set<QuestionInputType>([
  'single_choice', 'multi_choice', 'short_text', 'long_text', 'money_range',
  'date', 'duration', 'date_or_duration', 'attachment', 'entity_picker', 'boolean',
]);
const WORKFLOW_STATES = new Set<WorkflowState>([
  'intent_pending', 'intent_confirmed', 'collecting', 'drafting', 'reviewing',
  'draft_saved', 'handed_off', 'completed', 'paused', 'failed', 'cancelled',
]);
const ERROR_CODES = new Set<PlatformAssistantErrorCode>([
  'INVALID_REQUEST', 'CONTEXT_STALE', 'BLOCK_VERSION_CONFLICT', 'UNAUTHORIZED_CONTEXT',
  'RESOURCE_NOT_FOUND', 'ACTION_FORBIDDEN', 'AI_UNAVAILABLE', 'AI_OUTPUT_INVALID',
  'AI_QUOTA_EXCEEDED', 'IDEMPOTENCY_CONFLICT', 'INTERNAL_ERROR',
]);

export function safeParseStructuredBlock(value: unknown, fallbackIndex = 0): StructuredBlock {
  if (!isRecord(value) || typeof value.type !== 'string' || !BLOCK_TYPES.has(value.type)) {
    return fallbackNotice('UNSUPPORTED_BLOCK', fallbackIndex);
  }
  const parsed = parseKnownV1Block(value);
  return parsed ?? fallbackNotice('INVALID_BLOCK', fallbackIndex);
}

export function safeParseStructuredBlockV2(
  value: unknown,
  fallbackIndex = 0,
): PlatformAssistantV2StructuredBlock {
  return parseStructuredBlockBySchema(value, fallbackIndex).block;
}

/**
 * Persisted runs may legitimately contain frozen v1 blocks and adaptive v2
 * blocks together. Dispatch from the block's own schema_version rather than
 * the response envelope so restore remains safe across protocol upgrades.
 */
export function parseStructuredBlockBySchema(
  value: unknown,
  fallbackIndex = 0,
): StructuredBlockParseResult {
  if (!isRecord(value)) {
    return blockParseFailure('UNSUPPORTED_BLOCK', value, fallbackIndex);
  }
  if (value.schema_version === '1.0') {
    if (typeof value.type !== 'string' || !BLOCK_TYPES.has(value.type)) {
      return blockParseFailure('UNSUPPORTED_BLOCK', value, fallbackIndex);
    }
    const block = parseKnownV1Block(value);
    return block
      ? { block, diagnostic: null }
      : blockParseFailure('INVALID_BLOCK', value, fallbackIndex);
  }
  if (value.schema_version === '2.0') {
    if (typeof value.type !== 'string' || !V2_BLOCK_TYPES.has(value.type)) {
      return blockParseFailure('UNSUPPORTED_BLOCK', value, fallbackIndex);
    }
    const parsed = value.type === 'question_group'
      ? parseAdaptiveQuestionGroup(value)
      : parseInterviewState(value);
    return parsed
      ? { block: parsed, diagnostic: null }
      : blockParseFailure('INVALID_BLOCK', value, fallbackIndex);
  }
  return blockParseFailure('UNSUPPORTED_BLOCK', value, fallbackIndex);
}

export function collectStructuredBlockDiagnostics(
  values: readonly unknown[],
): StructuredBlockParseDiagnostic[] {
  return values.flatMap((value, index) => {
    const result = parseStructuredBlockBySchema(value, index);
    return result.diagnostic ? [result.diagnostic] : [];
  });
}

function parseKnownV1Block(value: Record<string, unknown>): StructuredBlock | null {
  return value.type === 'intent_confirmation'
    ? parseIntentConfirmation(value)
    : value.type === 'question_group'
      ? parseQuestionGroup(value)
      : value.type === 'draft_preview'
        ? parseDraftPreview(value)
        : value.type === 'action_result'
          ? parseActionResult(value)
          : value.type === 'entity_summary'
            ? parseEntitySummary(value)
            : value.type === 'deep_link'
              ? parseDeepLink(value)
              : parseNotice(value);
}

export function safeParseTurnResponse(value: unknown): PlatformAssistantTurnResponse | null {
  if (!isRecord(value) || !hasOnlyKeys(value, [
    'protocol_version', 'request_id', 'server_time', 'session_id', 'run_id',
    'message_id', 'assistant_text', 'ui_blocks', 'workflow', 'context', 'usage',
  ])) return null;
  if (value.protocol_version !== '1.0'
    || !boundedString(value.request_id, 1)
    || !dateTimeString(value.server_time)
    || !boundedString(value.session_id, 1)
    || !(value.run_id === null || boundedString(value.run_id, 1))
    || !boundedString(value.message_id, 1)
    || !boundedString(value.assistant_text, 0, 20_000)
    || !Array.isArray(value.ui_blocks)) return null;
  const workflow = value.workflow === null ? null : parseWorkflow(value.workflow);
  const context = parseResolvedContext(value.context);
  const usage = parseUsage(value.usage);
  if ((value.workflow !== null && !workflow) || !context || !usage) return null;
  return {
    protocol_version: '1.0',
    request_id: value.request_id,
    server_time: value.server_time,
    session_id: value.session_id,
    run_id: value.run_id,
    message_id: value.message_id,
    assistant_text: value.assistant_text,
    ui_blocks: value.ui_blocks.map((block, index) => safeParseStructuredBlock(block, index)),
    workflow,
    context,
    usage,
  };
}

export function safeParseTurnResponseV2(value: unknown): PlatformAssistantTurnResponseV2 | null {
  if (!isRecord(value) || !hasOnlyKeys(value, [
    'protocol_version', 'request_id', 'server_time', 'session_id', 'run_id',
    'message_id', 'assistant_text', 'ui_blocks', 'workflow', 'context', 'usage',
  ])) return null;
  if (value.protocol_version !== '2.0'
    || !boundedString(value.request_id, 1)
    || !dateTimeString(value.server_time)
    || !boundedString(value.session_id, 1)
    || !(value.run_id === null || boundedString(value.run_id, 1))
    || !boundedString(value.message_id, 1)
    || !boundedString(value.assistant_text, 0, 20_000)
    || !Array.isArray(value.ui_blocks)) return null;
  const workflow = value.workflow === null ? null : parseWorkflow(value.workflow);
  const context = parseResolvedContext(value.context);
  const usage = parseUsage(value.usage);
  if ((value.workflow !== null && !workflow) || !context || !usage) return null;
  return {
    protocol_version: '2.0',
    request_id: value.request_id,
    server_time: value.server_time,
    session_id: value.session_id,
    run_id: value.run_id,
    message_id: value.message_id,
    assistant_text: value.assistant_text,
    ui_blocks: value.ui_blocks.map((block, index) => safeParseStructuredBlockV2(block, index)),
    workflow,
    context,
    usage,
  };
}

export function safeParseAnyTurnResponse(value: unknown): AnyPlatformAssistantTurnResponse | null {
  return safeParseTurnResponse(value) || safeParseTurnResponseV2(value);
}

export function safeParseErrorEnvelope(value: unknown): PlatformAssistantErrorEnvelope | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['protocol_version', 'request_id', 'server_time', 'error'])
    || value.protocol_version !== '1.0'
    || !boundedString(value.request_id, 1)
    || !dateTimeString(value.server_time)
    || !isRecord(value.error)
    || !hasOnlyKeys(value.error, ['code', 'message', 'retryable', 'field_errors'])
    || !ERROR_CODES.has(value.error.code as PlatformAssistantErrorCode)
    || !boundedString(value.error.message, 1, 1_000)
    || typeof value.error.retryable !== 'boolean') return null;
  const fieldErrors = value.error.field_errors === undefined
    ? undefined
    : parseFieldErrors(value.error.field_errors);
  if (value.error.field_errors !== undefined && !fieldErrors) return null;
  return {
    protocol_version: '1.0',
    request_id: value.request_id,
    server_time: value.server_time,
    error: {
      code: value.error.code as PlatformAssistantErrorCode,
      message: value.error.message,
      retryable: value.error.retryable,
      ...(fieldErrors ? { field_errors: fieldErrors } : {}),
    },
  };
}

function parseAdaptiveQuestionGroup(value: Record<string, unknown>): AdaptiveQuestionGroupBlock | null {
  const common = parseCommonV2(value, 'question_group', ['pending', 'submitted', 'superseded', 'disabled'], [
    'submit_label', 'questions', 'allow_free_text',
  ]);
  if (!common || !boundedString(value.submit_label, 1, 80)
    || !Array.isArray(value.questions) || value.questions.length < 1 || value.questions.length > 3
    || typeof value.allow_free_text !== 'boolean') return null;
  const questions = value.questions.map(parseQuestion);
  if (questions.some((question) => question === null)) return null;
  return {
    ...common,
    submit_label: value.submit_label,
    questions: questions as StructuredQuestion[],
    allow_free_text: value.allow_free_text,
  };
}

function parseInterviewState(value: Record<string, unknown>): InterviewStateBlock | null {
  const common = parseCommonV2(value, 'interview_state', [
    'pending', 'reviewing', 'succeeded', 'blocked', 'superseded',
  ], ['facts', 'classification', 'missing_information', 'readiness']);
  if (!common || !Array.isArray(value.facts) || value.facts.length > 100
    || !Array.isArray(value.missing_information) || value.missing_information.length > 50) return null;
  const facts = value.facts.map(parseInterviewFact);
  const classification = parseInterviewClassification(value.classification);
  const missingInformation = value.missing_information.map(parseInterviewMissingInformation);
  const readiness = parseInterviewReadiness(value.readiness);
  if (facts.some((fact) => fact === null) || !classification
    || missingInformation.some((item) => item === null) || !readiness) return null;
  return {
    ...common,
    facts: facts as InterviewFact[],
    classification,
    missing_information: missingInformation as InterviewMissingInformation[],
    readiness,
  };
}

function parseCommonV2<Type extends 'question_group' | 'interview_state', Status extends BlockStatus>(
  value: Record<string, unknown>,
  type: Type,
  statuses: readonly Status[],
  additionalKeys: readonly string[],
): BlockCommonV2<Type, Status> | null {
  if (!hasOnlyKeys(value, [
    'schema_version', 'block_id', 'block_version', 'type', 'status', 'title', 'description', ...additionalKeys,
  ])
    || value.schema_version !== '2.0' || value.type !== type
    || !/^block_[A-Za-z0-9_-]{4,120}$/.test(String(value.block_id))
    || !positiveInteger(value.block_version)
    || !statuses.includes(value.status as Status)
    || !boundedString(value.title, 1, 200)
    || !boundedString(value.description, 0, 2_000)) return null;
  return {
    schema_version: '2.0', block_id: value.block_id as string, block_version: value.block_version,
    type, status: value.status as Status, title: value.title, description: value.description,
  };
}

function parseInterviewFact(value: unknown): InterviewFact | null {
  const statuses: InterviewFactStatus[] = ['candidate', 'confirmed', 'conflict', 'superseded'];
  const sources: DraftFieldSource[] = [
    'user_message', 'user_choice', 'user_edit', 'attachment_extraction',
    'existing_record', 'ai_expansion', 'system_default',
  ];
  if (!isRecord(value) || !hasOnlyKeys(value, [
    'key', 'label', 'value', 'source', 'status', 'confidence', 'hard_fact', 'editable', 'edit_action_id',
  ]) || !identifier(value.key) || !boundedString(value.label, 1, 300)
    || !sources.includes(value.source as DraftFieldSource)
    || !statuses.includes(value.status as InterviewFactStatus)
    || !confidence(value.confidence)
    || typeof value.hard_fact !== 'boolean' || typeof value.editable !== 'boolean'
    || !(value.edit_action_id === null || identifier(value.edit_action_id))) return null;
  const factValue = sanitizeJsonValue(value.value);
  if (factValue === undefined) return null;
  return {
    key: value.key,
    label: value.label,
    value: factValue,
    source: value.source as DraftFieldSource,
    status: value.status as InterviewFactStatus,
    confidence: value.confidence,
    hard_fact: value.hard_fact,
    editable: value.editable,
    edit_action_id: value.edit_action_id,
  };
}

function parseInterviewClassification(value: unknown): InterviewClassification | null {
  const statuses: InterviewClassificationStatus[] = ['matched', 'suggested', 'needs_confirmation', 'unmatched'];
  const categoryId = isRecord(value) ? (value.category_id ?? null) : null;
  const categoryName = isRecord(value) ? (value.name ?? null) : null;
  if (!isRecord(value) || !hasOnlyKeys(value, ['category_id', 'name', 'confidence', 'status'])
    || !(categoryId === null || boundedString(categoryId, 1, 160))
    || !(categoryName === null || boundedString(categoryName, 1, 300))
    || !confidence(value.confidence)
    || !statuses.includes(value.status as InterviewClassificationStatus)) return null;
  if ((value.status === 'matched' || value.status === 'suggested')
    && (categoryId === null || categoryName === null)) return null;
  return {
    category_id: categoryId,
    name: categoryName,
    confidence: value.confidence,
    status: value.status as InterviewClassificationStatus,
  };
}

function parseInterviewMissingInformation(value: unknown): InterviewMissingInformation | null {
  const severities = ['blocking', 'warning', 'info'] as const;
  if (!isRecord(value) || !hasOnlyKeys(value, ['key', 'label', 'severity', 'reason'])
    || !identifier(value.key) || !boundedString(value.label, 1, 300)
    || !severities.includes(value.severity as never) || !boundedString(value.reason, 1, 1_000)) return null;
  return {
    key: value.key,
    label: value.label,
    severity: value.severity as InterviewMissingInformation['severity'],
    reason: value.reason,
  };
}

function parseInterviewReadiness(value: unknown): InterviewReadiness | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['ready', 'blocking_fields'])
    || typeof value.ready !== 'boolean' || !stringArray(value.blocking_fields, true)) return null;
  if ((value.ready && value.blocking_fields.length > 0)
    || (!value.ready && value.blocking_fields.length === 0)) return null;
  return { ready: value.ready, blocking_fields: value.blocking_fields };
}

function parseIntentConfirmation(value: Record<string, unknown>): IntentConfirmationBlock | null {
  const common = parseCommon(value, 'intent_confirmation', ['pending', 'submitted', 'superseded', 'disabled'], ['options', 'allow_free_text']);
  if (!common || !Array.isArray(value.options) || value.options.length < 2 || value.options.length > 5
    || typeof value.allow_free_text !== 'boolean') return null;
  const options = value.options.map(parseOption);
  if (options.some((option) => option === null)) return null;
  return { ...common, options: options as BlockOption[], allow_free_text: value.allow_free_text };
}

function parseQuestionGroup(value: Record<string, unknown>): QuestionGroupBlock | null {
  const common = parseCommon(value, 'question_group', ['pending', 'submitted', 'superseded', 'disabled'], ['submit_label', 'questions']);
  if (!common || !boundedString(value.submit_label, 1, 80)
    || !Array.isArray(value.questions) || value.questions.length < 1 || value.questions.length > 4) return null;
  const questions = value.questions.map(parseQuestion);
  if (questions.some((question) => question === null)) return null;
  return { ...common, submit_label: value.submit_label, questions: questions as StructuredQuestion[] };
}

function parseDraftPreview(value: Record<string, unknown>): DraftPreviewBlock | null {
  const common = parseCommon(value, 'draft_preview', ['reviewing', 'submitted', 'superseded', 'disabled'], [
    'draft_id', 'draft_version', 'summary', 'sections', 'missing_fields', 'actions',
  ]);
  if (!common || !boundedString(value.draft_id, 1) || !positiveInteger(value.draft_version)
    || !boundedString(value.summary, 0, 5_000)
    || !Array.isArray(value.sections) || value.sections.length < 1
    || !Array.isArray(value.missing_fields) || !Array.isArray(value.actions) || value.actions.length < 1) return null;
  const sections = value.sections.map(parseDraftSection);
  const missingFields = value.missing_fields.map(parseMissingField);
  const actions = value.actions.map(parseAction);
  if ([...sections, ...missingFields, ...actions].some((item) => item === null)) return null;
  return {
    ...common,
    draft_id: value.draft_id,
    draft_version: value.draft_version,
    summary: value.summary,
    sections: sections as DraftPreviewBlock['sections'],
    missing_fields: missingFields as DraftPreviewBlock['missing_fields'],
    actions: actions as BlockAction[],
  };
}

function parseActionResult(value: Record<string, unknown>): ActionResultBlock | null {
  const common = parseCommon(value, 'action_result', ['succeeded', 'failed', 'blocked'], [
    'action_id', 'result_status', 'result_code', 'message', 'resource_ref', 'actions',
  ]);
  const resultStatuses = ['succeeded', 'partial', 'failed', 'blocked'] as const;
  if (!common || !identifier(value.action_id) || !resultStatuses.includes(value.result_status as never)
    || !boundedString(value.result_code, 1) || !boundedString(value.message, 1)) return null;
  const resourceRef = value.resource_ref === undefined || value.resource_ref === null
    ? value.resource_ref
    : parseSimpleEntityRef(value.resource_ref);
  const actions = value.actions === undefined ? undefined : parseActions(value.actions);
  if (value.resource_ref !== undefined && value.resource_ref !== null && !resourceRef) return null;
  if (value.actions !== undefined && !actions) return null;
  return {
    ...common,
    action_id: value.action_id,
    result_status: value.result_status as ActionResultBlock['result_status'],
    result_code: value.result_code,
    message: value.message,
    ...(value.resource_ref !== undefined ? { resource_ref: resourceRef } : {}),
    ...(actions ? { actions } : {}),
  };
}

function parseEntitySummary(value: Record<string, unknown>): EntitySummaryBlock | null {
  const common = parseCommon(value, 'entity_summary', ['pending', 'succeeded', 'disabled'], [
    'entity_ref', 'fields', 'allowed_action_ids',
  ]);
  const entityRef = parseSimpleEntityRef(value.entity_ref);
  if (!common || !entityRef || !Array.isArray(value.fields) || !stringArray(value.allowed_action_ids, true)) return null;
  const fields = value.fields.map(parseSummaryField);
  if (fields.some((field) => field === null)) return null;
  return { ...common, entity_ref: entityRef, fields: fields as EntitySummaryBlock['fields'], allowed_action_ids: value.allowed_action_ids };
}

function parseDeepLink(value: Record<string, unknown>): DeepLinkBlock | null {
  const common = parseCommon(value, 'deep_link', ['pending', 'disabled'], ['route_id', 'route_params', 'label']);
  if (!common || !boundedString(value.route_id, 1) || !isRecord(value.route_params)
    || Object.keys(value.route_params).length > 8 || !boundedString(value.label, 1)) return null;
  const routeParams: Record<string, string> = {};
  for (const [key, item] of Object.entries(value.route_params)) {
    if (!/^[a-z][A-Za-z0-9_]{0,63}$/.test(key) || !boundedString(item, 1, 160)) return null;
    routeParams[key] = item;
  }
  return { ...common, route_id: value.route_id, route_params: routeParams, label: value.label };
}

function parseNotice(value: Record<string, unknown>): NoticeBlock | null {
  const common = parseCommon(value, 'notice', ['pending', 'succeeded', 'failed', 'blocked', 'disabled'], [
    'tone', 'code', 'message', 'actions',
  ]);
  const tones = ['info', 'success', 'warning', 'error', 'neutral'] as const;
  const actions = parseActions(value.actions);
  if (!common || !tones.includes(value.tone as never) || !boundedString(value.code, 1)
    || !boundedString(value.message, 1, 5_000) || !actions) return null;
  return { ...common, tone: value.tone as NoticeBlock['tone'], code: value.code, message: value.message, actions };
}

function parseCommon<Type extends StructuredBlock['type'], Status extends BlockStatus>(
  value: Record<string, unknown>,
  type: Type,
  statuses: readonly Status[],
  additionalKeys: readonly string[],
): BlockCommon<Type, Status> | null {
  if (!hasOnlyKeys(value, [
    'schema_version', 'block_id', 'block_version', 'type', 'status', 'title', 'description', ...additionalKeys,
  ])
    || value.schema_version !== '1.0' || value.type !== type
    || !/^block_[A-Za-z0-9_-]{4,120}$/.test(String(value.block_id))
    || !positiveInteger(value.block_version)
    || !statuses.includes(value.status as Status)
    || !boundedString(value.title, 1, 200)
    || !boundedString(value.description, 0, 2_000)) return null;
  return {
    schema_version: '1.0', block_id: value.block_id as string, block_version: value.block_version,
    type, status: value.status as Status, title: value.title, description: value.description,
  };
}

function parseOption(value: unknown): BlockOption | null {
  if (!isRecord(value) || !hasOnlyKeys(value, [
    'id', 'label', 'description', 'recommended', 'disabled', 'disabled_reason',
  ]) || !boundedString(value.id, 1, 120) || !boundedString(value.label, 1, 200)
    || !optionalString(value.description, 500) || !optionalBoolean(value.recommended)
    || !optionalBoolean(value.disabled) || !optionalString(value.disabled_reason, 500)) return null;
  return {
    id: value.id, label: value.label,
    ...(value.description !== undefined ? { description: value.description } : {}),
    ...(value.recommended !== undefined ? { recommended: value.recommended } : {}),
    ...(value.disabled !== undefined ? { disabled: value.disabled } : {}),
    ...(value.disabled_reason !== undefined ? { disabled_reason: value.disabled_reason } : {}),
  };
}

function parseQuestion(value: unknown): StructuredQuestion | null {
  if (!isRecord(value) || !hasOnlyKeys(value, [
    'id', 'label', 'help_text', 'input_type', 'required', 'options', 'allow_custom',
    'allow_uncertain', 'allow_ai_suggestion', 'max_selections',
    'mutually_exclusive_option_ids', 'min_length', 'max_length', 'entity_type',
  ]) || !identifier(value.id) || !boundedString(value.label, 1, 300)
    || !QUESTION_TYPES.has(value.input_type as QuestionInputType) || typeof value.required !== 'boolean'
    || !optionalString(value.help_text, 1_000) || !optionalBoolean(value.allow_custom)
    || !optionalBoolean(value.allow_uncertain) || !optionalBoolean(value.allow_ai_suggestion)
    || !optionalPositiveInteger(value.max_selections) || !optionalNonNegativeInteger(value.min_length)
    || !optionalPositiveInteger(value.max_length) || !optionalString(value.entity_type)) return null;
  const options = value.options === undefined ? undefined : parseOptions(value.options);
  if (value.options !== undefined && !options) return null;
  if (value.mutually_exclusive_option_ids !== undefined && !stringArray(value.mutually_exclusive_option_ids, true)) return null;
  return {
    id: value.id, label: value.label, input_type: value.input_type as QuestionInputType, required: value.required,
    ...(value.help_text !== undefined ? { help_text: value.help_text } : {}),
    ...(options ? { options } : {}),
    ...(value.allow_custom !== undefined ? { allow_custom: value.allow_custom } : {}),
    ...(value.allow_uncertain !== undefined ? { allow_uncertain: value.allow_uncertain } : {}),
    ...(value.allow_ai_suggestion !== undefined ? { allow_ai_suggestion: value.allow_ai_suggestion } : {}),
    ...(value.max_selections !== undefined ? { max_selections: value.max_selections } : {}),
    ...(value.mutually_exclusive_option_ids !== undefined ? { mutually_exclusive_option_ids: value.mutually_exclusive_option_ids } : {}),
    ...(value.min_length !== undefined ? { min_length: value.min_length } : {}),
    ...(value.max_length !== undefined ? { max_length: value.max_length } : {}),
    ...(value.entity_type !== undefined ? { entity_type: value.entity_type } : {}),
  };
}

function parseDraftSection(value: unknown): DraftPreviewBlock['sections'][number] | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['id', 'title', 'fields'])
    || !boundedString(value.id, 1) || !boundedString(value.title, 1)
    || !Array.isArray(value.fields) || value.fields.length < 1) return null;
  const fields = value.fields.map(parseDraftField);
  return fields.some((field) => field === null) ? null : { id: value.id, title: value.title, fields: fields as DraftPreviewField[] };
}

function parseDraftField(value: unknown): DraftPreviewField | null {
  const sources: DraftFieldSource[] = ['user_message', 'user_choice', 'user_edit', 'attachment_extraction', 'existing_record', 'ai_expansion', 'system_default'];
  if (!isRecord(value) || !hasOnlyKeys(value, [
    'key', 'label', 'value', 'source', 'source_ref', 'confidence', 'editable', 'needs_confirmation',
  ]) || !boundedString(value.key, 1) || !boundedString(value.label, 1)
    || !sources.includes(value.source as DraftFieldSource) || typeof value.editable !== 'boolean'
    || typeof value.needs_confirmation !== 'boolean' || !optionalNullableString(value.source_ref)
    || !optionalNullableConfidence(value.confidence)) return null;
  const fieldValue = sanitizeJsonValue(value.value);
  if (fieldValue === undefined) return null;
  return {
    key: value.key, label: value.label, value: fieldValue, source: value.source as DraftFieldSource,
    editable: value.editable, needs_confirmation: value.needs_confirmation,
    ...(value.source_ref !== undefined ? { source_ref: value.source_ref as string | null } : {}),
    ...(value.confidence !== undefined ? { confidence: value.confidence as number | null } : {}),
  };
}

function parseMissingField(value: unknown): DraftPreviewBlock['missing_fields'][number] | null {
  const severities = ['blocking', 'warning', 'info'] as const;
  if (!isRecord(value) || !hasOnlyKeys(value, ['key', 'label', 'severity', 'reason'])
    || !boundedString(value.key, 1) || !boundedString(value.label, 1)
    || !severities.includes(value.severity as never) || !boundedString(value.reason, 1)) return null;
  return { key: value.key, label: value.label, severity: value.severity as 'blocking' | 'warning' | 'info', reason: value.reason };
}

function parseAction(value: unknown): BlockAction | null {
  const styles = ['primary', 'secondary', 'text', 'danger'] as const;
  if (!isRecord(value) || !hasOnlyKeys(value, ['id', 'label', 'style', 'disabled', 'disabled_reason'])
    || !identifier(value.id) || !boundedString(value.label, 1) || !styles.includes(value.style as never)
    || !optionalBoolean(value.disabled) || !optionalString(value.disabled_reason)) return null;
  return {
    id: value.id, label: value.label, style: value.style as BlockAction['style'],
    ...(value.disabled !== undefined ? { disabled: value.disabled } : {}),
    ...(value.disabled_reason !== undefined ? { disabled_reason: value.disabled_reason } : {}),
  };
}

function parseActions(value: unknown): BlockAction[] | null {
  if (!Array.isArray(value)) return null;
  const actions = value.map(parseAction);
  return actions.some((action) => action === null) ? null : actions as BlockAction[];
}

function parseOptions(value: unknown): BlockOption[] | null {
  if (!Array.isArray(value)) return null;
  const options = value.map(parseOption);
  return options.some((option) => option === null) ? null : options as BlockOption[];
}

function parseSummaryField(value: unknown): EntitySummaryBlock['fields'][number] | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['key', 'label', 'value'])
    || typeof value.key !== 'string' || typeof value.label !== 'string') return null;
  const fieldValue = sanitizeJsonValue(value.value);
  return fieldValue === undefined ? null : { key: value.key, label: value.label, value: fieldValue };
}

function parseSimpleEntityRef(value: unknown): { type: string; id: string } | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['type', 'id'])
    || !boundedString(value.type, 1) || !boundedString(value.id, 1)) return null;
  return { type: value.type, id: value.id };
}

function parseWorkflow(value: unknown): PlatformAssistantWorkflow | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['capability_id', 'capability_version', 'state', 'row_version', 'progress'])
    || typeof value.capability_id !== 'string' || typeof value.capability_version !== 'string'
    || !WORKFLOW_STATES.has(value.state as WorkflowState) || !positiveInteger(value.row_version)
    || !isRecord(value.progress) || !hasOnlyKeys(value.progress, ['completed_required', 'total_required'])
    || !nonNegativeInteger(value.progress.completed_required) || !nonNegativeInteger(value.progress.total_required)) return null;
  return {
    capability_id: value.capability_id, capability_version: value.capability_version,
    state: value.state as WorkflowState, row_version: value.row_version,
    progress: { completed_required: value.progress.completed_required, total_required: value.progress.total_required },
  };
}

function parseResolvedContext(value: unknown): ResolvedContext | null {
  if (!isRecord(value) || !hasOnlyKeys(value, [
    'page_instance_id', 'route_id', 'resolved_pathname', 'organization_id', 'entity_refs',
    'authorization', 'projection_refs', 'context_version', 'row_version', 'stale',
  ]) || !/^page_[A-Za-z0-9_-]{8,120}$/.test(String(value.page_instance_id))
    || !identifier(value.route_id, 80) || !boundedString(value.resolved_pathname, 1, 500)
    || !String(value.resolved_pathname).startsWith('/')
    || !(value.organization_id === null || boundedString(value.organization_id, 0, 160))
    || !Array.isArray(value.entity_refs) || value.entity_refs.length > 8
    || !boundedString(value.authorization, 1, 80) || !stringArray(value.projection_refs, true)
    || !positiveInteger(value.context_version) || !(value.row_version === null || positiveInteger(value.row_version))
    || typeof value.stale !== 'boolean') return null;
  const refs = value.entity_refs.map(parseSimpleEntityRef);
  if (refs.some((ref) => ref === null)) return null;
  return {
    page_instance_id: value.page_instance_id as string, route_id: value.route_id,
    resolved_pathname: value.resolved_pathname, organization_id: value.organization_id,
    entity_refs: refs as Array<{ type: string; id: string }>, authorization: value.authorization,
    projection_refs: value.projection_refs, context_version: value.context_version,
    row_version: value.row_version, stale: value.stale,
  };
}

function parseUsage(value: unknown): { request_id: string | null } | null {
  if (!isRecord(value) || !hasOnlyKeys(value, ['request_id'])
    || !(value.request_id === null || boundedString(value.request_id, 1))) return null;
  return { request_id: value.request_id };
}

function parseFieldErrors(value: unknown): Array<{ field: string; code: string; message: string }> | null {
  if (!Array.isArray(value)) return null;
  const result = value.map((item) => {
    if (!isRecord(item) || !hasOnlyKeys(item, ['field', 'code', 'message'])
      || !boundedString(item.field, 1) || !boundedString(item.code, 1) || !boundedString(item.message, 1)) return null;
    return { field: item.field, code: item.code, message: item.message };
  });
  return result.some((item) => item === null) ? null : result as Array<{ field: string; code: string; message: string }>;
}

function fallbackNotice(code: 'UNSUPPORTED_BLOCK' | 'INVALID_BLOCK', index: number): NoticeBlock {
  return {
    schema_version: '1.0',
    block_id: `block_safe_fallback_${Math.max(0, index)}`,
    block_version: 1,
    type: 'notice',
    status: 'blocked',
    title: '暂时无法显示该内容',
    description: '该结构化内容未通过安全校验。',
    tone: 'warning',
    code,
    message: '请刷新后重试，或改用手工流程继续。',
    actions: [],
  };
}

function blockParseFailure(
  code: 'UNSUPPORTED_BLOCK' | 'INVALID_BLOCK',
  value: unknown,
  index: number,
): StructuredBlockParseResult {
  const record = isRecord(value) ? value : null;
  return {
    block: fallbackNotice(code, index),
    diagnostic: {
      code,
      block_index: Math.max(0, index),
      schema_version: record && typeof record.schema_version === 'string'
        ? record.schema_version.slice(0, 32)
        : null,
      block_type: record && typeof record.type === 'string'
        ? record.type.slice(0, 80)
        : null,
      block_id: record && typeof record.block_id === 'string'
        ? record.block_id.slice(0, 160)
        : null,
    },
  };
}

function sanitizeJsonValue(value: unknown, depth = 0): JsonValue | undefined {
  if (depth > 20) return undefined;
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value;
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (Array.isArray(value)) {
    const sanitized = value.map((item) => sanitizeJsonValue(item, depth + 1));
    return sanitized.some((item) => item === undefined) ? undefined : sanitized as JsonValue[];
  }
  if (!isRecord(value)) return undefined;
  const result: Record<string, JsonValue> = {};
  for (const [key, item] of Object.entries(value)) {
    const sanitized = sanitizeJsonValue(item, depth + 1);
    if (sanitized === undefined) return undefined;
    result[key] = sanitized;
  }
  return result;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: readonly string[]): boolean {
  const allowedSet = new Set(allowed);
  return Object.keys(value).every((key) => allowedSet.has(key));
}

function boundedString(value: unknown, minimum: number, maximum = Number.MAX_SAFE_INTEGER): value is string {
  return typeof value === 'string' && value.length >= minimum && value.length <= maximum;
}

function optionalString(value: unknown, maximum = Number.MAX_SAFE_INTEGER): value is string | undefined {
  return value === undefined || boundedString(value, 0, maximum);
}

function optionalNullableString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === 'string';
}

function optionalBoolean(value: unknown): value is boolean | undefined {
  return value === undefined || typeof value === 'boolean';
}

function positiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 1;
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function optionalPositiveInteger(value: unknown): value is number | undefined {
  return value === undefined || positiveInteger(value);
}

function optionalNonNegativeInteger(value: unknown): value is number | undefined {
  return value === undefined || nonNegativeInteger(value);
}

function optionalNullableConfidence(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || confidence(value);
}

function confidence(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1;
}

function identifier(value: unknown, maximum = Number.MAX_SAFE_INTEGER): value is string {
  return boundedString(value, 1, maximum) && /^[a-z][a-z0-9_.-]+$/.test(value);
}

function stringArray(value: unknown, unique = false): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
    && (!unique || new Set(value).size === value.length);
}

function dateTimeString(value: unknown): value is string {
  return typeof value === 'string' && !Number.isNaN(Date.parse(value));
}
