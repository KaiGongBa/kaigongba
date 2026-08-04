import {
  Bell,
  Bot,
  BriefcaseBusiness,
  CheckCheck,
  ClipboardList,
  ExternalLink,
  FileText,
  HelpCircle,
  Inbox,
  LoaderCircle,
  MessageCircle,
  Send,
  Sparkles,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import { TENANT_ID, api } from '@/api/client';
import kaiXiaohuaImage from '@/assets/brand/kai-xiaohua.png';
import { getEnterpriseAuthSession } from '@/auth';
import { isPlatformAssistantAgent } from '@/employee';
import { marketplaceRepository } from '@/features/marketplace/repository';
import type { CollaborationNotification, CollaborationNotificationList } from '@/features/marketplace/types';
import { nextKaiAssistantState, type KaiAssistantView } from '@/features/marketplace/uiMigrationContracts';
import type { AgentProfileRead, ChatMessage, ChatSession, ChatTurnResponse } from '@/types';

import './kaiAssistantDrawer.css';

type NotificationFilter = 'all' | 'todos' | 'progress' | 'system';

export default function KaiAssistantDrawer({
  sidebarCollapsed,
  onToggleSidebar,
}: {
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}) {
  const navigate = useNavigate();
  const [state, setState] = useState({ open: false, view: 'chat' as KaiAssistantView });
  const [notifications, setNotifications] = useState<CollaborationNotificationList>({ items: [], unreadCount: 0 });
  const [notificationsLoading, setNotificationsLoading] = useState(false);
  const [notificationFilter, setNotificationFilter] = useState<NotificationFilter>('all');
  const [assistant, setAssistant] = useState<AgentProfileRead | null>(null);
  const [assistantSessionId, setAssistantSessionId] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState('');
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const restoreExpandedSidebarRef = useRef(false);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);
  const user = getEnterpriseAuthSession()?.user;

  const loadNotifications = useCallback(async () => {
    setNotificationsLoading(true);
    try {
      const result = await marketplaceRepository.listCollaborationNotifications();
      setNotifications(result);
    } catch {
      setNotifications({ items: [], unreadCount: 0 });
    } finally {
      setNotificationsLoading(false);
    }
  }, []);

  const loadAssistantSession = useCallback(async () => {
    setChatLoading(true);
    setChatError('');
    try {
      const [agents, sessions] = await Promise.all([
        api.get<AgentProfileRead[]>(`/api/chat/agents?tenant_id=${encodeURIComponent(TENANT_ID)}`),
        api.get<ChatSession[]>(`/api/chat/sessions?tenant_id=${encodeURIComponent(TENANT_ID)}`),
      ]);
      const platformAssistant = agents.find(isPlatformAssistantAgent) || null;
      if (!platformAssistant) {
        setAssistant(null);
        setMessages([]);
        setChatError('平台总助尚未完成配置，请联系系统管理员。');
        return;
      }
      setAssistant(platformAssistant);
      const session = sessions
        .filter((item) => item.agent_id === platformAssistant.id)
        .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))[0];
      if (!session) {
        setAssistantSessionId('');
        setMessages([]);
        return;
      }
      setAssistantSessionId(session.id);
      const rows = await api.get<ChatMessage[]>(
        `/api/chat/sessions/${encodeURIComponent(session.id)}/messages?tenant_id=${encodeURIComponent(TENANT_ID)}`,
      );
      setMessages(rows.filter((item) => item.role === 'user' || item.role === 'assistant'));
    } catch (error) {
      setChatError(error instanceof Error ? error.message : '开小花会话加载失败');
    } finally {
      setChatLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadNotifications();
  }, [loadNotifications]);

  useEffect(() => {
    if (!state.open) return;
    void loadAssistantSession();
  }, [loadAssistantSession, state.open]);

  useEffect(() => {
    if (state.open) {
      closeRef.current?.focus();
      const closeOnEscape = (event: globalThis.KeyboardEvent) => {
        if (event.key !== 'Escape') return;
        event.preventDefault();
        closeDrawer();
      };
      window.addEventListener('keydown', closeOnEscape);
      return () => window.removeEventListener('keydown', closeOnEscape);
    }
    if (wasOpenRef.current) {
      launcherRef.current?.focus();
    }
    wasOpenRef.current = state.open;
    return undefined;
  // closeDrawer intentionally reads the latest controlled sidebar prop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.open]);

  function openDrawer(view: KaiAssistantView = 'chat') {
    if (!state.open) {
      restoreExpandedSidebarRef.current = !sidebarCollapsed;
      if (!sidebarCollapsed) onToggleSidebar();
    }
    wasOpenRef.current = true;
    setState((current) => nextKaiAssistantState(current, { type: 'open', view }));
  }

  function closeDrawer() {
    if (restoreExpandedSidebarRef.current && sidebarCollapsed) onToggleSidebar();
    restoreExpandedSidebarRef.current = false;
    setState((current) => nextKaiAssistantState(current, { type: 'close' }));
  }

  async function sendMessage() {
    const message = draft.trim();
    if (!message || !assistant || sending) return;
    const now = new Date().toISOString();
    setDraft('');
    setChatError('');
    setMessages((current) => [...current, {
      id: `local-user-${crypto.randomUUID()}`,
      role: 'user',
      content: message,
      created_at: now,
    }]);
    setSending(true);
    try {
      const result = await api.post<ChatTurnResponse>('/api/chat/turn', {
        tenant_id: TENANT_ID,
        session_id: assistantSessionId || undefined,
        agent_id: assistant.id,
        client_turn_id: crypto.randomUUID(),
        message,
        interaction_mode: 'normal',
      });
      setAssistantSessionId(result.session_id);
      setMessages((current) => [...current, {
        id: `local-assistant-${crypto.randomUUID()}`,
        role: 'assistant',
        content: result.reply,
        created_at: new Date().toISOString(),
      }]);
    } catch (error) {
      setChatError(error instanceof Error ? error.message : '消息发送失败');
    } finally {
      setSending(false);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void sendMessage();
  }

  async function openNotification(item: CollaborationNotification) {
    try {
      if (item.status === 'unread') {
        await marketplaceRepository.markCollaborationNotificationsRead([item.id]);
        setNotifications((current) => ({
          unreadCount: Math.max(0, current.unreadCount - 1),
          items: current.items.map((entry) => (
            entry.id === item.id ? { ...entry, status: 'read' } : entry
          )),
        }));
      }
      if (safeAssistantRoute(item.route)) navigate(item.route);
    } catch {
      // Keep the real notification visible so the user can retry.
    }
  }

  async function markAllNotificationsRead() {
    try {
      const result = await marketplaceRepository.markCollaborationNotificationsRead([], true);
      setNotifications(result);
    } catch {
      // Keep the current unread state when the server rejects the update.
    }
  }

  return (
    <>
      {!state.open && (
        <button
          ref={launcherRef}
          type="button"
          className="kai-assistant-launcher"
          aria-label={`打开开小花${notifications.unreadCount ? `，${notifications.unreadCount} 条未读` : ''}`}
          onClick={() => openDrawer('chat')}
          onKeyDown={(event) => activateButtonWithKeyboard(event, () => openDrawer('chat'))}
        >
          <span>有事问开小花</span>
          <img src={kaiXiaohuaImage} alt="" />
          {notifications.unreadCount > 0 && <b>{Math.min(99, notifications.unreadCount)}</b>}
        </button>
      )}

      {state.open && (
        <aside className="kai-assistant-drawer" role="complementary" aria-label="开小花平台总助">
          <header className="kai-assistant-header">
            <span className="kai-assistant-avatar"><img src={kaiXiaohuaImage} alt="开小花" /></span>
            <span className="kai-assistant-title">
              <strong>开小花</strong>
              <small>平台总助在线 · 独立会话</small>
            </span>
            <button ref={closeRef} type="button" aria-label="关闭开小花" onClick={closeDrawer}><X /></button>
          </header>

          <nav className="kai-assistant-tabs" role="tablist" aria-label="开小花功能">
            <DrawerTab active={state.view === 'chat'} icon={<MessageCircle />} onClick={() => setState((current) => nextKaiAssistantState(current, { type: 'select-view', view: 'chat' }))}>对话</DrawerTab>
            <DrawerTab active={state.view === 'notifications'} icon={<Bell />} onClick={() => setState((current) => nextKaiAssistantState(current, { type: 'select-view', view: 'notifications' }))}>
              通知{notifications.unreadCount > 0 ? ` ${notifications.unreadCount}` : ''}
            </DrawerTab>
            <DrawerTab active={state.view === 'help'} icon={<HelpCircle />} onClick={() => setState((current) => nextKaiAssistantState(current, { type: 'select-view', view: 'help' }))}>使用帮助</DrawerTab>
          </nav>

          {state.view === 'chat' && (
            <section className="kai-assistant-panel kai-assistant-chat" role="tabpanel" aria-label="开小花对话">
              <div className="kai-assistant-scroll">
                <div className="kai-assistant-intro">
                  <Sparkles />
                  <div><h2>{greeting(user?.display_name || user?.username)}</h2><p>我可以帮你找项目、查待办和解释平台功能，但不会进入数字员工私有会话或替你完成结构化确认。</p></div>
                </div>
                {chatLoading && <div className="kai-assistant-empty"><LoaderCircle className="is-spinning" />正在读取独立会话…</div>}
                {!chatLoading && messages.length === 0 && !chatError && (
                  <div className="kai-assistant-empty"><Bot /><strong>从一个问题开始</strong><span>例如：我的订单在哪里？如何发布服务？</span></div>
                )}
                <div className="kai-assistant-messages" aria-live="polite">
                  {messages.map((message) => (
                    <article key={message.id} className={message.role === 'user' ? 'is-user' : 'is-assistant'}>
                      <small>{message.role === 'user' ? '你' : '开小花'} · {formatTime(message.created_at)}</small>
                      <p>{message.content}</p>
                    </article>
                  ))}
                  {sending && <article className="is-assistant"><small>开小花 · 正在回复</small><p className="kai-assistant-thinking"><i /><i /><i /></p></article>}
                </div>
                {chatError && <p className="kai-assistant-error" role="alert">{chatError}</p>}
              </div>
              <form className="kai-assistant-composer" onSubmit={(event) => { event.preventDefault(); void sendMessage(); }}>
                <textarea
                  value={draft}
                  aria-label="给开小花发送消息"
                  placeholder="问开小花关于项目、订单或平台的问题"
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={handleComposerKeyDown}
                />
                <footer><span>不读取乙方提示词、内部知识库和员工私聊</span><button type="submit" disabled={!draft.trim() || !assistant || sending} aria-label="发送给开小花"><Send /></button></footer>
              </form>
            </section>
          )}

          {state.view === 'notifications' && (
            <NotificationPanel
              filter={notificationFilter}
              onFilterChange={setNotificationFilter}
              notifications={notifications}
              loading={notificationsLoading}
              onOpen={(item) => void openNotification(item)}
              onMarkAllRead={() => void markAllNotificationsRead()}
            />
          )}

          {state.view === 'help' && <HelpPanel onNavigate={navigate} />}
        </aside>
      )}
    </>
  );
}

function DrawerTab({ active, icon, children, onClick }: { active: boolean; icon: ReactNode; children: ReactNode; onClick: () => void }) {
  return <button type="button" role="tab" aria-selected={active} className={active ? 'is-active' : ''} onClick={onClick} onKeyDown={(event) => activateButtonWithKeyboard(event, onClick)}>{icon}{children}</button>;
}

function activateButtonWithKeyboard(event: KeyboardEvent<HTMLButtonElement>, action: () => void) {
  if (event.key !== 'Enter' && event.key !== ' ' && event.key !== 'Spacebar') return;
  event.preventDefault();
  action();
}

function NotificationPanel({
  filter,
  onFilterChange,
  notifications,
  loading,
  onOpen,
  onMarkAllRead,
}: {
  filter: NotificationFilter;
  onFilterChange: (filter: NotificationFilter) => void;
  notifications: CollaborationNotificationList;
  loading: boolean;
  onOpen: (item: CollaborationNotification) => void;
  onMarkAllRead: () => void;
}) {
  const counts = useMemo(() => ({
    all: notifications.items.length,
    todos: notifications.items.filter((item) => notificationCategory(item) === 'todos').length,
    progress: notifications.items.filter((item) => notificationCategory(item) === 'progress').length,
    system: notifications.items.filter((item) => notificationCategory(item) === 'system').length,
  }), [notifications.items]);
  const visible = notifications.items.filter((item) => (
    filter === 'all' || notificationCategory(item) === filter
  ));
  return (
    <section className="kai-assistant-panel kai-assistant-notifications" role="tabpanel" aria-label="开小花通知">
      <header>
        <div className="kai-notification-filters" role="tablist" aria-label="通知分类">
          {(['all', 'todos', 'progress', 'system'] as const).map((value) => (
            <button key={value} type="button" role="tab" aria-selected={filter === value} className={filter === value ? 'is-active' : ''} onClick={() => onFilterChange(value)}>
              {notificationFilterLabel(value)} {counts[value]}
            </button>
          ))}
        </div>
        {notifications.unreadCount > 0 && <button type="button" className="kai-mark-read" onClick={onMarkAllRead}><CheckCheck />全部已读</button>}
      </header>
      <div className="kai-assistant-scroll">
        {loading && <div className="kai-assistant-empty"><LoaderCircle className="is-spinning" />正在读取通知…</div>}
        {!loading && visible.length === 0 && <div className="kai-assistant-empty"><Inbox /><strong>当前分类没有通知</strong></div>}
        <div className="kai-notification-list">
          {visible.map((item) => (
            <button key={item.id} type="button" className={item.status === 'unread' ? 'is-unread' : ''} onClick={() => onOpen(item)}>
              <i className={`is-${item.riskLevel}`} />
              <span><strong>{item.title}</strong><em>{item.body}</em><small>{formatDateTime(item.createdAt)}{item.orderId ? ` · ${item.orderId}` : ''}</small></span>
              <ExternalLink />
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

function HelpPanel({ onNavigate }: { onNavigate: (route: string) => void }) {
  const items = [
    { title: '查看 AI 员工和项目进度', description: '在项目中心按员工或项目查看', route: '/workspace/gallery?view=agents', icon: <Bot /> },
    { title: '发布需求并比较报价', description: '进入真实需求、匹配和报价流程', route: '/enterprise/demands', icon: <FileText /> },
    { title: '查找订单、支付与交付', description: '查看采购或服务关系下的订单', route: '/enterprise/orders', icon: <ClipboardList /> },
    { title: '发布和经营 AI 服务', description: '管理发布、报价和服务交付', route: '/enterprise/publishing', icon: <BriefcaseBusiness /> },
    { title: '接入外部 Agent', description: '配置长期 API 连接与运行边界', route: '/enterprise/agents/external/connect', icon: <ExternalLink /> },
  ];
  return (
    <section className="kai-assistant-panel kai-assistant-help" role="tabpanel" aria-label="开小花使用帮助">
      <div className="kai-assistant-scroll">
        <div className="kai-assistant-intro"><HelpCircle /><div><h2>你想完成什么？</h2><p>开小花只做导航、解释和待办协助；交易确认仍需在对应业务页面由有权用户完成。</p></div></div>
        <div className="kai-help-list">
          {items.map((item) => <button type="button" key={item.route} onClick={() => onNavigate(item.route)}><i>{item.icon}</i><span><strong>{item.title}</strong><small>{item.description}</small></span><ExternalLink /></button>)}
        </div>
      </div>
    </section>
  );
}

function notificationCategory(item: CollaborationNotification): Exclude<NotificationFilter, 'all'> {
  const type = item.notificationType.toLowerCase();
  if (item.route.startsWith('/enterprise/accounts') || type.includes('system') || type.includes('account')) return 'system';
  if (type.includes('milestone') || type.includes('execution') || type.includes('delivery') || type.includes('progress')) return 'progress';
  return 'todos';
}

function notificationFilterLabel(filter: NotificationFilter) {
  return { all: '全部', todos: '待办', progress: '项目进展', system: '系统通知' }[filter];
}

function safeAssistantRoute(route: string) {
  return route.startsWith('/enterprise/') || route.startsWith('/workspace/');
}

function greeting(name?: string) {
  const hour = new Date().getHours();
  const prefix = hour < 12 ? '上午好' : hour < 18 ? '下午好' : '晚上好';
  return `${prefix}${name ? `，${name}` : ''}`;
}

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '--:--' : new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(date);
}

function formatDateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '时间未知' : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
}
