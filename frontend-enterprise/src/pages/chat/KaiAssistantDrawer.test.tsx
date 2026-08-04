// @vitest-environment jsdom

import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { apiGet, apiPost, listNotifications, markNotificationsRead } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  listNotifications: vi.fn(),
  markNotificationsRead: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  TENANT_ID: 'tenant_demo',
  api: { get: apiGet, post: apiPost },
}));

vi.mock('@/features/marketplace/repository', () => ({
  marketplaceRepository: {
    listCollaborationNotifications: listNotifications,
    markCollaborationNotificationsRead: markNotificationsRead,
  },
}));

import KaiAssistantDrawer from './KaiAssistantDrawer';

beforeEach(() => {
  apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/api/chat/agents')) {
      return Promise.resolve([
        platformAssistant(),
        { ...platformAssistant(), id: 'agent_employee', name: '法务员工', metadata: { owner_user_id: 'user_real' } },
      ]);
    }
    if (path.startsWith('/api/chat/sessions/session_kai/messages')) {
      return Promise.resolve([
        message('msg_kai', 'assistant', '平台总助真实会话消息'),
      ]);
    }
    if (path.startsWith('/api/chat/sessions/session_employee/messages')) {
      return Promise.resolve([
        message('msg_private', 'assistant', '员工私有会话内容'),
      ]);
    }
    if (path.startsWith('/api/chat/sessions')) {
      return Promise.resolve([
        { id: 'session_employee', agent_id: 'agent_employee', updated_at: '2026-08-01T08:00:00Z', status: 'active' },
        { id: 'session_kai', agent_id: 'agent_kai', updated_at: '2026-08-01T09:00:00Z', status: 'active' },
      ]);
    }
    throw new Error(`unexpected GET ${path}`);
  });
  apiPost.mockResolvedValue({
    reply: '我可以帮你定位真实业务页面，但不会代替你确认或验收。',
    session_id: 'session_kai',
    session_state: {},
  });
  listNotifications.mockResolvedValue({
    unreadCount: 1,
    items: [{
      id: 'notification_real',
      organizationId: 'org_real',
      orderId: 'order_real',
      notificationType: 'material.requested',
      title: '请补充真实订单材料',
      body: '订单材料请求等待处理。',
      riskLevel: 'medium',
      status: 'unread',
      route: '/enterprise/orders/order_real?tab=materials',
      payload: { target_id: 'order_real' },
      createdAt: '2026-08-01T09:30:00Z',
    }],
  });
  markNotificationsRead.mockResolvedValue({ unreadCount: 0, items: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('Kai Xiaohua isolated assistant drawer', () => {
  it('opens in place, collapses the sidebar, closes and restores focus without changing the URL', async () => {
    renderDrawer('/enterprise/orders/order_real?tab=materials');

    const launcher = await screen.findByRole('button', { name: /打开开小花/ });
    fireEvent.click(launcher);

    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_real?tab=materials');
    expect(screen.getByTestId('sidebar-state').textContent).toBe('collapsed');
    expect(screen.getByRole('complementary', { name: '开小花平台总助' })).toBeTruthy();
    expect(screen.getAllByRole('tab')).toHaveLength(3);

    fireEvent.click(screen.getByRole('button', { name: '关闭开小花' }));
    await waitFor(() => expect(screen.getByTestId('sidebar-state').textContent).toBe('expanded'));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole('button', { name: /打开开小花/ })));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_real?tab=materials');
  });

  it('uses real notification IDs and routes while keeping the drawer mounted', async () => {
    renderDrawer('/enterprise/transactions');
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    fireEvent.click(screen.getByRole('tab', { name: /通知/ }));

    fireEvent.click(await screen.findByRole('button', { name: /请补充真实订单材料/ }));

    await waitFor(() => expect(markNotificationsRead).toHaveBeenCalledWith(['notification_real']));
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe(
      '/enterprise/orders/order_real?tab=materials',
    ));
    expect(screen.getByRole('complementary', { name: '开小花平台总助' })).toBeTruthy();
  });

  it('loads and sends only the dedicated platform assistant session', async () => {
    renderDrawer('/workspace/chat/session_employee');
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));

    expect(await screen.findByText('平台总助真实会话消息')).toBeTruthy();
    expect(screen.queryByText('员工私有会话内容')).toBeNull();

    const input = screen.getByRole('textbox', { name: '给开小花发送消息' });
    fireEvent.change(input, { target: { value: '订单入口在哪里？' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: false });

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/api/chat/turn', expect.objectContaining({
      tenant_id: 'tenant_demo',
      session_id: 'session_kai',
      agent_id: 'agent_kai',
      message: '订单入口在哪里？',
    })));
    expect(apiPost.mock.calls[apiPost.mock.calls.length - 1]?.[1]).not.toHaveProperty('channel');
    expect(await screen.findByText('我可以帮你定位真实业务页面，但不会代替你确认或验收。')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /确认验收|退款|放款/ })).toBeNull();
  });

  it('offers safe help deep links without adding a fourth target view', async () => {
    renderDrawer('/workspace/gallery?view=agents');
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    fireEvent.click(screen.getByRole('tab', { name: '使用帮助' }));
    fireEvent.click(screen.getByRole('button', { name: /查找订单、支付与交付/ }));

    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders');
    expect(screen.getAllByRole('tab')).toHaveLength(3);
  });

  it('supports keyboard opening, tab switching and Escape focus restoration', async () => {
    renderDrawer('/enterprise/transactions');
    const launcher = await screen.findByRole('button', { name: /打开开小花/ });

    launcher.focus();
    fireEvent.keyDown(launcher, { key: 'Enter' });
    const helpTab = screen.getByRole('tab', { name: '使用帮助' });
    helpTab.focus();
    fireEvent.keyDown(helpTab, { key: ' ' });

    expect(screen.getByRole('tabpanel', { name: '开小花使用帮助' })).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(document.activeElement).toBe(
      screen.getByRole('button', { name: /打开开小花/ }),
    ));
    expect(screen.queryByRole('complementary', { name: '开小花平台总助' })).toBeNull();
  });
});

function renderDrawer(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <DrawerHarness />
    </MemoryRouter>,
  );
}

function DrawerHarness() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  return (
    <>
      <KaiAssistantDrawer sidebarCollapsed={collapsed} onToggleSidebar={() => setCollapsed((value) => !value)} />
      <output data-testid="location">{location.pathname}{location.search}</output>
      <output data-testid="sidebar-state">{collapsed ? 'collapsed' : 'expanded'}</output>
    </>
  );
}

function platformAssistant() {
  return {
    id: 'agent_kai', tenant_id: 'tenant_demo', name: '开小花', description: '平台总助', persona_prompt: '',
    is_overall: false, status: 'active', metadata: { platform_assistant: true }, resources: [],
    created_at: '2026-08-01T08:00:00Z', updated_at: '2026-08-01T08:00:00Z',
  };
}

function message(id: string, role: 'user' | 'assistant', content: string) {
  return { id, role, content, metadata: {}, created_at: '2026-08-01T09:00:00Z' };
}
