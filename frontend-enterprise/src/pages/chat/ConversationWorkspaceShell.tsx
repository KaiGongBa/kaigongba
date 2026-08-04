import { useEffect, useRef, type CSSProperties } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import AppSidebar from '@/components/AppSidebar';
import { SidebarProvider } from '@/components/ui/sidebar';
import { useIsMobile } from '@/hooks/use-mobile';
import MarketplaceWorkspacePage, {
  isMarketplaceWorkspacePath,
  selectedMarketplaceRoute,
} from '@/features/marketplace/MarketplaceWorkspacePage';

import ChatDialogs from './components/ChatDialogs';
import ChatGalleryPage from './ChatGalleryPage';
import KaiAssistantDrawer from './KaiAssistantDrawer';
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

function projectAgentId(pathname: string) {
  const match = pathname.match(/^\/workspace\/projects\/agents\/([^/]+)$/);
  return match ? decodeURIComponent(match[1]) : undefined;
}

export default function ConversationWorkspaceShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const routeParameters = chatRouteParameters(location.pathname);
  const chat = useChatSession(routeParameters);
  const isMobile = useIsMobile();
  const restoreExpandedSidebarRef = useRef(false);
  const marketplaceActive = isMarketplaceWorkspacePath(location.pathname);
  const selectedProjectAgentId = projectAgentId(location.pathname);
  const galleryActive = location.pathname === '/workspace/gallery' || Boolean(selectedProjectAgentId);
  const chatActive = location.pathname.startsWith('/workspace/chat');

  useEffect(() => {
    if (isMobile) {
      if (!chat.sidebarCollapsed && !restoreExpandedSidebarRef.current) {
        restoreExpandedSidebarRef.current = true;
        chat.toggleSidebar();
      }
      return;
    }
    if (restoreExpandedSidebarRef.current) {
      if (chat.sidebarCollapsed) chat.toggleSidebar();
      restoreExpandedSidebarRef.current = false;
    }
  }, [chat.sidebarCollapsed, chat.toggleSidebar, isMobile]);

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
        <ChatGalleryPage chat={chat} selectedAgentId={selectedProjectAgentId} />
      )}

      <KaiAssistantDrawer
        sidebarCollapsed={chat.sidebarCollapsed}
        onToggleSidebar={chat.toggleSidebar}
      />
      <ChatDialogs chat={chat} />
    </SidebarProvider>
  );
}
