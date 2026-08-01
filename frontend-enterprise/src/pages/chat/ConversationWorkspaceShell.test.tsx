// @vitest-environment jsdom

import { useState } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useNavigate } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

let chatInstanceInitializations = 0;

vi.mock('./useChatSession', () => ({
  useChatSession: () => {
    const [instanceId] = useState(() => {
      chatInstanceInitializations += 1;
      return chatInstanceInitializations;
    });
    return {
      instanceId,
      sidebarCollapsed: false,
      toggleSidebar: vi.fn(),
      visibleSidebarSessions: [],
      sessionsLoading: false,
      agents: [],
      sessionId: '',
      sessionAgentFilter: 'all',
      setSessionAgentFilter: vi.fn(),
      sessionFilterOptions: [],
      sessionReadTimes: {},
      openSession: vi.fn(),
      openDraftForAgent: vi.fn(),
      displayedAgent: undefined,
      openGallery: vi.fn(),
      handoffs: [],
      openHandoffInbox: vi.fn(),
      openRename: vi.fn(),
      requestDelete: vi.fn(),
      openAdmin: vi.fn(),
    };
  },
}));

vi.mock('@/components/AppSidebar', () => ({
  default: ({ marketplaceSelected, galleryActive }: { marketplaceSelected?: string; galleryActive?: boolean }) => (
    <aside data-testid="shared-sidebar" data-marketplace={marketplaceSelected || ''} data-gallery={String(Boolean(galleryActive))} />
  ),
}));

vi.mock('@/components/ui/sidebar', () => ({
  SidebarProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('./components/ChatDialogs', () => ({
  default: () => <div data-testid="shared-dialogs" />,
}));

vi.mock('./ChatGalleryPage', () => ({
  default: ({ chat, selectedAgentId }: { chat: { instanceId: number }; selectedAgentId?: string }) => <div data-testid="gallery-content" data-agent={selectedAgentId || ''}>{chat.instanceId}</div>,
}));

vi.mock('./ChatPage', () => ({
  default: ({ chat }: { chat: { instanceId: number } }) => <div data-testid="chat-content">{chat.instanceId}</div>,
}));

vi.mock('./KaiAssistantDrawer', () => ({
  default: ({ sidebarCollapsed }: { sidebarCollapsed: boolean }) => (
    <div data-kai-assistant-host="true" data-sidebar-collapsed={String(sidebarCollapsed)} />
  ),
}));

vi.mock('@/features/marketplace/MarketplaceWorkspacePage', () => ({
  default: () => <div data-testid="marketplace-content" />,
  isMarketplaceWorkspacePath: (path: string) => path.startsWith('/enterprise/orders'),
  selectedMarketplaceRoute: () => '/enterprise/orders',
}));

import ConversationWorkspaceShell from './ConversationWorkspaceShell';

function RouteDriver() {
  const navigate = useNavigate();
  return (
    <div>
      <button type="button" onClick={() => navigate('/enterprise/orders')}>open-market</button>
      <button type="button" onClick={() => navigate('/workspace/chat/session-route-contract')}>open-chat</button>
      <button type="button" onClick={() => navigate('/workspace/gallery')}>open-gallery</button>
      <button type="button" onClick={() => navigate('/workspace/projects/agents/agent-route-contract')}>open-agent-projects</button>
    </div>
  );
}

afterEach(() => {
  cleanup();
  chatInstanceInitializations = 0;
});

describe('conversation workspace shell', () => {
  it('keeps one chat session state and one sidebar while moving between project, market and chat content', () => {
    render(
      <MemoryRouter initialEntries={['/workspace/gallery']}>
        <ConversationWorkspaceShell />
        <RouteDriver />
      </MemoryRouter>,
    );

    expect(screen.getAllByTestId('shared-sidebar')).toHaveLength(1);
    expect(screen.getAllByTestId('shared-dialogs')).toHaveLength(1);
    expect(screen.getByTestId('gallery-content').textContent).toBe('1');

    fireEvent.click(screen.getByRole('button', { name: 'open-market' }));
    expect(screen.getByTestId('marketplace-content')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'open-chat' }));
    expect(screen.getByTestId('chat-content').textContent).toBe('1');

    fireEvent.click(screen.getByRole('button', { name: 'open-gallery' }));
    expect(screen.getByTestId('gallery-content').textContent).toBe('1');

    fireEvent.click(screen.getByRole('button', { name: 'open-agent-projects' }));
    expect(screen.getByTestId('gallery-content').getAttribute('data-agent')).toBe('agent-route-contract');
    expect(screen.getByTestId('shared-sidebar').getAttribute('data-gallery')).toBe('true');
    expect(chatInstanceInitializations).toBe(1);
  });

  it('mounts Kai Xiaohua once in the shared route-neutral shell', () => {
    render(
      <MemoryRouter initialEntries={['/enterprise/orders']}>
        <ConversationWorkspaceShell />
      </MemoryRouter>,
    );

    expect(document.querySelector('[data-kai-assistant-host="true"]')).toBeTruthy();
  });
});
