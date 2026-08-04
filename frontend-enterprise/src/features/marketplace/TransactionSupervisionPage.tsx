import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Eye,
  FileClock,
  RefreshCw,
  Search,
  ShieldAlert,
  X,
} from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { notify } from '@/components/ui/app-toast';

import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { ActionItem, CollaborationDashboardOrder } from './types';
import { useMarketplaceResource } from './useMarketplaceResource';

export default function TransactionSupervisionPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState('all');
  const [selectedId, setSelectedId] = useState(searchParams.get('orderId') || '');
  const [comment, setComment] = useState('');
  const [working, setWorking] = useState(false);
  const resource = useMarketplaceResource(
    () => marketplaceRepository.getPlatformDashboard(),
    'platform-transaction-supervision',
  );
  const orders = useMemo(() => (resource.data?.orders || []).filter((item) => {
    if (status === 'exception' && item.riskLevel === 'normal') return false;
    if (status !== 'all' && status !== 'exception' && item.status !== status) return false;
    const needle = keyword.trim().toLocaleLowerCase();
    return !needle || `${item.code} ${item.title} ${item.buyerName} ${item.providerName}`.toLocaleLowerCase().includes(needle);
  }), [keyword, resource.data?.orders, status]);
  const selected = (resource.data?.orders || []).find((item) => item.id === selectedId) || orders[0];
  const selectedActions = (resource.data?.recentActions || []).filter((item) => item.orderId === selected?.id);

  async function review(action: ActionItem, decision: 'approve' | 'reject') {
    if (!comment.trim()) {
      notify.error('请填写平台复核意见');
      return;
    }
    const confirmation = action.targetType === 'order_change'
      ? (decision === 'approve' ? '确认完成演示金额调整并使订单变更生效？' : '确认拒绝该金额变更？')
      : (decision === 'approve' ? '确认取消订单并执行演示退款？' : '确认平台拒绝取消申请？');
    if (!window.confirm(confirmation)) return;
    setWorking(true);
    try {
      if (action.targetType === 'order_change') {
        await marketplaceRepository.applyOrderChangeDemoAdjustment(action.targetId, decision === 'approve' ? 'apply_demo_adjustment' : 'reject', comment.trim());
      } else {
        await marketplaceRepository.decidePlatformCancellation(action.targetId, decision === 'approve' ? 'cancel_and_demo_refund' : 'reject', comment.trim());
      }
      notify.success('平台复核结果已写入订单记录');
      setComment('');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '平台复核失败');
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="marketplace-page supervision-page">
      <MarketplaceHeader
        title="交易监管"
        hideOrganization
        action={<button type="button" className="marketplace-secondary-button" onClick={resource.reload}><RefreshCw />刷新数据</button>}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {resource.data && (
        <>
          <section className="supervision-intro"><div><small>平台监管看板</small><h1>全部订单与履约异常</h1><p>统一查看订单、里程碑、SOP 执行、待办和演示资金状态；平台操作全部留痕。</p></div><span><ShieldAlert />仅平台管理员可访问</span></section>
          <section className="supervision-stats">
            <SupervisionStat label="全部订单" value={resource.data.counts.total || 0} icon={<FileClock />} />
            <SupervisionStat label="履约中" value={resource.data.counts.inProgress || 0} icon={<Clock3 />} tone="blue" />
            <SupervisionStat label="待平台处理" value={resource.data.recentActions.length} icon={<CircleDollarSign />} tone="orange" />
            <SupervisionStat label="异常订单" value={resource.data.counts.exceptions || 0} icon={<AlertTriangle />} tone="red" />
            <SupervisionStat label="争议处理中" value={resource.data.counts.disputes || 0} icon={<ShieldAlert />} tone="purple" />
          </section>
          <section className="supervision-toolbar">
            <label><Search /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索订单号、项目或企业" /></label>
            <select aria-label="订单状态" value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">全部状态</option><option value="paid">待开始</option><option value="in_progress">履约中</option><option value="pending_acceptance">待验收</option><option value="completed">已完成</option><option value="cancelled">已取消</option><option value="exception">仅看异常</option></select>
          </section>
          <div className="supervision-layout">
            <section className="supervision-table-card">
              <table><thead><tr><th>订单 / 项目</th><th>甲乙双方</th><th>当前履约</th><th>SOP / Agent</th><th>资金状态</th><th>风险</th><th /></tr></thead><tbody>
                {orders.map((item) => <OrderRow key={item.id} item={item} selected={selected?.id === item.id} onSelect={() => setSelectedId(item.id)} />)}
              </tbody></table>
              {!orders.length && <div className="collaboration-empty"><CheckCircle2 /><strong>没有符合条件的订单</strong><span>请调整搜索或状态筛选。</span></div>}
            </section>
            {selected && (
              <aside className="supervision-detail">
                <header><div><small>{selected.code}</small><h2>{selected.title}</h2><p>{selected.buyerName} → {selected.providerName}</p></div><button type="button" aria-label="关闭订单详情" onClick={() => setSelectedId('')}><X /></button></header>
                <div className="supervision-progress"><span><strong>{selected.progressPercent}%</strong><small>整体进度</small></span><i><b style={{ width: `${selected.progressPercent}%` }} /></i></div>
                <dl><div><dt>当前里程碑</dt><dd>{selected.currentMilestone}</dd></div><div><dt>订单状态</dt><dd>{orderStatus(selected.status)}</dd></div><div><dt>执行健康</dt><dd><em className={`is-${selected.executionHealth}`}>{isTerminalOrder(selected.status) ? '执行已关闭' : healthText(selected.executionHealth)}</em></dd></div><div><dt>订单金额</dt><dd>¥ {money(selected.totalAmount)}</dd></div><div><dt>支付状态</dt><dd>{paymentText(selected.paymentStatus)}</dd></div><div><dt>结算状态</dt><dd>{settlementText(selected.settlementStatus)}</dd></div></dl>
                <button type="button" className="supervision-open-order" onClick={() => navigate(`/enterprise/orders/${selected.id}`)}><Eye />查看订单全量记录 <ChevronRight /></button>
                <section className="supervision-actions"><h3>待平台复核</h3>{selectedActions.length ? selectedActions.map((action) => <article key={action.id}><header><i><CircleDollarSign /></i><span><strong>{action.title}</strong><small>{action.summary}</small></span></header><textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="填写复核依据与处理意见（必填）" /><div><button type="button" disabled={working} onClick={() => void review(action, 'reject')}>不通过</button><button type="button" className="is-primary" disabled={working} onClick={() => void review(action, 'approve')}>{action.targetType === 'order_change' ? '完成演示调整' : '取消并演示退款'}</button></div></article>) : <p>当前没有待平台复核事项。</p>}</section>
                <footer><ShieldAlert /><span><strong>系统边界</strong>平台复核不会调用 StaffDeck 改变订单；StaffDeck 只能回传执行结果。</span></footer>
              </aside>
            )}
          </div>
        </>
      )}
    </main>
  );
}

function OrderRow({ item, selected, onSelect }: { item: CollaborationDashboardOrder; selected: boolean; onSelect: () => void }) {
  const terminal = isTerminalOrder(item.status);
  return <tr className={selected ? 'is-selected' : ''} onClick={onSelect}><td><strong>{item.title}</strong><small>{item.code}<br />{item.serviceName}</small></td><td><span>{item.buyerName}</span><small>→ {item.providerName}</small></td><td><strong>{item.currentMilestone}</strong><small>{item.progressPercent}% · {item.expectedDeliveryAt ? `预计 ${formatDate(item.expectedDeliveryAt)}` : '待排期'}</small></td><td><span className={`supervision-agent is-${item.executionHealth}`}><Bot />{terminal ? '执行已关闭' : healthText(item.executionHealth)}</span><small>{terminal ? '不再创建执行任务' : item.executionStatus || '尚未启动'}</small></td><td><span>{settlementText(item.settlementStatus)}</span><small>¥ {money(item.totalAmount)}</small></td><td><em className={`supervision-risk is-${item.riskLevel}`}>{item.currentMilestone === '平台争议处理已结案' ? '已结案' : riskText(item.riskLevel)}</em>{item.pendingActionCount > 0 && <small>{item.pendingActionCount} 项待办</small>}</td><td><button type="button" aria-label={`查看订单 ${item.code}`} onClick={(event) => { event.stopPropagation(); onSelect(); }}><ChevronRight /></button></td></tr>;
}

function SupervisionStat({ label, value, icon, tone = 'slate' }: { label: string; value: number; icon: ReactNode; tone?: string }) { return <article className={`is-${tone}`}><i>{icon}</i><span><small>{label}</small><strong>{value}</strong></span></article>; }
function orderStatus(value: string) { return { paid: '待开始', in_progress: '履约中', pending_acceptance: '待验收', completed: '已完成', cancelled: '已取消', disputed: '争议处理中' }[value] || value; }
function settlementText(value: string) { return { held_demo: '演示托管中', frozen_dispute_demo: '争议冻结中', release_eligible_demo: '待演示放款', change_adjustment_pending_demo: '待金额调整', frozen_cancel_demo: '取消复核冻结', demo_refunded: '已演示全额退款', demo_partially_refunded: '已演示部分退款', demo_released: '已演示全额放款', demo_split_settled: '已演示分配结算', demo_partially_settled: '已演示部分结算' }[value] || value; }
function paymentText(value: string) { return { pending: '待支付', paid: '已支付', failed: '支付失败', refunded: '已退款', partially_refunded: '部分退款' }[value] || value; }
function healthText(value: string) { return { not_started: '尚未启动', healthy: '运行正常', failed: '执行异常', blocked: '执行阻塞' }[value] || value; }
function isTerminalOrder(value: string) { return value === 'completed' || value === 'cancelled'; }
function riskText(value: string) { return { normal: '正常', medium: '关注', high: '高风险' }[value] || value; }
function money(value: string) { return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(new Date(value)); }
