import { afterEach, describe, expect, it } from 'vitest';

import {
  clearSharedAgentScope,
  persistSessionFilter,
  persistSharedAgentScope,
  readSessionFilter,
  readSharedAgentScope,
} from './agent-scope-storage';

describe('agent scope storage', () => {
  afterEach(() => {
    clearSharedAgentScope();
    persistSessionFilter('user-a', '');
  });

  it('keeps the selected employee in module memory', () => {
    persistSharedAgentScope('agent-a', 'user-a');

    expect(readSharedAgentScope()).toBe('agent-a');
  });

  it('isolates in-memory session filters by user', () => {
    persistSessionFilter('user-a', 'agent-a');
    persistSessionFilter('user-b', 'agent-b');

    expect(readSessionFilter('user-a')).toBe('agent-a');
    expect(readSessionFilter('user-b')).toBe('agent-b');
  });
});
