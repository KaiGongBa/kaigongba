import { useMemo, useState } from 'react';
import {
  ArrowRight,
  CalendarDays,
  Check,
  ChevronLeft,
  FileSpreadsheet,
  FileText,
  LockKeyhole,
  Minus,
  PencilLine,
  ShieldCheck,
  Star,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { EnterpriseRoute } from '@/enums/routes';
import {
  CompactStat,
  MarketplaceHeader,
  MarketplaceState,
  MarketTabs,
  ProviderMark,
  VerificationBadge,
} from './components';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type ServiceTab = 'intro' | 'capability' | 'delivery' | 'versions' | 'reviews';

const tabs: Array<{ value: ServiceTab; label: string }> = [
  { value: 'intro', label: '服务介绍' },
  { value: 'capability', label: '能力与SOP' },
  { value: 'delivery', label: '交付与验收' },
  { value: 'versions', label: '服务版本' },
  { value: 'reviews', label: '评价（128）' },
];

export default function AiEmployeeDetailPage() {
  const navigate = useNavigate();
  const { employeeId = '' } = useParams();
  const organization = useMarketplaceOrganization();
  const [tab, setTab] = useState<ServiceTab>('intro');
  const [quantity, setQuantity] = useState(1);
  const [expectedDate, setExpectedDate] = useState('');
  const resource = useMarketplaceResource(
    () => marketplaceRepository.getAiService(employeeId, organization.selected?.id),
    `${employeeId}:${organization.selected?.id || 'all'}`,
  );

  const service = resource.data;
  const total = useMemo(() => (service?.price || 0) * quantity, [quantity, service?.price]);

  function startOrder() {
    if (!service) return;
    const params = new URLSearchParams({
      quantity: String(quantity),
      service_version: service.versions.find((version) => version.current)?.version || service.versions[0]?.version || '',
    });
    if (expectedDate) params.set('expected_date', expectedDate);
    navigate(`/enterprise/services/${service.id}/order?${params.toString()}`);
  }

  return (
    <main className="marketplace-page marketplace-page--detail">
      <MarketplaceHeader
        breadcrumb={(
          <button type="button" className="marketplace-breadcrumb" onClick={() => navigate(EnterpriseRoute.AiEmployeeMarket)}>
            <ChevronLeft />
            <span>AI员工市场</span>
            <i>/</i>
            <strong>{service?.name || '服务详情'}</strong>
          </button>
        )}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />

      {service && (
        <div className="service-detail-layout">
          <section className="service-detail-main">
            <article className="service-hero-card">
              <img className="service-hero-card__avatar" src={service.avatar} alt="" />
              <div className="service-hero-card__content">
                <div className="service-hero-card__title">
                  <h1>{service.name}</h1>
                  <span>{service.category}</span>
                  <i>在线</i>
                  <VerificationBadge state="verified-service" />
                </div>
                <div className="service-provider-line">
                  <span>发布者：{service.provider}</span>
                  <button type="button" onClick={() => notify.info('服务商主页将在供给侧页面接入')}>查看主页 <ArrowRight /></button>
                </div>
                <p>{service.description}</p>
                <div className="service-hero-card__stats">
                  <CompactStat value={service.completedOrders.toLocaleString()} label="已完成订单" />
                  <CompactStat value={<><Star />{service.rating.toFixed(1)}</>} label="评分" />
                  <CompactStat value={`${service.onTimeRate}%`} label="按时交付" />
                </div>
              </div>
            </article>

            <MarketTabs items={tabs} value={tab} onChange={setTab} />

            {tab === 'intro' && (
              <div className="service-detail-stack">
                <div className="service-scope-grid">
                  <section className="marketplace-panel">
                    <h2><ShieldCheck />服务范围</h2>
                    <ul className="check-list">
                      {service.serviceScope.map((item) => <li key={item}><Check />{item}</li>)}
                    </ul>
                  </section>
                  <section className="marketplace-panel">
                    <h2><Minus />不包含</h2>
                    <ul className="dot-list">
                      {service.exclusions.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </section>
                </div>

                <section className="marketplace-panel">
                  <h2><FileText />交付物</h2>
                  <div className="deliverable-list">
                    {service.deliverables.map((item, index) => (
                      <button type="button" key={item.name} onClick={() => notify.info('这是交付物格式示例，正式订单文件由权限接口签发临时下载地址')}>
                        {index === 2 ? <FileSpreadsheet /> : <FileText />}
                        <span><strong>{item.name}</strong><small>{item.format} · {item.size}</small></span>
                        <ArrowRight />
                      </button>
                    ))}
                  </div>
                </section>

                <section className="marketplace-panel">
                  <h2>服务流程</h2>
                  <div className="service-process">
                    {service.process.map((step, index) => (
                      <div key={step.title}>
                        <i>{index + 1}</i>
                        <span><strong>{step.title}</strong><small>{step.description}</small></span>
                        {index < service.process.length - 1 && <ArrowRight />}
                      </div>
                    ))}
                  </div>
                </section>

                <section className="marketplace-panel">
                  <h2>验收标准</h2>
                  <ol className="acceptance-list">
                    {service.acceptanceCriteria.map((item, index) => <li key={item}><i>{index + 1}</i>{item}</li>)}
                  </ol>
                  <div className="private-capability-note">
                    <LockKeyhole />
                    内部提示词、私有知识库、密钥和内部成本不向采购方展示
                  </div>
                </section>
              </div>
            )}

            {tab === 'capability' && (
              <section className="marketplace-panel service-tab-panel">
                <h2>能力与已冻结 SOP 摘要</h2>
                <div className="capability-overview">
                  {service.process.map((step, index) => (
                    <div key={step.title}><i>{index + 1}</i><strong>{step.title}</strong><span>{step.description}</span></div>
                  ))}
                </div>
                <p>成交后订单仅引用成交时的服务版本与 SOP 快照；服务方后续修改模板不会影响已成交订单。</p>
              </section>
            )}

            {tab === 'delivery' && (
              <section className="marketplace-panel service-tab-panel">
                <h2>交付物与验收规则</h2>
                <p>每次提交都会形成不可覆盖的交付版本，记录提交时间、提交人和关联里程碑。</p>
                <ul className="check-list">
                  {service.acceptanceCriteria.map((item) => <li key={item}><Check />{item}</li>)}
                </ul>
              </section>
            )}

            {tab === 'versions' && (
              <section className="marketplace-panel service-tab-panel">
                <h2>服务版本</h2>
                <div className="version-list">
                  {service.versions.map((version) => (
                    <div key={version.version}>
                      <strong>{version.version}</strong>
                      {version.current && <span>当前版本</span>}
                      <time>{version.releasedAt}</time>
                      <p>{version.summary}</p>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {tab === 'reviews' && (
              <section className="marketplace-panel service-tab-panel">
                <h2>真实订单评价</h2>
                <div className="review-list">
                  <article><strong>交付结构清晰，风险条款定位准确。</strong><span>北京星云科技有限公司 · 已验证订单</span></article>
                  <article><strong>人工复核很有价值，修改建议可以直接使用。</strong><span>山海零售有限公司 · 已验证订单</span></article>
                </div>
              </section>
            )}
          </section>

          <aside className="service-detail-aside">
            <section className="marketplace-panel service-purchase-card">
              <div className="marketplace-price is-large">
                <strong>¥{service.price}</strong><span>/{service.priceUnit}</span>
              </div>
              <div className="service-purchase-meta">
                <span><CalendarDays />预计{service.averageMinutes}分钟</span>
                <span><PencilLine />含{service.includedRevisions}次修改</span>
              </div>
              <label>
                <span>购买数量</span>
                <div className="quantity-stepper">
                  <button type="button" aria-label="减少数量" onClick={() => setQuantity((value) => Math.max(1, value - 1))}>−</button>
                  <strong>{quantity}</strong>
                  <button type="button" aria-label="增加数量" onClick={() => setQuantity((value) => value + 1)}>+</button>
                </div>
              </label>
              <label className="service-date-field">
                <span>期望完成时间</span>
                <input type="date" value={expectedDate} onChange={(event) => setExpectedDate(event.target.value)} />
              </label>
              <div className="service-price-breakdown">
                <p><span>单价</span><strong>¥ {service.price}</strong></p>
                <p><span>数量</span><strong>× {quantity}</strong></p>
                <p><span>平台服务费（0%）</span><strong>¥ 0</strong></p>
                <p className="is-total"><span>合计</span><strong>¥ {total}</strong></p>
              </div>
              <button type="button" className="marketplace-primary-button is-wide" onClick={startOrder}>立即使用</button>
              <button type="button" className="marketplace-secondary-button is-wide" onClick={() => navigate(EnterpriseRoute.DemandCreate)}>发布需求询价</button>
              <small className="service-snapshot-note"><LockKeyhole />下单后冻结当前服务版本 {service.versions[0]?.version}</small>
            </section>

            <section className="marketplace-panel provider-trust-card">
              <h2>发布者与信任</h2>
              <div>
                <ProviderMark name={service.provider} />
                <span><strong>{service.provider}</strong><VerificationBadge state="verified-service" /><small>综合评分 {service.rating}　服务完成率 {service.onTimeRate}%</small></span>
              </div>
              <button type="button">查看主页 <ArrowRight /></button>
            </section>

            <section className="marketplace-panel sla-card">
              <h2>响应与交付 SLA</h2>
              <p><span>平均首次响应</span><strong>{service.responseMinutes} 分钟</strong></p>
              <p><span>平均交付时效</span><strong>{service.averageMinutes} 分钟</strong></p>
              <p><span>按时交付率</span><strong>{service.onTimeRate}%</strong></p>
              <p><span>退款保障</span><strong>不满意可申请退款</strong></p>
            </section>
          </aside>
        </div>
      )}
    </main>
  );
}
