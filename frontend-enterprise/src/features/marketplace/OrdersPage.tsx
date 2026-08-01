import {
  AlertCircle,
  ArrowRight,
  Bot,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  FileText,
  Filter,
  PackageCheck,
  PlayCircle,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { MarketplaceHeader, MarketplaceState } from './components';
import { TransactionSectionTabs } from './MarketplaceSectionTabs';
import { marketplaceRepository } from './repository';
import type { TransactionOrder } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';
import { normalizeOrderPerspective } from './uiMigrationContracts';

type OrderPerspective = 'buyer' | 'provider';

export default function OrdersPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const organization = useMarketplaceOrganization();
  const normalizedPerspective = normalizeOrderPerspective(searchParams.get('perspective'));
  const perspective: OrderPerspective = normalizedPerspective === 'provider' ? 'provider' : 'buyer';
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState('all');
  const [expanded, setExpanded] = useState<string>();
  const resource = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.listOrders(organization.selected.id, perspective)
      : Promise.resolve([]),
    `orders:${organization.selected?.id || 'none'}:${perspective}`,
  );
  const orders = resource.data || [];
  const filtered = useMemo(
    () => orders.filter((order) => {
      const matchesText = [order.code, order.title, order.serviceName, order.buyerName, order.providerName]
        .some((value) => value.toLocaleLowerCase().includes(keyword.trim().toLocaleLowerCase()));
      return matchesText && (status === 'all' || order.status === status);
    }),
    [keyword, orders, status],
  );
  const counts = useMemo(() => ({
    pending: orders.filter((item) => ['paid', 'pending'].includes(item.status)).length,
    running: orders.filter((item) => ['in_progress', 'running'].includes(item.status)).length,
    acceptance: orders.filter((item) => ['pending_acceptance', 'submitted'].includes(item.status)).length,
    dispute: orders.filter((item) => item.status === 'disputed').length,
  }), [orders]);
  const todoOrders = useMemo(
    () => orders.filter((item) => !['completed', 'cancelled'].includes(item.status)).slice(0, 3),
    [orders],
  );

  function selectPerspective(nextPerspective: OrderPerspective) {
    const next = new URLSearchParams(searchParams);
    next.set('perspective', nextPerspective);
    setSearchParams(next);
  }

  return (
    <main className="marketplace-page marketplace-management-page transaction-page transaction-orders-page">
      <MarketplaceHeader
        title="我的订单"
        searchValue={keyword}
        searchPlaceholder="搜索订单编号、项目名称、对方或服务名称"
        onSearchChange={setKeyword}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={<button type="button" className="marketplace-submit-button" onClick={() => navigate('/enterprise/demands/new')}>发布需求</button>}
      />
      <TransactionSectionTabs />

      <div className="transaction-order-tabs" role="tablist" aria-label="订单角色视角">
        <button type="button" role="tab" aria-selected={perspective === 'buyer'} aria-controls="transaction-orders-panel" className={perspective === 'buyer' ? 'is-active' : ''} onClick={() => selectPerspective('buyer')}>我发起的 <span>{perspective === 'buyer' ? orders.length : ''}</span></button>
        <button type="button" role="tab" aria-selected={perspective === 'provider'} aria-controls="transaction-orders-panel" className={perspective === 'provider' ? 'is-active' : ''} onClick={() => selectPerspective('provider')}>我承接的 <span>{perspective === 'provider' ? orders.length : ''}</span></button>
        <button type="button" role="tab" aria-selected={false} aria-disabled="true" disabled>内部任务 <span>0</span></button>
      </div>
      <p className="transaction-order-help">每个订单的角色由发起方和承接方决定；同一用户在不同订单中可能分别作为采购方或服务方。</p>

      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {!resource.loading && !resource.error && (
        <div className="transaction-orders-layout" id="transaction-orders-panel" role="tabpanel">
          <div className="transaction-orders-main">
            <section className="transaction-order-stats">
              <OrderStat icon={<CalendarClock />} title="待处理" value={counts.pending} tone="orange" />
              <OrderStat icon={<PlayCircle />} title="进行中" value={counts.running} tone="green" />
              <OrderStat icon={<ClipboardCheck />} title="待验收" value={counts.acceptance} tone="blue" />
              <OrderStat icon={<AlertCircle />} title="争议处理中" value={counts.dispute} tone="red" />
            </section>

            <section className="transaction-order-filters">
              <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="订单状态">
                <option value="all">全部状态</option>
                <option value="paid">已付款</option>
                <option value="in_progress">进行中</option>
                <option value="pending_acceptance">待验收</option>
                <option value="disputed">争议处理中</option>
                <option value="completed">已完成</option>
                <option value="cancelled">已取消</option>
              </select>
              <p><Filter />共 {filtered.length} 个订单，列表随企业、角色和状态实时更新</p>
              <button type="button" aria-label="刷新" onClick={resource.reload}><RefreshCw /></button>
            </section>

            {filtered.length === 0 ? (
              <section className="marketplace-inline-empty transaction-orders-empty">
                <PackageCheck />
                <strong>{orders.length ? '没有符合筛选条件的订单' : '当前企业还没有此类订单'}</strong>
                <span>演示支付成功后，系统会从冻结协议快照创建真实订单与里程碑。</span>
                {perspective === 'buyer' && <button type="button" className="marketplace-primary-button" onClick={() => navigate('/enterprise/demands')}>查看我的需求</button>}
              </section>
            ) : (
              <section className="transaction-orders-table">
                <header>
                  <span>订单 / 本单角色</span><span>交易对方</span><span>当前履约</span><span>金额 / 资金</span><span>交付 / 状态</span><span>操作</span>
                </header>
                {filtered.map((order) => {
                  const isExpanded = expanded === order.id;
                  const counterpart = perspective === 'buyer' ? order.providerName : order.buyerName;
                  return (
                    <article key={order.id} className={isExpanded ? 'is-expanded' : ''}>
                      <button type="button" className="transaction-order-row" aria-expanded={isExpanded} aria-controls={`order-details-${order.id}`} onClick={() => setExpanded(isExpanded ? undefined : order.id)}>
                        <span className="transaction-order-title"><i>{isExpanded ? <ChevronDown /> : <ChevronRight />}</i><FileText /><b>{order.code}<strong>{order.title}</strong><small>{order.serviceName} · <em className={`is-${order.currentRole}`}>{roleText(order.currentRole)}</em></small></b></span>
                        <span><b>{counterpart}</b><small>{perspective === 'buyer' ? '服务方企业' : '采购方企业'}</small></span>
                        <span className="transaction-order-fulfillment"><b>{order.currentMilestoneName}</b><small>节点 {order.currentMilestoneSequence}/{order.milestoneCount} · {order.progressPercent}%</small><i><em style={{ width: `${order.progressPercent}%` }} /></i></span>
                        <span><b>¥ {money(order.totalAmount)}</b><small>{settlementStatusText(order.settlementStatus)}</small></span>
                        <span><b>{order.expectedDeliveryAt ? formatShort(order.expectedDeliveryAt) : '待排期'}</b><small>预计交付</small><em className={`marketplace-status is-${order.status}`}>{orderStatus(order.status)}</em></span>
                        <span><i className="transaction-order-action">{isExpanded ? '收起详情' : '查看详情'}</i></span>
                      </button>
                      {isExpanded && organization.selected && (
                        <OrderDetails
                          order={order}
                          organizationId={organization.selected.id}
                          onOpen={() => navigate(`/enterprise/orders/${order.id}`)}
                          onAgreement={() => navigate(`/enterprise/agreements/${order.agreementId}`)}
                          onPayment={() => navigate(`/enterprise/payments/${order.paymentOrderId}`)}
                        />
                      )}
                    </article>
                  );
                })}
              </section>
            )}
          </div>

          <aside className="transaction-orders-aside">
            <section className="transaction-card">
              <header><h2>今日待办</h2><button type="button" onClick={() => navigate('/enterprise/confirmations')}>全部待办 <ChevronRight /></button></header>
              {todoOrders.length ? todoOrders.map((order) => (
                <button type="button" className="transaction-order-todo" key={order.id} onClick={() => navigate(`/enterprise/orders/${order.id}`)}>
                  <strong>{order.currentMilestoneName}</strong>
                  <span>{order.title}</span>
                  <small>{order.code}<em>{order.expectedDeliveryAt ? `${formatShort(order.expectedDeliveryAt)} 前` : '待排期'}</em></small>
                </button>
              )) : <p className="transaction-muted">当前企业在此角色下没有待处理订单。</p>}
            </section>
            <section className="transaction-card transaction-quick-links">
              <h2>快捷入口</h2>
              <button type="button" onClick={() => navigate('/enterprise/confirmations')}><CheckCircle2 />待我确认 <ChevronRight /></button>
              <button type="button" onClick={() => navigate('/enterprise/publishing')}><FileText />我的发布 <ChevronRight /></button>
              <button type="button" onClick={() => navigate('/enterprise/provider')}><ShieldCheck />服务商工作台 <ChevronRight /></button>
              <button type="button" onClick={() => navigate('/enterprise/market/agents')}><Bot />AI员工市场 <ChevronRight /></button>
            </section>
            <section className="transaction-card transaction-order-tip">
              <h2>小贴士</h2>
              <p>订单与项目相互独立，快照、支付事件和里程碑按企业及订单隔离。</p>
              <button type="button" onClick={() => navigate('/enterprise/accounts/organization')}>了解更多 <ArrowRight /></button>
            </section>
          </aside>
        </div>
      )}
    </main>
  );
}

function OrderDetails({
  order,
  organizationId,
  onOpen,
  onAgreement,
  onPayment,
}: {
  order: TransactionOrder;
  organizationId: string;
  onOpen: () => void;
  onAgreement: () => void;
  onPayment: () => void;
}) {
  const detail = useMarketplaceResource(
    () => marketplaceRepository.getOrder(order.id, organizationId),
    `order-detail:${order.id}:${organizationId}`,
  );
  return (
    <div className="transaction-order-details" id={`order-details-${order.id}`}>
      <MarketplaceState loading={detail.loading} error={detail.error} onRetry={detail.reload} />
      {detail.data && (
        <>
          <section>
            <strong>冻结版本</strong>
            <span>服务版本：{String((detail.data.snapshot?.service as Record<string, unknown> | undefined)?.version || '-')}</span>
            <span>协议快照：{detail.data.snapshotDigest?.slice(0, 18)}…</span>
            <span>冻结时间：{formatDateTime(detail.data.createdAt)}</span>
          </section>
          <section>
            <strong>里程碑</strong>
            {detail.data.milestones?.map((milestone) => <span key={milestone.id}><i className={milestone.status === 'accepted' ? 'is-done' : ''} />{milestone.sequence}. {milestone.name} · ¥{money(milestone.amount)} · {milestoneStatusText(milestone.status)}</span>)}
          </section>
          <section>
            <strong>资金与审计</strong>
            <span>支付状态：{paymentStatusText(detail.data.paymentStatus)}</span>
            <span>结算状态：{settlementStatusText(detail.data.settlementStatus)}</span>
            <span>订单快照与里程碑已真实落库</span>
          </section>
          <section className="transaction-order-detail-actions">
            <strong>快捷操作</strong>
            <button type="button" className="is-primary" onClick={onOpen}>进入订单工作区</button>
            <button type="button" onClick={onPayment}>查看支付单</button>
            <button type="button" onClick={onAgreement}>查看协议</button>
          </section>
        </>
      )}
    </div>
  );
}

function OrderStat({ icon, title, value, tone }: { icon: React.ReactNode; title: string; value: number; tone: string }) {
  return <article className={`is-${tone}`}><span>{icon}</span><div><small>{title}</small><strong>{value}</strong></div></article>;
}

function roleText(value: string) {
  return { buyer: '采购方', provider: '服务方', platform: '平台' }[value] || value;
}

function orderStatus(value: string) {
  return {
    paid: '已付款',
    in_progress: '进行中',
    pending_acceptance: '待验收',
    completed: '已完成',
    cancelled: '已取消',
    disputed: '争议处理中',
  }[value] || value;
}

function paymentStatusText(value: string) {
  return { pending: '待支付', paid: '已支付', failed: '支付失败', refunded: '已退款', partially_refunded: '部分退款' }[value] || value;
}

function settlementStatusText(value: string) {
  return {
    held_demo: '演示资金冻结',
    frozen_dispute_demo: '争议冻结中',
    release_eligible_demo: '待演示放款',
    change_adjustment_pending_demo: '待演示金额调整',
    frozen_cancel_demo: '取消复核冻结',
    demo_refunded: '已演示全额退款',
    demo_partially_refunded: '已演示部分退款',
    demo_released: '已演示全额放款',
    demo_split_settled: '已演示分配结算',
    demo_partially_settled: '已演示部分结算',
  }[value] || value;
}

function milestoneStatusText(value: string) {
  return { pending: '待开始', in_progress: '进行中', pending_acceptance: '待验收', revision_requested: '修改中', accepted: '已验收', disputed: '争议中', closed_by_dispute: '争议结案，不再执行' }[value] || value;
}

function money(value: string) {
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatShort(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}
