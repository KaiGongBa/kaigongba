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

    render(<PlatformModelGatewayPanel />);

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
});
