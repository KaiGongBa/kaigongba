import { api, TENANT_ID } from '@/api/client';
import { notify } from '@/components/ui/app-toast';
import type { AgentProfileRead } from '@/types';

import ProjectCenterPage from './ProjectCenterPage';
import type { UseChatSession } from './useChatSession';

export default function ChatGalleryPage({
  chat,
  selectedAgentId,
}: {
  chat: UseChatSession;
  selectedAgentId?: string;
}) {
  async function startProjectEmployeeChat(agent: AgentProfileRead) {
    try {
      await api.post<AgentProfileRead>(`/api/chat/agents/${agent.id}/use?tenant_id=${TENANT_ID}`, {});
      await chat.refreshAgents(agent.id);
      chat.setSessionAgentFilter(agent.id);
      chat.openDraftForAgent(agent.id);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '无法打开数字员工');
    }
  }

  return (
    <ProjectCenterPage
      agents={chat.agents}
      selectedAgentId={selectedAgentId}
      onOpenChat={startProjectEmployeeChat}
    />
  );
}
