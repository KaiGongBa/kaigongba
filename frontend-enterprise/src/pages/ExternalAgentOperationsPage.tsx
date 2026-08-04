import { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowLeft, Ban, CheckCircle2, Clipboard, KeyRound, LoaderCircle, Play, RefreshCw, RotateCcw, ShieldCheck, Unplug, Wifi } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '@/api/client';
import { notify } from '@/components/ui/app-toast';
import { Button } from '@/components/ui/button';

type Connection = { id: string; organizationId: string; agentProfileId?: string; provider: string; runtimeType: string; executionMode: string; transport: string; externalAgentRef: string; endpoint: string; protocolVersion: string; status: string; healthStatus: string; lastHeartbeatAt?: string; lastManifestSyncAt?: string; syncPolicy: string; metadata: Record<string, unknown>; createdAt: string; updatedAt: string };
type Policy = { id: string; connectionId: string; allowedDomains: string[]; blockedDomains: string[]; webhookDeliveryEnabled: boolean; maxRequestsPerMinute: number; maxConcurrentTasks: number; heartbeatIntervalSeconds: number; status: string; updatedAt: string };
type TaskEvent = { id: string; sequence: number; eventType: string; summary: string; payload: Record<string, unknown>; actorType: string; createdAt: string };
type Task = { id: string; connectionId: string; capabilityAssetId: string; capabilityExternalId: string; status: string; goal: string; input: Record<string, unknown>; output: Record<string, unknown>; error: Record<string, unknown>; artifactRefs: Array<Record<string, unknown>>; priority: number; attemptCount: number; maxAttempts: number; approvalState: string; leaseExpiresAt?: string; timeoutAt: string; nextRetryAt?: string; resultReceiptId?: string; createdAt: string; startedAt?: string; completedAt?: string; events: TaskEvent[] };
type Operations = { connection: Connection; policy: Policy; taskMetrics: Record<string, number>; healthMetrics: Record<string, unknown>; alerts: Array<{ level: string; code: string; message: string }>; recentHeartbeats: Array<Record<string, unknown>>; recentTasks: Task[] };
type Asset = { id: string; externalId: string; kind: string; name: string; description: string; selected: boolean; callable: boolean; portable: boolean; riskLevel: string; verificationStatus: string; permissions: string[] };
type Manifest = { id: string; sourceDigest: string; status: string; normalizedAgent: Record<string, unknown>; assets: Asset[]; submittedAt: string };

export default function ExternalAgentOperationsPage() {
  const { connectionId = '' } = useParams();
  const navigate = useNavigate();
  const [operations, setOperations] = useState<Operations | null>(null);
  const [manifest, setManifest] = useState<Manifest | null>(null);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [tab, setTab] = useState<'overview' | 'tasks' | 'capabilities' | 'security'>('overview');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [credential, setCredential] = useState('');
  const [taskFormOpen, setTaskFormOpen] = useState(false);

  const load = useCallback(async (silent = false) => {
    if (!connectionId) return;
    if (!silent) setLoading(true);
    try {
      const [ops, mf] = await Promise.all([
        api.get<Operations>(`/api/enterprise/external-agents/${encodeURIComponent(connectionId)}/operations`),
        api.get<Manifest>(`/api/enterprise/external-agents/${encodeURIComponent(connectionId)}/manifest`).catch(() => null),
      ]);
      setOperations(ops);
      setManifest(mf);
      if (selectedTask) {
        const updated = ops.recentTasks.find((item) => item.id === selectedTask.id);
        if (updated) setSelectedTask(updated);
      }
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '外接 Agent 连接数据加载失败');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [connectionId, selectedTask]);

  useEffect(() => { void load(); }, [connectionId]);
  useEffect(() => { const timer = window.setInterval(() => void load(true), 5000); return () => window.clearInterval(timer); }, [connectionId]);

  async function rotateCredential() {
    setBusy(true);
    try {
      const result = await api.post<{ credential: string }>(`/api/enterprise/external-agents/${encodeURIComponent(connectionId)}/rotate-credential`, { idempotency_key: `web-rotate-${crypto.randomUUID()}` });
      setCredential(result.credential);
      notify.success('新凭据已签发；旧凭据已立即撤销');
    } catch (error) { notify.error(error instanceof Error ? error.message : '凭据轮换失败'); } finally { setBusy(false); }
  }

  async function disconnect() {
    if (!window.confirm('断开后会立即撤销所有 Agent 凭据，未完成任务将不能继续回传。确认断开？')) return;
    setBusy(true);
    try {
      await api.post(`/api/enterprise/external-agents/${encodeURIComponent(connectionId)}/disconnect`, { reason: '企业负责人从连接管理页断开' });
      notify.success('外部 Agent 连接已断开');
      await load(true);
    } catch (error) { notify.error(error instanceof Error ? error.message : '连接断开失败'); } finally { setBusy(false); }
  }

  if (loading) return <main className="external-agent-ops-page"><div className="external-agent-loading"><LoaderCircle className="is-spinning" />正在加载连接运行数据…</div></main>;
  if (!operations) return <main className="external-agent-ops-page"><div className="external-agent-empty">连接不存在或当前账号无权访问。</div></main>;
  const connection = operations.connection;
  const callableAssets = manifest?.assets.filter((item) => item.selected && item.callable) || [];

  return <main className="external-agent-ops-page">
    <header><button type="button" onClick={() => navigate('/enterprise/agents')}><ArrowLeft />数字员工</button><div><div className="external-agent-ops-title"><h1>{String(manifest?.normalizedAgent.name || connection.externalAgentRef)}</h1><span>外接</span><em className={`is-${connection.healthStatus}`}>{healthLabel(connection.healthStatus)}</em></div><p>{connection.provider} · {connection.runtimeType} · {connection.transport} · 外部运行</p></div><div className="external-agent-ops-header-actions"><button type="button" onClick={() => void load()}><RefreshCw />刷新</button><Button onClick={() => setTaskFormOpen(true)} disabled={connection.status !== 'available' || callableAssets.length === 0}><Play />创建任务</Button></div></header>
    {operations.alerts.length > 0 && <section className="external-agent-ops-alerts">{operations.alerts.map((item) => <div className={`is-${item.level}`} key={item.code}><AlertTriangle /><span><strong>{alertTitle(item.code)}</strong><small>{item.message}</small></span></div>)}</section>}
    <nav>{(['overview', 'tasks', 'capabilities', 'security'] as const).map((item) => <button className={tab === item ? 'is-active' : ''} type="button" key={item} onClick={() => setTab(item)}>{({ overview: '运行概览', tasks: '任务与回执', capabilities: '已接能力', security: '安全与连接' } as const)[item]}</button>)}</nav>
    {tab === 'overview' && <Overview operations={operations} />}
    {tab === 'tasks' && <TasksPanel tasks={operations.recentTasks} selectedTask={selectedTask} onSelect={async (task) => { const detail = await api.get<Task>(`/api/enterprise/external-agent-tasks/${encodeURIComponent(task.id)}`); setSelectedTask(detail); }} onAction={async (task, action) => { setBusy(true); try { if (action === 'approve') await api.post(`/api/enterprise/external-agent-tasks/${task.id}/approval`, { decision: 'approved', comment: '连接管理页人工批准' }); if (action === 'retry') await api.post(`/api/enterprise/external-agent-tasks/${task.id}/retry`, { idempotency_key: `web-retry-${crypto.randomUUID()}` }); if (action === 'cancel') await api.post(`/api/enterprise/external-agent-tasks/${task.id}/cancel`, { reason: '连接管理页人工取消', idempotency_key: `web-cancel-${crypto.randomUUID()}` }); await load(true); notify.success('任务状态已更新'); } catch (error) { notify.error(error instanceof Error ? error.message : '任务操作失败'); } finally { setBusy(false); } }} busy={busy} />}
    {tab === 'capabilities' && <CapabilitiesPanel manifest={manifest} />}
    {tab === 'security' && <SecurityPanel connection={connection} policy={operations.policy} busy={busy} credential={credential} setCredential={setCredential} onRotate={rotateCredential} onDisconnect={disconnect} onSaved={() => load(true)} />}
    {taskFormOpen && <TaskCreateDialog connection={connection} assets={callableAssets} onClose={() => setTaskFormOpen(false)} onCreated={async () => { setTaskFormOpen(false); setTab('tasks'); await load(true); }} />}
  </main>;
}

function Overview({ operations }: { operations: Operations }) {
  const metrics = operations.taskMetrics;
  const health = operations.healthMetrics;
  return <div className="external-agent-ops-overview"><section className="external-agent-ops-stats"><article><span>连接状态</span><strong>{healthLabel(operations.connection.healthStatus)}</strong><small>{operations.connection.lastHeartbeatAt ? `最近心跳 ${formatTime(operations.connection.lastHeartbeatAt)}` : '尚无心跳'}</small></article><article><span>执行中</span><strong>{(metrics.leased || 0) + (metrics.running || 0)}</strong><small>Agent 报告 {String(health.reported_running_tasks || 0)} 个运行任务</small></article><article><span>已完成</span><strong>{metrics.succeeded || 0}</strong><small>失败/超时 {(metrics.failed || 0) + (metrics.expired || 0)}</small></article><article><span>API 请求</span><strong>{String(health.request_count_60m || 0)}</strong><small>限流 {String(health.limited_count_60m || 0)} 次</small></article></section><div className="external-agent-ops-columns"><section><h2>实时连接</h2><dl><Info label="连接 ID" value={operations.connection.id} /><Info label="协议版本" value={operations.connection.protocolVersion} /><Info label="Runtime" value={`${operations.connection.runtimeType} / ${operations.connection.provider}`} /><Info label="传输方式" value={operations.connection.transport} /><Info label="最后同步" value={formatTime(operations.connection.lastManifestSyncAt)} /><Info label="最近延迟" value={health.latest_latency_ms == null ? '—' : `${String(health.latest_latency_ms)} ms`} /></dl></section><section><h2>最近心跳</h2><div className="external-agent-heartbeat-list">{operations.recentHeartbeats.length ? operations.recentHeartbeats.slice(0, 8).map((item) => <div key={String(item.id)}><i className={`is-${String(item.status)}`} /><span><strong>{healthLabel(String(item.status))}</strong><small>{formatTime(String(item.created_at))} · 延迟 {item.latency_ms == null ? '—' : `${String(item.latency_ms)} ms`}</small></span><em>运行 {String(item.running_task_count)} / 队列 {String(item.queue_depth)}</em></div>) : <p>Agent 接入助手尚未上报心跳。</p>}</div></section></div></div>;
}

function TasksPanel({ tasks, selectedTask, onSelect, onAction, busy }: { tasks: Task[]; selectedTask: Task | null; onSelect: (task: Task) => void; onAction: (task: Task, action: 'approve' | 'retry' | 'cancel') => void; busy: boolean }) {
  return <div className="external-agent-task-layout"><section className="external-agent-task-list"><header><h2>外部执行任务</h2><span>{tasks.length} 条</span></header>{tasks.length ? tasks.map((task) => <button type="button" className={selectedTask?.id === task.id ? 'is-active' : ''} key={task.id} onClick={() => onSelect(task)}><i className={`is-${task.status}`} /><span><strong>{task.goal}</strong><small>{task.capabilityExternalId} · {formatTime(task.createdAt)}</small></span><em>{taskStatus(task.status)}</em></button>) : <div className="external-agent-empty">尚未向该员工派发任务。</div>}</section><section className="external-agent-task-detail">{selectedTask ? <><header><div><span>任务 {selectedTask.id}</span><h2>{selectedTask.goal}</h2></div><em className={`is-${selectedTask.status}`}>{taskStatus(selectedTask.status)}</em></header><div className="external-agent-task-actions">{selectedTask.approvalState === 'pending' && <button type="button" disabled={busy} onClick={() => onAction(selectedTask, 'approve')}><CheckCircle2 />批准执行</button>}{['failed', 'expired'].includes(selectedTask.status) && <button type="button" disabled={busy} onClick={() => onAction(selectedTask, 'retry')}><RotateCcw />重新排队</button>}{!['succeeded', 'failed', 'cancelled', 'expired'].includes(selectedTask.status) && <button type="button" disabled={busy} onClick={() => onAction(selectedTask, 'cancel')}><Ban />取消任务</button>}</div><dl><Info label="能力" value={selectedTask.capabilityExternalId} /><Info label="尝试次数" value={`${selectedTask.attemptCount} / ${selectedTask.maxAttempts}`} /><Info label="结果回执" value={selectedTask.resultReceiptId || '—'} /><Info label="超时时间" value={formatTime(selectedTask.timeoutAt)} /></dl><h3>执行时间线</h3><div className="external-agent-task-timeline">{selectedTask.events.map((event) => <div key={event.id}><i /><span><strong>{event.summary}</strong><small>{event.eventType} · {event.actorType} · {formatTime(event.createdAt)}</small></span></div>)}</div>{Object.keys(selectedTask.output).length > 0 && <><h3>结构化结果</h3><pre>{JSON.stringify(selectedTask.output, null, 2)}</pre></>}</> : <div className="external-agent-empty">选择左侧任务查看租约、回执和完整事件时间线。</div>}</section></div>;
}

function CapabilitiesPanel({ manifest }: { manifest: Manifest | null }) {
  if (!manifest) return <div className="external-agent-empty">尚未发现能力清单。</div>;
  return <section className="external-agent-ops-capabilities"><header><div><h2>已确认能力</h2><p>清单摘要 {manifest.sourceDigest.slice(0, 16)}… · {formatTime(manifest.submittedAt)}</p></div><span>{manifest.assets.filter((item) => item.selected).length} 项已启用</span></header><div>{manifest.assets.map((asset) => <article className={asset.selected ? '' : 'is-disabled'} key={asset.id}><span>{asset.kind.toUpperCase()}</span><div><strong>{asset.name}</strong><p>{asset.description || '无补充说明'}</p><footer><em>风险 {riskLabel(asset.riskLevel)}</em><em>{asset.callable ? '可调用' : '仅登记'}</em><em>{asset.portable ? '可导入' : '不可导出'}</em><em>{asset.verificationStatus}</em></footer></div><i>{asset.selected ? '已启用' : '未选择'}</i></article>)}</div></section>;
}

function SecurityPanel({ connection, policy, busy, credential, setCredential, onRotate, onDisconnect, onSaved }: { connection: Connection; policy: Policy; busy: boolean; credential: string; setCredential: (value: string) => void; onRotate: () => Promise<void>; onDisconnect: () => Promise<void>; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState(policy);
  const [saving, setSaving] = useState(false);
  async function save() { setSaving(true); try { await api.put(`/api/enterprise/external-agents/${encodeURIComponent(connection.id)}/network-policy`, { allowed_domains: form.allowedDomains, blocked_domains: form.blockedDomains, webhook_delivery_enabled: form.webhookDeliveryEnabled, max_requests_per_minute: form.maxRequestsPerMinute, max_concurrent_tasks: form.maxConcurrentTasks, heartbeat_interval_seconds: form.heartbeatIntervalSeconds }); notify.success('网络与运行策略已保存'); await onSaved(); } catch (error) { notify.error(error instanceof Error ? error.message : '策略保存失败'); } finally { setSaving(false); } }
  return <div className="external-agent-security-layout"><section><header><ShieldCheck /><div><h2>网络与运行策略</h2><p>所有云端任务投递均先校验 HTTPS、域名白名单及解析后的公网地址。</p></div></header><div className="external-agent-security-form"><label><span>允许域名（每行一个）</span><textarea rows={4} value={form.allowedDomains.join('\n')} onChange={(event) => setForm({ ...form, allowedDomains: lines(event.target.value) })} /></label><label><span>阻止域名（每行一个）</span><textarea rows={4} value={form.blockedDomains.join('\n')} onChange={(event) => setForm({ ...form, blockedDomains: lines(event.target.value) })} /></label><label><span>每分钟 API 上限</span><input type="number" min={10} max={10000} value={form.maxRequestsPerMinute} onChange={(event) => setForm({ ...form, maxRequestsPerMinute: Number(event.target.value) })} /></label><label><span>最大并发任务</span><input type="number" min={1} max={50} value={form.maxConcurrentTasks} onChange={(event) => setForm({ ...form, maxConcurrentTasks: Number(event.target.value) })} /></label><label><span>心跳间隔（秒）</span><input type="number" min={15} max={3600} value={form.heartbeatIntervalSeconds} onChange={(event) => setForm({ ...form, heartbeatIntervalSeconds: Number(event.target.value) })} /></label><label className="is-switch"><input type="checkbox" disabled={!['webhook', 'a2a'].includes(connection.transport)} checked={form.webhookDeliveryEnabled} onChange={(event) => setForm({ ...form, webhookDeliveryEnabled: event.target.checked })} /><span>允许平台主动向该端点投递任务</span></label></div><Button disabled={saving} onClick={() => void save()}>{saving ? <LoaderCircle className="is-spinning" /> : <ShieldCheck />}保存策略</Button></section><aside><h2>连接凭据</h2><p>凭据只在签发时展示一次。轮换后旧凭据立即失效，必须在外部 Agent 中同步替换。</p><button type="button" disabled={busy} onClick={() => void onRotate()}><KeyRound />轮换 Agent 凭据</button>{credential && <div className="external-agent-new-credential"><strong>新凭据（仅显示本次）</strong><code>{credential}</code><button type="button" onClick={() => { void navigator.clipboard.writeText(credential); notify.success('新凭据已复制'); }}><Clipboard />复制</button><button type="button" onClick={() => setCredential('')}>我已安全保存</button></div>}<hr /><h2>危险操作</h2><p>断开连接将撤销所有凭据，不删除历史任务、回执或审计记录。</p><button type="button" className="is-danger" disabled={busy || connection.status === 'disconnected'} onClick={() => void onDisconnect()}><Unplug />断开连接</button></aside></div>;
}

function TaskCreateDialog({ connection, assets, onClose, onCreated }: { connection: Connection; assets: Asset[]; onClose: () => void; onCreated: () => Promise<void> }) {
  const [assetId, setAssetId] = useState(assets[0]?.id || ''); const asset = useMemo(() => assets.find((item) => item.id === assetId), [assetId, assets]); const [goal, setGoal] = useState(''); const [input, setInput] = useState('{}'); const [requiresApproval, setRequiresApproval] = useState(false); const [busy, setBusy] = useState(false);
  async function create() { let parsed: Record<string, unknown>; try { parsed = JSON.parse(input) as Record<string, unknown>; } catch { notify.error('任务输入必须是有效 JSON 对象'); return; } setBusy(true); try { await api.post('/api/enterprise/external-agent-tasks', { connection_id: connection.id, capability_asset_id: assetId, goal, input: parsed, permission_grants: asset?.permissions || [], idempotency_key: `web-task-${crypto.randomUUID()}`, timeout_seconds: 1800, max_attempts: 3, requires_approval: requiresApproval }); notify.success('任务已创建并进入可靠队列'); await onCreated(); } catch (error) { notify.error(error instanceof Error ? error.message : '任务创建失败'); } finally { setBusy(false); } }
  return <div className="external-agent-dialog-backdrop" role="presentation" onMouseDown={onClose}><section role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><header><div><h2>创建外部执行任务</h2><p>任务由该 Agent 在原环境执行，平台只保存授权输入、事件和结果。</p></div><button type="button" onClick={onClose}>×</button></header><label><span>调用能力</span><select value={assetId} onChange={(event) => setAssetId(event.target.value)}>{assets.map((item) => <option value={item.id} key={item.id}>{item.name} · 风险 {riskLabel(item.riskLevel)}</option>)}</select></label><label><span>任务目标</span><textarea rows={4} value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="描述可验收的业务目标，不要粘贴密钥或口令" /></label><label><span>结构化输入（JSON）</span><textarea rows={7} className="is-code" value={input} onChange={(event) => setInput(event.target.value)} /></label><div className="external-agent-task-permissions"><strong>本次权限</strong>{asset?.permissions.length ? asset.permissions.map((item) => <span key={item}>{item}</span>) : <small>该能力未声明额外权限</small>}</div><label className="is-checkbox"><input type="checkbox" checked={requiresApproval || asset?.riskLevel === 'high'} disabled={asset?.riskLevel === 'high'} onChange={(event) => setRequiresApproval(event.target.checked)} />执行前需要人工批准{asset?.riskLevel === 'high' ? '（高风险能力强制）' : ''}</label><footer><button type="button" onClick={onClose}>取消</button><Button disabled={busy || !assetId || goal.trim().length < 2} onClick={() => void create()}>{busy ? <LoaderCircle className="is-spinning" /> : <Play />}创建任务</Button></footer></section></div>;
}

function Info({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function lines(value: string) { return value.split('\n').map((item) => item.trim()).filter(Boolean); }
function formatTime(value?: string) { return value ? new Date(value).toLocaleString() : '—'; }
function healthLabel(value: string) { return ({ online: '在线', degraded: '连接异常', offline: '离线', unknown: '待心跳', revoked: '已撤销' } as Record<string, string>)[value] || value; }
function taskStatus(value: string) { return ({ queued: '排队中', leased: '已领取', running: '执行中', waiting_approval: '待批准', waiting_input: '待补充', cancellation_requested: '取消中', succeeded: '已成功', failed: '失败', cancelled: '已取消', expired: '已超时' } as Record<string, string>)[value] || value; }
function riskLabel(value: string) { return ({ low: '低', medium: '中', high: '高' } as Record<string, string>)[value] || value; }
function alertTitle(value: string) { return ({ heartbeat_missing: '等待首次心跳', agent_offline: 'Agent 已离线', agent_degraded: '连接状态降级', task_failures: '存在异常任务', rate_limited: '请求触发限流', webhook_disabled: '云端投递已关闭' } as Record<string, string>)[value] || '运行提醒'; }
