import type { CSSProperties } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import AppSidebar from '@/components/AppSidebar';
import { SidebarProvider } from '@/components/ui/sidebar';
import MarketplaceWorkspacePage, {
  isMarketplaceWorkspacePath,
  selectedMarketplaceRoute,
} from '@/features/marketplace/MarketplaceWorkspacePage';

import ChatDialogs from './components/ChatDialogs';
import ChatGalleryPage from './ChatGalleryPage';
import { sessionHasUnreadReply } from './chatHelpers';
import ChatPage from './ChatPage';
import { useChatSession } from './useChatSession';

function chatRouteParameters(pathname: string) {
  const draftMatch = pathname.match(/^\/workspace\/chat\/draft\/([^/]+)$/);
  if (draftMatch) return { draftAgentId: decodeURIComponent(draftMatch[1]) };
  const sessionMatch = pathname.match(/^\/workspace\/chat\/([^/]+)$/);
  if (sessionMatch) return { sessionId: decodeURIComponent(sessionMatch[1]) };
  return {};
}

export default function ConversationWorkspaceShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const routeParameters = chatRouteParameters(location.pathname);
  const chat = useChatSession(routeParameters);
  const marketplaceActive = isMarketplaceWorkspacePath(location.pathname);
  const galleryActive = location.pathname === '/workspace/gallery';
  const chatActive = location.pathname.startsWith('/workspace/chat');

  return (
    <SidebarProvider
      open={!chat.sidebarCollapsed}
      onOpenChange={(open) => {
        if (open === chat.sidebarCollapsed) chat.toggleSidebar();
      }}
      style={
        {
          '--sidebar-width': '220px',
          '--sidebar-width-icon': '72px',
        } as CSSProperties
      }
      className="h-screen min-h-0 bg-[#fcfcfc] text-[#18181a]"
    >
      <AppSidebar
        variant="chat"
        sessions={chat.visibleSidebarSessions}
        sessionsLoading={chat.sessionsLoading}
        agents={chat.agents}
        activeSessionId={chat.sessionId}
        sessionFilter={chat.sessionAgentFilter}
        onSessionFilterChange={chat.setSessionAgentFilter}
        sessionFilterOptions={chat.sessionFilterOptions}
        isSessionUnread={(session) => sessionHasUnreadReply(
          session,
          chat.sessionReadTimes,
          chat.sessionId,
        )}
        onOpenSession={chat.openSession}
        onNewConversation={chatActive ? () => {
          const selectedAgent = chat.sessionAgentFilter === 'all'
            ? chat.displayedAgent
            : chat.agents.find((agent) => agent.id === chat.sessionAgentFilter);
          if (selectedAgent) chat.openDraftForAgent(selectedAgent.id);
          else chat.openGallery();
        } : undefined}
        onOpenGallery={chat.openGallery}
        galleryActive={galleryActive}
        marketplaceSelected={marketplaceActive ? selectedMarketplaceRoute(location.pathname) : undefined}
        onMarketplaceNavigate={navigate}
        handoffCount={chat.handoffs.length}
        onOpenHandoffs={chat.openHandoffInbox}
        onRenameSession={chat.openRename}
        onDeleteSession={chat.requestDelete}
        onOpenAdmin={chat.openAdmin}
      />

      {marketplaceActive ? (
        <MarketplaceWorkspacePage />
      ) : chatActive ? (
        <ChatPage chat={chat} />
      ) : (
        <ChatGalleryPage chat={chat} />
      )}

      <div data-kai-assistant-host="true" aria-hidden="true" />
      <ChatDialogs chat={chat} />
    </SidebarProvider>
  );
}
