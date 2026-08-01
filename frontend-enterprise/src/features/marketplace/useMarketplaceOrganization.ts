import { useCallback, useEffect, useMemo, useState } from 'react';
import { marketplaceRepository } from './repository';
import type { MarketplaceOrganization } from './types';
import { useMarketplaceResource } from './useMarketplaceResource';

const STORAGE_KEY = 'kaigongba_marketplace_organization';

export function useMarketplaceOrganization() {
  const resource = useMarketplaceResource(
    () => marketplaceRepository.listOrganizations(),
    'marketplace-organizations',
  );
  const [preferredId, setPreferredId] = useState(() => {
    try {
      return window.localStorage.getItem(STORAGE_KEY) || '';
    } catch {
      return '';
    }
  });
  const organizations = resource.data || [];
  const selected = useMemo(
    () => (
      organizations.find((organization) => organization.id === preferredId)
      || organizations.find((organization) => organization.slug === 'demo-buyer')
      || organizations[0]
      || null
    ),
    [organizations, preferredId],
  );

  useEffect(() => {
    if (!selected || selected.id === preferredId) return;
    setPreferredId(selected.id);
    persistSelection(selected.id);
  }, [preferredId, selected]);

  const selectOrganization = useCallback((organizationId: string) => {
    setPreferredId(organizationId);
    persistSelection(organizationId);
  }, []);

  return {
    organizations,
    selected,
    selectOrganization,
    loading: resource.loading,
    error: resource.error,
  };
}

function persistSelection(organizationId: MarketplaceOrganization['id']) {
  try {
    window.localStorage.setItem(STORAGE_KEY, organizationId);
  } catch {
    // 浏览器禁用存储时仅维持当前页面内的选择。
  }
}
