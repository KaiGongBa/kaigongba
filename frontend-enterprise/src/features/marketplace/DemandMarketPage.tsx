import {
  Building2,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Star,
  Wallet,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { RequirementSummary } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

import './demand-market.css';

type SortMode = 'recommended' | 'all' | 'saved';

export default function DemandMarketPage() {
  const navigate = useNavigate();
  const organization = useMarketplaceOrganization();
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState('all');
  const [budget, setBudget] = useState('all');
  const [delivery, setDelivery] = useState('all');
  const [sort, setSort] = useState<SortMode>('recommended');
  const [savedIds, setSavedIds] = useState<Set<string>>(() => new Set());
  const resource = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.listRequirements(organization.selected.id, 'market')
      : Promise.reject(new Error('请先选择浏览需求的企业')),
    `demand-market:${organization.selected?.id || 'none'}`,
  );
  const categories = useMemo(
    () => [...new Set((resource.data || []).map((item) => item.category).filter(Boolean))].sort(),
    [resource.data],
  );
  const items = useMemo(() => {
    const normalizedKeyword = keyword.trim().toLocaleLowerCase();
    const now = Date.now();
    return (resource.data || [])
      .filter((item) => !normalizedKeyword || `${item.title} ${item.category} ${item.buyerOrganizationName}`.toLocaleLowerCase().includes(normalizedKeyword))
      .filter((item) => category === 'all' || item.category === category)
      .filter((item) => budgetMatches(item, budget))
      .filter((item) => deliveryMatches(item, delivery, now))
      .filter((item) => sort !== 'saved' || savedIds.has(item.id))
      .sort((left, right) => {
        if (sort === 'all' || sort === 'saved') return Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
        return (right.matchScore || 0) - (left.matchScore || 0)
          || Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
      });
  }, [budget, category, delivery, keyword, resource.data, savedIds, sort]);

  return (
    <main className="marketplace-page marketplace-management-page demand-market-page">
      <MarketplaceHeader
        title="需求市场"
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <p className="demand-market-page-subtitle">AI 按你的服务能力筛选值得跟进的机会</p>

      <section className="demand-market-search-panel" aria-label="筛选需求">
        <label className="demand-market-search"><Search /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索需求、行业或采购企业" /></label>
        <label><span>服务领域</span><select value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">全部领域</option>{categories.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
        <label><span>预算范围</span><select value={budget} onChange={(event) => setBudget(event.target.value)}><option value="all">全部预算</option><option value="under10k">1 万以内</option><option value="10k50k">1–5 万</option><option value="over50k">5 万以上</option></select></label>
        <label><span>交付周期</span><select value={delivery} onChange={(event) => setDelivery(event.target.value)}><option value="all">全部周期</option><option value="7d">7 天内</option><option value="30d">30 天内</option></select></label>
      </section>

      <div className="demand-market-layout">
        <section className="demand-market-results">
          <header>
            <div className="demand-market-tabs" role="tablist" aria-label="需求排序">
              <SortButton active={sort === 'recommended'} onClick={() => setSort('recommended')}>为你推荐</SortButton>
              <SortButton active={sort === 'all'} onClick={() => setSort('all')}>全部公开需求</SortButton>
              <SortButton active={sort === 'saved'} onClick={() => setSort('saved')}>已收藏</SortButton>
            </div>
            <span>共 {items.length} 个需求</span>
          </header>
          <p className="demand-market-recommendation-note">基于你的已发布服务范围、可执行版本和预算边界，为你推荐匹配度较高的需求</p>
          <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
          {!resource.loading && items.length === 0 ? (
            <div className="marketplace-inline-empty"><Search /><strong>暂时没有符合条件的需求</strong><span>调整筛选条件，或稍后查看新发布项目。</span></div>
          ) : null}
          <div className="demand-market-list">
            {items.map((item, index) => (
              <DemandCard
                key={item.id}
                item={item}
                featured={sort === 'recommended' && index === 0}
                saved={savedIds.has(item.id)}
                onToggleSaved={() => setSavedIds((current) => {
                  const next = new Set(current);
                  if (next.has(item.id)) next.delete(item.id); else next.add(item.id);
                  return next;
                })}
                onOpen={() => navigate(`/enterprise/demands/${item.id}?source=market`)}
              />
            ))}
          </div>
        </section>

        <aside className="demand-market-preferences">
          <header><SlidersHorizontal /><div><strong>匹配偏好</strong><small>基于当前企业已发布服务</small></div></header>
          <div className="demand-market-preference-block"><span>匹配企业</span><strong>{organization.selected?.name || '尚未选择企业'}</strong></div>
          <div className="demand-market-preference-block"><span>优先条件</span><ul><li><CheckCircle2 />服务范围覆盖</li><li><CheckCircle2 />预算可承接</li><li><CheckCircle2 />工期可满足</li></ul></div>
          <div className="demand-market-trust"><ShieldCheck /><div><strong>交易安全提示</strong><p>公开需求不等于自动获邀。进入报价后，系统会建立可审计的参与记录。</p></div></div>
        </aside>
      </div>
    </main>
  );
}

function DemandCard({
  item,
  featured,
  saved,
  onToggleSaved,
  onOpen,
}: {
  item: RequirementSummary;
  featured: boolean;
  saved: boolean;
  onToggleSaved: () => void;
  onOpen: () => void;
}) {
  const matchScore = item.matchScore;
  const remaining = remainingDays(item.desiredDeliveryAt);
  return (
    <article className={`demand-market-card ${featured ? 'is-featured' : ''}`}>
      <div className="demand-market-match-score">
        <span>AI 匹配</span>
        <strong>{matchScore === undefined ? '待评估' : `${matchScore}%`}</strong>
        <small>{item.matchedServiceName || '选择服务后评估'}</small>
      </div>
      <div className="demand-market-card-main">
        <header>{featured ? <span className="demand-market-best"><Star />最佳推荐</span> : null}<span className="demand-market-category">{item.category}</span><span className={`marketplace-status is-${item.status}`}>{item.status === 'quoting' ? '报价中' : '公开招募'}</span></header>
        <h2>{item.title}</h2>
        <p>{item.matchReasons?.length ? item.matchReasons.slice(0, 2).join(' · ') : '需求已公开，查看详情后选择适合的服务参与。'}</p>
        <footer><span><Building2 />{item.buyerOrganizationName}</span><span><Clock3 />{formatRelativeTime(item.updatedAt)}</span></footer>
      </div>
      <dl className="demand-market-card-meta">
        <div><dt><Wallet />预算</dt><dd>¥{money(item.budgetMinAmount)}–{money(item.budgetMaxAmount)}</dd></div>
        <div><dt><CalendarDays />期望完成</dt><dd>{item.desiredDeliveryAt ? formatDate(item.desiredDeliveryAt) : '待协商'}{remaining !== null ? <small>{remaining >= 0 ? `还有 ${remaining} 天` : '已到期'}</small> : null}</dd></div>
      </dl>
      <div className="demand-market-actions"><button type="button" className="demand-market-open" onClick={onOpen}>查看并报价<ChevronRight /></button><button type="button" className={`demand-market-save ${saved ? 'is-saved' : ''}`} aria-label={saved ? `取消收藏${item.title}` : `收藏${item.title}`} onClick={onToggleSaved}><Star />{saved ? '已收藏' : '收藏'}</button></div>
    </article>
  );
}

function SortButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return <button type="button" role="tab" aria-selected={active} className={active ? 'is-active' : ''} onClick={onClick}>{children}</button>;
}

function budgetMatches(item: RequirementSummary, filter: string) {
  const max = Number(item.budgetMaxAmount);
  if (filter === 'under10k') return max <= 10_000;
  if (filter === '10k50k') return max > 10_000 && max <= 50_000;
  if (filter === 'over50k') return max > 50_000;
  return true;
}

function deliveryMatches(item: RequirementSummary, filter: string, now: number) {
  if (filter === 'all') return true;
  const deadline = item.desiredDeliveryAt ? Date.parse(item.desiredDeliveryAt) : Number.POSITIVE_INFINITY;
  const days = filter === '7d' ? 7 : 30;
  return deadline >= now && deadline <= now + days * 86_400_000;
}

function remainingDays(value?: string) {
  if (!value) return null;
  return Math.ceil((Date.parse(value) - Date.now()) / 86_400_000);
}

function money(value: string) { return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 }); }
function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(new Date(value)); }
function formatRelativeTime(value: string) {
  const hours = Math.max(1, Math.round((Date.now() - Date.parse(value)) / 3_600_000));
  if (hours < 24) return `${hours} 小时前更新`;
  return `${Math.round(hours / 24)} 天前更新`;
}
