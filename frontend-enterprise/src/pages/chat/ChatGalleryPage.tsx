import { api, TENANT_ID } from '@/api/client';
import { notify } from '@/components/ui/app-toast';
import { getEnterpriseAuthSession, isEnterpriseAdmin } from '@/auth';
import type { AgentProfileRead } from '@/types';

import EmployeeGalleryPage from '../EmployeeGalleryPage';
import type { UseChatSession } from './useChatSession';

export default function ChatGalleryPage({ chat }: { chat: UseChatSession }) {
  const auth = getEnterpriseAuthSession();
  const isAdmin = isEnterpriseAdmin(auth?.user);

  async function startGalleryChat(agent: AgentProfileRead) {
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
    <main className="min-h-0 flex-1 overflow-y-auto">
      <EmployeeGalleryPage
        currentUser={auth?.user}
        isAdmin={isAdmin}
        onStartChat={startGalleryChat}
        onLogout={chat.logout}
      />
    </main>
  );
}
