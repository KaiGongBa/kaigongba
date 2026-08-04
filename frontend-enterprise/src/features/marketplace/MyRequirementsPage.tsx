import { FilePlus2, FileText, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MarketplaceHeader, MarketplaceState } from './components';
import { TransactionSectionTabs } from './MarketplaceSectionTabs';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

const statusLabels: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  matching: '匹配中',
  quoting: '报价中',
  agreement_pending: '待签约',
  contracted: '已签约',
  closed: '已关闭',
};

export default function MyRequirementsPage() {
  const navigate = useNavigate();
  const organization = useMarketplaceOrganization();
  const [keyword, setKeyword] = useState('');
  const resource = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.listRequirements(organization.selected.id)
      : Promise.reject(new Error('请先选择企业')),
    `buyer-requirements:${organization.selected?.id || 'none'}`,
  );
  const items = useMemo(() => (resource.data || []).filter((item) => (
    !keyword.trim()
    || `${item.title} ${item.code} ${item.category}`.toLocaleLowerCase().includes(keyword.trim().toLocaleLowerCase())
  )), [keyword, resource.data]);

  return (
    <main className="marketplace-page marketplace-management-page transaction-page">
      <MarketplaceHeader
        title="我的需求"
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={(
          <button type="button" className="marketplace-primary-button" onClick={() => navigate('/enterprise/demands/new')}>
            <FilePlus2 />发布需求
          </button>
        )}
      />
      <TransactionSectionTabs />
      <p className="marketplace-page-subtitle">管理需求版本、匹配邀请、报价与协议状态。</p>
      <section className="marketplace-management-card">
        <div className="marketplace-card-heading">
          <div><h2>需求列表</h2><p>草稿仅企业内部可见，发布后由平台匹配并邀请服务商。</p></div>
          <label className="marketplace-small-search"><Search /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索编号、标题或分类" /></label>
        </div>
        <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
        {!resource.loading && items.length === 0 && (
          <div className="marketplace-inline-empty"><FileText /><strong>当前企业还没有需求</strong><span>发布真实需求后，平台会生成匹配理由并邀请服务商报价。</span></div>
        )}
        {items.length > 0 && (
          <div className="marketplace-table-wrap">
            <table className="marketplace-data-table">
              <thead><tr><th>需求</th><th>预算</th><th>期望完成</th><th>已邀请</th><th>有效报价</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td><div className="marketplace-table-title"><span className="marketplace-table-icon"><FileText /></span><span><strong>{item.title}</strong><small>{item.code} · {item.category}</small></span></div></td>
                    <td>¥{money(item.budgetMinAmount)}–¥{money(item.budgetMaxAmount)}</td>
                    <td>{item.desiredDeliveryAt ? formatDate(item.desiredDeliveryAt) : '-'}</td>
                    <td>{item.invitationCount}</td>
                    <td>{item.quoteCount}</td>
                    <td><span className={`marketplace-status is-${item.status}`}>{statusLabels[item.status] || item.status}</span></td>
                    <td>{formatDateTime(item.updatedAt)}</td>
                    <td><button type="button" className="marketplace-link-button" onClick={() => navigate(`/enterprise/demands/${item.id}`)}>{item.status === 'draft' ? '继续编辑' : '查看进展'}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}

function money(value: string) {
  return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value));
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}
