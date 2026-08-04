import {
  ArrowLeft,
  Check,
  CheckCircle2,
  Clock3,
  FileCheck2,
  Layers3,
  LockKeyhole,
  Minus,
  Plus,
  ShieldCheck,
} from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { notify } from '@/components/ui/app-toast';

import { MarketplaceHeader, MarketplaceState, ProviderMark } from './components';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

function clampQuantity(value: string | null): number {
  const parsed = Number(value || 1);
  return Number.isInteger(parsed) ? Math.min(99, Math.max(1, parsed)) : 1;
}

function newCheckoutKey(): string {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  return `web-direct-checkout-${suffix}`;
}

export default function DirectServiceCheckoutPage() {
  const navigate = useNavigate();
  const { serviceId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const organization = useMarketplaceOrganization();
  const [quantity, setQuantity] = useState(() => clampQuantity(searchParams.get('quantity')));
  const [expectedDate, setExpectedDate] = useState(() => searchParams.get('expected_date') || '');
  const [buyerNote, setBuyerNote] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [working, setWorking] = useState(false);
  const idempotencyKey = useRef(newCheckoutKey());
  const resource = useMarketplaceResource(
    () => marketplaceRepository.getAiService(serviceId, organization.selected?.id),
    `direct-checkout:${serviceId}:${organization.selected?.id || 'none'}`,
  );
  const service = resource.data;
  const currentVersion = service?.versions.find((version) => version.current) || service?.versions[0];
  const total = useMemo(() => (service?.price || 0) * quantity, [quantity, service?.price]);

  async function createAgreement() {
    if (!service || !organization.selected) {
      notify.error('请先选择本次采购所属企业');
      return;
    }
    if (service.mine) {
      notify.error('不能购买自己所属企业发布的服务');
      return;
    }
    if (!acknowledged) {
      notify.error('请先确认当前服务版本、交付范围与演示支付说明');
      return;
    }
    const desiredDeliveryAt = expectedDate
      ? new Date(`${expectedDate}T23:59:59`).toISOString()
      : undefined;
    setWorking(true);
    try {
      const agreement = await marketplaceRepository.createDirectServiceCheckout(service.id, {
        organization_id: organization.selected.id,
        service_version: currentVersion?.version,
        quantity,
        desired_delivery_at: desiredDeliveryAt,
        buyer_note: buyerNote.trim(),
        idempotency_key: idempotencyKey.current,
      });
      notify.success('购买配置已冻结，合作协议已经生成');
      navigate(`/enterprise/agreements/${agreement.id}`);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '生成合作协议失败');
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="marketplace-page marketplace-management-page transaction-page direct-checkout-page">
      <MarketplaceHeader
        breadcrumb={(
          <button
            type="button"
            className="marketplace-breadcrumb"
            onClick={() => navigate(service ? `/enterprise/market/agents/${service.id}` : '/enterprise/market/agents')}
          >
            <ArrowLeft />
            <strong>AI员工市场</strong>
            <span>/ {service?.name || '确认购买配置'}</span>
          </button>
        )}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />

      {service && (
        <>
          <div className="transaction-agreement-steps direct-checkout-steps">
            <span className="is-active"><Layers3 /><b>确认服务配置</b><small>冻结当前版本</small></span>
            <span><ShieldCheck /><b>双方确认协议</b><small>使用登录账号确认</small></span>
            <span><Clock3 /><b>演示支付</b><small>不会真实扣款</small></span>
            <span><CheckCircle2 /><b>生成真实订单</b><small>进入SOP与交付</small></span>
          </div>

          {service.mine && (
            <section className="transaction-demo-notice is-danger">
              <ShieldCheck />
              <strong>禁止自购</strong>
              <span>当前服务由你所属企业发布，请切换到与服务方无关联的采购账号验证真实交易。</span>
            </section>
          )}

          <div className="direct-checkout-layout">
            <div className="direct-checkout-main">
              <section className="transaction-card direct-checkout-service-card">
                <div className="direct-checkout-service-summary">
                  <img src={service.avatar} alt="" />
                  <div>
                    <span>{service.category}</span>
                    <h1>{service.name}</h1>
                    <p>{service.description}</p>
                    <small><ProviderMark name={service.provider} />服务商：{service.provider}</small>
                  </div>
                  <em>{currentVersion?.version || '当前版本'}</em>
                </div>
              </section>

              <section className="transaction-card">
                <h2><Layers3 />采购配置</h2>
                <div className="direct-checkout-fields">
                  <label>
                    <span>购买数量</span>
                    <div className="quantity-stepper">
                      <button type="button" aria-label="减少数量" onClick={() => setQuantity((value) => Math.max(1, value - 1))}><Minus /></button>
                      <strong>{quantity}</strong>
                      <button type="button" aria-label="增加数量" onClick={() => setQuantity((value) => Math.min(99, value + 1))}><Plus /></button>
                    </div>
                  </label>
                  <label>
                    <span>期望完成时间</span>
                    <input type="date" value={expectedDate} onChange={(event) => setExpectedDate(event.target.value)} />
                    <small>不填写时按服务版本的预计时效计算。</small>
                  </label>
                </div>
                <label>
                  <span>采购补充说明（选填）</span>
                  <textarea
                    value={buyerNote}
                    maxLength={2000}
                    placeholder="说明本次使用场景、需提供的材料或其他约束；价格、范围和验收标准的变更仍需双方结构化确认。"
                    onChange={(event) => setBuyerNote(event.target.value)}
                  />
                </label>
              </section>

              <section className="transaction-card direct-checkout-snapshot">
                <h2><LockKeyhole />成交时冻结的服务快照</h2>
                <div className="direct-checkout-snapshot-grid">
                  <div>
                    <h3>服务范围</h3>
                    <ul>{service.serviceScope.map((item) => <li key={item}><Check />{item}</li>)}</ul>
                  </div>
                  <div>
                    <h3>不包含</h3>
                    {service.exclusions.length
                      ? <ul className="is-exclusion">{service.exclusions.map((item) => <li key={item}><Minus />{item}</li>)}</ul>
                      : <p>当前版本未声明额外排除项。</p>}
                  </div>
                </div>
              </section>

              <section className="transaction-card direct-checkout-delivery">
                <h2><FileCheck2 />交付物与验收标准</h2>
                <div>
                  {service.deliverables.map((item) => (
                    <article key={item.name}>
                      <FileCheck2 />
                      <span><strong>{item.name}</strong><small>{item.format} · {item.size}</small></span>
                    </article>
                  ))}
                </div>
                <ol>{service.acceptanceCriteria.map((item, index) => <li key={item}><i>{index + 1}</i>{item}</li>)}</ol>
              </section>
            </div>

            <aside className="direct-checkout-aside">
              <section className="transaction-card direct-checkout-price-card">
                <h2>订单金额</h2>
                <dl>
                  <div><dt>服务单价</dt><dd>¥ {service.price.toLocaleString('zh-CN')}</dd></div>
                  <div><dt>购买数量</dt><dd>× {quantity}</dd></div>
                  <div><dt>平台服务费</dt><dd>¥ 0.00</dd></div>
                  <div className="is-total"><dt>协议总额</dt><dd>¥ {total.toLocaleString('zh-CN')}</dd></div>
                </dl>
                <p><LockKeyhole />服务版本、价格、范围、交付物与验收标准将在生成协议时冻结。</p>
              </section>

              <section className="transaction-card direct-checkout-buyer-card">
                <h2>采购主体</h2>
                <strong>{organization.selected?.name || '尚未选择企业'}</strong>
                <small>协议和后续订单将归属于当前企业。</small>
              </section>

              <section className="transaction-card direct-checkout-submit-card">
                <label className="direct-checkout-acknowledgement">
                  <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
                  <span>我已核对当前服务版本和交付规则，并知晓下一步需要双方在线确认协议；支付环节仅为演示支付，不会真实扣款。</span>
                </label>
                <button
                  type="button"
                  className="marketplace-submit-button"
                  disabled={working || service.mine || !organization.selected || !acknowledged}
                  onClick={() => void createAgreement()}
                >
                  {working ? '正在生成协议…' : '生成合作协议'}
                </button>
                <button type="button" className="marketplace-secondary-button" onClick={() => navigate(`/enterprise/market/agents/${service.id}`)}>返回服务详情</button>
              </section>
            </aside>
          </div>
        </>
      )}
    </main>
  );
}
