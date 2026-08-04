import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  CloudDownload,
  Diamond,
  Eye,
  EyeOff,
  LoaderCircle,
  Plus,
  RefreshCw,
  Route,
  Server,
  ShieldCheck,
} from 'lucide-react';

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
  AIModelCapabilityCheckRead,
  AIModelCertificationResponse,
  AIModelDeploymentRead,
  AIModelProductRead,
  AIModelRouteRead,
  AIPriceVersionRead,
  AIProviderCatalogSyncResponse,
  AIProviderConnectionRead,
  AIUsageSummaryRead,
} from '@/types';

export const AI_CAPABILITIES_UPDATED_EVENT = 'kaigongba-ai-capabilities-updated';

type PanelTab = 'connections' | 'models' | 'products' | 'routes' | 'costs' | 'audits';

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

const EMPTY_USAGE: AIUsageSummaryRead = {
  quota: {
    granted_credits: '0',
    reserved_credits: '0',
    consumed_credits: '0',
    available_credits: '0',
    percent_used: 0,
    hard_limit: false,
    warning_threshold_percent: 80,
  },
  totals: {
    request_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    platform_cost: '0',
    billable_credits: '0',
    byok_tokens: 0,
  },
  trend: [],
  by_agent: [],
};

const BASE_CAPABILITIES = new Set(['agent_chat', 'structured_generation']);

export default function PlatformModelGatewayPanel({ tenantId = TENANT_ID }: { tenantId?: string }) {
  const [tab, setTab] = useState<PanelTab>('connections');
  const [catalog, setCatalog] = useState<AIModelCatalogRead>(EMPTY_CATALOG);
  const [status, setStatus] = useState<AICapabilityStatusRead | null>(null);
  const [connections, setConnections] = useState<AIProviderConnectionRead[]>([]);
  const [deployments, setDeployments] = useState<AIModelDeploymentRead[]>([]);
  const [products, setProducts] = useState<AIModelProductRead[]>([]);
  const [routes, setRoutes] = useState<AIModelRouteRead[]>([]);
  const [audits, setAudits] = useState<AIInvocationAuditRead[]>([]);
  const [prices, setPrices] = useState<AIPriceVersionRead[]>([]);
  const [usage, setUsage] = useState<AIUsageSummaryRead>(EMPTY_USAGE);
  const [loading, setLoading] = useState(false);
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [deploymentOpen, setDeploymentOpen] = useState(false);
  const [routeOpen, setRouteOpen] = useState(false);
  const [certificationOpen, setCertificationOpen] = useState(false);
  const [priceOpen, setPriceOpen] = useState(false);
  const [quotaOpen, setQuotaOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [verifyingId, setVerifyingId] = useState('');
  const [syncingId, setSyncingId] = useState('');
  const [publishingId, setPublishingId] = useState('');
  const [certifying, setCertifying] = useState(false);
  const [certificationDeployment, setCertificationDeployment] = useState<AIModelDeploymentRead | null>(null);
  const [capabilityChecks, setCapabilityChecks] = useState<AIModelCapabilityCheckRead[]>([]);
  const [selectedCapabilities, setSelectedCapabilities] = useState<string[]>([]);

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
  const [priceForm, setPriceForm] = useState({
    deployment_id: '',
    currency: 'CNY',
    input_per_million: '',
    output_per_million: '',
    cached_input_per_million: '0',
    reasoning_per_million: '0',
    credits_per_currency_unit: '1',
  });
  const [quotaForm, setQuotaForm] = useState({
    credits: '2500',
    hard_limit: true,
    warning_threshold_percent: '80',
  });

  const capabilityLabel = useMemo(() => new Map(
    catalog.capabilities.map((item) => [item.id, item.label]),
  ), [catalog.capabilities]);

  async function load(showLoading = true) {
    if (showLoading) setLoading(true);
    try {
      const [catalogResult, statusResult, connectionRows, deploymentRows, productRows, routeRows, auditRows, priceRows, usageResult] = await Promise.all([
        api.get<AIModelCatalogRead>('/api/ai/catalog'),
        api.get<AICapabilityStatusRead>('/api/ai/capabilities/status'),
        api.get<AIProviderConnectionRead[]>('/api/ai/platform/connections'),
        api.get<AIModelDeploymentRead[]>('/api/ai/platform/deployments'),
        api.get<AIModelProductRead[]>('/api/ai/platform/products'),
        api.get<AIModelRouteRead[]>('/api/ai/platform/routes'),
        api.get<AIInvocationAuditRead[]>('/api/ai/platform/audits?limit=30'),
        api.get<AIPriceVersionRead[]>('/api/ai/platform/prices'),
        api.get<AIUsageSummaryRead>('/api/ai/usage/summary?days=30&scope=tenant'),
      ]);
      setCatalog(catalogResult);
      setStatus(statusResult);
      setConnections(connectionRows);
      setDeployments(deploymentRows);
      setProducts(productRows);
      setRoutes(routeRows);
      setAudits(auditRows);
      setPrices(priceRows);
      setUsage(usageResult?.quota ? usageResult : EMPTY_USAGE);
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

  async function openCertification(row: AIModelDeploymentRead) {
    setCertificationDeployment(row);
    setSelectedCapabilities([]);
    setCapabilityChecks([]);
    setCertificationOpen(true);
    try {
      const checks = await api.get<AIModelCapabilityCheckRead[]>(
        `/api/ai/platform/capability-checks?deployment_id=${encodeURIComponent(row.id)}&limit=100`,
      );
      setCapabilityChecks(checks);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '认证历史加载失败');
    }
  }

  async function certifyCapabilities() {
    if (!certificationDeployment || !selectedCapabilities.length) {
      notify.warning('请至少选择一项业务能力');
      return;
    }
    setCertifying(true);
    try {
      const result = await api.post<AIModelCertificationResponse>(
        `/api/ai/platform/deployments/${certificationDeployment.id}/certify`,
        { capabilities: selectedCapabilities, activate: true },
      );
      setCapabilityChecks((current) => [...result.checks, ...current]);
      setCertificationDeployment(result.deployment);
      setSelectedCapabilities([]);
      if (result.failed_capabilities.length) {
        notify.warning(`认证完成：${result.certified_capabilities.length} 项通过，${result.failed_capabilities.length} 项未通过`);
      } else {
        notify.success(`${result.certified_capabilities.length} 项能力认证通过`);
      }
      await load(false);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '能力认证失败');
    } finally {
      setCertifying(false);
    }
  }

  function openPriceEditor(deploymentId: string) {
    const current = prices.find((item) => item.deployment_id === deploymentId);
    setPriceForm({
      deployment_id: deploymentId,
      currency: current?.currency || 'CNY',
      input_per_million: current?.input_per_million || '',
      output_per_million: current?.output_per_million || '',
      cached_input_per_million: current?.cached_input_per_million || '0',
      reasoning_per_million: current?.reasoning_per_million || '0',
      credits_per_currency_unit: current?.credits_per_currency_unit || '1',
    });
    setPriceOpen(true);
  }

  async function savePriceVersion() {
    if (!priceForm.deployment_id || priceForm.input_per_million === '' || priceForm.output_per_million === '') {
      notify.warning('请选择模型并填写输入、输出价格');
      return;
    }
    setSaving(true);
    try {
      await api.post('/api/ai/platform/prices', {
        ...priceForm,
        source: 'operator',
      });
      setPriceOpen(false);
      notify.success('新价格版本已生效，旧版本仍保留');
      await load(false);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '价格版本保存失败');
    } finally {
      setSaving(false);
    }
  }

  async function grantTestQuota() {
    if (!(Number(quotaForm.credits) > 0)) {
      notify.warning('测试额度必须大于 0');
      return;
    }
    setSaving(true);
    try {
      await api.post('/api/ai/platform/quotas/grant', {
        tenant_id: tenantId,
        credits: quotaForm.credits,
        hard_limit: quotaForm.hard_limit,
        warning_threshold_percent: Number(quotaForm.warning_threshold_percent),
        idempotency_key: `web-quota-${crypto.randomUUID()}`,
      });
      setQuotaOpen(false);
      notify.success('测试额度已发放到当前租户');
      await load(false);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '测试额度发放失败');
    } finally {
      setSaving(false);
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
  const latestPriceByDeployment = useMemo(() => {
    const result = new Map<string, AIPriceVersionRead>();
    prices.forEach((price) => {
      if (!result.has(price.deployment_id)) result.set(price.deployment_id, price);
    });
    return result;
  }, [prices]);
  const quotaPercent = Math.max(0, Math.min(100, usage.quota.percent_used));

  return (
    <section className="mb-[20px] overflow-hidden rounded-[20px] border border-[#eceef1] bg-white shadow-[0_8px_28px_rgba(18,35,67,0.06)]">
      <div className="flex flex-wrap items-center justify-between gap-[16px] border-b border-[#eceef1] px-[22px] py-[18px]">
        <div className="flex min-w-0 items-center gap-[12px]">
          <span className="grid size-[38px] shrink-0 place-items-center rounded-[12px] bg-[#eef4ff] text-[#1a71ff]">
            <Diamond className="size-[18px]" />
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
          ['costs', '成本与额度'],
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
            description="全量保留聊天、图像、视频、音频、Embedding 与 Rerank 产品草稿；只有通过 agent_chat 认证的产品进入聊天下拉。"
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
                          {!row.capabilities.includes('agent_chat')
                            ? <span className="shrink-0 rounded-full bg-[#f1f2f5] px-[9px] py-[4px] text-[11px] text-[#757f9c]">专用产品草稿</span>
                            : published && row.visibility_mode === 'allowlist'
                            ? <span className="shrink-0 rounded-full bg-[#eef4ff] px-[9px] py-[4px] text-[11px] text-[#1a71ff]">灰度可见</span>
                            : <StateBadge ok={published && row.available} pending={!published} />}
                        </Td>
                        <Td>
                          <div className="flex gap-[6px]">
                            {!row.capabilities.includes('agent_chat') ? (
                              <span className="text-[11px] text-[#858b9c]">待对应运行时与使用页面</span>
                            ) : published ? (
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
                      <Td>{row.capabilities.length ? row.capabilities.map((item) => capabilityLabel.get(item) || item).join('、') : <span className="text-[#858b9c]">非聊天模型 · 已保留目录</span>}</Td>
                      <Td><StateBadge ok={row.enabled && row.health_status === 'healthy'} pending={row.health_status === 'unknown'} /></Td>
                      <Td>
                        {!row.capabilities.length ? (
                          <span className="rounded-full bg-[#f1f2f5] px-[9px] py-[5px] text-[11px] text-[#757f9c]">待接入专用运行时</span>
                        ) : row.enabled && row.health_status === 'healthy' ? (
                          <Button variant="outline" size="sm" onClick={() => void openCertification(row)}>
                            <ShieldCheck className="size-[13px]" />
                            认证能力
                          </Button>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={Boolean(verifyingId)}
                            onClick={() => void verifyDeployment(row)}
                          >
                            {verifyingId === row.id ? <LoaderCircle className="size-[13px] animate-spin" /> : <CheckCircle2 className="size-[13px]" />}
                            基础验证
                          </Button>
                        )}
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

        {tab === 'costs' && (
          <PanelSection
            title="成本与额度"
            description="价格采用版本留存；额度用于开用量控制，暂不连接真实收费。"
            actionLabel="发放测试额度"
            onAction={() => setQuotaOpen(true)}
          >
            <div className="grid gap-[10px] sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard label="本月平台 Token" value={compactNumber(usage.totals.total_tokens)} />
              <MetricCard label="聚合平台预估成本" value={`${moneySymbol('CNY')} ${decimalText(usage.totals.platform_cost)}`} />
              <MetricCard label="本月已计费额度" value={decimalText(usage.totals.billable_credits)} />
              <MetricCard label="额度使用率" value={`${quotaPercent}%`} />
            </div>

            <div className="mt-[14px] grid gap-[12px] xl:grid-cols-[minmax(0,1.6fr)_minmax(310px,0.9fr)]">
              <section className="rounded-[12px] border border-[#e7eaf0] p-[14px]">
                <h4 className="text-[12px] font-semibold text-[#18181a]">模型价格版本</h4>
                <div className="mt-[10px] overflow-x-auto">
                  <table className="w-full min-w-[620px] text-left text-[12px]">
                    <thead className="border-y border-[#eceef1] text-[#858b9c]"><tr><Th>模型</Th><Th>输入 / 1M</Th><Th>输出 / 1M</Th><Th>币种</Th><Th>操作</Th></tr></thead>
                    <tbody>
                      {deployments.map((deployment) => {
                        const price = latestPriceByDeployment.get(deployment.id);
                        return (
                          <tr key={deployment.id} className="border-b border-[#eceef1] last:border-b-0">
                            <Td>
                              <strong className="block text-[#18181a]">{deployment.name}</strong>
                              <small className="text-[10px] text-[#858b9c]">{price ? `${new Date(price.effective_from).toLocaleDateString('zh-CN')} 生效` : '尚未配置'}</small>
                            </Td>
                            <Td>{price ? `${moneySymbol(price.currency)} ${decimalText(price.input_per_million)}` : '—'}</Td>
                            <Td>{price ? `${moneySymbol(price.currency)} ${decimalText(price.output_per_million)}` : '—'}</Td>
                            <Td>{price?.currency || '—'}</Td>
                            <Td><Button variant="outline" size="sm" onClick={() => openPriceEditor(deployment.id)}>{price ? '新版本' : '配置'}</Button></Td>
                          </tr>
                        );
                      })}
                      {!deployments.length && <tr><td colSpan={5}><Empty text="请先同步或添加平台模型" /></td></tr>}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="rounded-[12px] border border-[#e7eaf0] p-[14px]">
                <h4 className="text-[12px] font-semibold text-[#18181a]">当前租户额度</h4>
                <div className="mt-[16px] flex items-center justify-between text-[12px]">
                  <span className="max-w-[190px] truncate text-[#464c5e]" title={tenantId}>{tenantId}</span>
                  <strong className="text-[#18181a]">{decimalText(usage.quota.consumed_credits)} / {decimalText(usage.quota.granted_credits)}</strong>
                </div>
                <div className="mt-[9px] h-[7px] overflow-hidden rounded-full bg-[#eef0f4]">
                  <span className="block h-full rounded-full bg-[#367df7]" style={{ width: `${quotaPercent}%` }} />
                </div>
                <dl className="mt-[14px] space-y-[8px] text-[11px]">
                  <QuotaInfo label="周期" value={usage.quota.cycle_start && usage.quota.cycle_end ? `${usage.quota.cycle_start} 至 ${usage.quota.cycle_end}` : '尚未发放额度'} />
                  <QuotaInfo label="预警阈值" value={`${usage.quota.warning_threshold_percent}%`} />
                  <QuotaInfo label="超额策略" value={usage.quota.hard_limit ? '硬限制' : '允许超额'} />
                </dl>
                {deployments.some((item) => !latestPriceByDeployment.has(item.id)) && (
                  <div className="mt-[14px] flex gap-[8px] rounded-[9px] bg-[#fff8e9] px-[10px] py-[9px] text-[11px] leading-[17px] text-[#9a6518]">
                    <AlertTriangle className="mt-[1px] size-[13px] shrink-0" />
                    未配置价格的模型仍记录 Token，但成本与额度显示为未计价。
                  </div>
                )}
              </section>
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

      <Dialog open={certificationOpen} onOpenChange={setCertificationOpen}>
        <DialogContent className="sm:max-w-[880px]">
          <DialogTitle>认证模型能力</DialogTitle>
          <p className="-mt-[6px] text-[11px] text-[#858b9c]">
            {certificationDeployment ? `${certificationDeployment.name} · ${certificationDeployment.model} · ${certificationDeployment.connection_name}` : ''}
          </p>
          <div className="grid gap-[14px] border-y border-[#eceef1] py-[16px] lg:grid-cols-[minmax(0,1.45fr)_minmax(270px,0.9fr)]">
            <section className="rounded-[12px] border border-[#e7eaf0] p-[14px]">
              <h4 className="text-[12px] font-semibold text-[#18181a]">选择本次认证能力</h4>
              <div className="mt-[10px] grid gap-[8px] sm:grid-cols-2">
                {catalog.capabilities.map((item) => {
                  const isBase = BASE_CAPABILITIES.has(item.id);
                  const selected = isBase || selectedCapabilities.includes(item.id);
                  return (
                    <label key={item.id} className={`flex min-h-[58px] gap-[9px] rounded-[10px] border px-[11px] py-[9px] ${isBase ? 'cursor-not-allowed bg-[#fafafa]' : 'cursor-pointer bg-white'} ${selected ? 'border-[#d7dbe3]' : 'border-[#e7eaf0]'}`}>
                      <input
                        className="mt-[2px] size-[13px] accent-[#18181a]"
                        type="checkbox"
                        disabled={isBase}
                        checked={selected}
                        onChange={(event) => setSelectedCapabilities((current) => event.target.checked ? [...current, item.id] : current.filter((value) => value !== item.id))}
                      />
                      <span className="min-w-0">
                        <strong className="block text-[12px] font-medium text-[#18181a]">{capabilityDialogLabel(item.id, item.label)}</strong>
                        <small className="mt-[3px] block text-[10px] leading-[15px] text-[#858b9c]">{capabilityDescription(item.id)}</small>
                      </span>
                    </label>
                  );
                })}
              </div>
            </section>

            <section className="rounded-[12px] border border-[#e7eaf0] p-[14px]">
              <h4 className="text-[12px] font-semibold text-[#18181a]">最近认证结果</h4>
              <div className="mt-[10px] max-h-[278px] overflow-y-auto">
                {catalog.capabilities.map((item) => {
                  const latest = latestCapabilityCheck(capabilityChecks, item.id);
                  if (!latest && !BASE_CAPABILITIES.has(item.id) && !selectedCapabilities.includes(item.id)) return null;
                  return (
                    <div key={item.id} className="flex items-center justify-between gap-[12px] border-b border-[#eceef1] py-[9px] text-[11px] last:border-b-0">
                      <span className="text-[#464c5e]">{capabilityDialogLabel(item.id, item.label)}</span>
                      <CapabilityResult check={latest} />
                    </div>
                  );
                })}
              </div>
              <QuotaInfo label="最近认证时间" value={capabilityChecks[0]?.finished_at ? new Date(capabilityChecks[0].finished_at).toLocaleString('zh-CN') : '尚无记录'} />
              <div className="mt-[13px] rounded-[9px] bg-[#fff8e9] px-[10px] py-[9px] text-[11px] leading-[17px] text-[#9a6518]">
                认证会产生少量真实模型调用费用；失败结果也会留存，不覆盖历史证据。
              </div>
            </section>
          </div>
          <div className="flex justify-end gap-[8px]">
            <Button variant="outline" disabled={certifying} onClick={() => setCertificationOpen(false)}>取消</Button>
            <Button className="bg-[#18181a] text-white hover:bg-[#2d2d32]" disabled={certifying || !selectedCapabilities.length} onClick={() => void certifyCapabilities()}>
              {certifying && <LoaderCircle className="size-[14px] animate-spin" />}
              开始认证 {selectedCapabilities.length} 项能力
            </Button>
          </div>
        </DialogContent>
      </Dialog>

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

      <Dialog open={priceOpen} onOpenChange={setPriceOpen}>
        <DialogContent className="sm:max-w-[620px]">
          <DialogTitle>新增模型价格版本</DialogTitle>
          <p className="-mt-[6px] text-[11px] text-[#858b9c]">保存后立即生效，历史价格不会被覆盖。</p>
          <div className="grid gap-[14px] sm:grid-cols-2">
            <Field label="平台模型"><Select value={priceForm.deployment_id} onValueChange={(value) => setPriceForm((form) => ({ ...form, deployment_id: value }))}><SelectTrigger><SelectValue placeholder="选择模型" /></SelectTrigger><SelectContent>{deployments.map((item) => <SelectItem key={item.id} value={item.id}>{item.name} · {item.model}</SelectItem>)}</SelectContent></Select></Field>
            <Field label="币种"><Select value={priceForm.currency} onValueChange={(value) => setPriceForm((form) => ({ ...form, currency: value }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="CNY">CNY</SelectItem><SelectItem value="USD">USD</SelectItem></SelectContent></Select></Field>
            <Field label="输入价格 / 1M Token"><Input type="number" min="0" value={priceForm.input_per_million} onChange={(event) => setPriceForm((form) => ({ ...form, input_per_million: event.target.value }))} /></Field>
            <Field label="输出价格 / 1M Token"><Input type="number" min="0" value={priceForm.output_per_million} onChange={(event) => setPriceForm((form) => ({ ...form, output_per_million: event.target.value }))} /></Field>
            <Field label="缓存输入 / 1M Token"><Input type="number" min="0" value={priceForm.cached_input_per_million} onChange={(event) => setPriceForm((form) => ({ ...form, cached_input_per_million: event.target.value }))} /></Field>
            <Field label="推理 Token / 1M"><Input type="number" min="0" value={priceForm.reasoning_per_million} onChange={(event) => setPriceForm((form) => ({ ...form, reasoning_per_million: event.target.value }))} /></Field>
            <div className="sm:col-span-2"><Field label="每 1 币种单位折算额度"><Input type="number" min="0.000001" value={priceForm.credits_per_currency_unit} onChange={(event) => setPriceForm((form) => ({ ...form, credits_per_currency_unit: event.target.value }))} /></Field></div>
          </div>
          <DialogActions saving={saving} onCancel={() => setPriceOpen(false)} onSave={() => void savePriceVersion()} />
        </DialogContent>
      </Dialog>

      <Dialog open={quotaOpen} onOpenChange={setQuotaOpen}>
        <DialogContent className="sm:max-w-[520px]">
          <DialogTitle>发放测试额度</DialogTitle>
          <p className="-mt-[6px] text-[11px] text-[#858b9c]">额度发放给当前租户 {tenantId}，仅用于平台 AI 用量控制。</p>
          <div className="grid gap-[14px]">
            <Field label="发放额度"><Input type="number" min="0.000001" value={quotaForm.credits} onChange={(event) => setQuotaForm((form) => ({ ...form, credits: event.target.value }))} /></Field>
            <Field label="预警阈值（%）"><Input type="number" min="1" max="100" value={quotaForm.warning_threshold_percent} onChange={(event) => setQuotaForm((form) => ({ ...form, warning_threshold_percent: event.target.value }))} /></Field>
            <label className="flex items-center gap-[8px] rounded-[9px] border border-[#e7eaf0] px-[10px] py-[9px] text-[12px] text-[#464c5e]"><input type="checkbox" checked={quotaForm.hard_limit} onChange={(event) => setQuotaForm((form) => ({ ...form, hard_limit: event.target.checked }))} />额度耗尽后停止平台模型调用</label>
          </div>
          <DialogActions saving={saving} onCancel={() => setQuotaOpen(false)} onSave={() => void grantTestQuota()} />
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
  return <div><div className="mb-[14px] flex flex-wrap items-start justify-between gap-[12px]"><div><h3 className="text-[13px] font-semibold text-[#18181a]">{title}</h3><p className="mt-[3px] text-[11px] text-[#858b9c]">{description}</p></div>{actionLabel && <Button className="bg-[#18181a] text-white hover:bg-[#2d2d32]" size="sm" disabled={actionDisabled} onClick={onAction}><Plus className="size-[14px]" />{actionLabel}</Button>}</div>{children}</div>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="flex flex-col gap-[6px]"><span className="text-[12px] font-medium text-[#464c5e]">{label}</span>{children}</label>;
}

function DialogActions({ saving, onCancel, onSave }: { saving: boolean; onCancel: () => void; onSave: () => void }) {
  return <div className="mt-[8px] flex justify-end gap-[8px]"><Button variant="outline" disabled={saving} onClick={onCancel}>取消</Button><Button className="bg-[#18181a] text-white hover:bg-[#2d2d32]" disabled={saving} onClick={onSave}>{saving && <LoaderCircle className="size-[14px] animate-spin" />}保存</Button></div>;
}

function StateBadge({ ok, pending = false, compact = false }: { ok: boolean; pending?: boolean; compact?: boolean }) {
  const label = ok ? '可用' : pending ? '待验证' : '不可用';
  return <span className={`shrink-0 rounded-full ${compact ? 'px-[7px] py-[2px] text-[10px]' : 'px-[9px] py-[4px] text-[11px]'} ${ok ? 'bg-[#eaf8f0] text-[#168a50]' : pending ? 'bg-[#fff4e8] text-[#b96a13]' : 'bg-[#f1f2f5] text-[#858b9c]'}`}>{label}</span>;
}

function Info({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="min-w-0"><dt className="text-[#a0a6b5]">{label}</dt><dd className={`mt-[2px] truncate text-[#464c5e] ${mono ? 'font-mono' : ''}`}>{value}</dd></div>;
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return <article className="rounded-[12px] border border-[#e7eaf0] px-[14px] py-[13px]"><div className="text-[11px] text-[#858b9c]">{label}</div><strong className="mt-[8px] block text-[20px] leading-none text-[#18181a]">{value}</strong></article>;
}

function QuotaInfo({ label, value }: { label: string; value: string }) {
  return <div className="mt-[8px] flex items-center justify-between gap-[12px] text-[11px]"><span className="text-[#858b9c]">{label}</span><strong className="text-right font-normal text-[#464c5e]">{value}</strong></div>;
}

function CapabilityResult({ check }: { check?: AIModelCapabilityCheckRead }) {
  if (!check) return <span className="text-[#b96a13]">待认证</span>;
  if (check.status === 'passed') return <span className="text-[#168a50]">已通过</span>;
  if (check.status === 'failed') return <span className="text-[#c23b3b]" title={check.error_code}>未通过</span>;
  return <span className="text-[#1a71ff]">认证中</span>;
}

function latestCapabilityCheck(checks: AIModelCapabilityCheckRead[], capability: string) {
  return checks.find((item) => item.capability === capability);
}

function capabilityDescription(capability: string) {
  const descriptions: Record<string, string> = {
    agent_chat: '基础验证，普通与流式对话',
    structured_generation: '基础验证，结构化 JSON 输出',
    demand_analysis: '需求摘要、目标与约束提取',
    matching: '推荐服务对象并生成理由',
    quote_draft: '范围、工期、里程碑与验收草案',
    evidence_summary: '只整理证据，不生成裁决',
    knowledge_processing: '标题、摘要与标签整理',
    skill_distillation: '结构化生成可调用 Skill',
  };
  return descriptions[capability] || '平台业务能力认证';
}

function capabilityDialogLabel(capability: string, fallback: string) {
  const labels: Record<string, string> = {
    agent_chat: '普通与流式对话',
    structured_generation: '结构化 JSON',
    demand_analysis: 'AI 需求分析',
    matching: 'AI 服务匹配',
    quote_draft: 'AI 报价草案',
    evidence_summary: '争议证据摘要',
    knowledge_processing: '知识整理',
    skill_distillation: 'Skill 整理与生成',
  };
  return labels[capability] || fallback;
}

function compactNumber(value: number) {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return String(value || 0);
}

function decimalText(value: string) {
  const number = Number(value || 0);
  return Number.isFinite(number)
    ? number.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
    : '0';
}

function moneySymbol(currency: string) {
  return currency === 'USD' ? '$' : '¥';
}

function Empty({ text }: { text: string }) {
  return <div className="col-span-full py-[28px] text-center text-[12px] text-[#a0a6b5]">{text}</div>;
}

function Th({ children }: { children: ReactNode }) { return <th className="px-[12px] py-[10px] font-medium">{children}</th>; }
function Td({ children }: { children: ReactNode }) { return <td className="px-[12px] py-[11px] text-[#464c5e]">{children}</td>; }
