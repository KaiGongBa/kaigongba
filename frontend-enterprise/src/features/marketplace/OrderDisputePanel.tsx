import {
  AlertTriangle,
  ArrowRight,
  CircleDollarSign,
  Clock3,
  FileArchive,
  LockKeyhole,
  Scale,
  ShieldAlert,
} from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { notify } from '@/components/ui/app-toast';

import { MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { OrderMilestone } from './types';
import { useMarketplaceResource } from './useMarketplaceResource';

export default function OrderDisputePanel({
  orderId,
  organizationId,
  heldAmount,
  milestones,
}: {
  orderId: string;
  organizationId: string;
  heldAmount: string;
  milestones: OrderMilestone[];
}) {
  const navigate = useNavigate();
  const [formOpen, setFormOpen] = useState(false);
  const [working, setWorking] = useState(false);
  const [milestoneId, setMilestoneId] = useState('');
  const [disputeType, setDisputeType] = useState('acceptance_disagreement');
  const [amount, setAmount] = useState(heldAmount);
  const [claim, setClaim] = useState('');
  const [statement, setStatement] = useState('');
  const [evidenceDays, setEvidenceDays] = useState(5);
  const resource = useMarketplaceResource(
    () => marketplaceRepository.getOrderDisputes(orderId, organizationId),
    `order-disputes:${orderId}:${organizationId}`,
  );

  async function submit() {
    if (claim.trim().length < 4 || statement.trim().length < 10) {
      notify.error('请完整填写处理诉求和事实说明');
      return;
    }
    if (Number(amount) < 0 || Number(amount) > Number(heldAmount)) {
      notify.error('争议金额不能超过当前托管金额');
      return;
    }
    if (!window.confirm('确认发起平台争议处理？发起后订单结算将立即冻结，并自动归档现有业务记录。')) return;
    setWorking(true);
    try {
      const created = await marketplaceRepository.createDispute(orderId, {
        organizationId,
        milestoneId: milestoneId || undefined,
        disputeType,
        disputedAmount: amount,
        claim: claim.trim(),
        statement: statement.trim(),
        evidenceDueDays: evidenceDays,
      });
      notify.success('已发起平台争议处理，订单结算已冻结');
      navigate(`/enterprise/disputes/${created.id}`);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '发起争议失败');
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="dispute-order-panel">
      <header className="dispute-section-head">
        <div>
          <span><Scale />平台争议处理</span>
          <h2>争议、举证与处理记录</h2>
          <p>这里的“争议处理”是平台履约纠纷处理机制，不是司法仲裁或法院裁判。</p>
        </div>
        {resource.data?.canCreate && !formOpen && (
          <button type="button" className="dispute-danger-button" onClick={() => setFormOpen(true)}>
            <ShieldAlert />发起争议
          </button>
        )}
      </header>
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />

      {resource.data?.activeCase && (
        <article className="dispute-active-case">
          <div className="dispute-active-icon"><LockKeyhole /></div>
          <div>
            <span className={`dispute-status is-${resource.data.activeCase.status}`}>
              {statusText(resource.data.activeCase.status)}
            </span>
            <h3>{resource.data.activeCase.code} · {resource.data.activeCase.claim}</h3>
            <p>争议金额 ¥ {money(resource.data.activeCase.disputedAmount)} · 结算已冻结 · 已归档 {resource.data.activeCase.evidenceCount} 项证据</p>
            <small>举证截止 {formatDateTime(resource.data.activeCase.evidenceDueAt)}</small>
          </div>
          <button type="button" onClick={() => navigate(`/enterprise/disputes/${resource.data!.activeCase!.id}`)}>
            进入案件 <ArrowRight />
          </button>
        </article>
      )}

      {formOpen && resource.data?.canCreate && (
        <section className="dispute-create-card">
          <div className="dispute-warning-banner">
            <AlertTriangle />
            <span><strong>发起后立即冻结结算</strong>合同、报价、聊天、交付版本与可见 SOP 事件将生成不可变证据摘要。</span>
          </div>
          <div className="dispute-form-grid">
            <label><span>争议类型</span><select value={disputeType} onChange={(event) => setDisputeType(event.target.value)}><option value="scope_disagreement">服务范围争议</option><option value="delivery_quality">交付质量争议</option><option value="delivery_delay">交付延期争议</option><option value="acceptance_disagreement">验收争议</option><option value="payment_disagreement">支付/结算争议</option><option value="cancellation_disagreement">取消争议</option><option value="other">其他</option></select></label>
            <label><span>关联里程碑（可选）</span><select value={milestoneId} onChange={(event) => setMilestoneId(event.target.value)}><option value="">整个订单</option>{milestones.map((item) => <option value={item.id} key={item.id}>{item.sequence}. {item.name}</option>)}</select></label>
            <label><span>争议金额</span><div className="dispute-money-input"><b>¥</b><input type="number" min="0" max={heldAmount} step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} /></div><small>当前可冻结托管金额 ¥ {money(heldAmount)}</small></label>
            <label><span>举证期限</span><select value={evidenceDays} onChange={(event) => setEvidenceDays(Number(event.target.value))}><option value={3}>3 天</option><option value={5}>5 天</option><option value={7}>7 天</option><option value={10}>10 天</option></select></label>
            <label className="is-wide"><span>处理诉求</span><input value={claim} maxLength={1000} onChange={(event) => setClaim(event.target.value)} placeholder="明确说明希望平台如何处理，例如：退回本里程碑 50% 款项" /></label>
            <label className="is-wide"><span>事实与理由</span><textarea value={statement} maxLength={6000} onChange={(event) => setStatement(event.target.value)} placeholder="按时间说明发生了什么、哪些合同或验收条款未满足，以及已采取的协商动作" /><small>{statement.length}/6000</small></label>
          </div>
          <footer><button type="button" onClick={() => setFormOpen(false)}>取消</button><button type="button" className="is-primary" disabled={working} onClick={() => void submit()}><LockKeyhole />确认发起并冻结结算</button></footer>
        </section>
      )}

      {resource.data && !resource.data.activeCase && !formOpen && (
        <div className="dispute-empty">
          <FileArchive />
          <strong>当前没有进行中的争议</strong>
          <span>{resource.data.canCreate ? '企业负责人可在协商无法解决时发起平台争议处理。' : '当前账号或订单状态不能发起新的争议。'}</span>
        </div>
      )}

      {resource.data && resource.data.history.length > 0 && (
        <section className="dispute-history">
          <h3>历史案件</h3>
          {resource.data.history.map((item) => (
            <button type="button" key={item.id} onClick={() => navigate(`/enterprise/disputes/${item.id}`)}>
              <Scale /><span><strong>{item.code} · {item.claim}</strong><small>{formatDateTime(item.createdAt)} · ¥ {money(item.disputedAmount)} · {item.evidenceCount} 项证据</small></span><em className={`dispute-status is-${item.status}`}>{statusText(item.status)}</em><ArrowRight />
            </button>
          ))}
        </section>
      )}

      <footer className="dispute-boundary-note">
        <CircleDollarSign /><span><strong>资金边界</strong>当前阶段仅支付、退款和放款使用演示渠道；案件、证据、调解、处理决定和申诉均为真实业务数据。</span><Clock3 />
      </footer>
    </section>
  );
}

function statusText(value: string) {
  return ({ awaiting_response: '待对方回应', evidence_collection: '举证中', platform_review: '平台审查中', mediation: '调解中', pending_decision: '待处理决定', decided: '已形成处理决定', appeal_pending: '申诉处理中', closed: '已结案' } as Record<string, string>)[value] || value;
}

function money(value: string) { return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
