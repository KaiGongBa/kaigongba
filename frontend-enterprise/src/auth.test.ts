import { describe, expect, it } from 'vitest';

import { canManagePlatformModels, type EnterpriseAuthUser } from './auth';

function user(
  role: EnterpriseAuthUser['role'],
  platformRole?: EnterpriseAuthUser['platform_role'],
): EnterpriseAuthUser {
  return {
    id: `user_${role}_${platformRole || 'none'}`,
    tenant_id: 'tenant_demo',
    username: 'tester',
    role,
    platform_role: platformRole,
  };
}

describe('platform model permissions', () => {
  it('allows only platform model administrators to see model gateway controls', () => {
    expect(canManagePlatformModels(user('admin', 'super_admin'))).toBe(true);
    expect(canManagePlatformModels(user('member', 'model_admin'))).toBe(true);
    expect(canManagePlatformModels(user('admin'))).toBe(false);
    expect(canManagePlatformModels(user('admin', 'operations'))).toBe(false);
    expect(canManagePlatformModels(user('admin', 'finance'))).toBe(false);
    expect(canManagePlatformModels(user('member', 'dispute_reviewer'))).toBe(false);
  });
});
