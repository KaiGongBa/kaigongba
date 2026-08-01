import {
  AlertTriangle,
  ArrowRight,
  Bot,
  CheckCircle2,
  ChevronRight,
  CirclePlay,
  Clock3,
  FileCheck2,
  FileText,
  RefreshCw,
  Search,
} from 'lucide-react';
import { useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { MarketplaceHeader, MarketplaceState } from './components';
import { ServiceSectionTabs } from './MarketplaceSectionTabs';
import { marketplaceRepository } from './repository';
import type { TransactionOrder } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';
import './service-order-workbench.css';

export default function ServiceOrderWorkbenchPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const organization = useMarketplaceOrganization();
  const resource = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.listOrders(organization.selected.id, 'provider')
      : Promise.resolve([]),
    `service-order-workbench:${organization.selected?.id || 'none'}`,
  );
  const query = searchParams.get('q') || '';
  const status = searchParams.get('status') || 'all';
  const orders = resource.data || [];
  const visibleOrders = useMemo(() => orders.filter((order) => {
    const needle = query.trim().toLocaleLowerCase();
    const matchesText = !needle || [order.code, order.title, order.serviceName, order.buyerName]
      .some((value) => value.toLocaleLowerCase().includes(needle));
    return matchesText && (status === 'all' || order.status === status);
  }), [orders, query, status]);
  const counts = {
    ready: orders.filter((item) => ['paid', 'pending'].includes(item.status)).length,
    running: orders.filter((item) => ['in_progress', 'running'].includes(item.status)).length,
    acceptance: orders.filter((item) => ['pending_acceptance', 'submitted'].includes(item.status)).length,
    exception: orders.filter((item) => ['disputed', 'refunding'].includes(item.status)).length,
  };

  function updateSearch(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (!value || value === 'all') next.delete(key);
    else next.set(key, value);
    next.set('view', 'workbench');
    setSearchParams(next);
  }

  return (
    <main className="marketplace-page service-order-workbench-page">
      <MarketplaceHeader
        title="服务商工作台"
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={(
          <div className="marketplace-action-group">
            <button type="button" className="marketplace-secondary-button" onClick={resource.reload}><RefreshCw />刷新</button>
            <button type="button" className="marketplace-primary-button" onClick={() => navigate('/enterprise/publishing')}>发布服务</button>
          </div>
        )}
      />
      <ServiceSectionTabs />
      <section className="service-workbench-intro"><div><h1>服务方交付工作区</h1><p>只展示当前企业作为服务方承接的真实订单；SOP、交付、补料、验收和异常处理继续在订单工作区完成。</p></div><span><Bot />服务方订单视角</span></section>
      <MarketplaceState loading={resource.loading || organization.loading} error={resource.error || organization.error} onRetry={resource.reload} />
      {!resource.loading && !resource.error && organization.selected && (
        <>
          <section className="service-workbench-stats">
            <ServiceStat label="待开始" value={counts.ready} detail="已付款待启动" icon={<Clock3 />} />
            <ServiceStat label="执行中" value={counts.running} detail="SOP 与人工任务" icon={<CirclePlay />} tone="green" />
            <ServiceStat label="待甲方验收" value={counts.acceptance} detail="交付已提交" icon={<FileCheck2 />} tone="blue" />
            <ServiceStat label="异常与争议" value={counts.exception} detail="需要人工处理" icon={<AlertTriangle />} tone="red" />
          </section>
          <section className="service-workbench-list">
            <header><div><h2>承接订单</h2><p>点击订单进入原有 8 页签工作区，不在本页复制履约状态机。</p></div><button type="button" onClick={() => navigate('/enterprise/orders?perspective=provider')}>完整订单列表 <ArrowRight /></button></header>
            <div className="service-workbench-filters">
              <label><Search /><input aria-label="搜索服务订单" value={query} onChange={(event) => updateSearch('q', event.target.value.trim())} placeholder="搜索订单、项目或采购方" /></label>
              <select aria-label="筛选服务订单状态" value={status} onChange={(event) => updateSearch('status', event.target.value)}>
                <option value="all">全部状态</option><option value="paid">待开始</option><option value="in_progress">进行中</option><option value="pending_acceptance">待验收</option><option value="disputed">争议中</option><option value="completed">已完成</option>
              </select>
              <span>{visibleOrders.length} / {orders.length} 笔</span>
            </div>
            {visibleOrders.length ? (
              <div className="service-workbench-order-list">
                {visibleOrders.map((order) => <ServiceOrderCard key={order.id} order={order} onOpen={() => navigate(`/enterprise/orders/${encodeURIComponent(order.id)}`)} />)}
              </div>
            ) : <section className="service-workbench-empty"><CheckCircle2 /><strong>{orders.length ? '没有符合筛选条件的服务订单' : '当前企业还没有承接订单'}</strong><span>{orders.length ? '调整搜索词或状态筛选后重试。' : '报价被选中、协议确认并完成支付后，服务订单会进入这里。'}</span></section>}
          </section>
        </>
      )}
    </main>
  );
}

function ServiceStat({ label, value, detail, icon, tone = 'gray' }: { label: string; value: number; detail: string; icon: React.ReactNode; tone?: string }) {
  return <article className={`is-${tone}`}><span>{icon}</span><div><small>{label}</small><strong>{value}</strong><em>{detail}</em></div></article>;
}

function ServiceOrderCard({ order, onOpen }: { order: TransactionOrder; onOpen: () => void }) {
  return (
    <button
      type="button"
      aria-label={`打开服务订单：${order.title}`}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <span className="service-order-code"><FileText /><span><small>{order.code}</small><strong data-i18n-ignore>{order.title}</strong><em data-i18n-ignore>{order.buyerName} · {order.serviceName}</em></span></span>
      <span><small>当前里程碑</small><strong>{order.currentMilestoneName || '待开始'}</strong><em>{order.currentMilestoneSequence}/{order.milestoneCount}</em></span>
      <span className="service-order-progress"><small>整体进度 <em>{order.progressPercent}%</em></small><i><b style={{ width: `${order.progressPercent}%` }} /></i><strong>{orderStatus(order.status)}</strong></span>
      <span><small>成交金额</small><strong>¥ {Number(order.totalAmount).toLocaleString('zh-CN')}</strong><em>{settlementStatus(order.settlementStatus)}</em></span>
      <ChevronRight />
    </button>
  );
}

function orderStatus(value: string) { return ({ paid: '待开始', pending: '待开始', in_progress: '进行中', running: '进行中', pending_acceptance: '待验收', submitted: '待验收', disputed: '争议中', completed: '已完成', cancelled: '已取消', refunding: '退款中' } as Record<string, string>)[value] || value; }
function settlementStatus(value: string) { return ({ pending: '待结算', held: '托管中', frozen: '争议冻结', settled: '已结算', released: '已放款', not_started: '未进入结算', held_demo: '演示资金冻结', frozen_dispute_demo: '争议冻结中', release_eligible_demo: '待演示放款', change_adjustment_pending_demo: '待金额调整', frozen_cancel_demo: '取消复核冻结', demo_refunded: '已演示全额退款', demo_partially_refunded: '已演示部分退款', demo_released: '已演示全额放款', demo_split_settled: '已演示分配结算', demo_partially_settled: '已演示部分结算' } as Record<string, string>)[value] || value; }
