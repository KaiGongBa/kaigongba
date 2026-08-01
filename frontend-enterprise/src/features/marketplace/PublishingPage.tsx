import { useMemo, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  Bot,
  CheckCircle2,
  Clock3,
  Code2,
  FilePenLine,
  PackageCheck,
  Plus,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui';
import { MarketplaceHeader, MarketplaceState, MarketTabs } from './components';
import { ServiceSectionTabs } from './MarketplaceSectionTabs';
import { marketplaceRepository } from './repository';
import type { PublishingItem } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type PublishTab = 'all' | 'ai_service' | 'skill';

const statusLabels: Record<string, string> = {
  published: '已上架',
  pending_review: '审核中',
  draft: '草稿',
  changes_requested: '需补充',
  rejected: '审核不通过',
  disabled: '已停用',
};

export default function PublishingPage() {
  const navigate = useNavigate();
  const organization = useMarketplaceOrganization();
  const [tab, setTab] = useState<PublishTab>('all');
  const [applicationOpen, setApplicationOpen] = useState(false);
  const [applicationSaving, setApplicationSaving] = useState(false);
  const [summary, setSummary] = useState('');
  const [categories, setCategories] = useState('企业服务、IT运维');
  const [contactEmail, setContactEmail] = useState('');
  const [contactPhone, setContactPhone] = useState('');

  const resource = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.getPublishingOverview(organization.selected.id)
      : Promise.resolve({
          providerStatus: 'not_applied',
          items: [],
          counts: { published: 0, pending_review: 0, draft: 0, attention: 0 },
        }),
    `publishing:${organization.selected?.id || 'none'}`,
  );
  const overview = resource.data;
  const canPublish = overview?.providerStatus === 'active';
  const items = useMemo(
    () => (overview?.items || []).filter((item) => tab === 'all' || item.itemType === tab),
    [overview?.items, tab],
  );

  function openEditor(type: 'ai_service' | 'skill', item?: PublishingItem) {
    const segment = type === 'ai_service' ? 'services' : 'skills';
    navigate(`/enterprise/publishing/${segment}/${item?.id || 'new'}`);
  }

  async function submitApplication() {
    if (!organization.selected || !summary.trim() || !contactEmail.trim()) {
      notify.error('请完整填写服务商简介和联系邮箱');
      return;
    }
    setApplicationSaving(true);
    try {
      await marketplaceRepository.submitProviderApplication(organization.selected.id, {
        summary,
        service_categories: categories.split(/[、,\n]/).map((item) => item.trim()).filter(Boolean),
        contact_email: contactEmail,
        contact_phone: contactPhone || undefined,
        cases: [],
      });
      notify.success('入驻申请已提交，平台审核通过后即可发布');
      setApplicationOpen(false);
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '提交失败');
    } finally {
      setApplicationSaving(false);
    }
  }

  return (
    <main className="marketplace-page marketplace-management-page">
      <MarketplaceHeader
        title="我的发布"
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={(
          <div className="marketplace-action-group">
            <button
              type="button"
              className="marketplace-primary-button"
              disabled={!canPublish}
              onClick={() => openEditor('ai_service')}
            >
              <Plus />发布AI员工服务
            </button>
            <button
              type="button"
              className="marketplace-secondary-button"
              disabled={!canPublish}
              onClick={() => openEditor('skill')}
            >
              <Plus />发布Skill
            </button>
          </div>
        )}
      />
      <ServiceSectionTabs />

      <p className="marketplace-page-subtitle">管理 AI 员工商业服务与第三方 Skill 的版本、审核和上架状态。</p>

      <MarketplaceState
        loading={resource.loading}
        error={resource.error}
        onRetry={resource.reload}
      />

      {!resource.loading && overview && (
        <>
          {overview.providerStatus !== 'active' && (
            <section className={`marketplace-provider-gate is-${overview.providerStatus}`}>
              <div>
                <strong>
                  {overview.providerStatus === 'pending_review' ? '服务商入驻正在审核' : '发布前需要完成服务商入驻'}
                </strong>
                <span>
                  {overview.providerStatus === 'pending_review'
                    ? '平台正在核验企业资料与服务案例，审核期间可以继续完善企业资料。'
                    : '提交真实企业资料、服务能力和联系人信息，通过平台审核后开放发布。'}
                </span>
              </div>
              {overview.providerStatus !== 'pending_review' && (
                <button type="button" onClick={() => setApplicationOpen(true)}>申请入驻</button>
              )}
            </section>
          )}

          <section className="marketplace-stat-grid">
            <PublishStat icon={<PackageCheck />} label="已上架" value={overview.counts.published} tone="blue" />
            <PublishStat icon={<Clock3 />} label="审核中" value={overview.counts.pending_review} tone="orange" />
            <PublishStat icon={<FilePenLine />} label="草稿" value={overview.counts.draft} tone="gray" />
            <PublishStat icon={<AlertCircle />} label="需处理" value={overview.counts.attention} tone="red" />
          </section>

          <MarketTabs
            items={[
              { value: 'all', label: `全部 ${overview.items.length}` },
              { value: 'ai_service', label: `AI员工服务 ${overview.items.filter((item) => item.itemType === 'ai_service').length}` },
              { value: 'skill', label: `Skill ${overview.items.filter((item) => item.itemType === 'skill').length}` },
            ]}
            value={tab}
            onChange={setTab}
          />

          <section className="marketplace-management-card">
            <div className="marketplace-card-heading">
              <div>
                <h2>发布列表</h2>
                <p>已成交订单继续使用成交时版本，修改后需重新提交审核。</p>
              </div>
            </div>
            {items.length === 0 ? (
              <div className="marketplace-inline-empty">
                <FilePenLine />
                <strong>当前企业还没有发布记录</strong>
                <span>{canPublish ? '创建第一个 AI 员工服务或 Skill。' : '完成服务商入驻后即可开始发布。'}</span>
              </div>
            ) : (
              <div className="marketplace-table-wrap">
                <table className="marketplace-data-table">
                  <thead>
                    <tr>
                      <th>发布内容</th>
                      <th>类型</th>
                      <th>公开版本</th>
                      <th>价格</th>
                      <th>发布状态</th>
                      <th>调用/订单</th>
                      <th>更新时间</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={`${item.itemType}-${item.id}`}>
                        <td>
                          <div className="marketplace-table-title">
                            <span className={`marketplace-table-icon is-${item.itemType}`}>
                              {item.itemType === 'ai_service' ? <Bot /> : <Code2 />}
                            </span>
                            <span>
                              <strong>{item.name}</strong>
                              <small>{item.description}</small>
                            </span>
                          </div>
                        </td>
                        <td>{item.itemType === 'ai_service' ? 'AI员工服务' : 'Skill'}</td>
                        <td>{item.version}</td>
                        <td>{item.price === 0 ? '免费' : `¥${item.price}/${item.priceUnit}`}</td>
                        <td>
                          <span className={`marketplace-status is-${item.status}`}>
                            {statusLabels[item.status] || item.status}
                          </span>
                          {item.reviewComment && <small className="marketplace-review-note">{item.reviewComment}</small>}
                        </td>
                        <td>{item.usageCount}</td>
                        <td>{formatDateTime(item.updatedAt)}</td>
                        <td>
                          <button
                            type="button"
                            className="marketplace-link-button"
                            onClick={() => openEditor(item.itemType, item)}
                          >
                            {item.status === 'published' ? '创建新版本' : '继续编辑'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}

      <Dialog open={applicationOpen} onOpenChange={setApplicationOpen}>
        <DialogContent className="marketplace-dialog">
          <DialogTitle>申请成为服务商</DialogTitle>
          <p>申请通过后，当前企业可以发布 AI 员工商业服务和第三方 Skill。</p>
          <label>
            <span>服务能力简介 *</span>
            <textarea value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="说明服务领域、团队能力和交付经验" />
          </label>
          <label>
            <span>服务分类</span>
            <input value={categories} onChange={(event) => setCategories(event.target.value)} />
          </label>
          <div className="marketplace-form-grid">
            <label>
              <span>联系邮箱 *</span>
              <input value={contactEmail} onChange={(event) => setContactEmail(event.target.value)} placeholder="contact@example.com" />
            </label>
            <label>
              <span>联系电话</span>
              <input value={contactPhone} onChange={(event) => setContactPhone(event.target.value)} />
            </label>
          </div>
          <div className="marketplace-dialog-actions">
            <button type="button" onClick={() => setApplicationOpen(false)}>取消</button>
            <button type="button" className="marketplace-primary-button" disabled={applicationSaving} onClick={() => void submitApplication()}>
              {applicationSaving ? '提交中…' : '提交平台审核'}
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </main>
  );
}

function PublishStat({
  icon,
  label,
  value,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <article className="marketplace-stat-card">
      <span className={`marketplace-stat-card__icon is-${tone}`}>{icon}</span>
      <span><small>{label}</small><strong>{value}</strong></span>
      {label === '已上架' && <CheckCircle2 className="marketplace-stat-card__check" />}
    </article>
  );
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value));
}
