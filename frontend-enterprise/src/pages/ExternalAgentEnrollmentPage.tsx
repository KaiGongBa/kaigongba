import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowLeft, BookOpen, CheckCircle2, Clipboard, Cloud, FileJson, KeyRound, LoaderCircle, RefreshCw, ShieldCheck, Terminal, Wifi } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { api } from '@/api/client';
import { notify } from '@/components/ui/app-toast';
import { Button } from '@/components/ui/button';
import type { MarketplaceOrganization } from '@/features/marketplace/types';

type EnrollmentCreated = {
  id: string;
  organizationId: string;
  status: string;
  pairingCode: string;
  pairingCodeHint: string;
  expiresAt: string;
  requestedScopes: string[];
  manifestVersion: string;
  installInstruction: string;
};

type EnrollmentRead = Omit<EnrollmentCreated, 'pairingCode' | 'installInstruction'> & {
  usedAt?: string;
  connectionId?: string;
  createdAt: string;
};

type DiscoveredAsset = {
  id: string;
  externalId: string;
  kind: string;
  name: string;
  description: string;
  version: string;
  portable: boolean;
  callable: boolean;
  selected: boolean;
  riskLevel: string;
  verificationStatus: string;
  sourceType: string;
  sourceHash: string;
  permissions: string[];
  evidence: Record<string, unknown>;
  provenance: Record<string, { source?: string; method?: string; confidence?: number }>;
};

type ManifestRead = {
  id: string;
  connectionId: string;
  sourceDigest: string;
  status: string;
  normalizedAgent: Record<string, unknown>;
  disclosure: Record<string, unknown>;
  validationErrors: Array<{ code: string; message: string }>;
  validationWarnings: Array<{ code: string; message: string }>;
  assets: DiscoveredAsset[];
  submittedAt: string;
  reviewedAt?: string;
};

type ImportDraftRead = {
  id: string;
  organizationId: string;
  connectionId: string;
  manifestId: string;
  agentName: string;
  roleName: string;
  jobDescription: string;
  serviceScope: string[];
  restrictions: string[];
  selectedAssetIds: string[];
  fieldProvenance: Record<string, { source?: unknown; method?: string; user_modified?: boolean }>;
  executionMode: string;
  syncPolicy: 'manual' | 'notify' | 'scheduled';
  status: string;
  agentProfileId?: string;
};

type ConnectionTestRead = {
  id: string;
  connectionId: string;
  agentProfileId: string;
  status: 'queued' | 'claimed' | 'passed' | 'failed' | 'expired';
  expected: Record<string, unknown>;
  result: Record<string, unknown>;
  error: Record<string, unknown>;
  expiresAt: string;
  completedAt?: string;
};

export default function ExternalAgentEnrollmentPage() {
  const navigate = useNavigate();
  const [organizations, setOrganizations] = useState<MarketplaceOrganization[]>([]);
  const [organizationId, setOrganizationId] = useState('');
  const [transport, setTransport] = useState<'polling' | 'webhook' | 'a2a' | 'manual'>('polling');
  const [enrollment, setEnrollment] = useState<EnrollmentCreated | null>(null);
  const [status, setStatus] = useState<EnrollmentRead | null>(null);
  const [manifest, setManifest] = useState<ManifestRead | null>(null);
  const [draft, setDraft] = useState<ImportDraftRead | null>(null);
  const [connectionTest, setConnectionTest] = useState<ConnectionTestRead | null>(null);
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [reviewing, setReviewing] = useState(false);
  const [draftBusy, setDraftBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.get<MarketplaceOrganization[]>('/api/marketplace/organizations').then((rows) => {
      if (cancelled) return;
      setOrganizations(rows);
      setOrganizationId(rows[0]?.id || '');
    }).catch((error) => notify.error(error instanceof Error ? error.message : '企业列表加载失败')).finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!enrollment || status?.status === 'registered') return undefined;
    const timer = window.setInterval(() => {
      api.get<EnrollmentRead>(`/api/enterprise/external-agent-enrollments/${encodeURIComponent(enrollment.id)}`).then(setStatus).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [enrollment, status?.status]);

  useEffect(() => {
    if (!enrollment || status?.status !== 'registered' || manifest?.status === 'approved') return undefined;
    let cancelled = false;
    const load = () => api.get<ManifestRead>(`/api/enterprise/external-agent-enrollments/${encodeURIComponent(enrollment.id)}/manifest`).then((result) => {
      if (cancelled) return;
      setManifest(result);
      setSelectedAssetIds(result.assets.filter((item) => item.selected).map((item) => item.id));
    }).catch(() => undefined);
    void load();
    const timer = window.setInterval(load, 3000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [enrollment, manifest?.status, status?.status]);

  useEffect(() => {
    if (manifest?.status !== 'approved' || !status?.connectionId || draft) return;
    api.post<ImportDraftRead>(`/api/enterprise/external-agents/${encodeURIComponent(status.connectionId)}/import-draft`, {
      idempotency_key: `web-agent-draft-${manifest.id}`,
    }).then(setDraft).catch((error) => notify.error(error instanceof Error ? error.message : '员工草稿生成失败'));
  }, [draft, manifest?.id, manifest?.status, status?.connectionId]);

  useEffect(() => {
    if (!connectionTest || ['passed', 'failed', 'expired'].includes(connectionTest.status)) return undefined;
    const timer = window.setInterval(() => {
      api.get<ConnectionTestRead>(`/api/enterprise/external-agent-connection-tests/${encodeURIComponent(connectionTest.id)}`).then(setConnectionTest).catch(() => undefined);
    }, 2500);
    return () => window.clearInterval(timer);
  }, [connectionTest]);

  const selectedOrganization = organizations.find((item) => item.id === organizationId);
  const expired = Boolean(enrollment && new Date(enrollment.expiresAt).getTime() <= Date.now());
  const pairingCode = enrollment?.pairingCode.trim() || '';
  const pairingReady = Boolean(pairingCode && !expired);
  const connectorSdkRevision = '833453adcfa1bd64d4eb9c9769756ea138b4414a';
  const connectorInstallCommand = `python3 -m pip install "git+https://github.com/KaiGongBa/kaigongba.git@${connectorSdkRevision}#subdirectory=sdk/python"`;
  const connectorManifestCommand = 'kaigongba-agent init-manifest --output kaigongba-agent-manifest.json';
  const connectorCommand = pairingReady ? `kaigongba-agent --server ${window.location.origin} connect --pairing-code '${pairingCode}' --manifest ./kaigongba-agent-manifest.json --provider self-hosted --external-agent-ref external-${enrollment?.id}` : '';
  const scopes = useMemo(() => {
    const base = ['manifest:write', 'heartbeat:write'];
    return transport === 'manual' ? base : [...base, 'tasks:claim', 'events:write', 'artifacts:write'];
  }, [transport]);

  async function createEnrollment() {
    if (!organizationId) {
      notify.error('请先选择外部 Agent 所属企业');
      return;
    }
    setCreating(true);
    try {
      const result = await api.post<EnrollmentCreated>('/api/enterprise/external-agent-enrollments', {
        organization_id: organizationId,
        idempotency_key: `web-enrollment-${crypto.randomUUID()}`,
        requested_scopes: scopes,
        manifest_version: '1.0',
      });
      setEnrollment(result);
      setStatus(null);
      notify.success('一次性配对码已生成');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '生成配对码失败');
    } finally {
      setCreating(false);
    }
  }

  async function copy(value: string, message: string) {
    if (!value.trim()) {
      notify.error('当前没有可复制的配对码或接入指令');
      return;
    }
    await navigator.clipboard.writeText(value);
    notify.success(message);
  }

  async function uploadManifestFile(file: File) {
    if (!status?.connectionId) return;
    try {
      const manifestPayload = JSON.parse(await file.text()) as Record<string, unknown>;
      const result = await api.post<ManifestRead>(`/api/enterprise/external-agents/${encodeURIComponent(status.connectionId)}/manifest`, {
        idempotency_key: `manual-manifest-${crypto.randomUUID()}`,
        manifest: manifestPayload,
      });
      setManifest(result);
      setSelectedAssetIds(result.assets.filter((item) => item.selected).map((item) => item.id));
      notify.success(result.status === 'rejected_validation' ? '清单已校验，请按错误提示修复' : '能力清单已上传并完成标准化');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : 'Manifest 上传失败');
    }
  }

  async function reviewManifest(decision: 'approved' | 'changes_requested') {
    if (!manifest) return;
    setReviewing(true);
    try {
      const result = await api.post<ManifestRead>(`/api/enterprise/external-agent-manifests/${encodeURIComponent(manifest.id)}/review`, {
        decision,
        selected_asset_ids: selectedAssetIds,
      });
      setManifest(result);
      notify.success(decision === 'approved' ? '能力清单已确认，正在生成员工草稿' : '已要求 Agent 修正并重新提交清单');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '能力清单审核失败');
    } finally {
      setReviewing(false);
    }
  }

  async function saveDraft() {
    if (!draft) return;
    setDraftBusy(true);
    try {
      const result = await api.put<ImportDraftRead>(`/api/enterprise/external-agent-import-drafts/${encodeURIComponent(draft.id)}`, {
        agent_name: draft.agentName,
        role_name: draft.roleName,
        job_description: draft.jobDescription,
        service_scope: draft.serviceScope,
        restrictions: draft.restrictions,
        sync_policy: draft.syncPolicy,
      });
      setDraft(result);
      notify.success('员工档案草稿已保存');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '草稿保存失败');
    } finally {
      setDraftBusy(false);
    }
  }

  async function confirmDraft() {
    if (!draft) return;
    setDraftBusy(true);
    try {
      const saved = draft.status === 'draft' ? await api.put<ImportDraftRead>(`/api/enterprise/external-agent-import-drafts/${encodeURIComponent(draft.id)}`, {
        agent_name: draft.agentName,
        role_name: draft.roleName,
        job_description: draft.jobDescription,
        service_scope: draft.serviceScope,
        restrictions: draft.restrictions,
        sync_policy: draft.syncPolicy,
      }) : draft;
      const result = await api.post<ImportDraftRead>(`/api/enterprise/external-agent-import-drafts/${encodeURIComponent(saved.id)}/confirm`, {
        idempotency_key: `web-confirm-agent-${saved.id}`,
      });
      setDraft(result);
      notify.success('外接 AI 员工已创建，下一步进行连接测试');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '员工创建失败');
    } finally {
      setDraftBusy(false);
    }
  }

  async function startConnectionTest() {
    if (!draft?.connectionId) return;
    if (transport === 'manual') {
      notify.error('临时手动执行模式不领取在线任务，无需进行连接测试');
      return;
    }
    setDraftBusy(true);
    try {
      const result = await api.post<ConnectionTestRead>(`/api/enterprise/external-agents/${encodeURIComponent(draft.connectionId)}/connection-tests`, {
        idempotency_key: `web-connection-test-${draft.id}`,
      });
      setConnectionTest(result);
      notify.success('无副作用连接测试已下发');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '连接测试创建失败');
    } finally {
      setDraftBusy(false);
    }
  }

  if (loading) return <main className="external-agent-enrollment-page"><div className="external-agent-loading"><LoaderCircle className="is-spinning" />正在加载企业数据…</div></main>;

  return (
    <main className="external-agent-enrollment-page">
      <header><button type="button" onClick={() => navigate('/enterprise/agents')}><ArrowLeft />数字员工</button><div><h1>外接已有 Agent</h1><p>让 Agent 在原环境扫描、登记并执行；平台默认只接收经你确认的能力元数据。</p></div><span><ShieldCheck />安全配对</span></header>
      <div className="external-agent-stepper"><span className="is-active"><b>1</b>生成配对</span><span className={enrollment ? 'is-active' : ''}><b>2</b>Agent 连接</span><span className={manifest ? 'is-active' : ''}><b>3</b>能力发现</span><span className={manifest?.status === 'approved' ? 'is-active' : ''}><b>4</b>确认员工</span><span className={draft?.status === 'confirmed' || connectionTest ? 'is-active' : ''}><b>5</b>连接测试</span></div>

      {!enrollment ? <section className="external-agent-enrollment-card">
        <div className="external-agent-card-heading"><KeyRound /><div><h2>创建一次性配对</h2><p>配对码 15 分钟有效、只能登记一个 Agent，使用后立即失效。</p></div></div>
        <div className="external-agent-form-grid"><label><span>所属企业</span><select value={organizationId} onChange={(event) => setOrganizationId(event.target.value)}>{organizations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label><span>首选通信方式</span><select value={transport} onChange={(event) => setTransport(event.target.value as typeof transport)}><option value="polling">主动轮询（本地 Agent 推荐）</option><option value="webhook">Webhook（云端 Agent）</option><option value="a2a">A2A</option><option value="manual">临时手动执行</option></select></label></div>
        <div className="external-agent-scope-list"><strong>本次授权范围</strong>{scopes.map((scope) => <span key={scope}><CheckCircle2 />{scopeLabel(scope)}</span>)}<small>不包含模型 Key、知识正文、完整对话、系统提示词或未选择的本地文件。</small></div>
        <Button disabled={creating || !organizationId} onClick={() => void createEnrollment()}>{creating ? <><LoaderCircle className="is-spinning" />正在生成</> : <><KeyRound />生成配对码</>}</Button>
      </section> : <div className="external-agent-enrollment-layout">
        <section className="external-agent-enrollment-card">
          <div className="external-agent-card-heading"><Wifi /><div><h2>{status?.status === 'registered' ? 'Agent 已安全登记' : '等待 Agent 连接'}</h2><p>{selectedOrganization?.name} · 配对码尾号 {enrollment.pairingCodeHint}</p></div></div>
          {status?.status === 'registered' && manifest?.status === 'approved' ? (draft ? <EmployeeDraftReview draft={draft} onChange={setDraft} busy={draftBusy} connectionTest={connectionTest} testable={transport !== 'manual'} onSave={saveDraft} onConfirm={confirmDraft} onStartTest={startConnectionTest} /> : <div className="external-agent-loading"><LoaderCircle className="is-spinning" />正在根据已确认能力生成员工草稿…</div>) : status?.status === 'registered' && manifest ? <ManifestReview manifest={manifest} selectedAssetIds={selectedAssetIds} onSelectionChange={setSelectedAssetIds} reviewing={reviewing} onReview={reviewManifest} /> : status?.status === 'registered' ? <div className="external-agent-manifest-wait"><div className="external-agent-success"><CheckCircle2 /><div><strong>Agent 登记成功</strong><span>连接 ID：{status.connectionId}</span><small>正在等待 Agent 在本地展示扫描范围并确认上报。</small></div></div><div className="external-agent-waiting"><LoaderCircle className="is-spinning" /><span>等待能力清单…</span></div><label className="external-agent-manifest-upload"><FileJson /><span><strong>手动上传 Manifest</strong><small>适用于暂不支持接入 Skill 的 Agent；仍会执行相同校验。</small></span><input type="file" accept="application/json,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadManifestFile(file); event.target.value = ''; }} /></label></div> : <>
            <div className={`external-agent-pairing-code ${expired ? 'is-expired' : ''}`}><small>{expired ? '配对码已过期' : '一次性配对码'}</small><strong>{pairingCode || '尚未生成'}</strong><button type="button" disabled={!pairingReady} onClick={() => void copy(pairingCode, '配对码已复制')}><Clipboard />复制</button></div>
            <ol className="external-agent-instructions"><li>安装“开工吧接入助手”，生成并人工确认 Manifest 扫描范围。</li><li>运行登记命令；Agent 将通过 preflight、register 和 Manifest 1.0 完成连接。</li><li>保持 worker 运行以持续上报心跳、领取连接测试和执行任务，无需开放本机公网端口。</li></ol>
            <div className="external-agent-connector-commands"><div><span><Terminal />安装接入助手</span><code>{connectorInstallCommand}</code><button type="button" onClick={() => void copy(connectorInstallCommand, '安装命令已复制')}><Clipboard />复制</button></div><div><span><FileJson />生成能力清单</span><code>{connectorManifestCommand}</code><button type="button" onClick={() => void copy(connectorManifestCommand, 'Manifest 命令已复制')}><Clipboard />复制</button></div><div><span><Wifi />连接当前平台</span><code>{connectorCommand || '配对码不可用，请重新生成后连接'}</code><button type="button" disabled={!pairingReady} onClick={() => void copy(connectorCommand, '连接命令已复制')}><Clipboard />复制</button></div><a href={`https://github.com/KaiGongBa/kaigongba/tree/${connectorSdkRevision}/sdk/python#readme`} target="_blank" rel="noreferrer"><BookOpen />查看安装、Manifest 与任务处理文档</a></div>
            <div className="external-agent-waiting"><LoaderCircle className="is-spinning" /><span>正在等待 Agent 主动出站连接…</span><button type="button" onClick={() => api.get<EnrollmentRead>(`/api/enterprise/external-agent-enrollments/${encodeURIComponent(enrollment.id)}`).then(setStatus)}><RefreshCw />刷新</button></div>
          </>}
        </section>
        <aside className="external-agent-enrollment-card"><div className="external-agent-card-heading"><Cloud /><div><h2>接入边界</h2><p>适用于 Codex、Coze、自建 Agent 等</p></div></div><dl><div><dt>运行位置</dt><dd>Agent 原环境</dd></div><div><dt>平台保存</dt><dd>身份、能力元数据、状态与结果</dd></div><div><dt>默认不保存</dt><dd>源码、密钥、知识正文与思维链</dd></div><div><dt>当前协议</dt><dd>1.0 / Manifest 1.0</dd></div><div><dt>连接状态</dt><dd>{status?.status === 'registered' ? '已登记，正在同步能力' : expired ? '配对码已过期' : '等待 Agent 主动连接'}</dd></div></dl><button type="button" className="external-agent-copy-instruction" disabled={!pairingReady} onClick={() => void copy(`${enrollment.installInstruction}\n${connectorInstallCommand}\n${connectorManifestCommand}\n${connectorCommand}`, '接入指令已复制')}><Clipboard />复制完整接入指令</button></aside>
      </div>}
    </main>
  );
}

function EmployeeDraftReview({ draft, onChange, busy, connectionTest, testable, onSave, onConfirm, onStartTest }: { draft: ImportDraftRead; onChange: (value: ImportDraftRead) => void; busy: boolean; connectionTest: ConnectionTestRead | null; testable: boolean; onSave: () => Promise<void>; onConfirm: () => Promise<void>; onStartTest: () => Promise<void> }) {
  const confirmed = draft.status === 'confirmed';
  const update = <K extends keyof ImportDraftRead>(key: K, value: ImportDraftRead[K]) => onChange({ ...draft, [key]: value });
  const splitLines = (value: string) => value.split('\n').map((item) => item.trim()).filter(Boolean);
  return <div className="external-agent-draft-review">
    <div className="external-agent-draft-heading"><div><span>员工档案草稿</span><h2>{confirmed ? '员工已创建' : '确认员工档案'}</h2><p>自动字段均保留来源；修改只影响平台展示，不会改写外部 Agent。</p></div><em>外部运行</em></div>
    <div className="external-agent-draft-grid">
      <label><span>数字员工姓名 <FieldSource value={draft.fieldProvenance.agent_name} /></span><input disabled={confirmed} value={draft.agentName} onChange={(event) => update('agentName', event.target.value)} /></label>
      <label><span>职位 <FieldSource value={draft.fieldProvenance.role_name} /></span><input disabled={confirmed} value={draft.roleName} onChange={(event) => update('roleName', event.target.value)} /></label>
      <label className="is-wide"><span>岗位描述 <FieldSource value={draft.fieldProvenance.job_description} /></span><textarea disabled={confirmed} rows={4} value={draft.jobDescription} onChange={(event) => update('jobDescription', event.target.value)} /></label>
      <label><span>服务范围（每行一项） <FieldSource value={draft.fieldProvenance.service_scope} /></span><textarea disabled={confirmed} rows={5} value={draft.serviceScope.join('\n')} onChange={(event) => update('serviceScope', splitLines(event.target.value))} /></label>
      <label><span>明确限制（每行一项） <FieldSource value={draft.fieldProvenance.restrictions} /></span><textarea disabled={confirmed} rows={5} value={draft.restrictions.join('\n')} onChange={(event) => update('restrictions', splitLines(event.target.value))} /></label>
      <label><span>能力同步策略</span><select disabled={confirmed} value={draft.syncPolicy} onChange={(event) => update('syncPolicy', event.target.value as ImportDraftRead['syncPolicy'])}><option value="manual">手动审核后同步</option><option value="notify">检测变化并通知</option><option value="scheduled">定期同步（仍需确认）</option></select></label>
      <label><span>运行与绑定</span><div className="external-agent-readonly-value">外部运行 · 已选 {draft.selectedAssetIds.length} 项能力</div></label>
    </div>
    {!confirmed ? <div className="external-agent-review-actions"><button type="button" disabled={busy} onClick={() => void onSave()}>保存草稿</button><Button disabled={busy || !draft.agentName.trim() || !draft.roleName.trim() || !draft.jobDescription.trim()} onClick={() => void onConfirm()}>{busy ? <LoaderCircle className="is-spinning" /> : <CheckCircle2 />}确认并创建员工</Button></div> : <ConnectionTestPanel test={connectionTest} busy={busy} testable={testable} onStart={onStartTest} />}
  </div>;
}

function FieldSource({ value }: { value?: { source?: unknown; method?: string; user_modified?: boolean } }) {
  return <small title={JSON.stringify(value || {})}>{value?.user_modified ? '已人工修改' : value?.method === 'deterministic' ? '清单原值' : '规则生成'}</small>;
}

function ConnectionTestPanel({ test, busy, testable, onStart }: { test: ConnectionTestRead | null; busy: boolean; testable: boolean; onStart: () => Promise<void> }) {
  if (!testable) return <div className="external-agent-success"><CheckCircle2 /><div><strong>员工已按临时手动执行模式登记</strong><small>该模式不领取在线任务，因此不申请 tasks:claim / events:write 权限，也不进入连接测试或市场在线发布。</small></div></div>;
  if (!test) return <div className="external-agent-connection-test"><div><Wifi /><span><strong>执行无副作用连接测试</strong><small>仅核对员工名称、协议版本和能力数量，不读取任何外部数据。</small></span></div><Button disabled={busy} onClick={() => void onStart()}>{busy ? <LoaderCircle className="is-spinning" /> : <Wifi />}开始连接测试</Button></div>;
  if (test.status === 'passed') return <div className="external-agent-success"><CheckCircle2 /><div><strong>连接测试通过，员工已可用</strong><small>外部 Agent 身份、协议与已启用能力数量匹配。后续任务仍在 Agent 原环境执行。</small></div></div>;
  if (test.status === 'failed' || test.status === 'expired') return <div className="external-agent-manifest-errors"><AlertTriangle /><div><h3>{test.status === 'expired' ? '连接测试已过期' : '连接测试未通过'}</h3><p>{test.status === 'expired' ? '请重新创建测试并确认 Agent 连接器正在运行。' : '返回的身份或能力信息与已确认档案不一致，请检查接入配置。'}</p><button type="button" onClick={() => void onStart()}>重新测试</button></div></div>;
  return <div className="external-agent-connection-test is-waiting"><div><LoaderCircle className="is-spinning" /><span><strong>{test.status === 'claimed' ? 'Agent 已领取测试' : '等待 Agent 领取测试'}</strong><small>请保持外部 Agent 的开工吧接入助手运行；页面会自动刷新结果。</small></span></div><em>{new Date(test.expiresAt).toLocaleTimeString()} 前有效</em></div>;
}

function ManifestReview({ manifest, selectedAssetIds, onSelectionChange, reviewing, onReview }: { manifest: ManifestRead; selectedAssetIds: string[]; onSelectionChange: (value: string[]) => void; reviewing: boolean; onReview: (decision: 'approved' | 'changes_requested') => Promise<void> }) {
  const selected = new Set(selectedAssetIds);
  if (manifest.status === 'rejected_validation') return <div className="external-agent-manifest-errors"><AlertTriangle /><div><h3>能力清单未通过安全校验</h3>{manifest.validationErrors.map((item) => <p key={`${item.code}-${item.message}`}><code>{item.code}</code>{item.message}</p>)}</div></div>;
  return <div className="external-agent-manifest-review"><div className="external-agent-manifest-summary"><div><span>员工候选</span><strong>{String(manifest.normalizedAgent.name || '未命名 Agent')}</strong><small>{String(manifest.normalizedAgent.description || '')}</small></div><dl><div><dt>能力总数</dt><dd>{manifest.assets.length}</dd></div><div><dt>已选择</dt><dd>{selectedAssetIds.length}</dd></div><div><dt>清单摘要</dt><dd title={manifest.sourceDigest}>{manifest.sourceDigest.slice(0, 12)}…</dd></div></dl></div>{manifest.validationWarnings.length > 0 && <div className="external-agent-manifest-warning"><AlertTriangle />{manifest.validationWarnings.map((item) => item.message).join('；')}</div>}<div className="external-agent-asset-list">{manifest.assets.map((asset) => <label className={selected.has(asset.id) ? 'is-selected' : ''} key={asset.id}><input type="checkbox" checked={selected.has(asset.id)} disabled={manifest.status === 'approved'} onChange={(event) => onSelectionChange(event.target.checked ? [...selectedAssetIds, asset.id] : selectedAssetIds.filter((id) => id !== asset.id))} /><span className={`is-${asset.kind}`}>{assetKind(asset.kind)}</span><div><strong>{asset.name}<small>{asset.version || '未声明版本'}</small></strong><p>{asset.description || '无补充说明'}</p><footer><em className={`is-${asset.riskLevel}`}>风险 {riskLabel(asset.riskLevel)}</em><em>{asset.callable ? '可调用' : '仅登记'}</em><em>{asset.portable ? '可导入' : '不可导出'}</em><em title={JSON.stringify(asset.provenance)}>来源 {asset.sourceType} · {asset.verificationStatus === 'verified_metadata' ? '元数据已验证' : '待连接测试'}</em></footer></div></label>)}</div>{manifest.status === 'approved' ? <div className="external-agent-success"><CheckCircle2 /><div><strong>能力清单已确认</strong><small>已选择 {selectedAssetIds.length} 项能力，下一阶段将生成可编辑员工档案。</small></div></div> : <div className="external-agent-review-actions"><button type="button" disabled={reviewing} onClick={() => void onReview('changes_requested')}>要求修正</button><Button disabled={reviewing} onClick={() => void onReview('approved')}>{reviewing ? <LoaderCircle className="is-spinning" /> : <CheckCircle2 />}确认所选能力</Button></div>}</div>;
}

function scopeLabel(value: string) {
  return ({ 'manifest:write': '提交经用户确认的能力清单', 'heartbeat:write': '上报在线与健康状态', 'tasks:claim': '主动领取已授权任务', 'events:write': '回传业务进度事件', 'artifacts:write': '回传任务制品' } as Record<string, string>)[value] || value;
}

function assetKind(value: string) { return ({ skill: 'Skill', sop: 'SOP', tool: 'Tool', knowledge: '知识', model: '模型', runtime: '运行时' } as Record<string, string>)[value] || value; }
function riskLabel(value: string) { return ({ low: '低', medium: '中', high: '高' } as Record<string, string>)[value] || value; }
