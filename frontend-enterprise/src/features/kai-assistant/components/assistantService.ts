import { api } from '@/api/client';

import type {
  AnswerSubmission,
  PageContext,
  PlatformAssistantErrorEnvelope,
  PlatformAssistantTurnResponse,
  PlatformAssistantV2StructuredBlock,
} from '../protocol';
import {
  safeParseErrorEnvelope,
  safeParseAnyTurnResponse,
  safeParseStructuredBlock,
} from '../protocol';

export type AssistantTurnInput = Readonly<{
  pageContext: PageContext;
  sessionId: string | null;
  agentId: string;
  message: string;
}>;

export type AssistantTurnResult = Readonly<{
  sessionId: string;
  runId: string | null;
  messageId: string;
  assistantText: string;
  blocks: PlatformAssistantV2StructuredBlock[];
  workflow: PlatformAssistantTurnResponse['workflow'];
}>;

export type AssistantRunSnapshot = Readonly<{
  protocol_version: '1.0';
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
      };
      let response: unknown;
      try {
        response = await api.post<unknown>('/api/platform-assistant/turns', {
          protocol_version: '2.0',
          ...request,
        });
      } catch (error) {
        if (!isProtocolVersionRejection(error)) throw error;
        response = await api.post<unknown>('/api/platform-assistant/turns', {
          protocol_version: '1.0',
          ...request,
        });
      }
      return normalizeAssistantResult(response, {
        sessionId: input.sessionId || '',
        assistantText: '开小花暂时无法回复。',
      });
    },

    async submitAnswers(submission) {
      const response = await api.post<unknown>(
        `/api/platform-assistant/runs/${encodeURIComponent(submission.run_id)}/answers`,
        submission,
      );
      return normalizeAssistantResult(response, {
        sessionId: submission.session_id,
        runId: submission.run_id,
        assistantText: '已保存本组回答。',
      });
    },

    async resumeRun(sessionId, runId) {
      const response = await api.post<unknown>(
        `/api/platform-assistant/runs/${encodeURIComponent(runId)}/resume`,
        { protocol_version: '1.0', session_id: sessionId },
      );
      return normalizeAssistantResult(response, {
        sessionId,
        runId,
        assistantText: '已恢复上次工作流。',
      });
    },

    async cancelRun(sessionId, runId) {
      const response = await api.post<unknown>(
        `/api/platform-assistant/runs/${encodeURIComponent(runId)}/cancel`,
        { protocol_version: '1.0', session_id: sessionId },
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
  const turn = safeParseAnyTurnResponse(value);
  if (turn) {
    return {
      sessionId: turn.session_id,
      runId: turn.run_id,
      messageId: turn.message_id,
      assistantText: turn.assistant_text,
      blocks: turn.ui_blocks,
      workflow: turn.workflow,
    };
  }
  if (isRunSnapshot(value)) {
    return {
      sessionId: value.run.session_id,
      runId: value.run.run_id,
      messageId: `run_${value.run.row_version}`,
      assistantText: fallback.assistantText,
      blocks: value.ui_blocks.map((block, index) => safeParseStructuredBlock(block, index)),
      workflow: null,
    };
  }
  if (isLegacyChatTurn(value)) {
    return {
      sessionId: value.session_id,
      runId: fallback.runId ?? null,
      messageId: `legacy_${crypto.randomUUID()}`,
      assistantText: value.reply,
      blocks: [],
      workflow: null,
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
  if (!isRecord(value) || value.protocol_version !== '1.0' || !isRecord(value.run)
    || !Array.isArray(value.ui_blocks)) return false;
  return typeof value.run.run_id === 'string'
    && typeof value.run.session_id === 'string'
    && typeof value.run.state === 'string'
    && Number.isInteger(value.run.row_version);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
