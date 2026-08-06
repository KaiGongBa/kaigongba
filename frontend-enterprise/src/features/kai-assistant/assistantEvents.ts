import type { KaiAssistantView } from '@/features/marketplace/uiMigrationContracts';

export const OPEN_KAI_ASSISTANT_EVENT = 'kaigongba-open-kai-assistant';

export type OpenKaiAssistantDetail = {
  view?: KaiAssistantView;
  prompt?: string;
  autoSend?: boolean;
  startNewWorkflow?: boolean;
  entrypoint?: 'requirement.create';
  analysisRequestId?: string;
};

export function openKaiAssistant(detail: OpenKaiAssistantDetail = {}) {
  window.dispatchEvent(new CustomEvent<OpenKaiAssistantDetail>(OPEN_KAI_ASSISTANT_EVENT, { detail }));
}
