import {
  AlertTriangle,
  ArrowRight,
  Clock3,
  FileCheck2,
  RefreshCw,
  Scale,
  Search,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import { useMarketplaceResource } from './useMarketplaceResource';

export default function PlatformDisputesPage() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [status, setStatus] = useState('active');
  const resource = useMarketplaceResource(
    () => marketplaceRepository.getPlatformDisputes(),
    'platform-dispute-dashboard',
  );
  const rows = useMemo(() => (resource.data?.cases || []).filter((item) => {
    if (status === 'active' && item.status === 'closed') return false;
    if (status !== 'all' && status !== 'active' && item.status !== status) return false;
    const needle = keyword.trim().toLocaleLowerCase();
    return !needle || `${item.code} ${item.orderCode} ${item.orderTitle} ${item.buyerName} ${item.providerName} ${item.claim}`.toLocaleLowerCase().includes(needle);
  }), [keyword, resource.data?.cases, status]);

  return (
    <main className="marketplace-page platform-disputes-page">
      <MarketplaceHeader title="争议处理" hideOrganization action={<button type="button" className="marketplace-secondary-button" onClick={resource.reload}><RefreshCw />刷新</button>} />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {resource.data && (
        <>
          <section className="platform-dispute-intro"><div><span><Scale />平台争议处理中心</span><h1>案件、证据、调解与处理决定</h1><p>统一受理履约争议，冻结结算、归档证据、记录调解和双人复核；不使用“司法仲裁”表述。</p></div><aside><ShieldCheck /><span><strong>管理员专属</strong>敏感资金决定必须双人复核</span></aside></section>
          <section className="platform-dispute-stats">
            <Stat icon={<Scale />} label="全部案件" value={resource.data.counts.total || 0} tone="slate" />
            <Stat icon={<Clock3 />} label="待回应" value={resource.data.counts.awaitingResponse || 0} tone="orange" />
            <Stat icon={<FileCheck2 />} label="举证中" value={resource.data.counts.evidence || 0} tone="blue" />
            <Stat icon={<ShieldAlert />} label="待平台处理" value={resource.data.counts.platformReview || 0} tone="purple" />
            <Stat icon={<AlertTriangle />} label="申诉中" value={resource.data.counts.appealPending || 0} tone="red" />
          </section>
          <section className="platform-dispute-toolbar"><label><Search /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索案件号、订单、企业或诉求" /></label><select aria-label="案件状态" value={status} onChange={(event) => setStatus(event.target.value)}><option value="active">进行中案件</option><option value="all">全部案件</option><option value="awaiting_response">待对方回应</option><option value="evidence_collection">举证中</option><option value="platform_review">平台审查</option><option value="mediation">调解中</option><option value="pending_decision">待处理决定</option><option value="decided">已形成决定</option><option value="appeal_pending">申诉处理中</option><option value="closed">已结案</option></select></section>
          <section className="platform-dispute-table"><table><thead><tr><th>案件 / 订单</th><th>申请方与被申请方</th><th>争议类型与金额</th><th>节点与期限</th><th>证据</th><th>负责人</th><th /></tr></thead><tbody>{rows.map((item) => <tr key={item.id} onClick={() => navigate(`/enterprise/platform/disputes/${item.id}`)}><td><strong>{item.code}</strong><span>{item.orderTitle}</span><small>{item.orderCode}</small></td><td><strong>{item.requestedBy}</strong><small>被申请方：{item.respondentName}</small><span>{item.buyerName} ↔ {item.providerName}</span></td><td><span>{typeText(item.disputeType)}</span><strong>¥ {money(item.disputedAmount)}</strong><small>{item.claim}</small></td><td><em className={`dispute-status is-${item.status}`}>{statusText(item.status)}</em><small>{caseDeadline(item.status, item.evidenceDueAt, item.appealDueAt, item.closedAt)}</small></td><td><strong>{item.evidenceCount}</strong><small>项已固化</small></td><td><span>{item.assignedTo || '待领取'}</span><small>{item.riskLevel === 'high' ? '高风险' : item.riskLevel}</small></td><td><button type="button" aria-label={`查看案件 ${item.code}`}><ArrowRight /></button></td></tr>)}</tbody></table>{rows.length === 0 && <div className="dispute-empty"><ShieldCheck /><strong>没有符合条件的案件</strong><span>调整筛选条件后再试。</span></div>}</section>
        </>
      )}
    </main>
  );
}

function Stat({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number; tone: string }) { return <article className={`is-${tone}`}><i>{icon}</i><span><small>{label}</small><strong>{value}</strong></span></article>; }
function statusText(value: string) { return ({ awaiting_response: '待回应', evidence_collection: '举证中', platform_review: '平台审查', mediation: '调解中', pending_decision: '待处理决定', decided: '已形成决定', appeal_pending: '申诉中', closed: '已结案' } as Record<string, string>)[value] || value; }
function typeText(value: string) { return ({ scope_disagreement: '服务范围', delivery_quality: '交付质量', delivery_delay: '交付延期', acceptance_disagreement: '验收争议', payment_disagreement: '支付结算', cancellation_disagreement: '取消争议', other: '其他' } as Record<string, string>)[value] || value; }
function caseDeadline(status: string, evidenceDueAt: string, appealDueAt?: string, closedAt?: string) { if (status === 'closed') return `结案时间 ${closedAt ? formatDateTime(closedAt) : '-'}`; if (status === 'decided' || status === 'appeal_pending') return `申诉截止 ${appealDueAt ? formatDateTime(appealDueAt) : '-'}`; return `举证截止 ${formatDateTime(evidenceDueAt)}`; }
function money(value: string) { return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
