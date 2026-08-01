import { Building2 } from 'lucide-react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';

import IconAccounts from '@/assets/icons/sys-accounts.svg?react';
import AppHeader from '@/components/AppHeader';
import OrganizationTeamPage from '@/features/marketplace/OrganizationTeamPage';
import { cn } from '@/lib/utils';

import type { EnterpriseAuthUser } from '../auth';
import { isEnterpriseAdmin } from '../auth';
import AccountsPage from './AccountsPage';

const ACCOUNTS_PATH = '/enterprise/accounts';
const ORGANIZATION_PATH = '/enterprise/accounts/organization';

export function LegacyOrganizationTeamRedirect() {
  const location = useLocation();
  return (
    <Navigate
      replace
      to={{
        pathname: ORGANIZATION_PATH,
        search: location.search,
        hash: location.hash,
      }}
    />
  );
}

export default function AccountManagementLayout({
  currentUser,
  onLogout,
}: {
  currentUser: EnterpriseAuthUser;
  onLogout?: () => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const canManageAccounts = isEnterpriseAdmin(currentUser);
  const organizationSelected = location.pathname === ORGANIZATION_PATH;

  if (!canManageAccounts && !organizationSelected) {
    return <Navigate replace to={{ pathname: ORGANIZATION_PATH, search: location.search, hash: location.hash }} />;
  }
  if (location.pathname !== ACCOUNTS_PATH && !organizationSelected) {
    return <Navigate replace to={canManageAccounts ? ACCOUNTS_PATH : ORGANIZATION_PATH} />;
  }

  return (
    <main className="min-h-full box-border px-[48px] pt-[32px] pb-[43px] max-[900px]:px-[16px]">
      <AppHeader onLogout={onLogout} userName={currentUser.username} title="账号管理" />

      <nav
        aria-label="账号管理二级导航"
        className="mt-[18px] flex min-h-[44px] items-center gap-[4px] rounded-[14px] border border-[#e9ebf0] bg-white p-[4px] shadow-[0_8px_24px_rgba(24,24,26,0.04)]"
      >
        {canManageAccounts && (
          <button
            type="button"
            aria-current={!organizationSelected ? 'page' : undefined}
            onClick={() => navigate(ACCOUNTS_PATH)}
            className={cn(
              'flex h-[36px] items-center gap-[8px] rounded-[10px] px-[14px] text-[13px] transition-colors',
              !organizationSelected
                ? 'bg-[#18181a] text-white'
                : 'text-[#757f9c] hover:bg-[#f5f6f8] hover:text-[#18181a]',
            )}
          >
            <IconAccounts className="size-[15px]" />
            登录账号
          </button>
        )}
        <button
          type="button"
          aria-current={organizationSelected ? 'page' : undefined}
          onClick={() => navigate(ORGANIZATION_PATH)}
          className={cn(
            'flex h-[36px] items-center gap-[8px] rounded-[10px] px-[14px] text-[13px] transition-colors',
            organizationSelected
              ? 'bg-[#18181a] text-white'
              : 'text-[#757f9c] hover:bg-[#f5f6f8] hover:text-[#18181a]',
          )}
        >
          <Building2 className="size-[15px]" />
          企业与团队
        </button>
      </nav>

      <section className="mt-[14px] min-w-0">
        {organizationSelected ? (
          <OrganizationTeamPage />
        ) : (
          <AccountsPage currentUser={currentUser} onLogout={onLogout} embedded />
        )}
      </section>
    </main>
  );
}
