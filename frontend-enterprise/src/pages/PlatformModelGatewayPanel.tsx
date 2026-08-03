import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { CheckCircle2, CloudDownload, Eye, EyeOff, LoaderCircle, Plus, RefreshCw, Route, Server, ShieldCheck } from 'lucide-react';

import { api, TENANT_ID } from '@/api/client';
import { notify } from '@/components/ui/app-toast';
import {
  Dialog,
  DialogContent,
  DialogTitle,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui';
import { Button } from '@/components/ui/button';
import type {
  AICapabilityStatusRead,
  AIInvocationAuditRead,
  AIModelCatalogRead,
  AIModelDeploymentRead,
  AIModelProductRead,
  AIModelRouteRead,
  AIProviderCatalogSyncResponse,
  AIProviderConnectionRead,
} from '@/types';

export const AI_CAPABILITIES_UPDATED_EVENT = 'kaigongba-ai-capabilities-updated';

type PanelTab = 'connections' | 'models' | 'products' | 'routes' | 'audits';

const EMPTY_CATALOG: AIModelCatalogRead = {
  provider_kinds: [],
  model_families: [],
  capabilities: [],
  protocols: [],
};

const capabilityFallbackLabels: Record<string, string> = {
  agent_chat: '数字员工与开小花对话',
  structured_generation: '结构化 JSON 生成',
  demand_analysis: 'AI 需求分析',
  matching: 'AI 服务匹配',
  quote_draft: 'AI 报价草案',
  evidence_summary: '争议证据摘要',
  knowledge_processing: '知识整理',
  skill_distillation: 'Skill 整理与生成',
};

export default function PlatformModelGatewayPanel({ tenantId = TENANT_ID }: { tenantId?: string }) {
  const [tab, setTab] = useState<PanelTab>('connections');
  const [catalog, setCatalog] = useState<AIModelCatalogRead>(EMPTY_CATALOG);
  const [status, setStatus] = useState<AICapabilityStatusRead | null>(null);
  const [connections, setConnections] = useState<AIProviderConnectionRead[]>([]);
  const [deployments, setDeployments] = useState<AIModelDeploymentRead[]>([]);
  const [products, setProducts] = useState<AIModelProductRead[]>([]);
  const [routes, setRoutes] = useState<AIModelRouteRead[]>([]);
  const [audits, setAudits] = useState<AIInvocationAuditRead[]>([]);
  const [loading, setLoading] = useState(false);
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [deploymentOpen, setDeploymentOpen] = useState(false);
  const [routeOpen, setRouteOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [verifyingId, setVerifyingId] = useState('');
  const [syncingId, setSyncingId] = useState('');
  const [publishingId, setPublishingId] = useState('');

  const [connectionForm, setConnectionForm] = useState({
    name: '',
    provider_kind: 'openai_compatible',
    api_protocol: 'openai_chat_completions',
    base_url: '',
    api_key: '',
  });
  const [deploymentForm, setDeploymentForm] = useState({
    connection_id: '',
    name: '',
    model: '',
    model_family: 'custom',
    temperature: '0.2',
    max_output_tokens: '8192',
    capabilities: ['agent_chat'],
  });
  const [routeForm, setRouteForm] = useState({
    capability: 'agent_chat',
    deployment_id: '',
    priority: '100',
    timeout_seconds: '90',
    retry_count: '1',
  });

  const capabilityLabel = useMemo(() => new Map(
    catalog.capabilities.map((item) => [item.id, item.label]),
  ), [catalog.capabilities]);

  async function load(showLoading = true) {
    if (showLoading) setLoading(true);
    try {
      const [catalogResult, statusResult, connectionRows, deploymentRows, productRows, routeRows, auditRows] = await Promise.all([
        api.get<AIModelCatalogRead>('/api/ai/catalog'),
        api.get<AICapabilityStatusRead>('/api/ai/capabilities/status'),
        api.get<AIProviderConnectionRead[]>('/api/ai/platform/connections'),
        api.get<AIModelDeploymentRead[]>('/api/ai/platform/deployments'),
        api.get<AIModelProductRead[]>('/api/ai/platform/products'),
        api.get<AIModelRouteRead[]>('/api/ai/platform/routes'),
        api.get<AIInvocationAuditRead[]>('/api/ai/platform/audits?limit=30'),
      ]);
      setCatalog(catalogResult);
      setStatus(statusResult);
      setConnections(connectionRows);
      setDeployments(deploymentRows);
      setProducts(productRows);
      setRoutes(routeRows);
      setAudits(auditRows);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '平台模型配置加载失败');
    } finally {
      if (showLoading) setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function createConnection() {
    if (!connectionForm.name.trim() || !connectionForm.api_key.trim()) {
      notify.warning('请填写聚合平台名称和 API Key');
      return;
    }
    setSaving(true);
    try {
      await api.post('/api/ai/platform/connections', {
        ...connectionForm,
        base_url: connectionForm.base_url.trim() || null,
      });
      setConnectionOpen(false);
      setConnectionForm({
        name: '',
        provider_kind: 'openai_compatible',
        api_protocol: 'openai_chat_completions',
        base_url: '',
        api_key: '',
      });
      notify.success('聚合平台连接已保存，请继续添加并验证模型');
      await load(false);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  async function createDeployment() {
    if (!deploymentForm.connection_id || !deploymentForm.name.trim() || !deploymentForm.model.trim()) {
      notify.warning('请选择聚合平台并填写模型名称和 Model ID');
      return;
    }
    setSaving(true);
    try {
      await api.post('/api/ai/platform/deployments', {
        ...deploymentForm,
        temperature: Number(deploymentForm.temperature),
        max_output_tokens: Number(deploymentForm.max_output_tokens),
        protocol_options: {},
        pricing: {},
      });
      setDeploymentOpen(false);
      setDeploymentForm({
        connection_id: '',
        name: '',
        model: '',
        model_family: 'custom',
        temperature: '0.2',
        max_output_tokens: '8192',
        capabilities: ['agent_chat'],
      });
      notify.success('平台模型已添加，验证通过后才能进入能力路由');
      await load(false);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  async function verifyDeployment(row: AIModelDeploymentRead) {
    if (verifyingId) return;
    setVerifyingId(row.id);
    try {
      const result = await api.post<{ success: boolean; message: string }>(
        `/api/ai/platform/deployments/${row.id}/verify?activate=true`,
      );
      if (!result.success) {
        notify.error(`验证失败：${result.message}`);
      } else {
        notify.success('文本和结构化 JSON 验证通过，模型已启用');
      }
      await load(false);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '模型验证失败');
    } finally {
      setVerifyingId('');
    }
  }

  async function syncCatalog(row: AIProviderConnectionRead) {
    if (syncingId) return;
    setSyncingId(row.id);
    try {
      const result = await api.post<AIProviderCatalogSyncResponse>(
        `/api/ai/platform/connections/${row.id}/catalog/sync`,
        { create_product_drafts: true },
      );
      notify.success(
        `同步完成：发现 ${result.discovered_count} 个模型，新增 ${result.created_count} 个，生成 ${result.product_draft_count} 个产品草稿`,
      );
      await load(false);
      if (result.product_draft_count > 0) setTab('models');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '模型目录同步失败');
    } finally {
      setSyncingId('');
    }
  }

  async function setProductPublished(
    row: AIModelProductRead,
    publish: boolean,
    mode: 'allowlist' | 'all' = 'all',
  ) {
    if (publishingId) return;
    setPublishingId(row.id);
    try {
      await api.put(`/api/ai/platform/products/${row.id}`, {
        enabled: publish,
        visible_to_users: publish,
        visibility_mode: publish ? mode : row.visibility_mode,
      });
      if (publish && mode === 'allowlist') {
        await api.post(
          `/api/ai/platform/products/${row.id}/access?target_type=tenant&target_id=${encodeURIComponent(tenantId)}&enabled=true`,
        );
      }
      notify.success(
        publish
          ? mode === 'allowlist'
            ? '模型产品已向当前租户灰度发布'
            : '模型产品已向全部用户发布'
          : '模型产品已从用户模型下拉隐藏',
      );
      await load(false);
      window.dispatchEvent(new Event(AI_CAPABILITIES_UPDATED_EVENT));
    } catch (error) {
      notify.error(error instanceof Error ? error.message : publish ? '发布失败，请先验证至少一个模型部署' : '下架失败');
    } finally {
      setPublishingId('');
    }
  }

  async function saveRoute() {
    if (!routeForm.capability || !routeForm.deployment_id) {
      notify.warning('请选择能力和已验证模型');
      return;
    }
    setSaving(true);
    try {
      await api.post('/api/ai/platform/routes', {
        capability: routeForm.capability,
        deployment_id: routeForm.deployment_id,
        priority: Number(routeForm.priority),
        timeout_seconds: Number(routeForm.timeout_seconds),
        retry_count: Number(routeForm.retry_count),
        enabled: true,
      });
      setRouteOpen(false);
      notify.success('能力路由已保存');
      await load(false);
      window.dispatchEvent(new Event(AI_CAPABILITIES_UPDATED_EVENT));
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '路由保存失败');
    } finally {
      setSaving(false);
    }
  }

  const enabledDeployments = deployments.filter(
    (item) => item.enabled && item.health_status === 'healthy',
  );
  const availableCapabilityCount = status?.capabilities.filter((item) => item.available).length || 0;

  return (
    <section className="mb-[20px] overflow-hidden rounded-[20px] border border-[#eceef1] bg-white shadow-[0_8px_28px_rgba(18,35,67,0.06)]">
      <div className="flex flex-wrap items-center justify-between gap-[16px] border-b border-[#eceef1] px-[22px] py-[18px]">
        <div className="flex min-w-0 items-center gap-[12px]">
          <span className="grid size-[38px] shrink-0 place-items-center rounded-[12px] bg-[#eef4ff] text-[#1a71ff]">
            <ShieldCheck className="size-[20px]" />
          </span>
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold text-[#18181a]">平台默认 AI 服务</h2>
            <p className="mt-[3px] text-[12px] text-[#858b9c]">
              多聚合平台、多模型和主备路由；平台密钥不会下发到企业或浏览器。
            </p>
          </div>
        </div>
        <div className="flex items-center gap-[10px]">
          <span className={`rounded-full px-[10px] py-[5px] text-[11px] ${
            status?.platform_available
              ? 'bg-[#eaf8f0] text-[#168a50]'
              : 'bg-[#fff4e8] text-[#b96a13]'
          }`}>
            {status?.platform_available ? `已提供 ${availableCapabilityCount} 项能力` : '尚未配置可用路由'}
          </span>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`size-[14px] ${loading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
        </div>
      </div>

      <div className="flex gap-[4px] overflow-x-auto border-b border-[#eceef1] px-[18px] pt-[10px]">
        {([
          ['connections', `聚合平台 ${connections.length}`],
          ['models', `平台模型 ${deployments.length}`],
          ['products', `模型产品 ${products.length}`],
          ['routes', `能力路由 ${routes.length}`],
          ['audits', `调用审计 ${audits.length}`],
        ] as Array<[PanelTab, string]>).map(([value, label]) => (
          <button
            type="button"
            key={value}
            onClick={() => setTab(value)}
            className={`whitespace-nowrap border-b-2 px-[14px] py-[9px] text-[12px] ${
              tab === value
                ? 'border-[#18181a] font-medium text-[#18181a]'
                : 'border-transparent text-[#858b9c] hover:text-[#464c5e]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="p-[18px]">
        {tab === 'connections' && (
          <PanelSection
            title="聚合平台连接"
            description="一个连接保存一次服务端密钥，可以挂载多个不同厂商模型。"
            actionLabel="添加聚合平台"
            onAction={() => setConnectionOpen(true)}
          >
            <div className="grid gap-[10px] lg:grid-cols-2">
              {connections.map((row) => (
                <article key={row.id} className="rounded-[12px] border border-[#e7eaf0] p-[14px]">
                  <div className="flex items-start justify-between gap-[12px]">
                    <div className="flex min-w-0 items-center gap-[10px]">
                      <Server className="size-[16px] shrink-0 text-[#1a71ff]" />
                      <div className="min-w-0">
                        <strong className="block truncate text-[13px] text-[#18181a]">{row.name}</strong>
                        <span className="mt-[2px] block truncate text-[11px] text-[#858b9c]">
                          {catalog.provider_kinds.find((item) => item.id === row.provider_kind)?.label || row.provider_kind}
                        </span>
                      </div>
                    </div>
                    <StateBadge ok={row.enabled && row.trust_status === 'verified'} />
                  </div>
                  <dl className="mt-[12px] grid grid-cols-2 gap-x-[12px] gap-y-[7px] text-[11px]">
                    <Info label="模型数" value={String(row.model_count)} />
                    <Info label="API Key" value={row.api_key_masked || '—'} mono />
                    <Info label="协议" value={row.api_protocol} />
                    <Info label="Base URL" value={row.base_url || '默认地址'} />
                  </dl>
                  <div className="mt-[12px] flex justify-end border-t border-[#eef0f4] pt-[10px]">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={Boolean(syncingId)}
                      onClick={() => void syncCatalog(row)}
                    >
                      {syncingId === row.id ? <LoaderCircle className="size-[13px] animate-spin" /> : <CloudDownload className="size-[13px]" />}
                      同步模型目录
                    </Button>
                  </div>
                </article>
              ))}
              {!connections.length && <Empty text="还没有聚合平台连接" />}
            </div>
          </PanelSection>
        )}

        {tab === 'products' && (
          <PanelSection
            title="用户可选模型产品"
            description="聚合平台返回的是部署目录；验证部署后，再将逻辑模型产品发布到对话框和数字员工配置中。"
          >
            <div className="overflow-x-auto rounded-[12px] border border-[#e7eaf0]">
              <table className="w-full min-w-[820px] text-left text-[12px]">
                <thead className="bg-[#f8f9fb] text-[#757f9c]">
                  <tr><Th>产品名称</Th><Th>模型族 / 分类</Th><Th>标签</Th><Th>可用部署</Th><Th>用户可见</Th><Th>操作</Th></tr>
                </thead>
                <tbody>
                  {products.map((row) => {
                    const published = row.enabled && row.visible_to_users;
                    return (
                      <tr key={row.id} className="border-t border-[#eceef1]">
                        <Td><strong className="block text-[#18181a]">{row.display_name}</strong><small className="font-mono text-[#858b9c]">{row.slug}</small></Td>
                        <Td>{row.model_family} · {row.category}</Td>
                        <Td>{row.feature_tags.length ? row.feature_tags.join('、') : '—'}</Td>
                        <Td><span className={row.available ? 'text-[#168a50]' : 'text-[#b96a13]'}>{row.available_deployment_count} / {row.backing_deployment_count}</span></Td>
                        <Td>
                          {published && row.visibility_mode === 'allowlist'
                            ? <span className="shrink-0 rounded-full bg-[#eef4ff] px-[9px] py-[4px] text-[11px] text-[#1a71ff]">灰度可见</span>
                            : <StateBadge ok={published && row.available} pending={!published} />}
                        </Td>
                        <Td>
                          <div className="flex gap-[6px]">
                            {published ? (
                              <Button
                                variant="outline"
                                size="sm"
                                disabled={Boolean(publishingId)}
                                onClick={() => void setProductPublished(row, false)}
                              >
                                {publishingId === row.id ? <LoaderCircle className="size-[13px] animate-spin" /> : <EyeOff className="size-[13px]" />}
                                下架
                              </Button>
                            ) : (
                              <>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  disabled={Boolean(publishingId) || !row.available}
                                  onClick={() => void setProductPublished(row, true, 'allowlist')}
                                >
                                  {publishingId === row.id ? <LoaderCircle className="size-[13px] animate-spin" /> : <Eye className="size-[13px]" />}
                                  灰度发布
                                </Button>
                                <Button
                                  variant="outline"
                                  size="sm"
                                  disabled={Boolean(publishingId) || !row.available}
                                  onClick={() => void setProductPublished(row, true, 'all')}
                                >
                                  全量发布
                                </Button>
                              </>
                            )}
                          </div>
                        </Td>
                      </tr>
                    );
                  })}
                  {!products.length && <tr><td colSpan={6}><Empty text="同步聚合平台目录后，将自动生成模型产品草稿" /></td></tr>}
                </tbody>
              </table>
            </div>
          </PanelSection>
        )}

        {tab === 'models' && (
          <PanelSection
            title="平台模型"
            description="同一聚合平台可添加豆包、DeepSeek、GLM、Kimi 等多个 Model ID。"
            actionLabel="添加平台模型"
            actionDisabled={!connections.length}
            onAction={() => setDeploymentOpen(true)}
          >
            <div className="overflow-x-auto rounded-[12px] border border-[#e7eaf0]">
              <table className="w-full min-w-[780px] text-left text-[12px]">
                <thead className="bg-[#f8f9fb] text-[#757f9c]">
                  <tr><Th>名称 / Model ID</Th><Th>模型族</Th><Th>聚合平台</Th><Th>能力</Th><Th>状态</Th><Th>操作</Th></tr>
                </thead>
                <tbody>
                  {deployments.map((row) => (
                    <tr key={row.id} className="border-t border-[#eceef1]">
                      <Td><strong className="block text-[#18181a]">{row.name}</strong><small className="font-mono text-[#858b9c]">{row.model}</small></Td>
                      <Td>{catalog.model_families.find((item) => item.id === row.model_family)?.label || row.model_family}</Td>
                      <Td>{row.connection_name}</Td>
                      <Td>{row.capabilities.map((item) => capabilityLabel.get(item) || item).join('、')}</Td>
                      <Td><StateBadge ok={row.enabled && row.health_status === 'healthy'} pending={row.health_status === 'unknown'} /></Td>
                      <Td>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={Boolean(verifyingId)}
                          onClick={() => void verifyDeployment(row)}
                        >
                          {verifyingId === row.id ? <LoaderCircle className="size-[13px] animate-spin" /> : <CheckCircle2 className="size-[13px]" />}
                          验证
                        </Button>
                      </Td>
                    </tr>
                  ))}
                  {!deployments.length && <tr><td colSpan={6}><Empty text="还没有平台模型" /></td></tr>}
                </tbody>
              </table>
            </div>
          </PanelSection>
        )}

        {tab === 'routes' && (
          <PanelSection
            title="能力路由"
            description="数字越小优先级越高；同一能力配置多个模型时会按顺序重试和切换。"
            actionLabel="配置能力路由"
            actionDisabled={!enabledDeployments.length}
            onAction={() => setRouteOpen(true)}
          >
            <div className="grid gap-[10px] lg:grid-cols-2">
              {catalog.capabilities.map((capability) => {
                const items = routes.filter((route) => route.capability === capability.id);
                return (
                  <article key={capability.id} className="rounded-[12px] border border-[#e7eaf0] p-[14px]">
                    <div className="flex items-center justify-between gap-[12px]">
                      <div><strong className="text-[13px] text-[#18181a]">{capability.label}</strong><small className="ml-[8px] text-[#a0a6b5]">{capability.id}</small></div>
                      <span className="text-[11px] text-[#858b9c]">{items.length ? `${items.length} 条路由` : '未配置'}</span>
                    </div>
                    <div className="mt-[10px] space-y-[7px]">
                      {items.map((route) => (
                        <div key={route.id} className="flex items-center gap-[9px] rounded-[9px] bg-[#f8f9fb] px-[10px] py-[8px]">
                          <Route className="size-[13px] shrink-0 text-[#1a71ff]" />
                          <span className="min-w-0 flex-1 truncate text-[11px] text-[#464c5e]">P{route.priority} · {route.deployment_name} · {route.connection_name}</span>
                          <StateBadge ok={route.enabled && route.available} compact />
                        </div>
                      ))}
                      {!items.length && <p className="py-[8px] text-[11px] text-[#a0a6b5]">平台暂不为此能力提供默认模型。</p>}
                    </div>
                  </article>
                );
              })}
            </div>
          </PanelSection>
        )}

        {tab === 'audits' && (
          <PanelSection title="调用审计" description="只记录调用关系、哈希、耗时和错误码，不保存用户提示词原文。">
            <div className="overflow-x-auto rounded-[12px] border border-[#e7eaf0]">
              <table className="w-full min-w-[760px] text-left text-[12px]">
                <thead className="bg-[#f8f9fb] text-[#757f9c]"><tr><Th>时间</Th><Th>能力</Th><Th>操作</Th><Th>来源</Th><Th>状态</Th><Th>尝试</Th><Th>耗时</Th></tr></thead>
                <tbody>
                  {audits.map((row) => (
                    <tr key={row.id} className="border-t border-[#eceef1]">
                      <Td>{new Date(row.created_at).toLocaleString('zh-CN')}</Td>
                      <Td>{capabilityLabel.get(row.capability) || capabilityFallbackLabels[row.capability] || row.capability}</Td>
                      <Td>{row.operation}</Td><Td>{row.source_scope}</Td>
                      <Td><StateBadge ok={row.status === 'succeeded'} pending={row.status === 'started'} /></Td>
                      <Td>{row.attempt_count}</Td><Td>{row.latency_ms == null ? '—' : `${row.latency_ms} ms`}</Td>
                    </tr>
                  ))}
                  {!audits.length && <tr><td colSpan={7}><Empty text="尚无平台 AI 调用记录" /></td></tr>}
                </tbody>
              </table>
            </div>
          </PanelSection>
        )}
      </div>

      <Dialog open={connectionOpen} onOpenChange={setConnectionOpen}>
        <DialogContent className="sm:max-w-[620px]">
          <DialogTitle>添加聚合平台</DialogTitle>
          <div className="grid gap-[14px] sm:grid-cols-2">
            <Field label="连接名称"><Input value={connectionForm.name} onChange={(event) => setConnectionForm((form) => ({ ...form, name: event.target.value }))} placeholder="例如 聚合平台 A" /></Field>
            <Field label="平台类型"><Select value={connectionForm.provider_kind} onValueChange={(value) => setConnectionForm((form) => ({ ...form, provider_kind: value }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{catalog.provider_kinds.map((item) => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="API 协议"><Select value={connectionForm.api_protocol} onValueChange={(value) => setConnectionForm((form) => ({ ...form, api_protocol: value }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{catalog.protocols.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="Base URL"><Input value={connectionForm.base_url} onChange={(event) => setConnectionForm((form) => ({ ...form, base_url: event.target.value }))} placeholder="https://api.example.com/v1" /></Field>
            <div className="sm:col-span-2"><Field label="API Key（仅服务端加密保存）"><Input type="password" value={connectionForm.api_key} onChange={(event) => setConnectionForm((form) => ({ ...form, api_key: event.target.value }))} placeholder="sk-..." /></Field></div>
          </div>
          <DialogActions saving={saving} onCancel={() => setConnectionOpen(false)} onSave={() => void createConnection()} />
        </DialogContent>
      </Dialog>

      <Dialog open={deploymentOpen} onOpenChange={setDeploymentOpen}>
        <DialogContent className="sm:max-w-[680px]">
          <DialogTitle>添加平台模型</DialogTitle>
          <div className="grid gap-[14px] sm:grid-cols-2">
            <Field label="聚合平台"><Select value={deploymentForm.connection_id} onValueChange={(value) => setDeploymentForm((form) => ({ ...form, connection_id: value }))}><SelectTrigger><SelectValue placeholder="选择连接" /></SelectTrigger><SelectContent>{connections.map((item) => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="模型族"><Select value={deploymentForm.model_family} onValueChange={(value) => setDeploymentForm((form) => ({ ...form, model_family: value }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{catalog.model_families.map((item) => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="显示名称"><Input value={deploymentForm.name} onChange={(event) => setDeploymentForm((form) => ({ ...form, name: event.target.value }))} placeholder="例如 DeepSeek V3.1" /></Field>
            <Field label="Model ID"><Input value={deploymentForm.model} onChange={(event) => setDeploymentForm((form) => ({ ...form, model: event.target.value }))} placeholder="以聚合平台文档为准" /></Field>
            <Field label="Temperature"><Input type="number" value={deploymentForm.temperature} onChange={(event) => setDeploymentForm((form) => ({ ...form, temperature: event.target.value }))} /></Field>
            <Field label="Max Tokens"><Input type="number" value={deploymentForm.max_output_tokens} onChange={(event) => setDeploymentForm((form) => ({ ...form, max_output_tokens: event.target.value }))} /></Field>
            <div className="sm:col-span-2">
              <span className="mb-[7px] block text-[12px] font-medium text-[#464c5e]">支持能力</span>
              <div className="grid gap-[8px] sm:grid-cols-2">
                {catalog.capabilities.map((item) => (
                  <label key={item.id} className="flex cursor-pointer items-center gap-[8px] rounded-[9px] border border-[#e7eaf0] px-[10px] py-[8px] text-[12px] text-[#464c5e]">
                    <input type="checkbox" checked={deploymentForm.capabilities.includes(item.id)} onChange={(event) => setDeploymentForm((form) => ({ ...form, capabilities: event.target.checked ? [...form.capabilities, item.id] : form.capabilities.filter((value) => value !== item.id) }))} />
                    {item.label}
                  </label>
                ))}
              </div>
            </div>
          </div>
          <DialogActions saving={saving} onCancel={() => setDeploymentOpen(false)} onSave={() => void createDeployment()} />
        </DialogContent>
      </Dialog>

      <Dialog open={routeOpen} onOpenChange={setRouteOpen}>
        <DialogContent className="sm:max-w-[620px]">
          <DialogTitle>配置能力路由</DialogTitle>
          <div className="grid gap-[14px] sm:grid-cols-2">
            <Field label="能力"><Select value={routeForm.capability} onValueChange={(value) => setRouteForm((form) => ({ ...form, capability: value }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{catalog.capabilities.map((item) => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="已验证模型"><Select value={routeForm.deployment_id} onValueChange={(value) => setRouteForm((form) => ({ ...form, deployment_id: value }))}><SelectTrigger><SelectValue placeholder="选择模型" /></SelectTrigger><SelectContent>{enabledDeployments.map((item) => <SelectItem key={item.id} value={item.id}>{item.name} · {item.connection_name}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="优先级（越小越优先）"><Input type="number" value={routeForm.priority} onChange={(event) => setRouteForm((form) => ({ ...form, priority: event.target.value }))} /></Field>
            <Field label="超时秒数"><Input type="number" value={routeForm.timeout_seconds} onChange={(event) => setRouteForm((form) => ({ ...form, timeout_seconds: event.target.value }))} /></Field>
            <Field label="瞬时错误重试次数"><Input type="number" min={0} max={3} value={routeForm.retry_count} onChange={(event) => setRouteForm((form) => ({ ...form, retry_count: event.target.value }))} /></Field>
          </div>
          <DialogActions saving={saving} onCancel={() => setRouteOpen(false)} onSave={() => void saveRoute()} />
        </DialogContent>
      </Dialog>
    </section>
  );
}

function PanelSection({ title, description, actionLabel, actionDisabled, onAction, children }: { title: string; description: string; actionLabel?: string; actionDisabled?: boolean; onAction?: () => void; children: ReactNode }) {
  return <div><div className="mb-[14px] flex flex-wrap items-start justify-between gap-[12px]"><div><h3 className="text-[13px] font-semibold text-[#18181a]">{title}</h3><p className="mt-[3px] text-[11px] text-[#858b9c]">{description}</p></div>{actionLabel && <Button size="sm" disabled={actionDisabled} onClick={onAction}><Plus className="size-[14px]" />{actionLabel}</Button>}</div>{children}</div>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="flex flex-col gap-[6px]"><span className="text-[12px] font-medium text-[#464c5e]">{label}</span>{children}</label>;
}

function DialogActions({ saving, onCancel, onSave }: { saving: boolean; onCancel: () => void; onSave: () => void }) {
  return <div className="mt-[8px] flex justify-end gap-[8px]"><Button variant="outline" disabled={saving} onClick={onCancel}>取消</Button><Button disabled={saving} onClick={onSave}>{saving && <LoaderCircle className="size-[14px] animate-spin" />}保存</Button></div>;
}

function StateBadge({ ok, pending = false, compact = false }: { ok: boolean; pending?: boolean; compact?: boolean }) {
  const label = ok ? '可用' : pending ? '待验证' : '不可用';
  return <span className={`shrink-0 rounded-full ${compact ? 'px-[7px] py-[2px] text-[10px]' : 'px-[9px] py-[4px] text-[11px]'} ${ok ? 'bg-[#eaf8f0] text-[#168a50]' : pending ? 'bg-[#fff4e8] text-[#b96a13]' : 'bg-[#f1f2f5] text-[#858b9c]'}`}>{label}</span>;
}

function Info({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="min-w-0"><dt className="text-[#a0a6b5]">{label}</dt><dd className={`mt-[2px] truncate text-[#464c5e] ${mono ? 'font-mono' : ''}`}>{value}</dd></div>;
}

function Empty({ text }: { text: string }) {
  return <div className="col-span-full py-[28px] text-center text-[12px] text-[#a0a6b5]">{text}</div>;
}

function Th({ children }: { children: ReactNode }) { return <th className="px-[12px] py-[10px] font-medium">{children}</th>; }
function Td({ children }: { children: ReactNode }) { return <td className="px-[12px] py-[11px] text-[#464c5e]">{children}</td>; }
