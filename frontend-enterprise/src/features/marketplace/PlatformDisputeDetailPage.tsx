import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  Clock3,
  Download,
  FileArchive,
  FilePlus2,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  UserCheck,
  XCircle,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { notify } from '@/components/ui/app-toast';

import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { DisputeDetail, DisputeEvidence } from './types';
import { useMarketplaceResource } from './useMarketplaceResource';

export default function PlatformDisputeDetailPage() {
  const { caseId = '' } = useParams();
  const navigate = useNavigate();
  const [working, setWorking] = useState(false);
  const [supplementParty, setSupplementParty] = useState('');
  const [supplementTitle, setSupplementTitle] = useState('');
  const [supplementDescription, setSupplementDescription] = useState('');
  const [supplementDueAt, setSupplementDueAt] = useState('');
  const [mediationProposal, setMediationProposal] = useState('');
  const [mediationRefund, setMediationRefund] = useState('0');
  const [mediationRelease, setMediationRelease] = useState('0');
  const [outcome, setOutcome] = useState('split');
  const [decisionRefund, setDecisionRefund] = useState('0');
  const [decisionRelease, setDecisionRelease] = useState('0');
  const [decisionRationale, setDecisionRationale] = useState('');
  const [reviewComment, setReviewComment] = useState('');
  const [appealComment, setAppealComment] = useState('');
  const [finalComment, setFinalComment] = useState('');
  const resource = useMarketplaceResource(
    () => marketplaceRepository.getDispute(caseId),
    `platform-dispute:${caseId}`,
  );
  const detail = resource.data;
  const latestDecision = detail?.decisions[0];
  const pendingAppeals = useMemo(() => detail?.appeals.filter((item) => item.status === 'pending_review') || [], [detail?.appeals]);
  const effectiveSupplementParty = supplementParty || detail?.requestedByOrganizationId || '';

  async function run(action: () => Promise<DisputeDetail>, success: string) {
    setWorking(true);
    try {
      await action();
      notify.success(success);
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '平台操作失败');
    } finally {
      setWorking(false);
    }
  }

  function claimCase() {
    void run(() => marketplaceRepository.assignDispute(caseId), '案件已领取并记录分配操作');
  }

  function requestSupplement() {
    if (!effectiveSupplementParty || supplementTitle.trim().length < 2 || supplementDescription.trim().length < 4 || !supplementDueAt) {
      notify.error('请完整填写补件对象、要求和截止时间');
      return;
    }
    void run(() => marketplaceRepository.requestDisputeEvidence(caseId, {
      organizationId: effectiveSupplementParty,
      title: supplementTitle.trim(),
      description: supplementDescription.trim(),
      dueAt: new Date(supplementDueAt).toISOString(),
    }), '补件要求已发送并创建高优先级待办');
  }

  function mediate() {
    if (mediationProposal.trim().length < 10) {
      notify.error('请填写完整调解方案');
      return;
    }
    void run(() => marketplaceRepository.createDisputeMediation(caseId, {
      proposal: mediationProposal.trim(),
      refundAmount: mediationRefund,
      releaseAmount: mediationRelease,
    }), '调解方案已发送双方结构化确认');
  }

  function submitDecision() {
    if (decisionRationale.trim().length < 20) {
      notify.error('处理依据至少需要 20 个字符');
      return;
    }
    if (!window.confirm('确认提交平台处理决定？提交后必须由另一名管理员复核，资金暂不执行。')) return;
    void run(() => marketplaceRepository.createDisputeDecision(caseId, {
      outcome,
      refundAmount: decisionRefund,
      releaseAmount: decisionRelease,
      rationale: decisionRationale.trim(),
      appealDays: 3,
    }), '处理决定已提交，等待另一名管理员复核');
  }

  function reviewDecision(decision: 'approved' | 'rejected') {
    if (!latestDecision || reviewComment.trim().length < 4) {
      notify.error('请填写独立复核意见');
      return;
    }
    if (!window.confirm(`确认${decision === 'approved' ? '复核通过并向双方发布' : '退回处理决定'}？资金仍不会立即执行。`)) return;
    void run(() => marketplaceRepository.reviewDisputeDecision(latestDecision.id, decision, reviewComment.trim()), '复核结果已记录');
  }

  function reviewAppeal(appealId: string, decision: 'accepted' | 'rejected') {
    if (appealComment.trim().length < 4) {
      notify.error('请填写申诉审核意见');
      return;
    }
    void run(() => marketplaceRepository.reviewDisputeAppeal(appealId, decision, appealComment.trim()), '申诉审核结果已记录');
  }

  function finalize() {
    if (finalComment.trim().length < 4) {
      notify.error('请填写结案与资金执行说明');
      return;
    }
    if (!window.confirm('确认执行演示退款/放款并结案？该动作会写入资金操作记录，不能通过聊天撤回。')) return;
    void run(() => marketplaceRepository.finalizeDispute(caseId, finalComment.trim()), '演示资金操作已执行，案件已结案');
  }

  async function download(item: DisputeEvidence) {
    if (!item.fileId || !item.filename) return;
    try {
      const blob = await marketplaceRepository.downloadPlatformDisputeFile(item.fileId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = item.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '证据文件下载失败');
    }
  }

  return (
    <main className="marketplace-page platform-dispute-detail-page">
      <MarketplaceHeader breadcrumb={<button type="button" className="marketplace-breadcrumb" onClick={() => navigate('/enterprise/platform/disputes')}><ArrowLeft /><strong>争议处理</strong><span>/ {detail?.code || caseId}</span></button>} hideOrganization action={<button type="button" className="marketplace-secondary-button" onClick={resource.reload}><RefreshCw />刷新</button>} />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {detail && (
        <>
          <section className="platform-case-hero"><div><span><Scale />{detail.code}</span><h1>{detail.claim}</h1><p>{detail.orderCode} · {detail.orderTitle} · {detail.buyerName} ↔ {detail.providerName}</p></div><aside><em className={`dispute-status is-${detail.status}`}>{statusText(detail.status)}</em><strong>¥ {money(detail.disputedAmount)}</strong><small>{detail.evidence.length} 项证据 · {detail.assignedTo || '待领取'}</small></aside></section>
          <div className="platform-case-risk"><ShieldAlert /><span><strong>平台处理边界</strong>AI 仅整理证据，不自动裁决；处理决定双人复核后仍需经过申诉期，最终资金动作当前使用演示渠道。</span>{detail.capabilities.canAssign && <button type="button" disabled={working} onClick={claimCase}><UserCheck />{detail.assignedTo ? '重新领取' : '领取案件'}</button>}</div>

          <div className="platform-case-layout">
            <div className="platform-case-main">
              <section className="platform-case-card"><header><div><h2>双方诉辩</h2><p>申请与回应按结构化记录展示</p></div><Scale /></header><div className="platform-party-statements"><article><span>申请方 · {detail.requestedBy}</span><h3>{detail.claim}</h3><p>{detail.statement}</p></article><article><span>被申请方 · {detail.respondentName}</span>{detail.responseStatement ? <p>{detail.responseStatement}</p> : <div className="dispute-inline-empty"><Clock3 /><span>尚未提交回应</span></div>}</article></div></section>

              <section className="platform-case-card"><header><div><h2>证据目录</h2><p>自动归档与双方补充证据；仅平台材料不会向另一方泄露</p></div><FileArchive /></header><div className="platform-evidence-table"><table><thead><tr><th>证据</th><th>来源</th><th>可见性</th><th>摘要</th><th>时间</th><th /></tr></thead><tbody>{detail.evidence.map((item) => <tr key={item.id}><td><strong>{item.title}</strong><small>{item.description}</small></td><td>{item.isAutoArchived ? '系统自动归档' : `${item.submittedBy} · ${roleText(item.submittedRole)}`}</td><td>{item.visibility === 'platform_only' ? '仅平台可见' : '双方可见'}</td><td><code>{item.snapshotDigest.slice(0, 14)}…</code></td><td>{formatDateTime(item.createdAt)}</td><td>{item.fileId && <button type="button" onClick={() => void download(item)}><Download /></button>}</td></tr>)}</tbody></table></div></section>

              <section className="platform-case-card"><header><div><h2>AI 证据整理</h2><p>仅生成事实索引、证据类型和待核验项，不输出倾向性处理建议</p></div><Bot /></header>{Object.keys(detail.aiSummary).length ? <div className="platform-ai-summary"><div className="platform-ai-disclaimer"><AlertTriangle />{String(detail.aiSummary.disclaimer || '仅用于整理证据，不构成平台处理结论或自动裁决。')}</div><pre>{JSON.stringify(detail.aiSummary, null, 2)}</pre></div> : <div className="dispute-inline-empty"><Bot /><span>尚未生成证据整理摘要</span></div>}{detail.capabilities.canAssign && <footer><button type="button" disabled={working} onClick={() => void run(() => marketplaceRepository.generateDisputeSummary(caseId), 'AI 证据整理已更新')}><Bot />生成或更新摘要</button></footer>}</section>

              <section className="platform-case-card"><header><div><h2>全过程审计日志</h2><p>案件、证据、调解、复核、申诉与资金动作全部留痕</p></div><ShieldCheck /></header><div className="platform-case-timeline">{detail.timeline.map((item) => <article key={item.id}><i>{item.eventType.includes('decision') ? <ShieldCheck /> : item.eventType.includes('evidence') ? <FilePlus2 /> : <Clock3 />}</i><div><strong>{item.summary}</strong><span>{item.actor} · {roleText(item.actorRole)}</span><small>{formatDateTime(item.createdAt)}</small></div></article>)}</div></section>
            </div>

            <aside className="platform-case-actions">
              {detail.capabilities.canRequestEvidence && <section><header><FilePlus2 /><div><h3>要求补充材料</h3><p>生成截止时间、待办和通知</p></div></header><label><span>补件对象</span><select value={effectiveSupplementParty} onChange={(event) => setSupplementParty(event.target.value)}><option value={detail.requestedByOrganizationId}>{detail.requestedBy}</option><option value={detail.respondentOrganizationId}>{detail.respondentName}</option></select></label><label><span>材料名称</span><input value={supplementTitle} onChange={(event) => setSupplementTitle(event.target.value)} /></label><label><span>具体要求</span><textarea value={supplementDescription} onChange={(event) => setSupplementDescription(event.target.value)} /></label><label><span>截止时间</span><input type="datetime-local" value={supplementDueAt} onChange={(event) => setSupplementDueAt(event.target.value)} /></label><button type="button" disabled={working} onClick={requestSupplement}>发送补件要求</button></section>}

              {detail.capabilities.canMediate && <section><header><Scale /><div><h3>提出调解方案</h3><p>双方分别结构化确认</p></div></header><label><span>方案内容</span><textarea value={mediationProposal} onChange={(event) => setMediationProposal(event.target.value)} /></label><div className="platform-amount-pair"><label><span>建议退款</span><input type="number" min="0" value={mediationRefund} onChange={(event) => setMediationRefund(event.target.value)} /></label><label><span>建议放款</span><input type="number" min="0" value={mediationRelease} onChange={(event) => setMediationRelease(event.target.value)} /></label></div><button type="button" disabled={working} onClick={mediate}>发送调解方案</button></section>}

              {detail.capabilities.canSubmitDecision && <section className="is-critical"><header><ShieldAlert /><div><h3>提交处理决定</h3><p>提交人不能自行复核</p></div></header><label><span>处理结果</span><select value={outcome} onChange={(event) => setOutcome(event.target.value)}><option value="split">部分退款并部分放款</option><option value="full_refund">全额退款</option><option value="partial_refund">部分退款</option><option value="full_release">全额放款</option><option value="partial_release">部分放款</option><option value="reject_dispute">驳回争议</option></select></label><div className="platform-amount-pair"><label><span>退款金额</span><input type="number" min="0" value={decisionRefund} onChange={(event) => setDecisionRefund(event.target.value)} /></label><label><span>放款金额</span><input type="number" min="0" value={decisionRelease} onChange={(event) => setDecisionRelease(event.target.value)} /></label></div><label><span>事实与处理依据</span><textarea value={decisionRationale} onChange={(event) => setDecisionRationale(event.target.value)} /></label><button type="button" disabled={working} onClick={submitDecision}>提交另一人复核</button></section>}

              {detail.capabilities.canReviewDecision && latestDecision && <section className="is-critical"><header><UserCheck /><div><h3>独立复核处理决定</h3><p>原提交人无法执行此操作</p></div></header><div className="platform-decision-preview"><strong>{outcomeText(latestDecision.outcome)}</strong><span>退款 ¥ {money(latestDecision.refundAmount)} / 放款 ¥ {money(latestDecision.releaseAmount)}</span><p>{latestDecision.rationale}</p></div><label><span>独立复核意见</span><textarea value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} /></label><div className="platform-action-pair"><button type="button" disabled={working} onClick={() => reviewDecision('rejected')}><XCircle />退回</button><button type="button" className="is-primary" disabled={working} onClick={() => reviewDecision('approved')}><CheckCircle2 />复核通过</button></div></section>}

              {detail.capabilities.canReviewAppeal && pendingAppeals.map((item) => <section className="is-critical" key={item.id}><header><AlertTriangle /><div><h3>审核申诉</h3><p>{item.organizationName}</p></div></header><p>{item.reason}</p>{item.newEvidenceDescription && <small>新增证据：{item.newEvidenceDescription}</small>}<label><span>审核意见</span><textarea value={appealComment} onChange={(event) => setAppealComment(event.target.value)} /></label><div className="platform-action-pair"><button type="button" disabled={working} onClick={() => reviewAppeal(item.id, 'rejected')}>不受理</button><button type="button" className="is-primary" disabled={working} onClick={() => reviewAppeal(item.id, 'accepted')}>受理并重审</button></div></section>)}

              {detail.capabilities.canFinalize && <section className="is-critical"><header><CheckCircle2 /><div><h3>执行演示资金并结案</h3><p>仅在申诉处理完毕后可用</p></div></header><label><span>结案说明</span><textarea value={finalComment} onChange={(event) => setFinalComment(event.target.value)} /></label><button type="button" className="is-primary" disabled={working} onClick={finalize}>二次确认并结案</button></section>}

              <section><header><ShieldCheck /><div><h3>案件节点</h3><p>当前状态与历史决定</p></div></header><dl className="platform-case-facts"><div><dt>举证截止</dt><dd>{formatDateTime(detail.evidenceDueAt)}</dd></div><div><dt>申诉截止</dt><dd>{detail.appealDueAt ? formatDateTime(detail.appealDueAt) : '-'}</dd></div><div><dt>采购方放弃申诉</dt><dd>{detail.buyerAppealWaivedAt ? formatDateTime(detail.buyerAppealWaivedAt) : '未确认'}</dd></div><div><dt>服务方放弃申诉</dt><dd>{detail.providerAppealWaivedAt ? formatDateTime(detail.providerAppealWaivedAt) : '未确认'}</dd></div></dl>{detail.fundOperations.map((item) => <div className="platform-fund-row" key={item.id}><strong>{item.operationType.includes('refund') ? '退款' : '放款'} ¥ {money(item.amount)}</strong><span>{item.channel === 'demo' ? '演示渠道' : item.channel} · {formatDateTime(item.createdAt)}</span></div>)}</section>
            </aside>
          </div>
        </>
      )}
    </main>
  );
}

function statusText(value: string) { return ({ awaiting_response: '待回应', evidence_collection: '举证中', platform_review: '平台审查', mediation: '调解中', pending_decision: '待处理决定', decided: '已形成决定', appeal_pending: '申诉处理中', closed: '已结案' } as Record<string, string>)[value] || value; }
function roleText(value: string) { return ({ buyer: '采购方', provider: '服务方', platform: '平台管理员', system: '系统归档' } as Record<string, string>)[value] || value; }
function outcomeText(value: string) { return ({ full_refund: '全额退款', partial_refund: '部分退款', full_release: '全额放款', partial_release: '部分放款', split: '部分退款并部分放款', reject_dispute: '驳回争议诉求' } as Record<string, string>)[value] || value; }
function money(value: string) { return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
