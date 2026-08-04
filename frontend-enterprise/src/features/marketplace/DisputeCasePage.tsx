import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  Download,
  FileArchive,
  FileCheck2,
  FileUp,
  LockKeyhole,
  MessageSquareText,
  RefreshCw,
  Scale,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { notify } from '@/components/ui/app-toast';

import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { DisputeEvidence, DisputeDetail } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type CaseTab = 'overview' | 'evidence' | 'timeline' | 'decision';

export default function DisputeCasePage() {
  const { caseId = '' } = useParams();
  const navigate = useNavigate();
  const organization = useMarketplaceOrganization();
  const [tab, setTab] = useState<CaseTab>('overview');
  const [working, setWorking] = useState(false);
  const [response, setResponse] = useState('');
  const [evidenceTitle, setEvidenceTitle] = useState('');
  const [evidenceDescription, setEvidenceDescription] = useState('');
  const [evidenceRequestId, setEvidenceRequestId] = useState('');
  const [evidenceVisibility, setEvidenceVisibility] = useState<'case_parties' | 'platform_only'>('case_parties');
  const [evidenceFile, setEvidenceFile] = useState<File>();
  const [mediationComment, setMediationComment] = useState('');
  const [appealReason, setAppealReason] = useState('');
  const [appealEvidence, setAppealEvidence] = useState('');
  const resource = useMarketplaceResource(
    async () => {
      if (!organization.selected) throw new Error('请先选择当前企业');
      return marketplaceRepository.getDispute(caseId, organization.selected.id);
    },
    `dispute-case:${caseId}:${organization.selected?.id || 'none'}`,
  );
  const detail = resource.data;
  const openRequests = useMemo(
    () => detail?.evidenceRequests.filter((item) => item.status === 'open' && item.requestedFromOrganizationId === organization.selected?.id) || [],
    [detail?.evidenceRequests, organization.selected?.id],
  );
  const latestMediation = detail?.mediations[0];
  const latestDecision = detail?.decisions[0];

  async function run(action: () => Promise<DisputeDetail>, success: string) {
    setWorking(true);
    try {
      await action();
      notify.success(success);
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '操作失败');
    } finally {
      setWorking(false);
    }
  }

  function submitResponse() {
    if (!organization.selected || response.trim().length < 10) {
      notify.error('请填写完整的事实回应');
      return;
    }
    void run(
      () => marketplaceRepository.respondDispute(caseId, organization.selected!.id, response.trim()),
      '争议回应已提交，案件进入举证阶段',
    ).then(() => setResponse(''));
  }

  function submitEvidence() {
    if (!detail || !organization.selected || evidenceTitle.trim().length < 2 || evidenceDescription.trim().length < 4) {
      notify.error('请填写证据名称和内容说明');
      return;
    }
    void run(async () => {
      let fileId: string | undefined;
      if (evidenceFile) {
        const uploaded = await marketplaceRepository.uploadOrderFile(
          detail.orderId,
          organization.selected!.id,
          detail.milestoneId,
          'dispute_evidence',
          evidenceFile,
        );
        fileId = uploaded.id;
      }
      const result = await marketplaceRepository.submitDisputeEvidence(caseId, {
        organizationId: organization.selected!.id,
        title: evidenceTitle.trim(),
        description: evidenceDescription.trim(),
        fileId,
        evidenceRequestId: evidenceRequestId || undefined,
        visibility: evidenceVisibility,
      });
      setEvidenceTitle('');
      setEvidenceDescription('');
      setEvidenceRequestId('');
      setEvidenceFile(undefined);
      return result;
    }, '举证材料已提交并生成不可变摘要');
  }

  async function download(item: DisputeEvidence) {
    if (!item.fileId || !item.filename || !organization.selected) return;
    try {
      const blob = await marketplaceRepository.downloadOrderFile(item.fileId, organization.selected.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = item.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '下载失败');
    }
  }

  function respondMediation(decision: 'accepted' | 'rejected') {
    if (!latestMediation || !organization.selected) return;
    if (!window.confirm(`确认${decision === 'accepted' ? '同意' : '拒绝'}第 ${latestMediation.version} 版调解方案？`)) return;
    void run(
      () => marketplaceRepository.respondDisputeMediation(latestMediation.id, organization.selected!.id, decision, mediationComment),
      '调解意见已结构化记录',
    );
  }

  function appeal() {
    if (!organization.selected || appealReason.trim().length < 10) {
      notify.error('请填写至少 10 个字符的申诉理由');
      return;
    }
    void run(
      () => marketplaceRepository.appealDispute(caseId, organization.selected!.id, appealReason.trim(), appealEvidence.trim()),
      '申诉已提交，资金继续冻结',
    );
  }

  function waive() {
    if (!organization.selected || !window.confirm('确认放弃本次申诉权利？该确认会写入审计日志且不可撤回。')) return;
    void run(() => marketplaceRepository.waiveDisputeAppeal(caseId, organization.selected!.id), '已确认放弃本次申诉');
  }

  return (
    <main className="marketplace-page dispute-case-page">
      <MarketplaceHeader
        breadcrumb={<button type="button" className="marketplace-breadcrumb" onClick={() => navigate(detail ? `/enterprise/orders/${detail.orderId}?tab=disputes` : '/enterprise/orders')}><ArrowLeft /><strong>订单争议</strong><span>/ {detail?.code || caseId}</span></button>}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={<button type="button" className="marketplace-secondary-button" onClick={resource.reload}><RefreshCw />刷新</button>}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {detail && (
        <>
          <section className="dispute-case-hero">
            <div><span><Scale />平台争议处理案件</span><h1>{detail.code} · {detail.claim}</h1><p>{detail.orderCode} · {detail.orderTitle}</p></div>
            <div><span className={`dispute-status is-${detail.status}`}>{statusText(detail.status)}</span><strong>¥ {money(detail.disputedAmount)}</strong><small>争议金额</small></div>
          </section>
          <div className="dispute-legal-banner"><ShieldCheck /><span><strong>业务性质说明</strong>本页面记录平台依据合作协议开展的争议处理，不构成司法仲裁或法院裁判。争议期间订单结算保持冻结。</span><LockKeyhole /></div>

          <nav className="dispute-tabs">
            {([['overview', '案件概览'], ['evidence', `证据材料 ${detail.evidence.length}`], ['timeline', `处理时间线 ${detail.timeline.length}`], ['decision', '调解、决定与申诉']] as Array<[CaseTab, string]>).map(([value, label]) => <button type="button" key={value} className={tab === value ? 'is-active' : ''} onClick={() => setTab(value)}>{label}</button>)}
          </nav>

          {tab === 'overview' && (
            <div className="dispute-case-layout">
              <div className="dispute-case-main">
                <section className="dispute-card"><header><div><h2>申请方陈述</h2><p>{detail.requestedBy} · {formatDateTime(detail.createdAt)}</p></div><FileCheck2 /></header><h3>{detail.claim}</h3><p className="dispute-long-copy">{detail.statement}</p></section>
                <section className="dispute-card"><header><div><h2>被申请方回应</h2><p>{detail.respondentName}</p></div><MessageSquareText /></header>{detail.responseStatement ? <><p className="dispute-long-copy">{detail.responseStatement}</p><small>{detail.respondedBy} · {detail.respondedAt ? formatDateTime(detail.respondedAt) : ''}</small></> : <div className="dispute-inline-empty"><Clock3 /><span>等待被申请方提交首次结构化回应</span></div>}</section>
                {detail.capabilities.canRespond && <section className="dispute-action-card"><h2>提交争议回应</h2><p>请针对诉求逐项回应。提交后双方进入举证阶段，回应内容不能通过聊天替代。</p><textarea value={response} onChange={(event) => setResponse(event.target.value)} placeholder="说明认可和不认可的事实、对应协议条款及后续举证计划" /><footer><button type="button" className="is-primary" disabled={working} onClick={submitResponse}>确认并提交回应</button></footer></section>}
              </div>
              <aside className="dispute-case-side">
                <section><h3>案件信息</h3><dl><div><dt>采购方</dt><dd>{detail.buyerName}</dd></div><div><dt>服务方</dt><dd>{detail.providerName}</dd></div><div><dt>争议类型</dt><dd>{typeText(detail.disputeType)}</dd></div><div><dt>举证截止</dt><dd>{formatDateTime(detail.evidenceDueAt)}</dd></div><div><dt>平台处理人</dt><dd>{detail.assignedTo || '待分配'}</dd></div><div><dt>风险等级</dt><dd>{detail.riskLevel === 'high' ? '高风险' : detail.riskLevel}</dd></div></dl></section>
                <section><h3>证据归档</h3><p><strong>{detail.evidence.length}</strong> 项证据</p><span>系统已自动归档合同、报价、聊天、交付版本、验收与对甲方可见的 SOP 事件。</span><button type="button" onClick={() => setTab('evidence')}>查看证据目录</button></section>
              </aside>
            </div>
          )}

          {tab === 'evidence' && (
            <div className="dispute-evidence-layout">
              <section className="dispute-evidence-list"><header><div><h2>证据目录</h2><p>自动归档快照和双方补充材料均保留 SHA-256 摘要。</p></div></header>{detail.evidence.map((item) => <article key={item.id}><i className={item.isAutoArchived ? 'is-archive' : 'is-upload'}>{item.isAutoArchived ? <FileArchive /> : <FileUp />}</i><div><header><strong>{item.title}</strong><span>{item.isAutoArchived ? '系统归档' : roleText(item.submittedRole)}</span>{item.visibility === 'platform_only' && <em>仅平台可见</em>}</header><p>{item.description || '业务记录快照'}</p><small>{formatDateTime(item.createdAt)} · SHA-256 {item.snapshotDigest.slice(0, 16)}…</small></div>{item.fileId && item.filename && <button type="button" onClick={() => void download(item)}><Download />下载</button>}</article>)}</section>
              <aside>
                {openRequests.length > 0 && <section className="dispute-supplement-box"><h3><AlertTriangle />平台补件要求</h3>{openRequests.map((item) => <button type="button" key={item.id} className={evidenceRequestId === item.id ? 'is-selected' : ''} onClick={() => { setEvidenceRequestId(item.id); setEvidenceTitle(item.title); }}><strong>{item.title}</strong><span>{item.description}</span><small>截止 {formatDateTime(item.dueAt)}</small></button>)}</section>}
                {detail.capabilities.canSubmitEvidence && <section className="dispute-evidence-form"><h3>提交举证材料</h3><label><span>材料名称</span><input value={evidenceTitle} onChange={(event) => setEvidenceTitle(event.target.value)} /></label><label><span>内容说明</span><textarea value={evidenceDescription} onChange={(event) => setEvidenceDescription(event.target.value)} placeholder="说明该材料证明的事实及关联条款" /></label><label><span>可见范围</span><select value={evidenceVisibility} onChange={(event) => setEvidenceVisibility(event.target.value as 'case_parties' | 'platform_only')}><option value="case_parties">双方和平台可见</option><option value="platform_only">仅平台处理人员可见</option></select></label><label className="dispute-file-picker"><FileUp /><span>{evidenceFile?.name || '选择附件（可不上传，仅提交文字证据）'}</span><input type="file" onChange={(event) => setEvidenceFile(event.target.files?.[0])} /></label><button type="button" className="is-primary" disabled={working} onClick={submitEvidence}>提交并固化摘要</button></section>}
              </aside>
            </div>
          )}

          {tab === 'timeline' && <section className="dispute-timeline"><header><h2>全过程审计时间线</h2><p>关键操作按时间倒序记录，不能由聊天文字替代。</p></header>{detail.timeline.map((item) => <article key={item.id}><i>{timelineIcon(item.eventType)}</i><div><strong>{item.summary}</strong><p>{item.actor} · {roleText(item.actorRole)}</p><small>{formatDateTime(item.createdAt)}</small></div></article>)}</section>}

          {tab === 'decision' && (
            <div className="dispute-decision-layout">
              <div>
                <section className="dispute-card"><header><div><h2>平台调解方案</h2><p>双方必须分别结构化确认，聊天中的同意不视为确认。</p></div><Scale /></header>{latestMediation ? <div className="dispute-mediation"><span>第 {latestMediation.version} 版 · {mediationStatus(latestMediation.status)}</span><p>{latestMediation.proposal}</p><dl><div><dt>建议退款</dt><dd>¥ {money(latestMediation.proposedRefundAmount)}</dd></div><div><dt>建议放款</dt><dd>¥ {money(latestMediation.proposedReleaseAmount)}</dd></div><div><dt>采购方</dt><dd>{responseText(latestMediation.buyerResponse)}</dd></div><div><dt>服务方</dt><dd>{responseText(latestMediation.providerResponse)}</dd></div></dl>{detail.capabilities.canRespondMediation && <div className="dispute-mediation-actions"><textarea value={mediationComment} onChange={(event) => setMediationComment(event.target.value)} placeholder="补充确认意见（可选）" /><button type="button" disabled={working} onClick={() => respondMediation('rejected')}><XCircle />拒绝</button><button type="button" className="is-primary" disabled={working} onClick={() => respondMediation('accepted')}><CheckCircle2 />同意方案</button></div>}</div> : <div className="dispute-inline-empty"><Clock3 /><span>平台尚未提出调解方案</span></div>}</section>
                <section className="dispute-card"><header><div><h2>平台处理决定</h2><p>处理决定需由两名不同平台管理员提交和复核。</p></div><ShieldCheck /></header>{latestDecision ? <div className="dispute-decision-result"><span className={`dispute-status is-${latestDecision.status}`}>{decisionStatus(latestDecision.status)}</span><h3>{outcomeText(latestDecision.outcome)}</h3><div><strong>退款 ¥ {money(latestDecision.refundAmount)}</strong><strong>放款 ¥ {money(latestDecision.releaseAmount)}</strong></div><p>{latestDecision.rationale}</p><small>提交：{latestDecision.submittedBy} · 复核：{latestDecision.reviewedBy || '待另一名管理员复核'}{latestDecision.appealDueAt ? ` · 申诉截止 ${formatDateTime(latestDecision.appealDueAt)}` : ''}</small></div> : <div className="dispute-inline-empty"><Clock3 /><span>尚未形成平台处理决定</span></div>}</section>
              </div>
              <aside>
                {detail.capabilities.canAppeal && <section className="dispute-appeal-form"><h3>提交申诉</h3><p>请说明原处理决定中存在的事实或规则适用问题。申诉期间继续冻结资金。</p><textarea value={appealReason} onChange={(event) => setAppealReason(event.target.value)} placeholder="申诉理由（必填）" /><textarea value={appealEvidence} onChange={(event) => setAppealEvidence(event.target.value)} placeholder="新增证据说明（可选）" /><button type="button" disabled={working} onClick={appeal}>提交申诉</button></section>}
                {detail.capabilities.canWaiveAppeal && <section className="dispute-waiver"><LockKeyhole /><h3>确认处理决定</h3><p>如果不再申诉，可明确放弃本次申诉权利。双方均确认后，平台才能执行演示资金操作并结案。</p><button type="button" disabled={working} onClick={waive}>确认放弃申诉</button></section>}
                {detail.appeals.length > 0 && <section className="dispute-appeal-list"><h3>申诉记录</h3>{detail.appeals.map((item) => <article key={item.id}><strong>{item.organizationName}</strong><span>{item.reason}</span><small>{appealStatus(item.status)} · {formatDateTime(item.createdAt)}</small></article>)}</section>}
                {detail.fundOperations.length > 0 && <section className="dispute-fund-list"><h3>资金操作记录</h3>{detail.fundOperations.map((item) => <article key={item.id}><CircleFund operation={item.operationType} /><span><strong>{fundText(item.operationType)} ¥ {money(item.amount)}</strong><small>{item.channel === 'demo' ? '演示渠道' : item.channel} · {formatDateTime(item.createdAt)}</small></span></article>)}</section>}
              </aside>
            </div>
          )}
        </>
      )}
    </main>
  );
}

function CircleFund({ operation }: { operation: string }) { return operation.includes('refund') ? <ArrowLeft /> : <CheckCircle2 />; }
function statusText(value: string) { return ({ awaiting_response: '待对方回应', evidence_collection: '举证中', platform_review: '平台审查中', mediation: '调解中', pending_decision: '待处理决定', decided: '已形成处理决定', appeal_pending: '申诉处理中', closed: '已结案' } as Record<string, string>)[value] || value; }
function typeText(value: string) { return ({ scope_disagreement: '服务范围争议', delivery_quality: '交付质量争议', delivery_delay: '交付延期争议', acceptance_disagreement: '验收争议', payment_disagreement: '支付/结算争议', cancellation_disagreement: '取消争议', other: '其他' } as Record<string, string>)[value] || value; }
function roleText(value: string) { return ({ buyer: '采购方', provider: '服务方', platform: '平台处理人员', system: '系统归档' } as Record<string, string>)[value] || value; }
function mediationStatus(value: string) { return ({ proposed: '待双方确认', accepted: '双方已同意', rejected: '未达成一致' } as Record<string, string>)[value] || value; }
function responseText(value?: string) { return value === 'accepted' ? '已同意' : value === 'rejected' ? '已拒绝' : '待确认'; }
function decisionStatus(value: string) { return ({ pending_review: '待复核', approved: '复核通过', rejected: '复核未通过', applied: '已执行', superseded_by_appeal: '因申诉失效' } as Record<string, string>)[value] || value; }
function outcomeText(value: string) { return ({ full_refund: '全额退款', partial_refund: '部分退款', full_release: '全额放款', partial_release: '部分放款', split: '部分退款并部分放款', reject_dispute: '驳回争议诉求' } as Record<string, string>)[value] || value; }
function appealStatus(value: string) { return ({ pending_review: '待平台审核', accepted: '已受理', rejected: '未受理' } as Record<string, string>)[value] || value; }
function fundText(value: string) { return value.includes('refund') ? '退款' : '放款'; }
function timelineIcon(type: string) { return type.includes('decision') ? <ShieldCheck /> : type.includes('evidence') ? <FileCheck2 /> : type.includes('appeal') ? <AlertTriangle /> : <Clock3 />; }
function money(value: string) { return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
