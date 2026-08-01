import {
  AlertTriangle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Clock3,
  Download,
  FileCheck2,
  FileText,
  History,
  MessageSquareWarning,
  RotateCcw,
  ShieldAlert,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { notify } from '@/components/ui/app-toast';

import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { OrderFile } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type Decision = 'accept' | 'request_revision' | 'request_dispute';

export default function DeliverableAcceptancePage() {
  const navigate = useNavigate();
  const { orderId = '', deliverableId = '' } = useParams();
  const organization = useMarketplaceOrganization();
  const [decision, setDecision] = useState<Decision>();
  const [comments, setComments] = useState('');
  const [reasonCategory, setReasonCategory] = useState('内容缺失');
  const [requestedChanges, setRequestedChanges] = useState('');
  const [expectedResubmitAt, setExpectedResubmitAt] = useState('');
  const [working, setWorking] = useState(false);
  const [preview, setPreview] = useState<{
    kind: 'text' | 'image' | 'pdf' | 'unsupported';
    text?: string;
    url?: string;
  }>();
  const resource = useMarketplaceResource(
    async () => {
      if (!organization.selected) throw new Error('请先选择当前企业');
      return marketplaceRepository.getOrderWorkspace(orderId, organization.selected.id);
    },
    `deliverable-acceptance:${orderId}:${deliverableId}:${organization.selected?.id || 'none'}`,
  );
  const workspace = resource.data;
  const deliverable = workspace?.deliverables.find((item) => item.id === deliverableId);
  const currentVersion = deliverable?.versions.find((item) => item.id === deliverable.currentVersionId);
  const milestone = workspace?.order.milestones.find((item) => item.id === deliverable?.milestoneId);
  const relevantEvents = useMemo(
    () => workspace?.events.filter(
      (event) => event.payload.deliverable_id === deliverableId,
    ) || [],
    [deliverableId, workspace?.events],
  );
  const canDecide = workspace?.perspective === 'buyer'
    && deliverable?.status === 'submitted'
    && workspace.capabilities.canAccept;

  useEffect(() => {
    let active = true;
    let objectUrl = '';
    setPreview(undefined);
    if (!currentVersion || !organization.selected) return undefined;
    const contentType = currentVersion.file.contentType.toLocaleLowerCase();
    void marketplaceRepository.downloadOrderFile(
      currentVersion.file.id,
      organization.selected.id,
    ).then(async (blob) => {
      if (!active) return;
      if (contentType.startsWith('text/') || contentType.includes('json')) {
        setPreview({ kind: 'text', text: await blob.text() });
        return;
      }
      if (contentType.startsWith('image/')) {
        objectUrl = URL.createObjectURL(blob);
        setPreview({ kind: 'image', url: objectUrl });
        return;
      }
      if (contentType === 'application/pdf') {
        objectUrl = URL.createObjectURL(blob);
        setPreview({ kind: 'pdf', url: objectUrl });
        return;
      }
      setPreview({ kind: 'unsupported' });
    }).catch(() => {
      if (active) setPreview({ kind: 'unsupported' });
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [
    currentVersion?.file.contentType,
    currentVersion?.file.id,
    organization.selected?.id,
  ]);

  async function download(file: OrderFile) {
    if (!organization.selected) return;
    try {
      const blob = await marketplaceRepository.downloadOrderFile(file.id, organization.selected.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = file.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '文件下载失败');
    }
  }

  async function submitDecision() {
    if (!decision || !deliverable || !organization.selected) return;
    if (comments.trim().length < 2) {
      notify.error('请填写验收意见');
      return;
    }
    if (decision === 'request_revision' && !requestedChanges.trim()) {
      notify.error('请填写具体修改要求');
      return;
    }
    const prompt = decision === 'accept'
      ? '确认该交付物通过验收？此动作会推进里程碑。'
      : decision === 'request_dispute'
        ? '确认申请平台争议处理？提交后将暂停演示结算状态。'
        : '确认发送修改申请？服务方将按本次要求重新提交新版本。';
    if (!window.confirm(prompt)) return;
    setWorking(true);
    try {
      await marketplaceRepository.decideAcceptance(deliverable.id, {
        organization_id: organization.selected.id,
        action: decision,
        comments,
        idempotency_key: `${decision}-${deliverable.id}-${crypto.randomUUID()}`,
        reason_category: decision === 'request_revision' ? reasonCategory : undefined,
        requested_changes: decision === 'request_revision' ? requestedChanges : undefined,
        expected_resubmit_at: decision === 'request_revision' && expectedResubmitAt ? expectedResubmitAt : undefined,
      });
      notify.success(
        decision === 'accept'
          ? '验收已确认，里程碑状态已更新'
          : decision === 'request_revision'
            ? '修改申请已发送并留存'
            : '已申请平台争议处理，结算状态已冻结',
      );
      setDecision(undefined);
      setComments('');
      setRequestedChanges('');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '提交验收结果失败');
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="marketplace-page fulfillment-page acceptance-page">
      <MarketplaceHeader
        breadcrumb={(
          <button type="button" className="marketplace-breadcrumb" onClick={() => navigate(`/enterprise/orders/${orderId}`)}>
            <ArrowLeft />
            <strong>订单工作区</strong>
            <span>/ 交付验收</span>
          </button>
        )}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {workspace && !deliverable && (
        <div className="marketplace-state is-error"><AlertTriangle /><strong>交付物不存在</strong><span>请返回订单工作区重新选择。</span></div>
      )}
      {workspace && deliverable && currentVersion && milestone && (
        <>
          <section className="acceptance-head">
            <div>
              <span>里程碑 {milestone.sequence} · {milestone.name}</span>
              <h1>{deliverable.name}</h1>
              <p>{deliverable.description || '请依据冻结协议和当前里程碑验收标准进行确认。'}</p>
            </div>
            <div>
              <em className={`is-${deliverable.status}`}>{deliverableStatus(deliverable.status)}</em>
              <strong>当前版本 v{currentVersion.version}</strong>
              <small>{formatDateTime(currentVersion.submittedAt)} 由 {currentVersion.submittedBy} 提交</small>
            </div>
          </section>

          <div className="acceptance-layout">
            <div className="acceptance-main-stack">
              <section className="acceptance-preview-card">
                <header><div><FileText /><span><strong>{currentVersion.file.filename}</strong><small>{currentVersion.file.contentType} · {formatBytes(currentVersion.file.sizeBytes)} · SHA-256 {currentVersion.file.sha256Digest.slice(0, 16)}…</small></span></div><button type="button" onClick={() => void download(currentVersion.file)}><Download />下载原文件</button></header>
                <div className="acceptance-preview">
                  {!preview && <><Clock3 /><strong>正在生成安全预览</strong><span>文件仍可随时下载，不影响验收操作。</span></>}
                  {preview?.kind === 'text' && <pre>{preview.text}</pre>}
                  {preview?.kind === 'image' && <img src={preview.url} alt={currentVersion.file.filename} />}
                  {preview?.kind === 'pdf' && <iframe src={preview.url} title={`${currentVersion.file.filename} 预览`} />}
                  {preview?.kind === 'unsupported' && <><FileCheck2 /><strong>文件已安全存储</strong><span>当前格式暂不支持浏览器内预览，请下载原文件完成内容核验。</span><button type="button" onClick={() => void download(currentVersion.file)}>下载并查看</button></>}
                </div>
                <footer><span><History />本版说明</span><p>{currentVersion.changeSummary}</p></footer>
              </section>

              <section className="acceptance-card">
                <header><div><h2>版本历史</h2><p>历史版本只读保留，不能覆盖或删除。</p></div><span>{deliverable.versions.length} 个版本</span></header>
                <div className="acceptance-versions">
                  {[...deliverable.versions].reverse().map((version) => (
                    <article className={version.id === currentVersion.id ? 'is-current' : ''} key={version.id}>
                      <i>{version.status === 'accepted' ? <CheckCircle2 /> : <FileText />}</i>
                      <span><strong>v{version.version} {version.id === currentVersion.id ? '当前版本' : ''}</strong><small>{version.changeSummary}</small><em>{formatDateTime(version.submittedAt)} · {version.submittedBy}</em></span>
                      <b className={`is-${version.status}`}>{versionStatus(version.status)}</b>
                      <button type="button" aria-label={`下载版本 ${version.version}`} onClick={() => void download(version.file)}><Download /></button>
                    </article>
                  ))}
                </div>
              </section>

              {deliverable.revisionRequests.length > 0 && (
                <section className="acceptance-card">
                  <header><div><h2>修改申请记录</h2><p>每次申请都关联到具体交付版本。</p></div></header>
                  <div className="acceptance-revisions">
                    {deliverable.revisionRequests.map((request) => (
                      <article key={request.id}><RotateCcw /><span><strong>{request.reasonCategory}<em className={`is-${request.status}`}>{request.status === 'open' ? '处理中' : '已解决'}</em></strong><p>{request.requirements}</p><small>{request.requestedBy} · {formatDateTime(request.createdAt)}</small></span></article>
                    ))}
                  </div>
                </section>
              )}
            </div>

            <aside className="acceptance-side-stack">
              <section className="acceptance-card acceptance-criteria">
                <header><div><h2>本里程碑验收标准</h2><p>来源：成交时冻结的报价快照</p></div></header>
                {milestone.acceptanceCriteria.length ? milestone.acceptanceCriteria.map((item, index) => <p key={item}><i><Check /></i><span><strong>标准 {index + 1}</strong>{item}</span></p>) : <p><i><Check /></i><span><strong>默认标准</strong>交付物与冻结范围一致且可正常下载。</span></p>}
              </section>

              <section className="acceptance-card acceptance-decision">
                <header><div><h2>{workspace.perspective === 'buyer' ? '结构化验收' : '验收状态'}</h2><p>所有决定均独立留痕，不依赖聊天文字。</p></div></header>
                {canDecide ? (
                  <>
                    <div className="acceptance-actions">
                      <button type="button" className={decision === 'accept' ? 'is-active is-accept' : ''} onClick={() => setDecision('accept')}><CheckCircle2 /><span><strong>通过验收</strong><small>确认符合标准</small></span></button>
                      <button type="button" className={decision === 'request_revision' ? 'is-active is-revision' : ''} onClick={() => setDecision('request_revision')}><RotateCcw /><span><strong>申请修改</strong><small>明确原因与要求</small></span></button>
                      <button type="button" className={decision === 'request_dispute' ? 'is-active is-dispute' : ''} onClick={() => setDecision('request_dispute')}><ShieldAlert /><span><strong>平台争议处理</strong><small>暂停结算并归档</small></span></button>
                    </div>
                    {decision && (
                      <div className="acceptance-decision-form">
                        {decision === 'request_revision' && (
                          <>
                            <label><span>修改原因</span><select value={reasonCategory} onChange={(event) => setReasonCategory(event.target.value)}><option>内容缺失</option><option>格式不符合</option><option>数据错误</option><option>未达到验收标准</option><option>其他</option></select></label>
                            <label><span>具体修改要求</span><textarea value={requestedChanges} onChange={(event) => setRequestedChanges(event.target.value)} placeholder="指出具体文件、位置、问题和期望结果" /></label>
                            <label><span>期望重新提交时间</span><input type="datetime-local" value={expectedResubmitAt} onChange={(event) => setExpectedResubmitAt(event.target.value)} /></label>
                          </>
                        )}
                        {decision === 'request_dispute' && <div className="acceptance-warning"><MessageSquareWarning /><span><strong>平台争议处理</strong><small>提交后订单进入争议中并暂停结算。3H 将补齐证据、仲裁员、调解和裁决流程。</small></span></div>}
                        <label><span>{decision === 'accept' ? '验收意见' : decision === 'request_dispute' ? '争议诉求说明' : '补充说明'}</span><textarea value={comments} onChange={(event) => setComments(event.target.value)} placeholder="请填写可供双方和平台审计的明确意见" /></label>
                        <button type="button" disabled={working} onClick={() => void submitDecision()}>{working ? '正在提交…' : decision === 'accept' ? '确认通过验收' : decision === 'request_revision' ? '发送修改申请' : '申请平台争议处理'}</button>
                      </div>
                    )}
                  </>
                ) : (
                  <div className="acceptance-readonly"><Clock3 /><span><strong>{deliverableStatus(deliverable.status)}</strong><small>{workspace.perspective === 'provider' ? '服务方可查看记录，验收决定仅采购方负责人可提交。' : '当前版本没有可执行的验收动作。'}</small></span></div>
                )}
              </section>

              <section className="acceptance-card">
                <header><div><h2>交付审计记录</h2><p>与本交付物关联的关键事件</p></div></header>
                <div className="acceptance-audit">
                  {relevantEvents.length ? relevantEvents.map((event) => <article key={event.id}><i /><span><strong>{event.summary}</strong><small>{event.actor} · {formatDateTime(event.createdAt)}</small></span></article>) : <p>暂无关联事件。</p>}
                </div>
              </section>
            </aside>
          </div>
        </>
      )}
    </main>
  );
}

function deliverableStatus(value: string) {
  return {
    draft: '草稿',
    submitted: '待验收',
    revision_requested: '修改中',
    accepted: '已验收',
    disputed: '平台争议处理中',
  }[value] || value;
}

function versionStatus(value: string) {
  return {
    submitted: '待验收',
    revision_requested: '已退回',
    accepted: '已通过',
    dispute_requested: '争议中',
  }[value] || value;
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
