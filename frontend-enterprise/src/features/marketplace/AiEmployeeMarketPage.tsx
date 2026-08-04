import { useMemo, useState } from 'react';
import { ArrowRight, CheckCircle2, ChevronLeft, ChevronRight, ShieldCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { EnterpriseRoute } from '@/enums/routes';
import {
  CompactStat,
  FilterSelect,
  MarketSectionTitle,
  MarketplaceHeader,
  MarketplaceNotice,
  MarketplaceState,
  MarketTabs,
  VerificationBadge,
} from './components';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';
import type { AiService } from './types';

type MarketTab = 'recommended' | 'all' | 'mine' | 'gallery' | 'subscribed' | 'publishing';

const tabItems: Array<{ value: MarketTab; label: string }> = [
  { value: 'recommended', label: '推荐' },
  { value: 'all', label: '所有员工' },
  { value: 'mine', label: '我的数字员工' },
  { value: 'gallery', label: '数字员工广场' },
  { value: 'subscribed', label: '已订阅' },
  { value: 'publishing', label: '我的发布' },
];

const pageSize = 6;

export default function AiEmployeeMarketPage() {
  const navigate = useNavigate();
  const organization = useMarketplaceOrganization();
  const [keyword, setKeyword] = useState('');
  const [tab, setTab] = useState<MarketTab>('recommended');
  const [category, setCategory] = useState('all');
  const [deliveryFormat, setDeliveryFormat] = useState('all');
  const [price, setPrice] = useState('all');
  const [verified, setVerified] = useState('verified');
  const [sort, setSort] = useState('recommended');
  const [page, setPage] = useState(1);

  const resource = useMarketplaceResource(
    () => marketplaceRepository.listAiServices({
      organizationId: organization.selected?.id,
    }),
    `ai-services:${organization.selected?.id || 'all'}`,
  );

  const filtered = useMemo(() => {
    const query = {
      keyword,
      category,
      deliveryFormat,
      price,
      verified: verified === 'verified',
      scope: tab === 'subscribed' ? 'subscribed' as const : tab === 'mine' || tab === 'publishing' ? 'mine' as const : 'all' as const,
    };
    let items = resource.data?.items || [];
    items = items.filter((item) => {
      const haystack = `${item.name} ${item.category} ${item.provider} ${item.description}`.toLocaleLowerCase();
      if (keyword.trim() && !haystack.includes(keyword.trim().toLocaleLowerCase())) return false;
      if (category !== 'all' && item.category !== category) return false;
      if (deliveryFormat !== 'all' && item.deliveryFormat !== deliveryFormat) return false;
      if (verified === 'verified' && !item.verified) return false;
      if (price === 'under-100' && !(item.price < 100)) return false;
      if (price === '100-200' && !(item.price >= 100 && item.price <= 200)) return false;
      if (price === 'over-200' && !(item.price > 200)) return false;
      if (query.scope === 'subscribed' && !item.subscribed) return false;
      if (query.scope === 'mine' && !item.mine) return false;
      return true;
    });
    if (sort === 'rating') items = [...items].sort((a, b) => b.rating - a.rating);
    if (sort === 'orders') items = [...items].sort((a, b) => b.completedOrders - a.completedOrders);
    if (sort === 'price-low') items = [...items].sort((a, b) => a.price - b.price);
    return items;
  }, [category, deliveryFormat, keyword, price, resource.data?.items, sort, tab, verified]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const visibleItems = filtered.slice((Math.min(page, totalPages) - 1) * pageSize, Math.min(page, totalPages) * pageSize);
  const common = (resource.data?.items || []).filter((item) => item.subscribed).slice(0, 4);

  function resetFilters() {
    setCategory('all');
    setDeliveryFormat('all');
    setPrice('all');
    setVerified('verified');
    setKeyword('');
    setPage(1);
  }

  function openService(service: AiService) {
    navigate(`${EnterpriseRoute.AiEmployeeMarket}/${service.id}`);
  }

  return (
    <main className="marketplace-page marketplace-page--listing">
      <MarketplaceHeader
        title="AI员工市场"
        searchValue={keyword}
        onSearchChange={(value) => {
          setKeyword(value);
          setPage(1);
        }}
        searchPlaceholder="搜索AI员工、服务能力或交付场景"
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />

      <MarketTabs
        items={tabItems}
        value={tab}
        onChange={(next) => {
          setTab(next);
          setPage(1);
        }}
      />

      <div className="marketplace-toolbar">
        <div className="marketplace-toolbar__filters">
          <FilterSelect
            label="行业"
            value={category}
            onChange={(value) => { setCategory(value); setPage(1); }}
            options={[
              { value: 'all', label: '全部行业' },
              { value: '企业合同风控', label: '法务合规' },
              { value: '财务分析', label: '财务分析' },
              { value: '人才引擎', label: '招聘人事' },
              { value: '客户服务', label: '客户服务' },
            ]}
          />
          <FilterSelect
            label="交付形式"
            value={deliveryFormat}
            onChange={(value) => { setDeliveryFormat(value); setPage(1); }}
            options={[
              { value: 'all', label: '交付形式' },
              { value: '文档', label: '文档' },
              { value: '表格', label: '表格' },
              { value: '报告', label: '报告' },
              { value: '工作流', label: '工作流' },
            ]}
          />
          <FilterSelect
            label="价格区间"
            value={price}
            onChange={(value) => { setPrice(value); setPage(1); }}
            options={[
              { value: 'all', label: '价格区间' },
              { value: 'under-100', label: '¥100 以下' },
              { value: '100-200', label: '¥100–200' },
              { value: 'over-200', label: '¥200 以上' },
            ]}
          />
          <FilterSelect
            label="验证状态"
            value={verified}
            onChange={(value) => { setVerified(value); setPage(1); }}
            options={[
              { value: 'verified', label: '已验证' },
              { value: 'all', label: '全部状态' },
            ]}
          />
          <button type="button" className="marketplace-clear-filter" onClick={resetFilters}>清空筛选</button>
        </div>
        <FilterSelect
          label="排序"
          value={sort}
          onChange={setSort}
          options={[
            { value: 'recommended', label: '综合排序' },
            { value: 'rating', label: '评分最高' },
            { value: 'orders', label: '成交最多' },
            { value: 'price-low', label: '价格最低' },
          ]}
        />
      </div>

      <div className="marketplace-listing-layout">
        <section className="min-w-0">
          <MarketplaceNotice
            action={(
              <button type="button" className="marketplace-primary-button" onClick={() => navigate(EnterpriseRoute.DemandCreate)}>
                发布需求
              </button>
            )}
          >
            <strong>告诉平台你的需求，AI 为你匹配合适员工</strong>
            <span>描述任务目标与要求，平台将为你推荐最合适的 AI 员工</span>
          </MarketplaceNotice>

          <MarketplaceState
            loading={resource.loading}
            error={resource.error}
            empty={!resource.loading && !resource.error && visibleItems.length === 0}
            onRetry={resource.reload}
          />

          {!resource.loading && !resource.error && visibleItems.length > 0 && (
            <div className="ai-service-grid">
              {visibleItems.map((service) => (
                <article className="ai-service-card" key={service.id}>
                  <div className="ai-service-card__identity">
                    <img src={service.avatar} alt="" />
                    <div>
                      <div className="ai-service-card__name">
                        <h2>{service.name}</h2>
                        {service.verified && <VerificationBadge state="verified-service" compact />}
                      </div>
                      <span>{service.provider}</span>
                      <small><i />已验证</small>
                    </div>
                  </div>
                  <p>{service.description}</p>
                  <div className="ai-service-card__stats">
                    <CompactStat value={service.rating.toFixed(1)} label="评分" />
                    <CompactStat value={service.completedOrders.toLocaleString()} label="调用量" />
                    <CompactStat value={`${service.onTimeRate}%`} label="好评率" />
                  </div>
                  <div className="ai-service-card__footer">
                    <div className="marketplace-price">
                      <strong>¥{service.price}</strong><span>/{service.priceUnit}</span>
                      <small>平均响应 {service.averageMinutes} 分钟</small>
                    </div>
                    <div className="ai-service-card__actions">
                      <button type="button" className="marketplace-secondary-button" onClick={() => openService(service)}>查看详情</button>
                      <button type="button" className="marketplace-primary-button" onClick={() => openService(service)}>立即调用</button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}

          <footer className="marketplace-pagination">
            <span>共 {filtered.length || resource.data?.total || 0} 位AI员工</span>
            <div>
              <button type="button" aria-label="上一页" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft /></button>
              {Array.from({ length: Math.min(5, totalPages) }, (_, index) => index + 1).map((value) => (
                <button type="button" className={value === page ? 'is-active' : ''} key={value} onClick={() => setPage(value)}>{value}</button>
              ))}
              {totalPages > 5 && <span>…</span>}
              <button type="button" aria-label="下一页" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}><ChevronRight /></button>
            </div>
          </footer>
        </section>

        <aside className="marketplace-listing-aside">
          <div className="marketplace-side-card">
            <MarketSectionTitle title="我的常用员工" action={<button type="button">全部 <ArrowRight /></button>} />
            <div className="common-ai-list">
              {common.map((service) => (
                <button type="button" key={service.id} onClick={() => openService(service)}>
                  <img src={service.avatar} alt="" />
                  <span><strong>{service.name}</strong><small>{service.provider}</small></span>
                  <em>★ {service.rating.toFixed(1)}</em>
                  <i>调用</i>
                </button>
              ))}
            </div>
          </div>
          <div className="marketplace-side-card">
            <MarketSectionTitle title="开放市场规则" action={<button type="button">查看全部 <ArrowRight /></button>} />
            <ul className="market-rules-list">
              <li><ShieldCheck /><span><strong>服务质量保障</strong><small>平台提供交易担保与质量保障机制。</small></span></li>
              <li><ShieldCheck /><span><strong>隐私与安全</strong><small>严格保护企业数据与隐私，AI 员工不得擅自访问敏感信息。</small></span></li>
              <li><CheckCircle2 /><span><strong>公平交易</strong><small>禁止虚假宣传与恶意竞争，违规行为将受到平台处罚。</small></span></li>
            </ul>
          </div>
        </aside>
      </div>
    </main>
  );
}
