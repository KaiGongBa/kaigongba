import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Download,
  FileCheck2,
  FileText,
  FolderOpen,
  History,
  LockKeyhole,
  MessageSquareText,
  PackageCheck,
  PauseCircle,
  Play,
  RefreshCw,
  RotateCcw,
  Send,
  Square,
  UploadCloud,
  UserRound,
} from 'lucide-react';
import { useMemo, useState, type ChangeEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { notify } from '@/components/ui/app-toast';

import { MarketplaceHeader, MarketplaceState } from './components';
import { OrderChangePanel, OrderCommunicationPanel } from './OrderCollaborationPanels';
import OrderDisputePanel from './OrderDisputePanel';
import { marketplaceRepository } from './repository';
import type {
  Deliverable,
  MaterialRequest,
  OrderFile,
  OrderMilestone,
} from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type WorkspaceTab = 'overview' | 'execution' | 'communication' | 'changes' | 'disputes' | 'deliverables' | 'materials' | 'events';

function initialWorkspaceTab(): WorkspaceTab {
  const value = new URLSearchParams(window.location.search).get('tab');
  return ['overview', 'execution', 'communication', 'changes', 'disputes', 'deliverables', 'materials', 'events'].includes(value || '')
    ? value as WorkspaceTab
    : 'overview';
}

export default function OrderWorkspacePage() {
  const navigate = useNavigate();
  const { orderId = '' } = useParams();
  const organization = useMarketplaceOrganization();
  const [tab, setTab] = useState<WorkspaceTab>(initialWorkspaceTab);
  const [working, setWorking] = useState(false);
  const [materialPanelOpen, setMaterialPanelOpen] = useState(false);
  const [deliverablePanelOpen, setDeliverablePanelOpen] = useState(false);
  const [materialTitle, setMaterialTitle] = useState('');
  const [materialDescription, setMaterialDescription] = useState('');
  const [materialDueAt, setMaterialDueAt] = useState('');
  const [deliverableName, setDeliverableName] = useState('');
  const [deliverableDescription, setDeliverableDescription] = useState('');
  const [deliverableSummary, setDeliverableSummary] = useState('');
  const [deliverableFile, setDeliverableFile] = useState<File>();
  const [materialFiles, setMaterialFiles] = useState<Record<string, File | undefined>>({});
  const [materialNotes, setMaterialNotes] = useState<Record<string, string>>({});
  const [versionFiles, setVersionFiles] = useState<Record<string, File | undefined>>({});
  const [versionSummaries, setVersionSummaries] = useState<Record<string, string>>({});
  const resource = useMarketplaceResource(
    async () => {
      if (!organization.selected) throw new Error('请先选择当前企业');
      return marketplaceRepository.getOrderWorkspace(orderId, organization.selected.id);
    },
    `order-workspace:${orderId}:${organization.selected?.id || 'none'}`,
  );
  const workspace = resource.data;
  const order = workspace?.order;
  const terminal = order ? ['completed', 'cancelled'].includes(order.status) : false;
  const currentMilestone = order?.milestones.find(
    (item) => item.sequence === order.currentMilestoneSequence,
  );
  const currentDeliverables = useMemo(
    () => workspace?.deliverables.filter(
      (item) => item.milestoneId === currentMilestone?.id,
    ) || [],
    [currentMilestone?.id, workspace?.deliverables],
  );
  const currentMaterials = useMemo(
    () => workspace?.materialRequests.filter(
      (item) => item.milestoneId === currentMilestone?.id,
    ) || [],
    [currentMilestone?.id, workspace?.materialRequests],
  );
  const execution = workspace?.execution.current;
  const currentExecutionNode = execution?.nodes
    .filter((node) => node.nodeKey === execution.currentNodeKey)
    .sort((left, right) => right.attempt - left.attempt)[0];

  async function runAction(action: () => Promise<unknown>, success: string) {
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

  function startMilestone() {
    if (!order || !currentMilestone || !organization.selected) return;
    if (!window.confirm(`确认启动里程碑“${currentMilestone.name}”？启动后将进入正式履约。`)) return;
    void runAction(
      () => marketplaceRepository.startMilestone(
        order.id,
        currentMilestone.id,
        organization.selected!.id,
      ),
      '里程碑已启动',
    );
  }

  function startExecution() {
    if (!order || !currentMilestone || !organization.selected) return;
    if (!window.confirm(`确认冻结“${currentMilestone.name}”的 SOP 版本并启动 AI 员工？`)) return;
    void runAction(
      () => marketplaceRepository.startExecution(
        order.id,
        organization.selected!.id,
        currentMilestone.id,
        crypto.randomUUID(),
      ),
      'SOP 已冻结并启动',
    );
  }

  function commandExecution(
    action: 'pause' | 'resume' | 'cancel' | 'retry_node' | 'takeover' | 'complete_node',
    success: string,
    summary = '',
  ) {
    if (!execution || !organization.selected) return;
    if (action === 'cancel' && !window.confirm('确认终止本次 SOP 执行？执行记录仍会保留。')) return;
    void runAction(
      () => marketplaceRepository.commandExecution(
        execution.id,
        organization.selected!.id,
        action,
        crypto.randomUUID(),
        currentExecutionNode?.id,
        summary,
      ),
      success,
    );
  }

  function requestMaterial() {
    if (!order || !currentMilestone || !organization.selected) return;
    if (!materialTitle.trim() || !materialDescription.trim()) {
      notify.error('请填写材料名称和具体要求');
      return;
    }
    void runAction(
      () => marketplaceRepository.createMaterialRequest(
        order.id,
        organization.selected!.id,
        currentMilestone.id,
        materialTitle,
        materialDescription,
        materialDueAt,
      ).then(() => {
        setMaterialTitle('');
        setMaterialDescription('');
        setMaterialDueAt('');
        setMaterialPanelOpen(false);
      }),
      '材料请求已发送给采购方',
    );
  }

  function submitMaterial(request: MaterialRequest) {
    const file = materialFiles[request.id];
    if (!order || !organization.selected || !file) {
      notify.error('请先选择要提交的材料文件');
      return;
    }
    void runAction(async () => {
      const uploaded = await marketplaceRepository.uploadOrderFile(
        order.id,
        organization.selected!.id,
        request.milestoneId,
        'material',
        file,
      );
      await marketplaceRepository.submitMaterial(
        request.id,
        organization.selected!.id,
        [uploaded.id],
        materialNotes[request.id] || '按要求补充材料',
      );
      setMaterialFiles((items) => ({ ...items, [request.id]: undefined }));
      setMaterialNotes((items) => ({ ...items, [request.id]: '' }));
    }, '材料已提交并保留版本记录');
  }

  function createAndSubmitDeliverable() {
    if (!order || !currentMilestone || !organization.selected || !deliverableFile) {
      notify.error('请填写交付物并选择文件');
      return;
    }
    if (!deliverableName.trim() || !deliverableSummary.trim()) {
      notify.error('请填写交付物名称和版本说明');
      return;
    }
    void runAction(async () => {
      const deliverable = await marketplaceRepository.createDeliverable(
        order.id,
        organization.selected!.id,
        currentMilestone.id,
        deliverableName,
        deliverableDescription,
      );
      const uploaded = await marketplaceRepository.uploadOrderFile(
        order.id,
        organization.selected!.id,
        currentMilestone.id,
        'deliverable',
        deliverableFile,
      );
      await marketplaceRepository.submitDeliverableVersion(
        deliverable.id,
        organization.selected!.id,
        uploaded.id,
        deliverableSummary,
      );
      setDeliverableName('');
      setDeliverableDescription('');
      setDeliverableSummary('');
      setDeliverableFile(undefined);
      setDeliverablePanelOpen(false);
    }, '交付版本已提交，等待采购方验收');
  }

  function submitNewVersion(deliverable: Deliverable) {
    const file = versionFiles[deliverable.id];
    const summary = versionSummaries[deliverable.id];
    if (!order || !organization.selected || !file || !summary?.trim()) {
      notify.error('请选择文件并填写本次修改说明');
      return;
    }
    void runAction(async () => {
      const uploaded = await marketplaceRepository.uploadOrderFile(
        order.id,
        organization.selected!.id,
        deliverable.milestoneId,
        'deliverable',
        file,
      );
      await marketplaceRepository.submitDeliverableVersion(
        deliverable.id,
        organization.selected!.id,
        uploaded.id,
        summary,
      );
      setVersionFiles((items) => ({ ...items, [deliverable.id]: undefined }));
      setVersionSummaries((items) => ({ ...items, [deliverable.id]: '' }));
    }, '新交付版本已提交');
  }

  async function download(file: OrderFile) {
    if (!organization.selected) return;
    try {
      const blob = await marketplaceRepository.downloadOrderFile(
        file.id,
        organization.selected.id,
      );
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

  return (
    <main className="marketplace-page fulfillment-page">
      <MarketplaceHeader
        breadcrumb={(
          <button
            type="button"
            className="marketplace-breadcrumb"
            onClick={() => navigate('/enterprise/orders')}
          >
            <ArrowLeft />
            <strong>我的订单</strong>
            <span>/ {order?.code || orderId}</span>
          </button>
        )}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={order && (
          <button
            type="button"
            className="marketplace-secondary-button"
            onClick={() => navigate(`/enterprise/payments/${order.paymentOrderId}`)}
          >
            查看支付单
          </button>
        )}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {workspace && order && currentMilestone && (
        <>
          <section className="fulfillment-project-head">
            <div>
              <span className={`fulfillment-role is-${workspace.perspective}`}>
                {workspace.perspective === 'buyer' ? '采购方项目' : '服务方交付'}
              </span>
              <h1>{order.title}</h1>
              <p>{order.code} · {order.serviceName} · 对方企业：{workspace.perspective === 'buyer' ? order.providerName : order.buyerName}</p>
            </div>
            <div className="fulfillment-head-metrics">
              <span><small>整体进度</small><strong>{order.progressPercent}%</strong></span>
              <span><small>当前里程碑</small><strong>{order.currentMilestoneSequence}/{order.milestoneCount}</strong></span>
              <span><small>预计完成</small><strong>{order.expectedDeliveryAt ? formatDate(order.expectedDeliveryAt) : '待排期'}</strong></span>
              <em className={`marketplace-status is-${order.status}`}>{statusText(order.status)}</em>
            </div>
          </section>

          {terminal && (
            <section className="fulfillment-terminal-banner" role="status">
              <CheckCircle2 />
              <div>
                <strong>{order.currentMilestoneName}</strong>
                <span>{order.status === 'completed' ? '订单流程已经完成；未验收里程碑保留历史记录，但不会继续生成执行待办。' : '订单已经取消；历史交付、沟通与平台处理记录仍可查看。'}</span>
              </div>
              <button type="button" onClick={() => setTab('disputes')}>查看争议处理</button>
              <button type="button" onClick={() => setTab('events')}>查看完整记录</button>
            </section>
          )}

          <nav className="fulfillment-tabs">
            {([
              ['overview', '项目总览'],
              ['execution', terminal ? 'SOP 执行 · 已关闭' : `SOP 执行 ${execution ? execution.progressPercent : 0}%`],
              ['communication', '订单沟通'],
              ['changes', '变更与取消'],
              ['disputes', '争议处理'],
              ['deliverables', `交付物 ${workspace.deliverables.length}`],
              ['materials', `材料 ${workspace.materialRequests.length}`],
              ['events', `执行记录 ${workspace.events.length}`],
            ] as Array<[WorkspaceTab, string]>).map(([value, label]) => (
              <button
                type="button"
                key={value}
                className={tab === value ? 'is-active' : ''}
                onClick={() => setTab(value)}
              >
                {label}
              </button>
            ))}
          </nav>

          {tab === 'overview' && (
            <div className="fulfillment-layout">
              <div className="fulfillment-main-stack">
                <section className={`fulfillment-current-card ${terminal ? 'is-terminal' : ''}`}>
                  <header>
                    <div>
                      <span>{terminal ? '订单最终状态' : `当前里程碑 · ${currentMilestone.sequence}/${order.milestoneCount}`}</span>
                      <h2>{terminal ? order.currentMilestoneName : currentMilestone.name}</h2>
                      <p>{terminal ? '履约操作已关闭，下方里程碑仅作为成交快照与处理历史保留。' : currentMilestone.description || '按冻结报价范围完成本阶段工作并提交验收。'}</p>
                    </div>
                    <strong>{terminal ? '流程已关闭' : `¥ ${money(currentMilestone.amount)}`}</strong>
                  </header>
                  <div className="fulfillment-progress-track">
                    {order.milestones.map((milestone) => (
                      <div
                        key={milestone.id}
                        className={[
                          milestone.sequence < order.currentMilestoneSequence || milestone.status === 'accepted' ? 'is-complete' : '',
                          milestone.id === currentMilestone.id ? 'is-current' : '',
                        ].join(' ')}
                      >
                        <i>{milestone.status === 'accepted' ? <CheckCircle2 /> : milestone.sequence}</i>
                        <span>{milestone.name}<small>{milestoneStatus(milestone.status)}</small></span>
                      </div>
                    ))}
                  </div>
                  <footer>
                    <div><Clock3 /><span>计划工期<strong>{currentMilestone.durationDays} 个工作日</strong></span></div>
                    <div><PackageCheck /><span>交付要求<strong>{currentMilestone.deliverables.join('、') || '按协议范围交付'}</strong></span></div>
                    <div><FileCheck2 /><span>验收规则<strong>{currentMilestone.acceptanceCriteria.length} 项结构化标准</strong></span></div>
                    {workspace.capabilities.canStartMilestone && (
                      <button type="button" disabled={working} onClick={startMilestone}><Play />启动里程碑</button>
                    )}
                  </footer>
                </section>

                {workspace.perspective === 'provider' && workspace.capabilities.canRequestMaterial && (
                  <section className="fulfillment-action-strip">
                    <div><MessageSquareText /><span><strong>需要采购方补充材料？</strong><small>请通过结构化请求明确材料名称、用途和截止时间。</small></span></div>
                    <button type="button" onClick={() => setMaterialPanelOpen((value) => !value)}>请求材料</button>
                  </section>
                )}
                {materialPanelOpen && (
                  <section className="fulfillment-action-panel">
                    <h2>向采购方请求补充材料</h2>
                    <div className="fulfillment-form-grid">
                      <label><span>材料名称</span><input value={materialTitle} onChange={(event) => setMaterialTitle(event.target.value)} placeholder="例如：最新账号权限清单" /></label>
                      <label><span>期望提交时间</span><input type="datetime-local" value={materialDueAt} onChange={(event) => setMaterialDueAt(event.target.value)} /></label>
                      <label className="is-wide"><span>具体要求</span><textarea value={materialDescription} onChange={(event) => setMaterialDescription(event.target.value)} placeholder="说明文件范围、格式、用途及必要字段" /></label>
                    </div>
                    <footer><button type="button" onClick={() => setMaterialPanelOpen(false)}>取消</button><button type="button" className="is-primary" disabled={working} onClick={requestMaterial}><Send />发送请求</button></footer>
                  </section>
                )}

                <section className="fulfillment-section-card">
                  <header><div><h2>当前交付物</h2><p>版本提交后不可覆盖，修改稿会生成新的版本记录。</p></div>{workspace.perspective === 'provider' && workspace.capabilities.canSubmitDeliverable && <button type="button" onClick={() => setDeliverablePanelOpen((value) => !value)}><UploadCloud />新建并提交</button>}</header>
                  {deliverablePanelOpen && (
                    <div className="fulfillment-inline-form">
                      <label><span>交付物名称</span><input value={deliverableName} onChange={(event) => setDeliverableName(event.target.value)} /></label>
                      <label><span>版本说明</span><input value={deliverableSummary} onChange={(event) => setDeliverableSummary(event.target.value)} placeholder="说明本版完成内容" /></label>
                      <label className="is-wide"><span>内容说明</span><textarea value={deliverableDescription} onChange={(event) => setDeliverableDescription(event.target.value)} /></label>
                      <label className="fulfillment-file-field is-wide"><UploadCloud /><span>{deliverableFile?.name || '选择交付文件（最大 50MB）'}</span><input type="file" onChange={(event) => setDeliverableFile(event.target.files?.[0])} /></label>
                      <button type="button" disabled={working} onClick={createAndSubmitDeliverable}>提交验收</button>
                    </div>
                  )}
                  <DeliverableList
                    items={currentDeliverables}
                    closed={terminal}
                    perspective={workspace.perspective}
                    working={working}
                    versionFiles={versionFiles}
                    versionSummaries={versionSummaries}
                    onVersionFile={(id, file) => setVersionFiles((items) => ({ ...items, [id]: file }))}
                    onVersionSummary={(id, value) => setVersionSummaries((items) => ({ ...items, [id]: value }))}
                    onSubmitVersion={submitNewVersion}
                    onOpen={(id) => navigate(`/enterprise/orders/${order.id}/deliverables/${id}`)}
                    onDownload={download}
                  />
                </section>

                <section className="fulfillment-section-card">
                  <header><div><h2>材料协作</h2><p>采购方上传的材料按订单隔离并保留每次提交版本。</p></div><button type="button" onClick={() => setTab('materials')}>查看全部 <ChevronRight /></button></header>
                  <MaterialList
                    items={currentMaterials}
                    closed={terminal}
                    perspective={workspace.perspective}
                    working={working}
                    files={materialFiles}
                    notes={materialNotes}
                    onFile={(id, file) => setMaterialFiles((items) => ({ ...items, [id]: file }))}
                    onNote={(id, value) => setMaterialNotes((items) => ({ ...items, [id]: value }))}
                    onSubmit={submitMaterial}
                    onDownload={download}
                  />
                </section>
              </div>

              <aside className="fulfillment-side-stack">
                <section className="fulfillment-side-card">
                  <header><h2>对外可见执行摘要</h2><LockKeyhole /></header>
                  <div className="fulfillment-sop-state">
                    <Bot />
                    <span>
                      <strong>{execution ? executionStatus(execution.status) : terminal ? '执行已关闭' : '尚未启动 SOP'}</strong>
                      <small>{execution ? `${execution.sopSnapshot.summary.name || '订单 SOP'} · ${execution.progressPercent}%` : terminal ? '结案前未启动 SOP，不再创建执行任务' : '启动时将冻结订单对应的 SOP 版本'}</small>
                    </span>
                  </div>
                  {execution && <div className="fulfillment-mini-progress"><i style={{ width: `${execution.progressPercent}%` }} /></div>}
                  {currentExecutionNode && <p>当前节点：<strong>{currentExecutionNode.name}</strong><br />{currentExecutionNode.publicSummary}</p>}
                  <p>采购方只会看到节点状态和结果摘要，乙方提示词、知识库、密钥和内部成本始终隐藏。</p>
                  <div className="fulfillment-sop-actions">
                    {workspace.execution.canStart && <button type="button" disabled={working} onClick={startExecution}><Play />启动 SOP</button>}
                    {execution && <button type="button" onClick={() => setTab('execution')}>查看执行详情 <ChevronRight /></button>}
                  </div>
                </section>
                <section className="fulfillment-side-card">
                  <header><h2>近期动态</h2><button type="button" onClick={() => setTab('events')}>全部</button></header>
                  <EventTimeline events={workspace.events.slice(0, 6)} />
                </section>
                <section className="fulfillment-side-card">
                  <header><h2>订单联系人</h2><UserRound /></header>
                  <dl className="fulfillment-contacts">
                    <div><dt>采购方</dt><dd>{order.buyerName}</dd></div>
                    <div><dt>服务方</dt><dd>{order.providerName}</dd></div>
                    <div><dt>当前身份</dt><dd>{workspace.perspective === 'buyer' ? '采购方成员' : '服务方成员'}</dd></div>
                  </dl>
                </section>
                <section className="fulfillment-side-card fulfillment-funds">
                  <header><h2>资金状态</h2><strong>¥ {money(order.heldAmount)}</strong></header>
                  <p><CheckCircle2 />演示支付已确认，资金状态为模拟托管；真实支付接入后沿用同一订单接口。</p>
                  <span>{settlementStatusText(order.settlementStatus)}</span>
                </section>
              </aside>
            </div>
          )}

          {tab === 'execution' && (
            <section className="fulfillment-full-card execution-workspace">
              <header>
                <div>
                  <h2>SOP 与 AI 员工执行</h2>
                  <p>已成交订单使用冻结版本；执行不会直接改变验收、退款或放款状态。</p>
                </div>
                <button type="button" onClick={resource.reload}><RefreshCw />刷新</button>
              </header>
              {!execution ? (
                <div className="fulfillment-empty execution-empty">
                  <Bot />
                  <strong>{terminal ? '订单结案前未启动 SOP' : '当前里程碑尚未启动 SOP'}</strong>
                  <span>{terminal ? '订单流程已关闭，不再冻结版本或创建新的执行任务。' : '由乙方负责人启动，启动时会冻结 SOP 内容和版本 digest。'}</span>
                  {workspace.execution.canStart && <button type="button" disabled={working} onClick={startExecution}><Play />冻结并启动 SOP</button>}
                </div>
              ) : (
                <div className="execution-body">
                  <div className="execution-summary-row">
                    <div>
                      <span className={`execution-status is-${execution.status}`}>{executionStatus(execution.status)}</span>
                      <h3>{execution.sopSnapshot.summary.name || '订单 SOP'}</h3>
                      <p>版本 {execution.sopSnapshot.sourceSkillVersion || '-'} · 冻结于 {formatDateTime(execution.sopSnapshot.frozenAt)}</p>
                    </div>
                    <strong>{execution.progressPercent}%<small>执行进度</small></strong>
                  </div>
                  <div className="execution-progress"><i style={{ width: `${execution.progressPercent}%` }} /></div>
                  {workspace.perspective === 'provider' && (
                    <div className="execution-controls">
                      {execution.capabilities.canPause && <button type="button" disabled={working} onClick={() => commandExecution('pause', '执行已暂停')}><PauseCircle />暂停</button>}
                      {execution.capabilities.canResume && <button type="button" disabled={working} onClick={() => commandExecution('resume', '执行已恢复')}><Play />恢复</button>}
                      {execution.capabilities.canRetry && <button type="button" disabled={working} onClick={() => commandExecution('retry_node', '失败节点已重试')}><RotateCcw />重试节点</button>}
                      {execution.capabilities.canTakeover && currentExecutionNode?.executionMode !== 'human' && <button type="button" disabled={working} onClick={() => commandExecution('takeover', '节点已转为人工接管', '乙方交付人员已接管该节点')}><UserRound />人工接管</button>}
                      {execution.capabilities.canCompleteNode && currentExecutionNode?.executionMode === 'human' && <button type="button" className="is-primary" disabled={working} onClick={() => commandExecution('complete_node', '人工节点已完成', '乙方已完成人工处理并提交结果')}><CheckCircle2 />完成人工节点</button>}
                      {execution.capabilities.canCancel && <button type="button" className="is-danger" disabled={working} onClick={() => commandExecution('cancel', '执行已终止')}><Square />终止</button>}
                    </div>
                  )}
                  <div className="execution-grid">
                    <div className="execution-node-list">
                      <h3>节点轨迹</h3>
                      {execution.nodes.map((node) => (
                        <article key={node.id} className={`is-${node.status}`}>
                          <i>{node.status === 'succeeded' ? <CheckCircle2 /> : node.status === 'running' ? <Bot /> : node.sequence}</i>
                          <div>
                            <header><strong>{node.name}</strong><em>{executionNodeStatus(node.status)}</em></header>
                            <p>{node.publicSummary || '等待执行'}</p>
                            <small>{node.executionMode === 'human' ? `人工执行${node.claimedBy ? ` · ${node.claimedBy}` : ''}` : 'AI 员工执行'}{node.attempt > 1 ? ` · 第 ${node.attempt} 次尝试` : ''}</small>
                          </div>
                        </article>
                      ))}
                    </div>
                    <aside className="execution-event-panel">
                      <h3>执行事件</h3>
                      {execution.events.length ? execution.events.map((event) => (
                        <article key={event.eventId}>
                          <History />
                          <span><strong>{event.publicSummary || executionEventText(event.eventType)}</strong><small>{executionEventText(event.eventType)} · {formatDateTime(event.createdAt)}</small></span>
                        </article>
                      )) : <p>暂无执行事件</p>}
                    </aside>
                  </div>
                  <footer className="execution-privacy"><LockKeyhole /><span><strong>执行权限已隔离</strong>{execution.sopSnapshot.summary.privacyNotice || '采购方无法查看乙方提示词、知识库、密钥和内部成本。'}</span><code>SHA-256 {execution.sopSnapshot.definitionDigest.slice(0, 16)}…</code></footer>
                </div>
              )}
            </section>
          )}

          {tab === 'deliverables' && (
            <section className="fulfillment-full-card">
              <header><div><h2>全部交付物</h2><p>共 {workspace.deliverables.length} 项，版本和验收动作均留存审计记录。</p></div></header>
              <DeliverableList
                items={workspace.deliverables}
                closed={terminal}
                perspective={workspace.perspective}
                working={working}
                versionFiles={versionFiles}
                versionSummaries={versionSummaries}
                onVersionFile={(id, file) => setVersionFiles((items) => ({ ...items, [id]: file }))}
                onVersionSummary={(id, value) => setVersionSummaries((items) => ({ ...items, [id]: value }))}
                onSubmitVersion={submitNewVersion}
                onOpen={(id) => navigate(`/enterprise/orders/${order.id}/deliverables/${id}`)}
                onDownload={download}
              />
            </section>
          )}

          {tab === 'communication' && (
            <OrderCommunicationPanel
              orderId={order.id}
              organizationId={organization.selected!.id}
              milestoneId={currentMilestone.id}
              heldAmount={order.heldAmount}
              onBusinessChanged={resource.reload}
            />
          )}

          {tab === 'changes' && (
            <OrderChangePanel
              orderId={order.id}
              organizationId={organization.selected!.id}
              milestoneId={currentMilestone.id}
              heldAmount={order.heldAmount}
              onBusinessChanged={resource.reload}
            />
          )}

          {tab === 'disputes' && (
            <OrderDisputePanel
              orderId={order.id}
              organizationId={organization.selected!.id}
              heldAmount={order.heldAmount}
              milestones={order.milestones}
            />
          )}

          {tab === 'materials' && (
            <section className="fulfillment-full-card">
              <header><div><h2>材料请求与提交记录</h2><p>每次补充都会创建独立提交版本，原文件不被覆盖。</p></div></header>
              <MaterialList
                items={workspace.materialRequests}
                closed={terminal}
                perspective={workspace.perspective}
                working={working}
                files={materialFiles}
                notes={materialNotes}
                onFile={(id, file) => setMaterialFiles((items) => ({ ...items, [id]: file }))}
                onNote={(id, value) => setMaterialNotes((items) => ({ ...items, [id]: value }))}
                onSubmit={submitMaterial}
                onDownload={download}
              />
            </section>
          )}

          {tab === 'events' && (
            <section className="fulfillment-full-card">
              <header><div><h2>订单执行记录</h2><p>关键履约动作按时间倒序留痕，可供后续平台争议处理归档。</p></div><button type="button" onClick={resource.reload}><RefreshCw />刷新</button></header>
              <EventTimeline events={workspace.events} />
            </section>
          )}
        </>
      )}
    </main>
  );
}

function DeliverableList({
  items,
  closed,
  perspective,
  working,
  versionFiles,
  versionSummaries,
  onVersionFile,
  onVersionSummary,
  onSubmitVersion,
  onOpen,
  onDownload,
}: {
  items: Deliverable[];
  closed: boolean;
  perspective: 'buyer' | 'provider';
  working: boolean;
  versionFiles: Record<string, File | undefined>;
  versionSummaries: Record<string, string>;
  onVersionFile: (id: string, file?: File) => void;
  onVersionSummary: (id: string, value: string) => void;
  onSubmitVersion: (item: Deliverable) => void;
  onOpen: (id: string) => void;
  onDownload: (file: OrderFile) => void;
}) {
  if (!items.length) {
    return <div className="fulfillment-empty"><FolderOpen /><strong>{closed ? '结案前未创建交付物' : '尚未创建交付物'}</strong><span>{closed ? '订单流程已关闭，保留为空的交付历史。' : '服务方启动里程碑后可创建并提交首个版本。'}</span></div>;
  }
  return (
    <div className="fulfillment-deliverables">
      {items.map((item) => {
        const current = item.versions.find((version) => version.id === item.currentVersionId);
        const canResubmit = perspective === 'provider' && item.status === 'revision_requested';
        return (
          <article key={item.id}>
            <div className="fulfillment-file-icon"><FileText /></div>
            <div className="fulfillment-deliverable-copy">
              <div><strong>{item.name}</strong><em className={`is-${item.status}`}>{deliverableStatus(item.status)}</em></div>
              <p>{item.description || '按当前里程碑范围交付'}</p>
              <small>{current ? `当前 v${current.version} · ${formatDateTime(current.submittedAt)} · ${formatBytes(current.file.sizeBytes)}` : '尚未提交版本'}</small>
              {canResubmit && (
                <div className="fulfillment-resubmit">
                  <label><UploadCloud /><span>{versionFiles[item.id]?.name || '选择修改稿'}</span><input type="file" onChange={(event) => onVersionFile(item.id, event.target.files?.[0])} /></label>
                  <input value={versionSummaries[item.id] || ''} onChange={(event) => onVersionSummary(item.id, event.target.value)} placeholder="说明本版修改内容" />
                  <button type="button" disabled={working} onClick={() => onSubmitVersion(item)}>重新提交</button>
                </div>
              )}
            </div>
            <div className="fulfillment-deliverable-actions">
              {current && <button type="button" onClick={() => onDownload(current.file)}><Download />下载</button>}
              <button type="button" className="is-primary" onClick={() => onOpen(item.id)}>{perspective === 'buyer' && item.status === 'submitted' ? '查看并验收' : '查看版本'}<ChevronRight /></button>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function MaterialList({
  items,
  closed,
  perspective,
  working,
  files,
  notes,
  onFile,
  onNote,
  onSubmit,
  onDownload,
}: {
  items: MaterialRequest[];
  closed: boolean;
  perspective: 'buyer' | 'provider';
  working: boolean;
  files: Record<string, File | undefined>;
  notes: Record<string, string>;
  onFile: (id: string, file?: File) => void;
  onNote: (id: string, value: string) => void;
  onSubmit: (item: MaterialRequest) => void;
  onDownload: (file: OrderFile) => void;
}) {
  if (!items.length) {
    return <div className="fulfillment-empty"><PackageCheck /><strong>{closed ? '结案前没有材料请求' : '当前没有材料请求'}</strong><span>{closed ? '订单流程已关闭，不再创建新的材料待办。' : '需要补充信息时，由服务方发起结构化材料请求。'}</span></div>;
  }
  return (
    <div className="fulfillment-materials">
      {items.map((item) => (
        <article key={item.id}>
          <header>
            <div><CircleDot /><span><strong>{item.title}</strong><small>{item.description}</small></span></div>
            <em className={`is-${item.status}`}>{item.status === 'open' ? '待补充' : '已提交'}</em>
          </header>
          <p>发起人：{item.requestedBy} · {item.dueAt ? `期望 ${formatDateTime(item.dueAt)} 前提交` : '未设置截止时间'}</p>
          {item.submissions.map((submission) => (
            <div className="fulfillment-submission" key={submission.id}>
              <span><CheckCircle2 /><strong>提交 v{submission.version}</strong><small>{submission.submittedBy} · {formatDateTime(submission.createdAt)}</small></span>
              <p>{submission.note || '未填写说明'}</p>
              {submission.files.map((file) => <button type="button" key={file.id} onClick={() => onDownload(file)}><FileText />{file.filename}<Download /></button>)}
            </div>
          ))}
          {perspective === 'buyer' && item.status === 'open' && (
            <div className="fulfillment-material-submit">
              <label><UploadCloud /><span>{files[item.id]?.name || '选择材料文件'}</span><input type="file" onChange={(event: ChangeEvent<HTMLInputElement>) => onFile(item.id, event.target.files?.[0])} /></label>
              <input value={notes[item.id] || ''} onChange={(event) => onNote(item.id, event.target.value)} placeholder="补充说明（可选）" />
              <button type="button" disabled={working} onClick={() => onSubmit(item)}>提交材料</button>
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

function EventTimeline({ events }: { events: Array<{ id: string; summary: string; actor: string; partyRole: string; createdAt: string }> }) {
  if (!events.length) return <p className="fulfillment-empty-copy">暂无执行记录。</p>;
  return (
    <div className="fulfillment-event-list">
      {events.map((event) => (
        <article key={event.id}>
          <i><History /></i>
          <span><strong>{event.summary}</strong><small>{event.actor} · {partyText(event.partyRole)} · {formatDateTime(event.createdAt)}</small></span>
        </article>
      ))}
    </div>
  );
}

function statusText(value: string) {
  return {
    paid: '待开始',
    in_progress: '进行中',
    pending_acceptance: '待验收',
    completed: '已完成',
    cancelled: '已取消',
    disputed: '平台争议处理中',
  }[value] || value;
}

function executionStatus(value: string) {
  return {
    queued: '待执行',
    running: '执行中',
    paused: '已暂停',
    waiting_confirmation: '等待确认',
    succeeded: '执行完成',
    failed: '执行失败',
    cancelled: '已终止',
  }[value] || value;
}

function executionNodeStatus(value: string) {
  return {
    pending: '待执行',
    running: '执行中',
    waiting_confirmation: '等待确认',
    succeeded: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }[value] || value;
}

function executionEventText(value: string) {
  return {
    'run.started': 'SOP 启动',
    'run.paused': '执行暂停',
    'run.resumed': '执行恢复',
    'run.succeeded': '执行完成',
    'run.failed': '执行失败',
    'node.started': '节点开始',
    'node.succeeded': '节点完成',
    'node.failed': '节点失败',
    'command.takeover': '人工接管',
    'command.retry_node': '节点重试',
    'command.complete_node': '人工完成',
  }[value] || value;
}

function milestoneStatus(value: string) {
  return {
    pending: '待开始',
    in_progress: '进行中',
    pending_acceptance: '待验收',
    revision_requested: '修改中',
    accepted: '已验收',
    disputed: '争议中',
    closed_by_dispute: '争议结案，不再执行',
  }[value] || value;
}

function settlementStatusText(value: string) {
  return {
    held_demo: '演示冻结中',
    frozen_dispute_demo: '争议冻结中',
    release_eligible_demo: '待演示放款',
    demo_refunded: '已演示全额退款',
    demo_partially_refunded: '已演示部分退款',
    demo_released: '已演示全额放款',
    demo_split_settled: '已演示分配结算',
    demo_partially_settled: '已演示部分结算',
    change_adjustment_pending_demo: '待演示金额调整',
    frozen_cancel_demo: '取消复核冻结',
  }[value] || value;
}

function deliverableStatus(value: string) {
  return {
    draft: '草稿',
    submitted: '待验收',
    revision_requested: '需修改',
    accepted: '已验收',
    disputed: '争议中',
  }[value] || value;
}

function partyText(value: string) {
  return { buyer: '采购方', provider: '服务方', platform: '平台' }[value] || value;
}

function money(value: string) {
  return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(new Date(value));
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
