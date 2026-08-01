// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/components/AppHeader', () => ({
  default: ({ title }: { title: string }) => <header>{title}</header>,
}));

vi.mock('./AccountsPage', () => ({
  default: () => <div data-testid="login-accounts" />,
}));

vi.mock('@/features/marketplace/OrganizationTeamPage', () => ({
  default: () => <div data-testid="organization-team" />,
}));

import AccountManagementLayout, { LegacyOrganizationTeamRedirect } from './AccountManagementLayout';

const admin = {
  id: 'admin-user',
  tenant_id: 'tenant',
  username: 'admin',
  role: 'admin' as const,
};

const member = {
  id: 'member-user',
  tenant_id: 'tenant',
  username: 'member',
  role: 'member' as const,
};

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</output>;
}

afterEach(cleanup);

describe('account management information architecture', () => {
  it('keeps login accounts and organization team as separate second-level destinations for administrators', () => {
    render(
      <MemoryRouter initialEntries={['/enterprise/accounts']}>
        <AccountManagementLayout currentUser={admin} />
      </MemoryRouter>,
    );

    expect(screen.getByRole('navigation', { name: '账号管理二级导航' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '登录账号' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '企业与团队' })).toBeTruthy();
    expect(screen.getByTestId('login-accounts')).toBeTruthy();
  });

  it('routes a non-system-admin from the parent entry to organization team without granting account administration', async () => {
    render(
      <MemoryRouter initialEntries={['/enterprise/accounts']}>
        <Routes>
          <Route path="/enterprise/accounts/*" element={<AccountManagementLayout currentUser={member} />} />
        </Routes>
        <LocationProbe />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe('/enterprise/accounts/organization');
    });
    expect(screen.queryByRole('button', { name: '登录账号' })).toBeNull();
    expect(screen.getByTestId('organization-team')).toBeTruthy();
  });

  it('preserves search and hash while redirecting the old organization URL', async () => {
    render(
      <MemoryRouter initialEntries={['/enterprise/organization/team?organization=org-route-contract#members']}>
        <Routes>
          <Route path="/enterprise/organization/team" element={<LegacyOrganizationTeamRedirect />} />
          <Route path="/enterprise/accounts/organization" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('location').textContent).toBe(
        '/enterprise/accounts/organization?organization=org-route-contract#members',
      );
    });
  });
});
