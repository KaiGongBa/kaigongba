import { describe, expect, it } from 'vitest';

import type { EnterpriseAuthUser } from './auth';
import {
  employeeCardDisplayName,
  visibleWorkspaceEmployeeAgents,
} from './employee';
import type { AgentProfileRead } from './types';

const admin: EnterpriseAuthUser = {
  id: 'user_admin',
  tenant_id: 'tenant_demo',
  username: 'admin',
  role: 'admin',
};

describe('workspace employee presentation', () => {
  it('hides another account unpublished generated default from an administrator workspace', () => {
    const mine = employee('agent_mine', 'admin的数字员工', {
      owner_user_id: admin.id,
      is_default_employee: true,
    });
    const acceptance = employee('agent_acceptance', '5e17858297016590_buyer的数字员工', {
      owner_user_id: 'user_acceptance',
      owner_username: '5e17858297016590_buyer',
      is_default_employee: true,
    });
    const publicEmployee = employee('agent_public', '合同审查', {
      owner_user_id: 'user_provider',
      owner_username: 'provider',
      published_to_gallery: true,
    });

    expect(
      visibleWorkspaceEmployeeAgents([mine, acceptance, publicEmployee], admin, { activeOnly: true })
        .map((item) => item.id),
    ).toEqual(['agent_mine', 'agent_public']);
  });

  it('does not repeat the generated employee owner in the card title', () => {
    const generated = employee('agent_default', 'alice的数字员工', {
      owner_user_id: 'user_alice',
      owner_username: 'alice',
      is_default_employee: true,
    });
    const published = employee('agent_published', '合同审查', {
      owner_user_id: 'user_alice',
      owner_username: 'alice',
      published_to_gallery: true,
    });

    expect(employeeCardDisplayName(generated)).toBe('alice的数字员工');
    expect(employeeCardDisplayName(published)).toBe('合同审查 @alice');
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
    description: '',
    is_overall: false,
    status: 'active',
    metadata,
    resources: [],
    created_at: '2026-08-04T00:00:00Z',
    updated_at: '2026-08-04T00:00:00Z',
  };
}
