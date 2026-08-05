import { ArrowRight, BriefcaseBusiness, CheckCircle2, Clock3, FileQuestion, Send, Sparkles } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MarketplaceHeader, MarketplaceState } from './components';
import { ServiceSectionTabs } from './MarketplaceSectionTabs';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

export default function ProviderWorkbenchPage() {
  const navigate = useNavigate();
  const organization = useMarketplaceOrganization();
  const [queue, setQueue] = useState<'invitations' | 'drafts' | 'sent'>('invitations');
  const resource = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.getProviderWorkbench(organization.selected.id)
      : Promise.reject(new Error('请先选择服务商企业')),
    `provider-workbench:${organization.selected?.id || 'none'}`,
  );
  const workbench = resource.data;
  const needsOnboarding = resource.error.includes('尚未完成服务商入驻');

  return (
    <main className="marketplace-page marketplace-management-page transaction-page">
      <MarketplaceHeader
        title="报价管理"
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <ServiceSectionTabs />
      <p className="marketplace-page-subtitle">当前企业以服务方身份处理需求邀请、确认 AI 报价草案并跟踪报价结果；草案不会自动发送。</p>
      {needsOnboarding ? (
        <section className="provider-onboarding-state">
          <BriefcaseBusiness />
          <div><small>当前企业：{organization.selected?.name || '-'}</small><h2>先完成服务商入驻</h2><p>每个用户都可同时作为采购方和服务方，但承接订单前，当前企业仍需提交真实资料并通过平台审核。</p></div>
          <button type="button" onClick={() => navigate('/enterprise/publishing')}>前往入驻与发布 <ArrowRight /></button>
        </section>
      ) : <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />}
      {workbench && (
        <>
          <section className="marketplace-stat-grid">
            <Stat icon={<FileQuestion />} label="待处理邀请" value={workbench.counts.invitations || 0} tone="blue" />
            <Stat icon={<Sparkles />} label="报价待确认" value={workbench.counts.pending_confirmation || 0} tone="orange" />
            <Stat icon={<Send />} label="已发送报价" value={workbench.counts.sent || 0} tone="gray" />
            <Stat icon={<CheckCircle2 />} label="已选中" value={workbench.counts.selected || 0} tone="green" />
          </section>
          <nav className="provider-workbench-tabs" role="tablist" aria-label="服务方工作队列">
            <button type="button" role="tab" aria-selected={queue === 'invitations'} className={queue === 'invitations' ? 'is-active' : ''} onClick={() => setQueue('invitations')}><FileQuestion />需求邀请 <span>{workbench.counts.invitations || 0}</span></button>
            <button type="button" role="tab" aria-selected={queue === 'drafts'} className={queue === 'drafts' ? 'is-active' : ''} onClick={() => setQueue('drafts')}><Sparkles />报价待确认 <span>{workbench.counts.pending_confirmation || 0}</span></button>
            <button type="button" role="tab" aria-selected={queue === 'sent'} className={queue === 'sent' ? 'is-active' : ''} onClick={() => setQueue('sent')}><Send />已发送报价 <span>{workbench.counts.sent || 0}</span></button>
            <div><button type="button" onClick={() => navigate('/enterprise/publishing')}>管理服务商品</button><button type="button" onClick={() => navigate('/enterprise/provider?view=workbench')}>查看承接订单</button></div>
          </nav>
          {queue === 'invitations' && <section className="marketplace-management-card provider-queue-card" role="tabpanel">
            <div className="marketplace-card-heading"><div><h2>待处理需求邀请</h2><p>查看需求与澄清材料后，选择当前企业已发布的服务生成报价草案。</p></div></div>
            {workbench.pendingInvitations.length === 0 ? <div className="marketplace-inline-empty compact"><BriefcaseBusiness /><strong>没有待处理邀请</strong><span>新的匹配邀请会出现在这里。</span></div> : (
              <div className="marketplace-table-wrap"><table className="marketplace-data-table"><thead><tr><th>需求</th><th>采购方</th><th>预算</th><th>期望完成</th><th>状态</th><th>操作</th></tr></thead><tbody>{workbench.pendingInvitations.map((item) => <tr key={item.id}><td><div className="marketplace-table-title"><span className="marketplace-table-icon"><FileQuestion /></span><span><strong>{item.title}</strong><small>{item.code} · {item.category}</small></span></div></td><td>{item.buyerOrganizationName}</td><td>¥{money(item.budgetMinAmount)}–¥{money(item.budgetMaxAmount)}</td><td>{item.desiredDeliveryAt ? formatDate(item.desiredDeliveryAt) : '-'}</td><td><span className="marketplace-status is-pending">待处理</span></td><td><button type="button" className="marketplace-link-button" onClick={() => navigate(`/enterprise/demands/${item.id}`)}>查看并报价</button></td></tr>)}</tbody></table></div>
            )}
          </section>}
          {queue === 'drafts' && <section className="marketplace-management-card provider-queue-card" role="tabpanel">
            <div className="marketplace-card-heading"><div><h2>报价待确认</h2><p>报价草案和内部生成依据仅服务方可见。</p></div></div>
            {workbench.quoteDrafts.length === 0 ? <div className="marketplace-inline-empty compact"><Sparkles /><strong>没有待确认报价</strong></div> : (
              <div className="marketplace-table-wrap"><table className="marketplace-data-table"><thead><tr><th>报价需求</th><th>服务</th><th>AI 建议价</th><th>工期</th><th>版本</th><th>状态</th><th>操作</th></tr></thead><tbody>{workbench.quoteDrafts.map((quote) => <tr key={quote.id}><td><strong>{quote.requirementTitle}</strong><br /><small>{quote.requirementCode}</small></td><td>{quote.serviceName}</td><td>{quote.currentVersion ? `¥${money(quote.currentVersion.totalAmount)}` : '-'}</td><td>{quote.currentVersion ? `${quote.currentVersion.deliveryDays} 天` : '-'}</td><td>{quote.currentVersion ? `v${quote.currentVersion.version}` : '-'}</td><td><span className="marketplace-status is-pending_review">{quoteDraftStatus(quote.status)}</span></td><td><button type="button" className="marketplace-link-button" onClick={() => navigate(`/enterprise/provider/quotes/${quote.id}`)}>{quote.currentVersion ? '核对报价' : '查看状态'}</button></td></tr>)}</tbody></table></div>
            )}
          </section>}
          {queue === 'sent' && <section className="marketplace-management-card provider-queue-card" role="tabpanel">
            <div className="marketplace-card-heading"><div><h2>已发送报价</h2><p>报价版本、确认人和发送时间全程留痕。</p></div></div>
            {workbench.sentQuotes.length === 0 ? <div className="marketplace-inline-empty compact"><Clock3 /><strong>尚未发送报价</strong></div> : (
              <div className="marketplace-table-wrap"><table className="marketplace-data-table"><thead><tr><th>报价需求</th><th>报价</th><th>发送时间</th><th>确认人</th><th>状态</th><th>操作</th></tr></thead><tbody>{workbench.sentQuotes.map((quote) => <tr key={quote.id}><td><strong>{quote.requirementTitle}</strong><br /><small>{quote.requirementCode}</small></td><td>{quote.currentVersion ? `¥${money(quote.currentVersion.totalAmount)}` : '-'}</td><td>{quote.sentAt ? formatDateTime(quote.sentAt) : '-'}</td><td>{quote.confirmedBy || '-'}</td><td><span className={`marketplace-status is-${quote.status}`}>{quoteStatus(quote.status)}</span></td><td><button type="button" className="marketplace-link-button" onClick={() => navigate(`/enterprise/provider/quotes/${quote.id}`)}>查看详情</button></td></tr>)}</tbody></table></div>
            )}
          </section>}
        </>
      )}
    </main>
  );
}

function Stat({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number; tone: string }) {
  return <article className="marketplace-stat-card"><span className={`marketplace-stat-card__icon is-${tone}`}>{icon}</span><span><small>{label}</small><strong>{value}</strong></span></article>;
}
function quoteStatus(value: string) { return { sent: '已发送', selected: '已选中', rejected: '未选中', withdrawn: '已撤回' }[value] || value; }
function quoteDraftStatus(value: string) { return { queued: '已排队', generating: 'AI 生成中', ai_draft: '待服务方确认', pending_provider_confirmation: '待服务方确认', needs_clarification: '待补充信息', failed: '生成失败·将重试' }[value] || value; }
function money(value: string) { return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }); }
function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value)); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
