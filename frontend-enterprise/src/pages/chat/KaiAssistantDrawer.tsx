import {
  AlertTriangle,
  Bell,
  Bot,
  CheckCheck,
  ExternalLink,
  HelpCircle,
  Inbox,
  LoaderCircle,
  MessageCircle,
  PauseCircle,
  RotateCcw,
  Send,
  Sparkles,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { TENANT_ID, api } from '@/api/client';
import kaiXiaohuaImage from '@/assets/brand/kai-xiaohua.png';
import { getEnterpriseAuthSession } from '@/auth';
import { isPlatformAssistantAgent } from '@/employee';
import { AssistantHelpPanel } from '@/features/kai-assistant/components/AssistantHelpPanel';
import {
  createDefaultKaiAssistantService,
  normalizeAssistantResult,
  parseAssistantError,
  type AssistantTurnResult,
  type KaiAssistantService,
} from '@/features/kai-assistant/components/assistantService';
import {
  StructuredBlockRenderer,
  type StructuredBlockAction,
} from '@/features/kai-assistant/components/StructuredBlockRenderer';
import { collectAssistantOverlayPageContext, createPageInstanceId } from '@/features/kai-assistant/pageContext';
import { OPEN_KAI_ASSISTANT_EVENT, type OpenKaiAssistantDetail } from '@/features/kai-assistant/assistantEvents';
import { buildSafePlatformAssistantUrl } from '@/features/kai-assistant/routeRegistry';
import type {
  AnswerSubmission,
  PlatformAssistantErrorEnvelope,
  PlatformAssistantV2StructuredBlock,
  PlatformAssistantWorkflow,
  StructuredBlock,
} from '@/features/kai-assistant/protocol';
import { marketplaceRepository } from '@/features/marketplace/repository';
import type { CollaborationNotification, CollaborationNotificationList } from '@/features/marketplace/types';
import { nextKaiAssistantState, type KaiAssistantView } from '@/features/marketplace/uiMigrationContracts';
import type { AgentProfileRead, ChatMessage, ChatSession } from '@/types';

import './kaiAssistantDrawer.css';

type NotificationFilter = 'all' | 'todos' | 'progress' | 'system';

type AssistantUiMessage = Pick<ChatMessage, 'id' | 'role' | 'content' | 'created_at'> & {
  blocks?: PlatformAssistantV2StructuredBlock[];
  runId?: string | null;
  workflow?: PlatformAssistantWorkflow | null;
};

type AssistantFailure = PlatformAssistantErrorEnvelope['error'];

export default function KaiAssistantDrawer({
  sidebarCollapsed,
  onToggleSidebar,
  service,
}: {
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  service?: KaiAssistantService;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const assistantService = useMemo(() => service || createDefaultKaiAssistantService(), [service]);
  const [state, setState] = useState({ open: false, view: 'chat' as KaiAssistantView });
  const [notifications, setNotifications] = useState<CollaborationNotificationList>({ items: [], unreadCount: 0 });
  const [notificationsLoading, setNotificationsLoading] = useState(false);
  const [notificationFilter, setNotificationFilter] = useState<NotificationFilter>('all');
  const [assistant, setAssistant] = useState<AgentProfileRead | null>(null);
  const [assistantSessionId, setAssistantSessionId] = useState('');
  const [messages, setMessages] = useState<AssistantUiMessage[]>([]);
  const [supportPreparationMessage, setSupportPreparationMessage] = useState<AssistantUiMessage | null>(null);
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState<AssistantFailure | null>(null);
  const [draft, setDraft] = useState('');
  const [pendingLaunchPrompt, setPendingLaunchPrompt] = useState<{
    prompt: string;
    startNewWorkflow: boolean;
    entrypoint?: 'requirement.create';
    analysisRequestId?: string;
  } | null>(null);
  const [sending, setSending] = useState(false);
  const [completedBlocks, setCompletedBlocks] = useState<Set<string>>(() => new Set());
  const [activeWorkflow, setActiveWorkflow] = useState<{
    sessionId: string;
    runId: string;
    workflow: PlatformAssistantWorkflow | null;
  } | null>(null);
  const restoreExpandedSidebarRef = useRef(false);
  const launcherRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastUserMessageRef = useRef('');
  const routeKeyRef = useRef('');
  const pageInstanceIdRef = useRef(createPageInstanceId());
  const contextVersionRef = useRef(1);
  const answerAttemptsRef = useRef(new Map<string, {
    fingerprint: string;
    idempotencyKey: string;
    answers: AnswerSubmission['answers'];
  }>());
  const submittingBlocksRef = useRef(new Set<string>());
  const latestRequirementAnalysisIdRef = useRef('');
  const launchInProgressRef = useRef(false);
  const pendingLaunchPromptRef = useRef<typeof pendingLaunchPrompt>(null);
  const user = getEnterpriseAuthSession()?.user;

  useEffect(() => {
    const routeKey = `${location.pathname}${location.search}`;
    if (!routeKeyRef.current) {
      routeKeyRef.current = routeKey;
      return;
    }
    if (routeKeyRef.current === routeKey) return;
    routeKeyRef.current = routeKey;
    pageInstanceIdRef.current = createPageInstanceId();
    contextVersionRef.current = 1;
  }, [location.pathname, location.search]);

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
    setChatError(null);
    try {
      const [agents, sessions] = await Promise.all([
        api.get<AgentProfileRead[]>(`/api/chat/agents?tenant_id=${encodeURIComponent(TENANT_ID)}`),
        api.get<ChatSession[]>(`/api/chat/sessions?tenant_id=${encodeURIComponent(TENANT_ID)}`),
      ]);
      const platformAssistant = agents.find(isPlatformAssistantAgent) || null;
      if (!platformAssistant) {
        setAssistant(null);
        setMessages([]);
        setChatError({ code: 'AI_UNAVAILABLE', message: '平台总助尚未完成配置，请联系系统管理员。', retryable: true });
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
      const restoredMessages: AssistantUiMessage[] = rows.filter((item) => item.role === 'user' || item.role === 'assistant').map((item) => ({
        id: item.id,
        role: item.role,
        content: item.content,
        created_at: item.created_at,
      }));
      try {
        const snapshot = await api.get<unknown>(
          `/api/platform-assistant/runs/latest?session_id=${encodeURIComponent(session.id)}&protocol_version=2.0`,
        );
        const restored = normalizeAssistantResult(snapshot, {
          sessionId: session.id,
          assistantText: '已恢复上次未完成的结构化流程。',
        });
        restoredMessages.push({
          id: `restored-${restored.messageId}`,
          role: 'assistant',
          content: restored.assistantText,
          created_at: new Date().toISOString(),
          blocks: restored.blocks,
          runId: restored.runId,
          workflow: restored.workflow,
        });
        if (restored.runId && !isTerminalAssistantResult(restored)) {
          setActiveWorkflow({
            sessionId: restored.sessionId,
            runId: restored.runId,
            workflow: restored.workflow,
          });
        } else if (isTerminalAssistantResult(restored)) {
          setActiveWorkflow(null);
        }
      } catch {
        // A platform-assistant session may legitimately have no active run.
      }
      setMessages(restoredMessages);
    } catch (error) {
      setChatError(parseAssistantError(error));
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

  useEffect(() => {
    const handleOpenRequest = (event: Event) => {
      const detail = (event as CustomEvent<OpenKaiAssistantDetail>).detail || {};
      openDrawer(detail.view || 'chat');
      if (detail.prompt?.trim()) {
        const prompt = detail.prompt.trim();
        if (detail.entrypoint === 'requirement.create' && detail.analysisRequestId) {
          latestRequirementAnalysisIdRef.current = detail.analysisRequestId;
        }
        setDraft(prompt);
        if (detail.autoSend) {
          const launch = {
            prompt,
            startNewWorkflow: Boolean(detail.startNewWorkflow),
            entrypoint: detail.entrypoint,
            analysisRequestId: detail.analysisRequestId,
          };
          pendingLaunchPromptRef.current = launch;
          setPendingLaunchPrompt(launch);
        }
        else requestAnimationFrame(() => composerRef.current?.focus());
      }
    };
    window.addEventListener(OPEN_KAI_ASSISTANT_EVENT, handleOpenRequest);
    return () => window.removeEventListener(OPEN_KAI_ASSISTANT_EVENT, handleOpenRequest);
  // The listener is refreshed whenever the controlled shell state changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sidebarCollapsed, state.open]);

  useEffect(() => {
    if (
      !state.open
      || !assistant
      || chatLoading
      || sending
      || !pendingLaunchPrompt
      || launchInProgressRef.current
    ) return;
    const launch = pendingLaunchPromptRef.current || pendingLaunchPrompt;
    launchInProgressRef.current = true;
    pendingLaunchPromptRef.current = null;
    setPendingLaunchPrompt(null);
    void (async () => {
      try {
        if (launch.startNewWorkflow && activeWorkflow) {
          setSending(true);
          setChatError(null);
          appendAssistantResult(await assistantService.cancelRun(
            activeWorkflow.sessionId,
            activeWorkflow.runId,
          ));
          setActiveWorkflow(null);
          setSending(false);
        }
        await sendMessage(launch.prompt, launch.entrypoint, launch.analysisRequestId);
      } catch (error) {
          setChatError(parseAssistantError(error));
      } finally {
        launchInProgressRef.current = false;
        setSending(false);
        // A newer launch may have arrived while this request was awaiting the
        // backend. Re-emit the ref-backed queue after releasing the guard.
        if (pendingLaunchPromptRef.current) {
          setPendingLaunchPrompt({ ...pendingLaunchPromptRef.current });
        }
      }
    })();
  // sendMessage intentionally consumes the latest assistant/session state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkflow, assistant, assistantService, chatLoading, pendingLaunchPrompt, sending, state.open]);

  async function sendMessage(
    value?: string,
    entrypoint?: 'requirement.create',
    analysisRequestId?: string,
  ) {
    const message = (value ?? draft).trim();
    if (!message || !assistant || sending) return;
    const now = new Date().toISOString();
    setDraft('');
    lastUserMessageRef.current = message;
    setChatError(null);
    setMessages((current) => [...current, {
      id: `local-user-${crypto.randomUUID()}`,
      role: 'user',
      content: message,
      created_at: now,
    }]);
    setSending(true);
    try {
      const pageContext = collectAssistantOverlayPageContext(location, 'assistant.chat', {
        pageInstanceId: pageInstanceIdRef.current,
        organizationId: selectedOrganizationId(),
        contextVersion: contextVersionRef.current,
      });
      const result = await assistantService.sendTurn({
        pageContext,
        sessionId: assistantSessionId || null,
        agentId: assistant.id,
        message,
        entrypoint,
        clientRequestId: analysisRequestId,
      });
      appendAssistantResult(result, { analysisRequestId });
    } catch (error) {
      setChatError(parseAssistantError(error));
    } finally {
      setSending(false);
    }
  }

  function appendAssistantResult(
    result: AssistantTurnResult,
    options: { analysisRequestId?: string } = {},
  ) {
    setAssistantSessionId(result.sessionId);
    const messageId = result.messageId || `local-assistant-${crypto.randomUUID()}`;
    const nextMessage: AssistantUiMessage = {
      id: messageId,
      role: 'assistant',
      content: result.assistantText,
      created_at: new Date().toISOString(),
      blocks: result.blocks,
      runId: result.runId,
      workflow: result.workflow,
    };
    setMessages((current) => {
      const existingIndex = current.findIndex((message) => message.id === messageId);
      if (existingIndex < 0) return [...current, nextMessage];
      return current.map((message, index) => (index === existingIndex ? nextMessage : message));
    });
    const staleRequirementAnalysis = Boolean(
      options.analysisRequestId
      && latestRequirementAnalysisIdRef.current
      && options.analysisRequestId !== latestRequirementAnalysisIdRef.current,
    );
    if (!staleRequirementAnalysis) {
      if (isTerminalAssistantResult(result)) {
        setActiveWorkflow(null);
      } else if (result.runId) {
        setActiveWorkflow({ sessionId: result.sessionId, runId: result.runId, workflow: result.workflow });
      }
    }
    const requirementLink = result.blocks.find((block) => (
      block.type === 'deep_link'
      && block.route_id === 'enterprise.requirement.create'
    ));
    if (!staleRequirementAnalysis && location.pathname === '/enterprise/demands/new' && requirementLink?.type === 'deep_link') {
      const url = buildSafePlatformAssistantUrl(requirementLink.route_id, requirementLink.route_params);
      if (url && `${location.pathname}${location.search}` !== url) {
        // The user started this workflow from the real requirement form. Keep
        // that page mounted and attach the generated draft immediately so its
        // non-empty fields are filled without another click or another form.
        navigate(url, { replace: true });
      }
    }
  }

  useEffect(() => {
    if (!state.open || state.view !== 'chat') return;
    const scroll = () => {
      const container = chatScrollRef.current;
      if (container) container.scrollTop = container.scrollHeight;
      messagesEndRef.current?.scrollIntoView?.({ block: 'end', behavior: 'auto' });
    };
    const frame = requestAnimationFrame(scroll);
    return () => cancelAnimationFrame(frame);
  }, [chatError, chatLoading, messages.length, sending, state.open, state.view, supportPreparationMessage]);

  async function submitStructuredAnswers(
    message: AssistantUiMessage,
    input: Pick<AnswerSubmission, 'block_id' | 'block_version' | 'answers'>,
  ) {
    const runId = message.runId || activeWorkflow?.runId;
    const sessionId = assistantSessionId || activeWorkflow?.sessionId;
    const submissionKey = runId
      ? blockKey(runId, input.block_id, input.block_version)
      : '';
    if (!runId || !sessionId) {
      setChatError({ code: 'CONTEXT_STALE', message: '这组问题已失去工作流上下文，请恢复或重新发起。', retryable: true });
      return;
    }
    if (sending || submittingBlocksRef.current.has(submissionKey)) {
      return;
    }
    const fingerprint = answerFingerprint(input.answers);
    const previousAttempt = answerAttemptsRef.current.get(submissionKey);
    const attempt = previousAttempt?.fingerprint === fingerprint
      ? previousAttempt
      : {
          fingerprint,
          idempotencyKey: crypto.randomUUID(),
          answers: input.answers,
        };
    answerAttemptsRef.current.set(submissionKey, attempt);
    submittingBlocksRef.current.add(submissionKey);
    setSending(true);
    setChatError(null);
    try {
      const submittedBlock = message.blocks?.find((block) => (
        block.block_id === input.block_id
        && block.block_version === input.block_version
      ));
      const result = await assistantService.submitAnswers({
        protocol_version: submittedBlock?.schema_version === '2.0' ? '2.0' : '1.0',
        session_id: sessionId,
        run_id: runId,
        block_id: input.block_id,
        block_version: input.block_version,
        idempotency_key: attempt.idempotencyKey,
        answers: attempt.answers,
      });
      setCompletedBlocks((current) => new Set(current).add(blockKey(runId, input.block_id, input.block_version)));
      answerAttemptsRef.current.delete(submissionKey);
      appendAssistantResult(result);
    } catch (error) {
      setChatError(parseAssistantError(error));
    } finally {
      submittingBlocksRef.current.delete(submissionKey);
      setSending(false);
    }
  }

  function handleStructuredAction(action: StructuredBlockAction) {
    if (action.actionId.startsWith('intent:')) {
      void sendMessage(`我选择：${action.label}`);
      return;
    }
    if (action.actionId.includes('resume')) {
      void resumeWorkflow();
      return;
    }
    if (action.actionId.includes('cancel')) {
      void cancelWorkflow();
      return;
    }
    if (action.actionId.includes('retry')) {
      void retryLastTurn();
      return;
    }
    // Potentially consequential actions are prepared in the composer instead
    // of being executed from an untrusted block label.
    setDraft(`我想要「${action.label}」，请先说明将要执行的操作，并让我在对应业务页确认。`);
    requestAnimationFrame(() => composerRef.current?.focus());
  }

  async function resumeWorkflow() {
    if (!activeWorkflow || sending) return;
    setSending(true);
    setChatError(null);
    try {
      appendAssistantResult(await assistantService.resumeRun(activeWorkflow.sessionId, activeWorkflow.runId));
    } catch (error) {
      setChatError(parseAssistantError(error));
    } finally {
      setSending(false);
    }
  }

  async function cancelWorkflow() {
    if (!activeWorkflow || sending) return;
    setSending(true);
    setChatError(null);
    try {
      appendAssistantResult(await assistantService.cancelRun(activeWorkflow.sessionId, activeWorkflow.runId));
      setActiveWorkflow(null);
    } catch (error) {
      setChatError(parseAssistantError(error));
    } finally {
      setSending(false);
    }
  }

  async function retryLastTurn() {
    if (lastUserMessageRef.current) await sendMessage(lastUserMessageRef.current);
    else await loadAssistantSession();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    void sendMessage();
  }

  function showHumanSupportPreparation() {
    setState((current) => nextKaiAssistantState(current, { type: 'select-view', view: 'chat' }));
    setSupportPreparationMessage({
      id: `local-support-${crypto.randomUUID()}`,
      role: 'assistant',
      content: '我先帮你准备联系人工客服所需的信息。',
      created_at: new Date().toISOString(),
      blocks: humanSupportPreparationBlocks(location.pathname),
      runId: null,
      workflow: null,
    });
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
        <aside className={`kai-assistant-drawer ${activeWorkflow ? 'is-workflow' : ''}`} role="complementary" aria-label="开小花平台总助">
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
              <div ref={chatScrollRef} className="kai-assistant-scroll">
                <div className="kai-assistant-intro">
                  <Sparkles />
                  <div><h2>{greeting(user?.display_name || user?.username)}</h2><p>我可以帮你找项目、查待办和解释平台功能，但不会进入数字员工私有会话或替你完成结构化确认。</p></div>
                </div>
                <div className="kai-context-pill" title={location.pathname}>
                  <span>正在辅助当前页面</span><strong>{currentPageLabel(location.pathname)}</strong>
                </div>
                <div className="kai-quick-questions" aria-label="快捷提问">
                  {['我现在可以做什么？', '我的待办', '当前页面说明'].map((prompt) => (
                    <button key={prompt} type="button" disabled={!assistant || sending} onClick={() => void sendMessage(prompt)}>{prompt}</button>
                  ))}
                </div>
                {activeWorkflow && <WorkflowBar workflow={activeWorkflow.workflow} onResume={() => void resumeWorkflow()} onCancel={() => void cancelWorkflow()} disabled={sending} />}
                {chatLoading && <div className="kai-assistant-empty"><LoaderCircle className="is-spinning" />正在读取独立会话…</div>}
                {!chatLoading && messages.length === 0 && !supportPreparationMessage && !chatError && (
                  <div className="kai-assistant-empty"><Bot /><strong>从一个问题开始</strong><span>例如：我的订单在哪里？如何发布服务？</span></div>
                )}
                <div className="kai-assistant-messages" aria-live="polite">
                  {[...messages, ...(supportPreparationMessage ? [supportPreparationMessage] : [])].map((message) => (
                    <article key={message.id} className={`${message.role === 'user' ? 'is-user' : 'is-assistant'} ${message.blocks?.length ? 'has-blocks' : ''}`}>
                      <small>{message.role === 'user' ? '你' : '开小花'} · {formatTime(message.created_at)}</small>
                      {message.content && <p>{message.content}</p>}
                      {message.role === 'assistant' && message.blocks?.map((block) => (
                        <StructuredBlockRenderer
                          key={`${message.id}-${block.block_id}-${block.block_version}`}
                          block={block}
                          disabled={sending || completedBlocks.has(blockKey(message.runId, block.block_id, block.block_version))}
                          onSubmitAnswers={(submission) => void submitStructuredAnswers(message, submission)}
                          onAction={handleStructuredAction}
                          onNavigate={navigate}
                        />
                      ))}
                    </article>
                  ))}
                  {sending && <article className="is-assistant"><small>开小花 · 正在回复</small><p className="kai-assistant-thinking"><i /><i /><i /></p></article>}
                </div>
                {chatError && <AssistantErrorCard error={chatError} hasWorkflow={Boolean(activeWorkflow)} onRetry={() => void retryLastTurn()} onResume={() => void resumeWorkflow()} />}
                <div ref={messagesEndRef} className="kai-assistant-messages-end" aria-hidden="true" />
              </div>
              <form className="kai-assistant-composer" onSubmit={(event) => { event.preventDefault(); void sendMessage(); }}>
                <textarea
                  ref={composerRef}
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

          {state.view === 'help' && <AssistantHelpPanel onNavigate={navigate} onRequestHumanSupport={showHumanSupportPreparation} />}
        </aside>
      )}
    </>
  );
}

function isTerminalAssistantResult(result: AssistantTurnResult): boolean {
  const state = result.runState || result.workflow?.state;
  return state === 'completed' || state === 'cancelled';
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

function WorkflowBar({
  workflow,
  onResume,
  onCancel,
  disabled,
}: {
  workflow: PlatformAssistantWorkflow | null;
  onResume: () => void;
  onCancel: () => void;
  disabled: boolean;
}) {
  const completed = workflow?.progress.completed_required || 0;
  const total = workflow?.progress.total_required || 0;
  const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;
  const recoverable = !workflow || workflow.state === 'paused' || workflow.state === 'failed';
  return (
    <section className={`kai-workflow-bar is-${workflow?.state || 'recoverable'}`} aria-label="当前结构化任务">
      <header>
        <span><Sparkles /><strong>{workflow ? workflowStateLabel(workflow.state) : '可恢复任务'}</strong></span>
        {total > 0 && <small>{completed}/{total} 项必填信息</small>}
      </header>
      {total > 0 && <div className="kai-workflow-progress" aria-label={`进度 ${percent}%`}><i style={{ width: `${percent}%` }} /></div>}
      <footer>
        <span>草稿与真实业务操作分离，发布仍需到业务页确认。</span>
        <div>
          {recoverable && <button type="button" disabled={disabled} onClick={onResume}><RotateCcw />恢复</button>}
          <button type="button" disabled={disabled} onClick={onCancel}><PauseCircle />结束</button>
        </div>
      </footer>
    </section>
  );
}

function AssistantErrorCard({
  error,
  hasWorkflow,
  onRetry,
  onResume,
}: {
  error: AssistantFailure;
  hasWorkflow: boolean;
  onRetry: () => void;
  onResume: () => void;
}) {
  const conflict = error.code === 'BLOCK_VERSION_CONFLICT' || error.code === 'CONTEXT_STALE';
  const unavailable = error.code === 'AI_UNAVAILABLE' || error.code === 'AI_QUOTA_EXCEEDED';
  return (
    <section className={`kai-assistant-error is-${conflict ? 'conflict' : unavailable ? 'unavailable' : 'failed'}`} role="alert">
      <AlertTriangle />
      <span>
        <strong>{conflict ? '内容已更新' : unavailable ? '开小花暂时不可用' : '本次操作未完成'}</strong>
        <em>{error.message}</em>
        <small>{error.code}</small>
      </span>
      <div>
        {conflict && hasWorkflow && <button type="button" onClick={onResume}><RotateCcw />刷新后恢复</button>}
        {error.retryable && !conflict && <button type="button" onClick={onRetry}><RotateCcw />重试</button>}
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

function blockKey(runId: string | null | undefined, blockId: string, blockVersion: number) {
  return `${runId || 'no-run'}:${blockId}:${blockVersion}`;
}

function answerFingerprint(answers: AnswerSubmission['answers']) {
  return JSON.stringify(answers.map((answer) => ({
    question_id: answer.question_id,
    value: answer.value,
  })));
}

function selectedOrganizationId() {
  try {
    return window.localStorage.getItem('kaigongba_marketplace_organization') || null;
  } catch {
    return null;
  }
}

function currentPageLabel(pathname: string) {
  if (pathname.startsWith('/enterprise/orders/')) return '订单工作区';
  if (pathname === '/enterprise/orders') return '我的订单';
  if (pathname.startsWith('/enterprise/demands/new')) return '发布需求';
  if (pathname.startsWith('/enterprise/demands')) return '我的需求';
  if (pathname.startsWith('/enterprise/transactions')) return '交易中心';
  if (pathname.startsWith('/workspace/gallery')) return '项目中心';
  if (pathname.startsWith('/workspace/chat')) return '数字员工对话';
  return '当前业务页';
}

function workflowStateLabel(state: PlatformAssistantWorkflow['state']) {
  return ({
    intent_pending: '等待确认意图', intent_confirmed: '已确认意图', collecting: '正在收集信息', drafting: '正在整理草稿',
    reviewing: '请检查草稿', draft_saved: '草稿已保存', handed_off: '已交给业务页', completed: '任务已完成',
    paused: '任务已暂停', failed: '任务需恢复', cancelled: '任务已结束',
  } as Record<PlatformAssistantWorkflow['state'], string>)[state];
}

function notificationFilterLabel(filter: NotificationFilter) {
  return { all: '全部', todos: '待办', progress: '项目进展', system: '系统通知' }[filter];
}

function safeAssistantRoute(route: string) {
  return route.startsWith('/enterprise/') || route.startsWith('/workspace/');
}

function humanSupportPreparationBlocks(pathname: string): StructuredBlock[] {
  return [
    {
      schema_version: '1.0', block_id: `block_support_notice_${crypto.randomUUID()}`, block_version: 1,
      type: 'notice', status: 'pending', title: '联系人工客服前的准备',
      description: '当前仅整理信息，没有创建工单。', tone: 'info', code: 'HUMAN_SUPPORT_PREPARATION',
      message: '请先说明遇到的问题、期望结果和已尝试的操作。请勿提供密码、API 密钥或完整银行卡号。', actions: [],
    },
    {
      schema_version: '1.0', block_id: `block_support_fields_${crypto.randomUUID()}`, block_version: 1,
      type: 'entity_summary', status: 'succeeded', title: '建议提供的信息',
      description: '下列信息可帮助客服定位问题，不会自动外发。',
      entity_ref: { type: 'support_preparation', id: 'current' },
      fields: [
        { key: 'page', label: '当前页面', value: currentPageLabel(pathname) },
        { key: 'issue', label: '问题与期望', value: '请在对话中补充' },
        { key: 'business_reference', label: '业务编号', value: '如订单、需求、报价或争议编号' },
        { key: 'evidence', label: '问题证据', value: '可脱敏的报错文字、发生时间和操作步骤' },
      ],
      allowed_action_ids: [],
    },
  ];
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
