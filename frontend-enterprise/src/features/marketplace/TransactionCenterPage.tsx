import {
  ArrowRight,
  BriefcaseBusiness,
  CalendarCheck,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  FileText,
  Landmark,
  RefreshCw,
  Search,
  ShoppingBag,
  WalletCards,
} from 'lucide-react';
import { useMemo } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { MarketplaceHeader, MarketplaceState } from './components';
import { TransactionSectionTabs } from './MarketplaceSectionTabs';
import { marketplaceRepository } from './repository';
import {
  buildTransactionCenterModel,
  filterTransactionOrders,
  type TransactionPeriod,
  type TransactionRelationFilter,
  type TransactionStatusFilter,
} from './transactionCenterModel';
import type { ActionItem, TransactionOrder } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';
import './transaction-center.css';

export default function TransactionCenterPage({ now = new Date() }: { now?: Date }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const organization = useMarketplaceOrganization();
  const resource = useMarketplaceResource(
    async () => {
      if (!organization.selected) {
        return { orders: [], requirements: [], actionItems: { items: [], counts: {} } };
      }
      const [orders, requirements, actionItems] = await Promise.all([
        marketplaceRepository.listOrders(organization.selected.id, 'all'),
        marketplaceRepository.listRequirements(organization.selected.id, 'buyer'),
        marketplaceRepository.listActionItems(organization.selected.id),
      ]);
      return { orders, requirements, actionItems };
    },
    `transaction-center:${organization.selected?.id || 'none'}`,
  );
  const model = useMemo(
    () => buildTransactionCenterModel({
      orders: resource.data?.orders || [],
      requirements: resource.data?.requirements || [],
      actionItems: resource.data?.actionItems || { items: [], counts: {} },
      now,
    }),
    [now, resource.data],
  );
  const period: TransactionPeriod = searchParams.get('period') === 'all' ? 'all' : 'month';
  const relation = normalizeRelation(searchParams.get('relation'));
  const status = normalizeStatus(searchParams.get('status'));
  const query = searchParams.get('q') || '';
  const finance = model.finance[period];
  const visibleOrders = filterTransactionOrders(model.orders, { relation, status, query });

  function updateSearch(patch: Record<string, string>) {
    const next = new URLSearchParams(searchParams);
    Object.entries(patch).forEach(([key, value]) => {
      const isDefault = key === 'period' ? value === 'month' : value === 'all';
      if (!value || isDefault) next.delete(key);
      else next.set(key, value);
    });
    setSearchParams(next);
  }

  return (
    <main className="marketplace-page transaction-center-page">
      <MarketplaceHeader
        title="交易中心"
        searchValue={query}
        searchPlaceholder="搜索订单号、项目、服务或对方企业"
        onSearchChange={(value) => updateSearch({ q: value.trim() })}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={(
          <div className="marketplace-action-group">
            <button type="button" className="marketplace-secondary-button" onClick={() => navigate('/enterprise/publishing')}><BriefcaseBusiness />发布服务</button>
            <button type="button" className="marketplace-primary-button" onClick={() => navigate('/enterprise/demands/new')}>发布需求</button>
          </div>
        )}
      />
      <TransactionSectionTabs />

      <section className="transaction-center-intro">
        <div><h1>采购与服务交易总览</h1><p>同一账号可采购他人服务，也可向他人提供服务；系统按每笔订单关系识别采购方或服务方。</p></div>
        <span><CheckCircle2 />无需切换身份</span>
      </section>

      <MarketplaceState loading={organization.loading || resource.loading} error={organization.error || resource.error} onRetry={resource.reload} />
      {!organization.loading && !organization.selected && !resource.error && (
        <section className="transaction-center-empty"><Landmark /><strong>当前账号未加入可访问企业</strong><span>请先在管理端的账号管理中加入企业与团队。</span></section>
      )}

      {!resource.loading && !resource.error && organization.selected && (
        <>
          <section className="transaction-finance-card">
            <header>
              <div><h2>资金总览</h2><p>收入只统计已结算服务订单，支出只统计已支付采购订单；待处理资金不计入净收支。</p></div>
              <div className="transaction-period-switch">
                <button type="button" className={period === 'month' ? 'is-active' : ''} onClick={() => updateSearch({ period: 'month' })}>本月</button>
                <button type="button" className={period === 'all' ? 'is-active' : ''} onClick={() => updateSearch({ period: 'all' })}>累计</button>
              </div>
            </header>
            <div className="transaction-finance-primary">
              <FinancePrimary label={`${period === 'month' ? '本月' : '累计'}总收入`} value={finance.income} detail="已结算服务收入" tone="income" icon={<CircleDollarSign />} />
              <FinancePrimary label={`${period === 'month' ? '本月' : '累计'}总支出`} value={finance.expense} detail="已支付采购支出" tone="expense" icon={<ShoppingBag />} />
              <FinancePrimary label={`${period === 'month' ? '本月' : '累计'}净收支`} value={finance.net} detail="总收入 − 总支出" tone={finance.net < 0 ? 'negative' : 'net'} icon={<WalletCards />} signed />
            </div>
            <div className="transaction-finance-secondary">
              <FinanceSecondary label="待付款" summary={model.pendingPayment} detail="采购订单" />
              <FinanceSecondary label="待结算" summary={model.pendingSettlement} detail="服务订单" />
              <FinanceSecondary label="退款处理中" summary={model.refunding} detail="退款订单" />
              <FinanceSecondary label="争议冻结" summary={model.disputed} detail="争议订单" />
            </div>
          </section>

          <section className="transaction-center-stats">
            <button type="button" onClick={() => navigate('/enterprise/orders?perspective=buyer')}><span><BriefcaseBusiness /></span><small>进行中订单</small><strong>{model.runningOrderCount}</strong><em>采购与服务订单</em><ChevronRight /></button>
            <button type="button" onClick={() => navigate('/enterprise/confirmations')}><span><CalendarCheck /></span><small>待确认事项</small><strong>{model.pendingConfirmationCount}</strong><em>结构化确认队列</em><ChevronRight /></button>
            <button type="button" onClick={() => navigate('/enterprise/demands')}><span><FileText /></span><small>我的需求</small><strong>{model.requirementCount}</strong><em>成交前需求流程</em><ChevronRight /></button>
            <article><span><CheckCircle2 /></span><small>本月完成订单</small><strong>{model.completedThisMonthCount}</strong><em>按真实订单记录</em></article>
          </section>

          <section className="transaction-center-section">
            <header><div><h2>待确认事项</h2><p>进入对应业务对象完成结构化确认，聊天文字不能替代确认动作。</p></div><button type="button" onClick={() => navigate('/enterprise/confirmations')}>查看全部 <ArrowRight /></button></header>
            {model.actionItems.length ? (
              <div className="transaction-action-strip">
                {model.actionItems.slice(0, 3).map((item) => <ActionItemCard key={item.id} item={item} onOpen={() => navigate(item.route)} />)}
              </div>
            ) : <div className="transaction-inline-empty"><CheckCircle2 /><span>当前没有待确认事项</span></div>}
          </section>

          <section className="transaction-center-section">
            <header><div><h2>全部订单交易</h2><p>仅展示成交后的真实订单；需求、商机、报价和协议保留在各自业务页面。</p></div><button type="button" aria-label="刷新交易数据" onClick={resource.reload}><RefreshCw /></button></header>
            <div className="transaction-center-filters">
              <label><Search /><input value={query} onChange={(event) => updateSearch({ q: event.target.value.trim() })} placeholder="搜索订单或交易对方" aria-label="搜索全部交易" /></label>
              <select aria-label="按交易关系筛选" value={relation} onChange={(event) => updateSearch({ relation: event.target.value })}>
                <option value="all">全部关系</option><option value="buyer">采购方</option><option value="provider">服务方</option>
              </select>
              <select aria-label="按交易状态筛选" value={status} onChange={(event) => updateSearch({ status: event.target.value })}>
                <option value="all">全部状态</option><option value="active">进行中</option><option value="confirmation">待确认</option><option value="acceptance">待验收</option><option value="completed">已完成</option>
              </select>
              <span>{visibleOrders.length} / {model.orders.length} 笔订单</span>
            </div>
            {visibleOrders.length ? (
              <div className="transaction-center-orders">
                <header><span>订单与项目</span><span>我的关系 / 对方</span><span>金额</span><span>当前阶段</span><span>支付与结算</span><span>状态</span><span /></header>
                {visibleOrders.map((order) => <TransactionOrderRow key={order.id} order={order} onOpen={() => navigate(`/enterprise/orders/${encodeURIComponent(order.id)}`)} />)}
              </div>
            ) : <div className="transaction-center-empty is-inline"><FileText /><strong>{model.orders.length ? '没有符合筛选条件的订单' : '当前企业还没有订单'}</strong><span>{model.orders.length ? '请调整搜索、关系或状态筛选。' : '合同确认并完成支付后，真实订单会出现在这里。'}</span></div>}
          </section>
        </>
      )}
      <output className="sr-only" aria-hidden="true">{location.pathname}</output>
    </main>
  );
}

function FinancePrimary({ label, value, detail, tone, icon, signed = false }: { label: string; value: number; detail: string; tone: string; icon: React.ReactNode; signed?: boolean }) {
  return <article className={`is-${tone}`}><span>{icon}</span><div><small>{label}</small><strong>{signed && value > 0 ? '+' : ''}{money(value)}</strong><em>{detail}</em></div></article>;
}

function FinanceSecondary({ label, summary, detail }: { label: string; summary: { amount: number; count: number }; detail: string }) {
  return <article><small>{label}</small><strong>{money(summary.amount)}</strong><em>{summary.count} 笔{detail}</em></article>;
}

function ActionItemCard({ item, onOpen }: { item: ActionItem; onOpen: () => void }) {
  return (
    <button type="button" aria-label={`进入确认：${item.title}`} onClick={onOpen}>
      <header><span>{categoryText(item.category)}</span><em className={`is-${item.riskLevel}`}>{riskText(item.riskLevel)}</em></header>
      <strong data-i18n-ignore>{item.title}</strong>
      <p data-i18n-ignore>{item.summary || '进入业务详情完成结构化确认'}</p>
      <footer><span>{roleText(item.actingRole)}</span><em>{item.dueAt ? `截止 ${dateTime(item.dueAt)}` : `创建于 ${dateTime(item.createdAt)}`}</em></footer>
    </button>
  );
}

function TransactionOrderRow({ order, onOpen }: { order: TransactionOrder; onOpen: () => void }) {
  const counterpart = order.currentRole === 'buyer' ? order.providerName : order.buyerName;
  return (
    <button
      type="button"
      aria-label={`打开交易：${order.title}`}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <span className="transaction-order-main"><small>{order.code}</small><strong data-i18n-ignore>{order.title}</strong><em data-i18n-ignore>{order.serviceName}</em></span>
      <span><i className={`is-${order.currentRole}`}>{order.currentRole === 'buyer' ? '采购方' : '服务方'}</i><strong data-i18n-ignore>{counterpart}</strong></span>
      <span><strong>{money(Number(order.totalAmount))}</strong><small>成交金额</small></span>
      <span><strong>{order.currentMilestoneName || '待开始'}</strong><small>里程碑 {order.currentMilestoneSequence}/{order.milestoneCount} · {order.progressPercent}%</small></span>
      <span><strong>{paymentText(order.paymentStatus)}</strong><small>{settlementText(order.settlementStatus)}</small></span>
      <span><i className={`is-${order.status}`}>{orderStatusText(order.status)}</i><small>{shortDate(order.expectedDeliveryAt)}</small></span>
      <ChevronRight />
    </button>
  );
}

function normalizeRelation(value: string | null): TransactionRelationFilter {
  return value === 'buyer' || value === 'provider' ? value : 'all';
}
function normalizeStatus(value: string | null): TransactionStatusFilter {
  return value === 'active' || value === 'confirmation' || value === 'acceptance' || value === 'completed' ? value : 'all';
}
function money(value: number) { return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 }).format(value); }
function dateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
function shortDate(value?: string) { return value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(new Date(value)) : '待排期'; }
function categoryText(value: string) { return ({ quote: '报价确认', agreement: '协议确认', material: '补充材料', acceptance: '验收确认', order_change: '变更确认', order_cancel: '取消确认', finance: '资金复核' } as Record<string, string>)[value] || value; }
function riskText(value: string) { return ({ normal: '常规', medium: '关注', high: '高风险' } as Record<string, string>)[value] || value; }
function roleText(value: string) { return ({ provider_manager: '我作为服务方', buyer_manager: '我作为采购方', manager: '企业负责人', member: '项目成员', finance: '平台财务' } as Record<string, string>)[value] || value; }
function paymentText(value: string) { return ({ paid: '已付款', pending: '待付款', failed: '支付失败', refunded: '已退款', refunding: '退款中' } as Record<string, string>)[value] || value; }
function settlementText(value: string) { return ({ pending: '待结算', held: '托管中', frozen: '争议冻结', settled: '已结算', released: '已放款', not_started: '未进入结算', held_demo: '演示资金冻结', frozen_dispute_demo: '争议冻结中', release_eligible_demo: '待演示放款', change_adjustment_pending_demo: '待金额调整', frozen_cancel_demo: '取消复核冻结', demo_refunded: '已演示全额退款', demo_partially_refunded: '已演示部分退款', demo_released: '已演示全额放款', demo_split_settled: '已演示分配结算', demo_partially_settled: '已演示部分结算' } as Record<string, string>)[value] || value; }
function orderStatusText(value: string) { return ({ pending: '待开始', paid: '待开始', in_progress: '进行中', running: '进行中', pending_acceptance: '待验收', submitted: '待验收', completed: '已完成', disputed: '争议中', cancelled: '已取消', refunding: '退款中' } as Record<string, string>)[value] || value; }
