// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { AgentProfileRead } from '../types';

const testState = vi.hoisted(() => ({ rows: [] as AgentProfileRead[] }));

vi.mock('../api/client', () => ({
  TENANT_ID: 'tenant_demo',
  api: {
    get: vi.fn(async () => testState.rows),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock('../components/AppHeader', () => ({ default: () => null }));
vi.mock('../components/EmployeeAvatarEditor', () => ({ default: () => null }));
vi.mock('../components/EmployeeProfileEditor', () => ({ default: () => null }));
vi.mock('../components/ConfirmDialog', () => ({ ConfirmDialog: () => null }));
vi.mock('../components/EmployeeCard', () => ({
  default: ({ employee, canManage, showMenu }: {
    employee: AgentProfileRead;
    canManage: boolean;
    showMenu?: boolean;
  }) => (
    <article
      data-testid={`employee-${employee.id}`}
      data-manage={String(canManage)}
      data-menu={String(showMenu)}
    >
      {employee.name}
    </article>
  ),
}));

import AgentsPage from './AgentsPage';

afterEach(() => {
  cleanup();
  testState.rows = [];
  window.localStorage.clear();
});

describe('AgentsPage employee access roster', () => {
  it('shows owned and previously used gallery employees while keeping used employees read-only', async () => {
    testState.rows = [
      employee('agent_owned', 'Owned contract agent', {
        owner_user_id: 'user_demo',
      }),
      employee('agent_used', 'Used legal agent', {
        owner_user_id: 'admin',
        published_to_gallery: true,
        used_by_current_user: true,
      }),
      employee('agent_gallery_only', 'Unused gallery agent', {
        owner_user_id: 'admin',
        published_to_gallery: true,
        used_by_current_user: false,
      }),
    ];

    render(
      <MemoryRouter>
        <AgentsPage
          currentUser={{ id: 'user_demo', tenant_id: 'tenant_demo', username: 'user_demo', role: 'member' }}
        />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('Owned contract agent')).toBeTruthy());
    expect(screen.getByText('Used legal agent')).toBeTruthy();
    expect(screen.queryByText('Unused gallery agent')).toBeNull();
    expect(screen.getByTestId('employee-agent_owned').dataset.manage).toBe('true');
    expect(screen.getByTestId('employee-agent_owned').dataset.menu).toBe('true');
    expect(screen.getByTestId('employee-agent_used').dataset.manage).toBe('false');
    expect(screen.getByTestId('employee-agent_used').dataset.menu).toBe('false');
  });
});

function employee(
  id: string,
  name: string,
  metadata: AgentProfileRead['metadata'],
): AgentProfileRead {
  return {
    id,
    tenant_id: 'tenant_demo',
    name,
    description: `${name}负责真实业务交付。`,
    is_overall: false,
    status: 'active',
    metadata,
    resources: [],
    created_at: '2026-08-02T00:00:00Z',
    updated_at: '2026-08-02T00:00:00Z',
  };
}
