// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiState = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));

vi.mock('@/api/client', () => ({
  TENANT_ID: 'tenant_demo',
  api: {
    get: apiState.get,
    post: apiState.post,
    put: apiState.put,
    delete: vi.fn(),
  },
}));

import PlatformModelGatewayPanel from './PlatformModelGatewayPanel';
import { I18nProvider } from '@/i18n';

afterEach(() => {
  cleanup();
  apiState.get.mockReset();
  apiState.post.mockReset();
  apiState.put.mockReset();
});

describe('PlatformModelGatewayPanel', () => {
  it('shows platform connections, Chinese model families and routed capabilities', async () => {
    apiState.get.mockImplementation(async (url: string) => {
      if (url === '/api/ai/catalog') {
        return {
          provider_kinds: [{ id: 'openai_compatible', label: 'OpenAI 兼容聚合平台' }],
          model_families: [
            { id: 'doubao', label: '豆包' },
            { id: 'deepseek', label: 'DeepSeek' },
            { id: 'glm', label: 'GLM' },
            { id: 'kimi', label: 'Kimi' },
          ],
          capabilities: [{ id: 'agent_chat', label: '数字员工与开小花对话' }],
          protocols: ['openai_chat_completions'],
        };
      }
      if (url === '/api/ai/capabilities/status') {
        return {
          tenant_id: 'tenant_demo',
          platform_available: true,
          tenant_byok_available: false,
          effective_source: 'platform',
          capabilities: [{
            capability: 'agent_chat',
            available: true,
            source: 'platform',
            primary_model: 'deepseek-v3.1',
            fallback_count: 1,
          }],
        };
      }
      if (url === '/api/ai/platform/connections') {
        return [{
          id: 'aiprov_1',
          name: '聚合平台 A',
          provider_kind: 'openai_compatible',
          api_protocol: 'openai_chat_completions',
          base_url: 'https://example.com/v1',
          api_key_masked: 'sk-****7890',
          enabled: true,
          trust_status: 'verified',
          model_count: 2,
          created_at: '2026-08-03T00:00:00Z',
          updated_at: '2026-08-03T00:00:00Z',
        }];
      }
      if (url === '/api/ai/platform/deployments') {
        return [{
          id: 'aimodel_1',
          connection_id: 'aiprov_1',
          connection_name: '聚合平台 A',
          name: 'DeepSeek V3.1',
          model: 'deepseek-v3.1',
          model_family: 'deepseek',
          temperature: 0.2,
          max_output_tokens: 8192,
          capabilities: ['agent_chat'],
          protocol_options: {},
          pricing: {},
          enabled: true,
          health_status: 'healthy',
          created_at: '2026-08-03T00:00:00Z',
          updated_at: '2026-08-03T00:00:00Z',
        }];
      }
      if (url === '/api/ai/platform/routes') {
        return [{
          id: 'airoute_1',
          capability: 'agent_chat',
          deployment_id: 'aimodel_1',
          deployment_name: 'DeepSeek V3.1',
          connection_id: 'aiprov_1',
          connection_name: '聚合平台 A',
          model: 'deepseek-v3.1',
          model_family: 'deepseek',
          priority: 10,
          timeout_seconds: 90,
          retry_count: 1,
          enabled: true,
          available: true,
          created_at: '2026-08-03T00:00:00Z',
          updated_at: '2026-08-03T00:00:00Z',
        }];
      }
      return [];
    });

    render(<I18nProvider><PlatformModelGatewayPanel /></I18nProvider>);

    await waitFor(() => expect(screen.getByText('聚合平台 A')).toBeTruthy());
    expect(screen.getByText('已提供 1 项能力')).toBeTruthy();
    expect(screen.getByText('sk-****7890')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '平台模型 1' }));
    expect(screen.getByText('DeepSeek V3.1')).toBeTruthy();
    expect(screen.getByText('deepseek-v3.1')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '能力路由 1' }));
    expect(screen.getByText('数字员工与开小花对话')).toBeTruthy();
    expect(screen.getByText(/P10 · DeepSeek V3.1 · 聚合平台 A/)).toBeTruthy();
  });

  it('syncs the provider catalog without exposing the provider key', async () => {
    apiState.get.mockImplementation(async (url: string) => {
      if (url === '/api/ai/catalog') {
        return {
          provider_kinds: [{ id: 'crun', label: 'CRUN 聚合平台' }],
          model_families: [],
          capabilities: [],
          protocols: ['openai_chat_completions'],
        };
      }
      if (url === '/api/ai/capabilities/status') {
        return { platform_available: false, capabilities: [] };
      }
      if (url === '/api/ai/platform/connections') {
        return [{
          id: 'aiprov_crun',
          name: 'CRUN 主连接',
          provider_kind: 'crun',
          api_protocol: 'openai_chat_completions',
          base_url: 'https://api.crun.ai/api/v1',
          api_key_masked: 'ak_****test',
          enabled: true,
          trust_status: 'pending',
          model_count: 0,
          created_at: '2026-08-03T00:00:00Z',
          updated_at: '2026-08-03T00:00:00Z',
        }];
      }
      return [];
    });
    apiState.post.mockResolvedValue({
      connection_id: 'aiprov_crun',
      discovered_count: 24,
      created_count: 24,
      updated_count: 0,
      unavailable_count: 0,
      deployment_draft_count: 20,
      product_draft_count: 20,
      synced_at: '2026-08-03T00:00:00Z',
    });

    render(<PlatformModelGatewayPanel />);
    await waitFor(() => expect(screen.getByText('CRUN 主连接')).toBeTruthy());
    expect(screen.queryByText('ak_example_should_never_render')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '同步模型目录' }));
    await waitFor(() => expect(apiState.post).toHaveBeenCalledWith(
      '/api/ai/platform/connections/aiprov_crun/catalog/sync',
      { create_product_drafts: true },
    ));
  });

  it('keeps non-chat models in inventory and certifies only selected chat capabilities', async () => {
    apiState.get.mockImplementation(async (url: string) => {
      if (url === '/api/ai/catalog') {
        return {
          provider_kinds: [{ id: 'crun', label: 'CRUN 聚合平台' }],
          model_families: [{ id: 'deepseek', label: 'DeepSeek' }],
          capabilities: [
            { id: 'agent_chat', label: '普通与流式对话' },
            { id: 'structured_generation', label: '结构化 JSON' },
            { id: 'demand_analysis', label: 'AI 需求分析' },
          ],
          protocols: ['openai_chat_completions'],
        };
      }
      if (url === '/api/ai/capabilities/status') return { platform_available: true, capabilities: [] };
      if (url === '/api/ai/platform/connections') return [];
      if (url === '/api/ai/platform/deployments') {
        return [
          {
            id: 'aimodel_chat', connection_id: 'aiprov_crun', connection_name: 'CRUN 主连接', name: 'DeepSeek V3', model: 'deepseek-v3', model_family: 'deepseek', temperature: 0.2, max_output_tokens: 8192, capabilities: ['agent_chat', 'structured_generation'], protocol_options: {}, pricing: {}, enabled: true, health_status: 'healthy', created_at: '2026-08-03T00:00:00Z', updated_at: '2026-08-03T00:00:00Z',
          },
          {
            id: 'aimodel_video', connection_id: 'aiprov_crun', connection_name: 'CRUN 主连接', name: 'Sora Video 2', model: 'sora-video-2', model_family: 'custom', temperature: 0.2, max_output_tokens: 8192, capabilities: [], protocol_options: {}, pricing: {}, enabled: false, health_status: 'unknown', created_at: '2026-08-03T00:00:00Z', updated_at: '2026-08-03T00:00:00Z',
          },
        ];
      }
      if (url.startsWith('/api/ai/platform/capability-checks?deployment_id=aimodel_chat')) {
        return [{ id: 'check_base', certification_run_id: 'run_base', deployment_id: 'aimodel_chat', capability: 'agent_chat', check_type: 'chat_and_stream', status: 'passed', metadata: {}, started_at: '2026-08-03T00:00:00Z', finished_at: '2026-08-03T00:00:01Z', created_at: '2026-08-03T00:00:00Z' }];
      }
      if (url === '/api/ai/usage/summary?days=30&scope=tenant') return EMPTY_USAGE_TEST;
      return [];
    });
    apiState.post.mockImplementation(async (url: string) => {
      if (url === '/api/ai/platform/deployments/aimodel_chat/certify') {
        return {
          success: true,
          certification_run_id: 'run_demand',
          certified_capabilities: ['demand_analysis'],
          failed_capabilities: [],
          checks: [{ id: 'check_demand', certification_run_id: 'run_demand', deployment_id: 'aimodel_chat', capability: 'demand_analysis', check_type: 'business_capability', status: 'passed', metadata: {}, started_at: '2026-08-03T00:01:00Z', finished_at: '2026-08-03T00:01:01Z', created_at: '2026-08-03T00:01:00Z' }],
          deployment: { id: 'aimodel_chat', connection_id: 'aiprov_crun', connection_name: 'CRUN 主连接', name: 'DeepSeek V3', model: 'deepseek-v3', model_family: 'deepseek', temperature: 0.2, max_output_tokens: 8192, capabilities: ['agent_chat', 'structured_generation', 'demand_analysis'], protocol_options: {}, pricing: {}, enabled: true, health_status: 'healthy', created_at: '2026-08-03T00:00:00Z', updated_at: '2026-08-03T00:00:00Z' },
        };
      }
      return {};
    });

    render(<PlatformModelGatewayPanel />);
    await waitFor(() => expect(screen.getByRole('button', { name: '平台模型 2' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: '平台模型 2' }));
    expect(screen.getByText('Sora Video 2')).toBeTruthy();
    expect(screen.getByText('非聊天模型 · 已保留目录')).toBeTruthy();
    expect(screen.getByText('待接入专用运行时')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '认证能力' }));
    await waitFor(() => expect(screen.getByText('认证模型能力')).toBeTruthy());
    fireEvent.click(screen.getByRole('checkbox', { name: /AI 需求分析/ }));
    fireEvent.click(screen.getByRole('button', { name: '开始认证 1 项能力' }));
    await waitFor(() => expect(apiState.post).toHaveBeenCalledWith(
      '/api/ai/platform/deployments/aimodel_chat/certify',
      { capabilities: ['demand_analysis'], activate: true },
    ));
  });

  it('shows price versions and current tenant quota in the costs tab', async () => {
    apiState.get.mockImplementation(async (url: string) => {
      if (url === '/api/ai/catalog') return { provider_kinds: [], model_families: [], capabilities: [], protocols: [] };
      if (url === '/api/ai/capabilities/status') return { platform_available: false, capabilities: [] };
      if (url === '/api/ai/platform/deployments') return [{ id: 'aimodel_1', connection_id: 'aiprov_1', connection_name: 'CRUN', name: 'DeepSeek V3', model: 'deepseek-v3', model_family: 'deepseek', temperature: 0.2, max_output_tokens: 8192, capabilities: ['agent_chat'], protocol_options: {}, pricing: {}, enabled: true, health_status: 'healthy', created_at: '2026-08-03T00:00:00Z', updated_at: '2026-08-03T00:00:00Z' }];
      if (url === '/api/ai/platform/prices') return [{ id: 'price_1', deployment_id: 'aimodel_1', currency: 'CNY', input_per_million: '4', output_per_million: '12', cached_input_per_million: '0', reasoning_per_million: '0', credits_per_currency_unit: '1', source: 'operator', effective_from: '2026-08-03T00:00:00Z', created_at: '2026-08-03T00:00:00Z' }];
      if (url === '/api/ai/usage/summary?days=30&scope=tenant') return { ...EMPTY_USAGE_TEST, quota: { ...EMPTY_USAGE_TEST.quota, account_id: 'quota_1', granted_credits: '2500', consumed_credits: '680', available_credits: '1820', percent_used: 27.2, hard_limit: true, cycle_start: '2026-08-01', cycle_end: '2026-08-31' }, totals: { ...EMPTY_USAGE_TEST.totals, total_tokens: 2480000, platform_cost: '186.4', billable_credits: '680' } };
      return [];
    });

    render(<I18nProvider><PlatformModelGatewayPanel /></I18nProvider>);
    await waitFor(() => expect(screen.getByRole('button', { name: '成本与额度' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: '成本与额度' }));
    expect(screen.getByText('2.48M')).toBeTruthy();
    expect(screen.getByText('¥ 186.4')).toBeTruthy();
    expect(screen.getByText('680 / 2,500')).toBeTruthy();
    expect(screen.getByRole('button', { name: '新版本' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '发放测试额度' }));
    expect(screen.getAllByText('发放测试额度').length).toBeGreaterThan(1);
  });
});

const EMPTY_USAGE_TEST = {
  quota: { granted_credits: '0', reserved_credits: '0', consumed_credits: '0', available_credits: '0', percent_used: 0, hard_limit: false, warning_threshold_percent: 80 },
  totals: { request_count: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, platform_cost: '0', billable_credits: '0', byok_tokens: 0 },
  trend: [],
  by_agent: [],
};
