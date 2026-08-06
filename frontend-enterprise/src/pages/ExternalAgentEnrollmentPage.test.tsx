// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const apiGet = vi.fn();
const apiPost = vi.fn();

vi.mock('@/api/client', () => ({
  ApiError: class ApiError extends Error { status = 0; },
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
    put: vi.fn(),
  },
}));

vi.mock('@/components/ui/app-toast', () => ({
  notify: { success: vi.fn(), error: vi.fn() },
}));

import ExternalAgentEnrollmentPage from './ExternalAgentEnrollmentPage';

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

const organization = { id: 'org_resume', name: '恢复测试企业' };
const enrollment = {
  id: 'enrollment_resume',
  organizationId: organization.id,
  status: 'registered',
  pairingCodeHint: '1234',
  expiresAt: '2026-08-07T00:00:00Z',
  requestedScopes: ['manifest:write'],
  manifestVersion: '1.0',
  connectionId: 'externalagent_resume',
  createdAt: '2026-08-06T00:00:00Z',
};
const confirmedDraft = {
  id: 'draft_resume',
  organizationId: organization.id,
  connectionId: 'externalagent_resume',
  manifestId: 'manifest_resume',
  agentName: '已恢复外接员工',
  roleName: '外接执行员',
  jobDescription: '执行已授权 Skill',
  serviceScope: ['外接执行'],
  restrictions: ['不可越权'],
  selectedAssetIds: ['asset_1'],
  fieldProvenance: {},
  executionMode: 'external',
  syncPolicy: 'manual',
  status: 'confirmed',
  agentProfileId: 'agent_profile_resume',
};

afterEach(() => {
  cleanup();
  apiGet.mockReset();
  apiPost.mockReset();
});

describe('external Agent enrollment persistence', () => {
  it('restores a registered enrollment from the URL without creating a duplicate', async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === '/api/marketplace/organizations') return Promise.resolve([organization]);
      if (url === '/api/enterprise/external-agents/externalagent_resume') return Promise.resolve({ transport: 'polling' });
      if (url.endsWith('/manifest')) return Promise.resolve({
        id: 'manifest_resume',
        connectionId: 'externalagent_resume',
        sourceDigest: 'sha256:resume',
        status: 'pending_user_review',
        normalizedAgent: { name: '待审核 Codex Agent' },
        disclosure: {},
        validationErrors: [],
        validationWarnings: [],
        assets: [{
          id: 'asset_declared', externalId: 'declared-capability', kind: 'skill', name: '声明能力', description: '未扫描本地 Skill',
          version: '1.0', portable: false, callable: true, selected: true, riskLevel: 'medium', verificationStatus: 'declared_only',
          sourceType: 'declarative', sourceHash: 'sha256:declared', permissions: [], evidence: {}, provenance: {},
        }],
        submittedAt: '2026-08-06T00:00:00Z',
      });
      if (url.includes('/external-agent-enrollments/enrollment_resume')) return Promise.resolve({
        id: 'enrollment_resume',
        organizationId: organization.id,
        status: 'registered',
        pairingCodeHint: '1234',
        expiresAt: '2026-08-07T00:00:00Z',
        requestedScopes: ['manifest:write'],
        manifestVersion: '1.0',
        connectionId: 'externalagent_resume',
        createdAt: '2026-08-06T00:00:00Z',
      });
      return Promise.reject(new Error(`unexpected ${url}`));
    });

    const { container } = render(
      <MemoryRouter initialEntries={['/enterprise/agents/external/connect?enrollmentId=enrollment_resume']}>
        <Routes><Route path="/enterprise/agents/external/connect" element={<ExternalAgentEnrollmentPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText('待审核 Codex Agent')).toBeTruthy();
    expect(screen.getByText('恢复测试企业 · 配对码尾号 1234')).toBeTruthy();
    expect(screen.getByText(/仅声明未验证/)).toBeTruthy();
    expect(container.querySelectorAll('.external-agent-stepper')).toHaveLength(1);
    expect(apiPost).not.toHaveBeenCalledWith('/api/enterprise/external-agent-enrollments', expect.anything());
  });

  it('writes the enrollment ID to the URL while retaining the one-time code in memory', async () => {
    apiGet.mockResolvedValue([organization]);
    apiPost.mockResolvedValue({
      id: 'enrollment_new',
      organizationId: organization.id,
      status: 'pending',
      pairingCode: 'PAIR-ONLY-ONCE',
      pairingCodeHint: 'ONCE',
      expiresAt: '2099-08-07T00:00:00Z',
      requestedScopes: ['manifest:write'],
      manifestVersion: '1.0',
      installInstruction: '安装独立 Connector',
    });

    render(
      <MemoryRouter initialEntries={['/enterprise/agents/external/connect']}>
        <Routes><Route path="/enterprise/agents/external/connect" element={<><ExternalAgentEnrollmentPage /><LocationProbe /></>} /></Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: /生成配对码/ }));

    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/enterprise/agents/external/connect?enrollmentId=enrollment_new'));
    expect(screen.getByText('PAIR-ONLY-ONCE')).toBeTruthy();
    expect(screen.getByText(/kaigongba-agent discover preview/)).toBeTruthy();
    expect(screen.getByText(/kaigongba-agent discover confirm/)).toBeTruthy();
  });

  it.each(['webhook', 'a2a'] as const)('restores an existing pending connection test for the original %s transport', async (originalTransport) => {
    const latestTest = {
      id: 'connection_test_latest',
      connectionId: 'externalagent_resume',
      agentProfileId: 'agent_profile_resume',
      status: 'queued',
      expected: {}, result: {}, error: {},
      expiresAt: '2099-08-07T00:00:00Z',
    };
    apiGet.mockImplementation((url: string) => {
      if (url === '/api/marketplace/organizations') return Promise.resolve([organization]);
      if (url === '/api/enterprise/external-agents/externalagent_resume') return Promise.resolve({ transport: originalTransport });
      if (url.includes('/external-agent-enrollments/enrollment_resume/manifest')) return Promise.resolve({
        id: 'manifest_resume', connectionId: 'externalagent_resume', sourceDigest: 'sha256:resume', status: 'approved',
        normalizedAgent: { name: '已恢复外接员工' }, disclosure: { discovery_mode: 'metadata_discovery' },
        validationErrors: [], validationWarnings: [], assets: [], submittedAt: '2026-08-06T00:00:00Z',
      });
      if (url.includes('/external-agent-enrollments/enrollment_resume')) return Promise.resolve(enrollment);
      if (url.endsWith('/externalagent_resume/connection-test')) return Promise.resolve(latestTest);
      return Promise.reject(new Error(`unexpected ${url}`));
    });
    apiPost.mockImplementation((url: string) => {
      if (url.endsWith('/externalagent_resume/import-draft')) return Promise.resolve(confirmedDraft);
      return Promise.reject(new Error(`unexpected post ${url}`));
    });

    render(
      <MemoryRouter initialEntries={['/enterprise/agents/external/connect?enrollmentId=enrollment_resume']}>
        <Routes><Route path="/enterprise/agents/external/connect" element={<ExternalAgentEnrollmentPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText('等待 Agent 领取测试')).toBeTruthy();
    expect(screen.queryByText(/临时手动执行模式/)).toBeNull();
    expect(apiGet).toHaveBeenCalledWith('/api/enterprise/external-agents/externalagent_resume/connection-test');
    expect(apiPost).not.toHaveBeenCalledWith(expect.stringContaining('/confirm'), expect.anything());
  });

  it('creates a fresh idempotency key when the user retries an expired connection test', async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === '/api/marketplace/organizations') return Promise.resolve([organization]);
      if (url === '/api/enterprise/external-agents/externalagent_resume') return Promise.resolve({ transport: 'polling' });
      if (url.includes('/external-agent-enrollments/enrollment_resume/manifest')) return Promise.resolve({
        id: 'manifest_resume', connectionId: 'externalagent_resume', sourceDigest: 'sha256:resume', status: 'approved',
        normalizedAgent: { name: '已恢复外接员工' }, disclosure: { discovery_mode: 'metadata_discovery' },
        validationErrors: [], validationWarnings: [], assets: [], submittedAt: '2026-08-06T00:00:00Z',
      });
      if (url.includes('/external-agent-enrollments/enrollment_resume')) return Promise.resolve(enrollment);
      if (url.endsWith('/externalagent_resume/connection-test')) return Promise.resolve({
        id: 'connection_test_expired', connectionId: 'externalagent_resume', agentProfileId: 'agent_profile_resume', status: 'expired',
        expected: {}, result: {}, error: {}, expiresAt: '2026-08-05T00:00:00Z',
      });
      return Promise.reject(new Error(`unexpected ${url}`));
    });
    apiPost.mockImplementation((url: string) => {
      if (url.endsWith('/externalagent_resume/import-draft')) return Promise.resolve(confirmedDraft);
      if (url.endsWith('/externalagent_resume/connection-tests')) return Promise.resolve({
        id: 'connection_test_retry', connectionId: 'externalagent_resume', agentProfileId: 'agent_profile_resume', status: 'queued',
        expected: {}, result: {}, error: {}, expiresAt: '2099-08-07T00:00:00Z',
      });
      return Promise.reject(new Error(`unexpected post ${url}`));
    });

    render(
      <MemoryRouter initialEntries={['/enterprise/agents/external/connect?enrollmentId=enrollment_resume']}>
        <Routes><Route path="/enterprise/agents/external/connect" element={<ExternalAgentEnrollmentPage />} /></Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: '重新测试' }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith(
      '/api/enterprise/external-agents/externalagent_resume/connection-tests',
      expect.objectContaining({ idempotency_key: expect.stringMatching(/^web-connection-test-draft_resume-.+/) }),
    ));
    const request = apiPost.mock.calls.find(([url]) => String(url).endsWith('/connection-tests'))?.[1] as { idempotency_key: string };
    expect(request.idempotency_key).not.toBe('web-connection-test-draft_resume');
  });

  it('restores manual transport without requesting or presenting a connection test', async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === '/api/marketplace/organizations') return Promise.resolve([organization]);
      if (url === '/api/enterprise/external-agents/externalagent_resume') return Promise.resolve({ transport: 'manual' });
      if (url.includes('/external-agent-enrollments/enrollment_resume/manifest')) return Promise.resolve({
        id: 'manifest_resume', connectionId: 'externalagent_resume', sourceDigest: 'sha256:resume', status: 'approved',
        normalizedAgent: { name: '手动外接员工' }, disclosure: { discovery_mode: 'metadata_discovery' },
        validationErrors: [], validationWarnings: [], assets: [], submittedAt: '2026-08-06T00:00:00Z',
      });
      if (url.includes('/external-agent-enrollments/enrollment_resume')) return Promise.resolve({
        ...enrollment, connectionStatus: 'manual_ready', workflowStage: 'available',
      });
      return Promise.reject(new Error(`unexpected ${url}`));
    });
    apiPost.mockImplementation((url: string) => {
      if (url.endsWith('/externalagent_resume/import-draft')) return Promise.resolve(confirmedDraft);
      return Promise.reject(new Error(`unexpected post ${url}`));
    });

    render(
      <MemoryRouter initialEntries={['/enterprise/agents/external/connect?enrollmentId=enrollment_resume']}>
        <Routes><Route path="/enterprise/agents/external/connect" element={<ExternalAgentEnrollmentPage />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/员工已按临时手动执行模式登记/)).toBeTruthy();
    expect(apiGet).not.toHaveBeenCalledWith('/api/enterprise/external-agents/externalagent_resume/connection-test');
    expect(screen.queryByRole('button', { name: /开始连接测试|重新测试/ })).toBeNull();
  });
});
