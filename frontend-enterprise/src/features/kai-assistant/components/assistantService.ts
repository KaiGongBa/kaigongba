import { api } from '@/api/client';

import type {
  AnswerSubmission,
  PageContext,
  PlatformAssistantErrorEnvelope,
  PlatformAssistantTurnResponse,
  PlatformAssistantV2StructuredBlock,
  StructuredBlockParseDiagnostic,
} from '../protocol';
import {
  collectStructuredBlockDiagnostics,
  parseStructuredBlockBySchema,
  safeParseErrorEnvelope,
  safeParseAnyTurnResponse,
} from '../protocol';

export type AssistantTurnInput = Readonly<{
  pageContext: PageContext;
  sessionId: string | null;
  agentId: string;
  message: string;
  entrypoint?: 'requirement.create';
}>;

export type AssistantTurnResult = Readonly<{
  sessionId: string;
  runId: string | null;
  messageId: string;
  assistantText: string;
  blocks: PlatformAssistantV2StructuredBlock[];
  blockDiagnostics?: StructuredBlockParseDiagnostic[];
  workflow: PlatformAssistantTurnResponse['workflow'];
  runState?: string | null;
}>;

export type AssistantRunSnapshot = Readonly<{
  protocol_version: '1.0' | '2.0';
  run: {
    run_id: string;
    session_id: string;
    state: string;
    row_version: number;
  };
  ui_blocks: unknown[];
}>;

export interface KaiAssistantService {
  sendTurn(input: AssistantTurnInput): Promise<AssistantTurnResult>;
  submitAnswers(submission: AnswerSubmission): Promise<AssistantTurnResult>;
  resumeRun(sessionId: string, runId: string): Promise<AssistantTurnResult>;
  cancelRun(sessionId: string, runId: string): Promise<AssistantTurnResult>;
}

type LegacyChatTurnResponse = {
  reply: string;
  session_id: string;
};

/** Default transport prefers the adaptive v2 protocol and negotiates v1 only when required. */
export function createDefaultKaiAssistantService(): KaiAssistantService {
  return {
    async sendTurn(input) {
      const requestId = crypto.randomUUID();
      const request = {
        client_request_id: requestId,
        session_id: input.sessionId,
        message: input.message,
        page_context: input.pageContext,
        ...(input.entrypoint ? { entrypoint: input.entrypoint } : {}),
      };
      const response = await postWithProtocolNegotiation(
        '/api/platform-assistant/turns',
        request,
        '2.0',
      );
      return normalizeAssistantResult(response, {
        sessionId: input.sessionId || '',
        assistantText: '开小花暂时无法回复。',
      });
    },

    async submitAnswers(submission) {
      const { protocol_version: preferredVersion, ...request } = submission;
      const response = await postWithProtocolNegotiation(
        `/api/platform-assistant/runs/${encodeURIComponent(submission.run_id)}/answers`,
        request,
        preferredVersion,
      );
      return normalizeAssistantResult(response, {
        sessionId: submission.session_id,
        runId: submission.run_id,
        assistantText: '已保存本组回答。',
      });
    },

    async resumeRun(sessionId, runId) {
      const response = await postWithProtocolNegotiation(
        `/api/platform-assistant/runs/${encodeURIComponent(runId)}/resume`,
        { session_id: sessionId },
        '2.0',
      );
      return normalizeAssistantResult(response, {
        sessionId,
        runId,
        assistantText: '已恢复上次工作流。',
      });
    },

    async cancelRun(sessionId, runId) {
      const response = await postWithProtocolNegotiation(
        `/api/platform-assistant/runs/${encodeURIComponent(runId)}/cancel`,
        { session_id: sessionId },
        '2.0',
      );
      return normalizeAssistantResult(response, {
        sessionId,
        runId,
        assistantText: '已取消当前工作流，已保存的真实业务数据不会被删除。',
      });
    },
  };
}

export function normalizeAssistantResult(
  value: unknown,
  fallback: { sessionId: string; runId?: string | null; assistantText: string },
): AssistantTurnResult {
  const unsafeBlocks = rawUiBlocks(value);
  const blockDiagnostics = unsafeBlocks
    ? collectStructuredBlockDiagnostics(unsafeBlocks)
    : [];
  const turn = safeParseAnyTurnResponse(value);
  if (turn) {
    return {
      sessionId: turn.session_id,
      runId: turn.run_id,
      messageId: turn.message_id,
      assistantText: turn.assistant_text,
      blocks: turn.ui_blocks,
      blockDiagnostics,
      workflow: turn.workflow,
      runState: turn.workflow?.state ?? null,
    };
  }
  if (isRunSnapshot(value)) {
    return {
      sessionId: value.run.session_id,
      runId: value.run.run_id,
      messageId: `run_${value.run.row_version}`,
      assistantText: fallback.assistantText,
      blocks: value.ui_blocks.map((block, index) => parseStructuredBlockBySchema(block, index).block),
      blockDiagnostics,
      workflow: null,
      runState: value.run.state,
    };
  }
  if (isLegacyChatTurn(value)) {
    return {
      sessionId: value.session_id,
      runId: fallback.runId ?? null,
      messageId: `legacy_${crypto.randomUUID()}`,
      assistantText: value.reply,
      blocks: [],
      blockDiagnostics: [],
      workflow: null,
      runState: null,
    };
  }
  throw new Error('开小花返回了无法安全显示的内容');
}

function isProtocolVersionRejection(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false;
  const status = 'status' in error ? Number((error as { status?: unknown }).status) : 0;
  const body = 'body' in error ? String((error as { body?: unknown }).body).toLowerCase() : '';
  return (status === 400 || status === 422)
    && body.includes('protocol_version')
    && (body.includes('2.0') || body.includes('literal'));
}

async function postWithProtocolNegotiation(
  path: string,
  request: Record<string, unknown>,
  preferredVersion: '1.0' | '2.0',
): Promise<unknown> {
  try {
    return await api.post<unknown>(path, {
      protocol_version: preferredVersion,
      ...request,
    });
  } catch (error) {
    if (preferredVersion !== '2.0' || !isProtocolVersionRejection(error)) throw error;
    const legacyRequest = { ...request };
    delete legacyRequest.entrypoint;
    return api.post<unknown>(path, {
      protocol_version: '1.0',
      ...legacyRequest,
    });
  }
}

export function parseAssistantError(error: unknown): PlatformAssistantErrorEnvelope['error'] {
  const body = error && typeof error === 'object' && 'body' in error
    ? String((error as { body: unknown }).body)
    : '';
  if (body) {
    try {
      const parsed = safeParseErrorEnvelope(JSON.parse(body));
      if (parsed) return parsed.error;
    } catch {
      // Fall through to the stable, non-sensitive error below.
    }
  }
  const message = error instanceof Error && error.message
    ? error.message
    : '开小花暂时无法连接';
  return { code: 'INTERNAL_ERROR', message, retryable: true };
}

function isLegacyChatTurn(value: unknown): value is LegacyChatTurnResponse {
  if (!isRecord(value)) return false;
  return typeof value.reply === 'string' && typeof value.session_id === 'string';
}

function isRunSnapshot(value: unknown): value is AssistantRunSnapshot {
  if (!isRecord(value) || !['1.0', '2.0'].includes(String(value.protocol_version)) || !isRecord(value.run)
    || !Array.isArray(value.ui_blocks)) return false;
  return typeof value.run.run_id === 'string'
    && typeof value.run.session_id === 'string'
    && typeof value.run.state === 'string'
    && Number.isInteger(value.run.row_version);
}

function rawUiBlocks(value: unknown): unknown[] | null {
  return isRecord(value) && Array.isArray(value.ui_blocks) ? value.ui_blocks : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
