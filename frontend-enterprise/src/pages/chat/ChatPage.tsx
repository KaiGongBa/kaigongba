import { cn } from '@/lib/utils';

import { CHAT_MAIN_CLASS } from './chatPageStyles';
import type { UseChatSession } from './useChatSession';
import ChatHeader from './components/ChatHeader';
import MessageList from './components/MessageList';
import Composer from './components/Composer';

export default function ChatPage({ chat }: { chat: UseChatSession }) {
  return (
    <main className={cn(CHAT_MAIN_CLASS, 'flex-1')}>
      <ChatHeader chat={chat} />
      <MessageList chat={chat} />
      <Composer chat={chat} />
    </main>
  );
}
