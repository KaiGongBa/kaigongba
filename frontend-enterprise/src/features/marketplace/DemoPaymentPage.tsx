import {
  AlertCircle,
  ArrowLeft,
  Ban,
  Check,
  CheckCircle2,
  Clock3,
  Copy,
  CreditCard,
  FileCheck2,
  FlaskConical,
  Info,
  PackageCheck,
  RotateCcw,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { notify } from '@/components/ui/app-toast';

import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { PaymentOrder } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type DemoResult = 'success' | 'failed' | 'cancelled' | 'timeout';

const RESULT_OPTIONS: Array<{
  value: DemoResult;
  title: string;
  description: string;
  icon: typeof CheckCircle2;
}> = [
  { value: 'success', title: '成功支付', description: '验签通过后创建订单', icon: CheckCircle2 },
  { value: 'failed', title: '支付失败', description: '记录失败回调', icon: XCircle },
  { value: 'cancelled', title: '用户取消', description: '记录取消支付', icon: Ban },
  { value: 'timeout', title: '超时', description: '记录支付超时无回调', icon: Clock3 },
];

export default function DemoPaymentPage() {
  const navigate = useNavigate();
  const { paymentOrderId = '' } = useParams();
  const organization = useMarketplaceOrganization();
  const [latest, setLatest] = useState<PaymentOrder>();
  const [result, setResult] = useState<DemoResult>('success');
  const [confirmationCode, setConfirmationCode] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [working, setWorking] = useState(false);
  const [callbackId, setCallbackId] = useState(() => `web-${crypto.randomUUID()}`);
  const resource = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.getPaymentOrder(paymentOrderId, organization.selected.id)
      : Promise.reject(new Error('请切换到支付单参与企业')),
    `payment:${paymentOrderId}:${organization.selected?.id || 'none'}`,
  );

  useEffect(() => {
    setLatest(undefined);
  }, [paymentOrderId, organization.selected?.id]);

  const payment = latest || resource.data;
  const callbackRows = useMemo(
    () => Object.entries(payment?.callbackPreview || {}),
    [payment?.callbackPreview],
  );
  const succeeded = payment?.status === 'succeeded';
  const pending = payment?.status === 'pending';

  async function simulate() {
    if (!payment || !organization.selected || !acknowledged) {
      notify.error('请确认本次操作仅用于演示支付');
      return;
    }
    if (!confirmationCode.trim()) {
      notify.error('请输入管理员演示支付确认码');
      return;
    }
    const resultText = RESULT_OPTIONS.find((item) => item.value === result)?.title || result;
    if (!window.confirm(`确定模拟“${resultText}”结果？本次回调会写入真实支付事件${result === 'success' ? '并生成真实订单' : ''}。`)) return;
    setWorking(true);
    try {
      const updated = await marketplaceRepository.simulateDemoPayment(payment.id, {
        organization_id: organization.selected.id,
        result,
        confirmation_code: confirmationCode.trim(),
        callback_id: callbackId,
        acknowledged_demo: true,
      });
      setLatest(updated);
      setConfirmationCode('');
      notify.success(updated.orderId ? `支付回调处理完成，订单 ${updated.orderCode} 已生成` : '支付回调处理完成');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '演示支付处理失败');
    } finally {
      setWorking(false);
    }
  }

  function resetCallback() {
    setCallbackId(`web-${crypto.randomUUID()}`);
    notify.success('已生成新的回调幂等键');
  }

  return (
    <main className="marketplace-page marketplace-management-page transaction-page">
      <MarketplaceHeader
        breadcrumb={(
          <button
            type="button"
            className="marketplace-breadcrumb"
            onClick={() => navigate(payment ? `/enterprise/agreements/${payment.agreementId}` : '/enterprise/orders')}
          >
            <ArrowLeft /><strong>我的订单</strong><span>/ 待付款 / {payment?.code || paymentOrderId}</span>
          </button>
        )}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {payment && (
        <>
          <div className="transaction-agreement-steps transaction-payment-steps">
            <span className="is-done"><Check /><b>配置服务</b><small>已完成</small></span>
            <span className="is-done"><Check /><b>确认协议</b><small>已完成</small></span>
            <span className={succeeded ? 'is-done' : 'is-active'}><CreditCard /><b>演示支付</b><small>{paymentStatus(payment.status)}</small></span>
            <span className={succeeded ? 'is-done' : ''}><PackageCheck /><b>创建订单</b><small>{payment.orderCode || '支付成功后完成'}</small></span>
          </div>

          <section className="transaction-demo-notice">
            <AlertCircle />
            <strong>演示支付环境</strong>
            <span>不会产生真实扣款；后续接入持牌支付渠道时沿用相同支付单与回调状态模型。</span>
            <button type="button" onClick={() => notify.info('演示支付只替代资金渠道；支付单、回调事件、订单和里程碑均为真实业务数据。')}>演示说明</button>
          </section>

          <div className="transaction-payment-layout">
            <div className="transaction-payment-main">
              <section className="transaction-card transaction-payment-choice">
                <h2>1. 选择支付方式 <small>（仅演示支付）</small></h2>
                <article className="is-selected">
                  <CheckCircle2 />
                  <span><FlaskConical /></span>
                  <div><strong>演示支付（模拟环境）</strong><small>管理员发起模拟结果，用于演示全流程与回调处理，不会产生真实扣款。</small></div>
                  <em>当前环境</em>
                </article>
                <h2>2. 选择模拟结果</h2>
                <div className="transaction-result-options">
                  {RESULT_OPTIONS.map((option) => {
                    const Icon = option.icon;
                    return (
                      <button
                        type="button"
                        key={option.value}
                        className={result === option.value ? 'is-selected' : ''}
                        disabled={!pending}
                        onClick={() => setResult(option.value)}
                      >
                        <span>{result === option.value ? <CheckCircle2 /> : null}</span>
                        <Icon />
                        <strong>{option.title}</strong>
                        <small>{option.description}</small>
                      </button>
                    );
                  })}
                </div>
                <p className="transaction-payment-hint"><Info />平台仍会执行回调验签、幂等去重、状态校验和审计留痕。</p>
              </section>

              <div className="transaction-payment-lower">
                <div className="transaction-payment-column">
                  <section className="transaction-card transaction-callback-preview">
                    <h2>3. 回调（Callback）预览</h2>
                    <dl>
                      {callbackRows.map(([key, value]) => (
                        <div key={key}>
                          <dt>{callbackLabel(key)} <small>（{key}）</small></dt>
                          <dd>{String(value)}</dd>
                        </div>
                      ))}
                      <div><dt>幂等键 <small>（idempotency_key）</small></dt><dd>{payment.idempotencyKey}</dd></div>
                    </dl>
                    <p><ShieldCheck />签名原文与密钥不在页面展示；后端仅留存验签摘要与处理结果。</p>
                  </section>

                  <section className="transaction-card transaction-admin-confirm">
                    <h2>4. 管理员验证 <small>（演示专用）</small></h2>
                    {payment.canSimulate ? (
                      <>
                        <p>请输入管理员确认码以执行模拟结果：</p>
                        <input
                          type="password"
                          value={confirmationCode}
                          disabled={!pending}
                          onChange={(event) => setConfirmationCode(event.target.value)}
                          placeholder="请输入管理员演示支付确认码"
                          autoComplete="off"
                        />
                        <small>确认码仅用于防止误操作，不属于真实支付凭证。</small>
                      </>
                    ) : (
                      <p className="transaction-warning"><ShieldCheck />当前账号或企业身份仅可查看支付单；模拟回调需要平台管理员在采购方企业下操作。</p>
                    )}
                  </section>
                </div>

                <section className="transaction-card transaction-event-timeline">
                  <h2>5. 流程事件时间线</h2>
                  {payment.events.map((event, index) => (
                    <article className={event.resultStatus === 'succeeded' || index === 0 ? 'is-done' : ''} key={event.id}>
                      <span>{event.resultStatus === 'succeeded' || index === 0 ? <Check /> : <Clock3 />}</span>
                      <div>
                        <strong>{eventName(event.eventType, event.resultStatus)}</strong>
                        <small>{event.signatureValid ? '回调验签通过并完成幂等处理' : '支付单已创建，等待支付'}</small>
                      </div>
                      <time>{formatDateTime(event.createdAt)}</time>
                    </article>
                  ))}
                  {!succeeded && <article><span /><div><strong>订单已支付（将创建）</strong><small>成功回调落库后幂等生成订单</small></div><time>—</time></article>}
                  {!succeeded && <article><span /><div><strong>管理员人工复核（如需）</strong><small>异常结果可进入平台复核</small></div><time>—</time></article>}
                </section>
              </div>
            </div>

            <aside className="transaction-payment-aside">
              <section className="transaction-card transaction-payment-summary">
                <h2>支付单</h2>
                <dl>
                  <div><dt>协议编号</dt><dd>{payment.agreementCode}</dd></div>
                  <div><dt>支付单号</dt><dd>{payment.code}<button type="button" aria-label="复制支付单号" onClick={() => void navigator.clipboard.writeText(payment.code)}><Copy /></button></dd></div>
                  <div><dt>采购方（甲方）</dt><dd>{payment.buyerName}</dd></div>
                  <div><dt>服务方（乙方）</dt><dd>{payment.providerName}</dd></div>
                  <div><dt>服务内容</dt><dd>{payment.serviceName}</dd></div>
                  <div><dt>服务版本</dt><dd>{payment.serviceVersion || '-'}</dd></div>
                </dl>
                <hr />
                <div className="transaction-payment-total"><span>服务总价</span><strong>¥ {money(payment.amount)}</strong></div>
                <h3>里程碑分配</h3>
                {payment.milestones.map((item) => <p key={item.sequence}><span>· {item.name}</span><b>¥ {money(item.amount)}</b></p>)}
                <div className="transaction-payment-due"><span>应付金额（本次）</span><strong>¥ {money(payment.amount)}</strong></div>
                <hr />
                <dl>
                  <div><dt>协议状态</dt><dd className="is-success"><CheckCircle2 />双方已确认</dd></div>
                  <div><dt>支付状态</dt><dd>{paymentStatus(payment.status)}</dd></div>
                  <div><dt>订单编号</dt><dd>{payment.orderCode || '待支付成功后生成'}</dd></div>
                </dl>
              </section>

              <section className="transaction-card transaction-payment-action">
                {succeeded ? (
                  <>
                    <span className="transaction-success"><PackageCheck />演示支付成功，真实订单已生成。</span>
                    <button type="button" className="marketplace-submit-button" onClick={() => navigate('/enterprise/orders')}>查看订单</button>
                  </>
                ) : pending ? (
                  <>
                    <label><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />我确认本页为演示支付，不会真实扣款，业务记录将真实写入。</label>
                    <button type="button" className="marketplace-submit-button" disabled={!payment.canSimulate || !acknowledged || working} onClick={() => void simulate()}>{working ? '正在处理回调…' : `模拟${RESULT_OPTIONS.find((item) => item.value === result)?.title || ''}${result === 'success' ? '并创建订单' : ''}`}</button>
                  </>
                ) : (
                  <>
                    <span className="transaction-warning"><AlertCircle />本支付单已进入“{paymentStatus(payment.status)}”终态，不能修改。</span>
                    <button type="button" className="marketplace-submit-button" onClick={() => navigate(`/enterprise/agreements/${payment.agreementId}`)}>返回协议创建新支付单</button>
                  </>
                )}
                <button type="button" className="marketplace-secondary-button" onClick={() => navigate(`/enterprise/agreements/${payment.agreementId}`)}>返回协议</button>
                {pending && <button type="button" className="marketplace-link-button" onClick={resetCallback}><RotateCcw />更换本次回调幂等键</button>}
                <p><FileCheck2 />支付结果会写入不可覆盖的事件记录，并通过幂等键防止重复创建订单。</p>
              </section>
            </aside>
          </div>
        </>
      )}
    </main>
  );
}

function callbackLabel(value: string) {
  return {
    payment_order_id: '支付单号',
    payment_code: '支付单编号',
    agreement_id: '协议主键',
    amount: '金额',
    currency: '币种',
    channel: '渠道',
    result: '状态',
    callback_id: '回调编号',
    occurred_at: '发生时间',
  }[value] || value;
}

function eventName(type: string, status?: string) {
  if (type === 'payment_order.created') return '创建支付单';
  if (type === 'payment.callback.processed') return `回调处理 · ${paymentStatus(status || '')}`;
  return type;
}

function paymentStatus(value: string) {
  return {
    pending: '待支付',
    succeeded: '支付成功',
    failed: '支付失败',
    cancelled: '已取消',
    timed_out: '已超时',
  }[value] || value;
}

function money(value: string) {
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value));
}
