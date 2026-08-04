export const ENTERPRISE_AGENT_STORAGE_KEY = 'ultrarag_enterprise_agent_scope';
export const SELECTED_AGENT_STORAGE_KEY = ENTERPRISE_AGENT_STORAGE_KEY;
export const SESSION_FILTER_STORAGE_PREFIX = 'skill_agent_session_filter';

let sharedAgentScope = '';
const sessionFilters = new Map<string, string>();

export function sessionFilterStorageKey(userId: string): string {
  return `${SESSION_FILTER_STORAGE_PREFIX}:${userId || 'anonymous'}`;
}

export function readSharedAgentScope(): string {
  return sharedAgentScope;
}

export function persistSharedAgentScope(agentId: string, userId?: string): void {
  void userId;
  if (!agentId) return;
  sharedAgentScope = agentId;
}

export function clearSharedAgentScope(userId?: string): void {
  void userId;
  sharedAgentScope = '';
}

export function readSessionFilter(userId: string): string {
  return sessionFilters.get(sessionFilterStorageKey(userId)) || '';
}

export function persistSessionFilter(userId: string, agentId: string): void {
  const key = sessionFilterStorageKey(userId);
  if (agentId) sessionFilters.set(key, agentId);
  else sessionFilters.delete(key);
}

export function emitAgentScopeChange(agentId: string): void {
  window.dispatchEvent(
    new CustomEvent('ultrarag-enterprise-agent-scope-change', {
      detail: { agentId },
    }),
  );
}
