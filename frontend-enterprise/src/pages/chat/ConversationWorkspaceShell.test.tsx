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
  default: ({ chat }: { chat: { instanceId: number } }) => <div data-testid="gallery-content">{chat.instanceId}</div>,
}));

vi.mock('./ChatPage', () => ({
  default: ({ chat }: { chat: { instanceId: number } }) => <div data-testid="chat-content">{chat.instanceId}</div>,
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
    expect(chatInstanceInitializations).toBe(1);
  });

  it('reserves a route-neutral mount point for the later Kai Xiaohua drawer', () => {
    render(
      <MemoryRouter initialEntries={['/enterprise/orders']}>
        <ConversationWorkspaceShell />
      </MemoryRouter>,
    );

    expect(document.querySelector('[data-kai-assistant-host="true"]')).toBeTruthy();
  });
});
