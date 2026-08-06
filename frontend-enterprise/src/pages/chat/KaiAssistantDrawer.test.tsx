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
import type { AssistantTurnResult, KaiAssistantService } from '@/features/kai-assistant/components/assistantService';
import { QuestionGroupBlock } from '@/features/kai-assistant/components/QuestionGroupBlock';
import { OPEN_KAI_ASSISTANT_EVENT } from '@/features/kai-assistant/assistantEvents';
import type {
  AdaptiveQuestionGroupBlock,
  InterviewStateBlock as InterviewStateBlockType,
  PlatformAssistantV2StructuredBlock,
  QuestionGroupBlock as QuestionGroupBlockType,
  StructuredBlock,
} from '@/features/kai-assistant/protocol';

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
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1024 });
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

  it('opens from a business-page request and prefills the natural-language requirement', async () => {
    renderDrawer('/enterprise/demands/new');

    window.dispatchEvent(new CustomEvent(OPEN_KAI_ASSISTANT_EVENT, {
      detail: { view: 'chat', prompt: '我想发布一个融资路演PPT需求', autoSend: true },
    }));

    expect(await screen.findByRole('complementary', { name: '开小花平台总助' })).toBeTruthy();
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/api/platform-assistant/turns', expect.objectContaining({
      message: '我想发布一个融资路演PPT需求',
      protocol_version: '2.0',
    })));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/demands/new');
  });

  it('attaches an AI-generated draft to the current requirement form automatically', async () => {
    const service = mockAssistantService(directDraftResult());
    renderDrawer('/enterprise/demands/new', service);

    window.dispatchEvent(new CustomEvent(OPEN_KAI_ASSISTANT_EVENT, {
      detail: {
        view: 'chat',
        prompt: '直接分析并扩写融资路演PPT需求',
        autoSend: true,
        startNewWorkflow: true,
        entrypoint: 'requirement.create',
      },
    }));

    await waitFor(() => expect(service.sendTurn).toHaveBeenCalledWith(expect.objectContaining({
      entrypoint: 'requirement.create',
    })));
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe(
      '/enterprise/demands/new?draftId=reqdraft_auto_fill_001',
    ));
    expect(await screen.findByText('AI 已扩写并填入需求')).toBeTruthy();
  });

  it('ignores an older analysis response after a newer request sequence starts', async () => {
    let resolveFirst!: (result: AssistantTurnResult) => void;
    let resolveSecond!: (result: AssistantTurnResult) => void;
    const service = mockAssistantService(directDraftResult());
    vi.mocked(service.sendTurn)
      .mockReset()
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
    renderDrawer('/enterprise/demands/new', service);

    window.dispatchEvent(new CustomEvent(OPEN_KAI_ASSISTANT_EVENT, {
      detail: {
        view: 'chat', prompt: '第一份旧需求', autoSend: true, startNewWorkflow: true,
        entrypoint: 'requirement.create', analysisRequestId: 'requirement-analysis-1-old',
      },
    }));
    await waitFor(() => expect(service.sendTurn).toHaveBeenCalledTimes(1));
    window.dispatchEvent(new CustomEvent(OPEN_KAI_ASSISTANT_EVENT, {
      detail: {
        view: 'chat', prompt: '第二份最新需求', autoSend: true, startNewWorkflow: true,
        entrypoint: 'requirement.create', analysisRequestId: 'requirement-analysis-2-new',
      },
    }));

    resolveFirst(directDraftResult('reqdraft_stale_result_001'));
    await waitFor(() => expect(service.sendTurn).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/demands/new');
    resolveSecond(directDraftResult('reqdraft_latest_result_002'));

    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe(
      '/enterprise/demands/new?draftId=reqdraft_latest_result_002',
    ));
    expect(service.sendTurn).toHaveBeenNthCalledWith(1, expect.objectContaining({
      clientRequestId: 'requirement-analysis-1-old',
    }));
    expect(service.sendTurn).toHaveBeenNthCalledWith(2, expect.objectContaining({
      clientRequestId: 'requirement-analysis-2-new',
    }));
  });

  it('opens restored chat history at the newest message and follows new replies', async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView,
    });
    renderDrawer('/enterprise/transactions');
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));

    await screen.findByText('平台总助真实会话消息');
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    const previousCalls = scrollIntoView.mock.calls.length;
    const composer = screen.getByRole('textbox', { name: '给开小花发送消息' });
    fireEvent.change(composer, { target: { value: '请显示最新状态' } });
    fireEvent.keyDown(composer, { key: 'Enter' });
    await screen.findByText('我可以帮你定位真实业务页面，但不会代替你确认或验收。');
    await waitFor(() => expect(scrollIntoView.mock.calls.length).toBeGreaterThan(previousCalls));
  });

  it('archives an existing assistant workflow before a demand-page new-requirement launch', async () => {
    const service = mockAssistantService(v2InterviewResult());
    renderDrawer('/enterprise/demands/new', service);
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    await screen.findByText('平台总助真实会话消息');

    const composer = screen.getByRole('textbox', { name: '给开小花发送消息' });
    fireEvent.change(composer, { target: { value: '先创建一个旧需求' } });
    fireEvent.keyDown(composer, { key: 'Enter' });
    expect(await screen.findByText('需求理解进度')).toBeTruthy();

    window.dispatchEvent(new CustomEvent(OPEN_KAI_ASSISTANT_EVENT, {
      detail: {
        view: 'chat',
        prompt: '现在开始一个全新的产品发布会需求',
        autoSend: true,
        startNewWorkflow: true,
        entrypoint: 'requirement.create',
      },
    }));

    await waitFor(() => expect(service.cancelRun).toHaveBeenCalledWith('session_structured', 'run_requirement'));
    await waitFor(() => expect(service.sendTurn).toHaveBeenCalledTimes(2));
    expect(service.sendTurn).toHaveBeenLastCalledWith(expect.objectContaining({
      message: '现在开始一个全新的产品发布会需求',
      entrypoint: 'requirement.create',
    }));
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

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/api/platform-assistant/turns', expect.objectContaining({
      protocol_version: '2.0',
      session_id: 'session_kai',
      message: '订单入口在哪里？',
      page_context: expect.objectContaining({ route_id: 'assistant.chat' }),
    })));
    expect(apiPost.mock.calls[apiPost.mock.calls.length - 1]?.[1]).not.toHaveProperty('channel');
    expect(await screen.findByText('我可以帮你定位真实业务页面，但不会代替你确认或验收。')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /确认验收|退款|放款/ })).toBeNull();
  });

  it('offers safe help deep links without adding a fourth target view', async () => {
    renderDrawer('/workspace/gallery?view=agents');
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    fireEvent.click(screen.getByRole('tab', { name: '使用帮助' }));
    fireEvent.click(screen.getByRole('button', { name: /订单\s+查看采购与服务订单/ }));

    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders');
    expect(screen.getAllByRole('tab')).toHaveLength(3);
  });

  it('sends all three quick questions through turns and keeps a dynamic business route mounted', async () => {
    const service = mockAssistantService(guidanceResult());
    renderDrawer('/enterprise/provider/quotes/quote_dynamic', service);
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    await screen.findByText('平台总助真实会话消息');

    for (const prompt of ['我现在可以做什么？', '我的待办', '当前页面说明']) {
      fireEvent.click(screen.getByRole('button', { name: prompt }));
      await waitFor(() => expect(service.sendTurn).toHaveBeenCalledWith(expect.objectContaining({ message: prompt })));
    }

    expect(service.sendTurn).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/provider/quotes/quote_dynamic');
    expect(screen.getByRole('complementary', { name: '开小花平台总助' })).toBeTruthy();
  });

  it('renders general guidance as entity summary, safe deep link and notice', async () => {
    const service = mockAssistantService(guidanceResult());
    renderDrawer('/enterprise/orders/order_dynamic', service);
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    await screen.findByText('平台总助真实会话消息');

    fireEvent.click(screen.getByRole('button', { name: '当前页面说明' }));

    expect(await screen.findByText('当前订单摘要')).toBeTruthy();
    expect(screen.getByText('前往订单')).toBeTruthy();
    expect(screen.getByText('你仍需在业务页确认')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '打开订单列表' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders');
  });

  it('covers seven help areas, fails closed for unregistered detail collections and prepares human support locally', async () => {
    renderDrawer('/enterprise/orders/order_real?tab=disputes');
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    fireEvent.click(screen.getByRole('tab', { name: '使用帮助' }));

    for (const label of ['项目与 AI 员工', '订单', '需求', '报价', '合同与协议', '交付与验收', '平台争议处理']) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    for (const label of ['合同与协议', '交付与验收', '平台争议处理']) {
      expect(screen.getByRole('button', { name: new RegExp(label) }).hasAttribute('disabled')).toBe(true);
    }
    expect(screen.getAllByText(/当前版本不可直达/)).toHaveLength(3);

    fireEvent.click(screen.getByRole('button', { name: '联系人工客服' }));
    expect(await screen.findByText('联系人工客服前的准备')).toBeTruthy();
    expect(screen.getByText('当前仅整理信息，没有创建工单。')).toBeTruthy();
    expect(screen.getByText('建议提供的信息')).toBeTruthy();
    expect(apiPost).not.toHaveBeenCalled();
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_real?tab=disputes');
  });

  it('retries a failed quick question without navigating away', async () => {
    const service = mockAssistantService(guidanceResult());
    vi.mocked(service.sendTurn).mockRejectedValueOnce(new Error('网络连接中断'));
    renderDrawer('/enterprise/agreements/agreement_dynamic', service);
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    await screen.findByText('平台总助真实会话消息');

    fireEvent.click(screen.getByRole('button', { name: '我的待办' }));
    expect(await screen.findByText('本次操作未完成')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /重试/ }));

    await waitFor(() => expect(service.sendTurn).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('当前订单摘要')).toBeTruthy();
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/agreements/agreement_dynamic');
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

  it('keeps the overlay on the current route at mobile width', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
    renderDrawer('/enterprise/orders/order_mobile?tab=materials');

    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));

    expect(screen.getByRole('complementary', { name: '开小花平台总助' })).toBeTruthy();
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_mobile?tab=materials');
    expect(screen.getByRole('textbox', { name: '给开小花发送消息' })).toBeTruthy();
  });

  it('renders v2 interview state before adaptive questions and submits a custom answer', async () => {
    const service = mockAssistantService(v2InterviewResult());
    renderDrawer('/enterprise/demands/new', service);
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    await screen.findByText('平台总助真实会话消息');

    const composer = screen.getByRole('textbox', { name: '给开小花发送消息' });
    fireEvent.change(composer, { target: { value: '需要设计一套品牌视觉' } });
    fireEvent.keyDown(composer, { key: 'Enter' });

    const interviewHeading = await screen.findByText('需求理解进度');
    const questionHeading = screen.getByText('继续补充关键信息');
    expect(interviewHeading.compareDocumentPosition(questionHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText('已收集信息')).toBeTruthy();
    expect(screen.getByText('也可在下方对话框用自然语言补充')).toBeTruthy();

    fireEvent.change(screen.getByRole('textbox', { name: '期望视觉风格自定义答案' }), {
      target: { value: '克制、专业、有东方感' },
    });
    fireEvent.click(screen.getByRole('button', { name: '统一发送' }));

    await waitFor(() => expect(service.submitAnswers).toHaveBeenCalledWith(expect.objectContaining({
      protocol_version: '2.0',
      block_id: 'block_adaptive_style',
      answers: [expect.objectContaining({
        question_id: 'visual_style',
        value: { option_ids: [], custom_text: '克制、专业、有东方感' },
      })],
    })));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/demands/new');
  });

  it('keeps a completed result visible without reactivating it for a new requirement', async () => {
    const service = mockAssistantService(completedWorkflowResult());
    vi.mocked(service.sendTurn)
      .mockReset()
      .mockResolvedValueOnce(completedWorkflowResult())
      .mockResolvedValueOnce(v2InterviewResult());
    renderDrawer('/enterprise/demands/new', service);
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    await screen.findByText('平台总助真实会话消息');

    const composer = screen.getByRole('textbox', { name: '给开小花发送消息' });
    fireEvent.change(composer, { target: { value: '查看刚才完成的需求' } });
    fireEvent.keyDown(composer, { key: 'Enter' });
    expect(await screen.findAllByText('历史需求已经完成')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: '恢复旧流程' }));
    expect(service.resumeRun).not.toHaveBeenCalled();

    fireEvent.change(composer, { target: { value: '现在新建一个品牌视觉需求' } });
    fireEvent.keyDown(composer, { key: 'Enter' });
    await waitFor(() => expect(service.sendTurn).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('需求理解进度')).toBeTruthy();
    expect(screen.getAllByText('历史需求已经完成')).toHaveLength(2);
  });

  it('collects a question group locally and submits all selected answers once', async () => {
    const blocks: StructuredBlock[] = [questionGroupBlock()];
    const service = mockAssistantService(structuredResult(blocks));
    renderDrawer('/enterprise/demands/new', service);
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    await screen.findByText('平台总助真实会话消息');

    const composer = screen.getByRole('textbox', { name: '给开小花发送消息' });
    fireEvent.change(composer, { target: { value: '我想做一个企业官网' } });
    fireEvent.keyDown(composer, { key: 'Enter', shiftKey: false });

    expect(await screen.findByText('需求类型')).toBeTruthy();
    fireEvent.click(screen.getByRole('radio', { name: /企业官网/ }));
    fireEvent.click(screen.getByRole('button', { name: '统一发送' }));

    await waitFor(() => expect(service.submitAnswers).toHaveBeenCalledTimes(1));
    expect(service.submitAnswers).toHaveBeenCalledWith(expect.objectContaining({
      protocol_version: '1.0',
      session_id: 'session_structured',
      run_id: 'run_requirement',
      block_id: 'block_question_requirement',
      block_version: 1,
      answers: [expect.objectContaining({
        question_id: 'requirement_type',
        value: { option_ids: ['website'] },
      })],
    }));
    expect(screen.getByRole('button', { name: '已提交' }).hasAttribute('disabled')).toBe(true);
  });

  it('reuses the exact answer request after a lost response', async () => {
    const service = mockAssistantService(structuredResult([questionGroupBlock()]));
    vi.mocked(service.submitAnswers).mockRejectedValueOnce(new Error('网络连接中断'));
    renderDrawer('/enterprise/demands/new', service);
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    await screen.findByText('平台总助真实会话消息');

    const composer = screen.getByRole('textbox', { name: '给开小花发送消息' });
    fireEvent.change(composer, { target: { value: '我想做一个企业官网' } });
    fireEvent.keyDown(composer, { key: 'Enter', shiftKey: false });
    fireEvent.click(await screen.findByRole('radio', { name: /企业官网/ }));
    fireEvent.click(screen.getByRole('button', { name: '统一发送' }));

    expect(await screen.findByText('本次操作未完成')).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('button', { name: '统一发送' }).hasAttribute('disabled')).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: '统一发送' }));

    await waitFor(() => expect(service.submitAnswers).toHaveBeenCalledTimes(2));
    const first = vi.mocked(service.submitAnswers).mock.calls[0]?.[0];
    const retry = vi.mocked(service.submitAnswers).mock.calls[1]?.[0];
    expect(retry?.idempotency_key).toBe(first?.idempotency_key);
    expect(retry?.answers).toEqual(first?.answers);
  });

  it('renders all seven safe block types, opens only a registered deep link and degrades unknown blocks', async () => {
    const blocks = allBlockTypes();
    const service = mockAssistantService(structuredResult(blocks as StructuredBlock[]));
    renderDrawer('/enterprise/demands', service);
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    await screen.findByText('平台总助真实会话消息');
    const composer = screen.getByRole('textbox', { name: '给开小花发送消息' });
    fireEvent.change(composer, { target: { value: '帮我梳理需求' } });
    fireEvent.keyDown(composer, { key: 'Enter' });

    expect(await screen.findByText('请确认你的意图')).toBeTruthy();
    expect(screen.getByText('需求草稿')).toBeTruthy();
    expect(screen.getByText('草稿已保存')).toBeTruthy();
    expect(screen.getByText('当前需求')).toBeTruthy();
    expect(screen.getByText('前往需求详情')).toBeTruthy();
    expect(screen.getByText('温馨提示')).toBeTruthy();
    expect(screen.getByText('UNSUPPORTED_BLOCK')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '打开订单' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_safe?tab=materials');
    expect(screen.getByRole('complementary', { name: '开小花平台总助' })).toBeTruthy();
    expect(screen.queryByText(/onerror/)).toBeNull();
  });

  it('shows a version-conflict recovery state and resumes the existing run', async () => {
    const service = mockAssistantService(structuredResult([questionGroupBlock()]));
    vi.mocked(service.submitAnswers).mockRejectedValueOnce({
      body: JSON.stringify({
        protocol_version: '1.0', request_id: 'request_conflict', server_time: '2026-08-04T12:00:00+08:00',
        error: { code: 'BLOCK_VERSION_CONFLICT', message: '问题组已更新，请刷新。', retryable: true },
      }),
    });
    renderDrawer('/enterprise/demands/new', service);
    fireEvent.click(await screen.findByRole('button', { name: /打开开小花/ }));
    await screen.findByText('平台总助真实会话消息');
    const composer = screen.getByRole('textbox', { name: '给开小花发送消息' });
    fireEvent.change(composer, { target: { value: '创建需求' } });
    fireEvent.keyDown(composer, { key: 'Enter' });
    fireEvent.click(await screen.findByRole('radio', { name: /企业官网/ }));
    fireEvent.click(screen.getByRole('button', { name: '统一发送' }));

    expect(await screen.findByText('内容已更新')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /刷新后恢复/ }));
    await waitFor(() => expect(service.resumeRun).toHaveBeenCalledWith('session_structured', 'run_requirement'));
  });

  it('supports date-or-duration mode and authorized entity selection without guessing IDs', () => {
    const onSubmit = vi.fn();
    const block: QuestionGroupBlockType = {
      schema_version: '1.0', block_id: 'block_question_schedule', block_version: 1, type: 'question_group', status: 'pending',
      title: '交付安排', description: '', submit_label: '统一发送',
      questions: [
        { id: 'schedule', label: '交付时间', input_type: 'date_or_duration', required: true },
        { id: 'organization', label: '代表哪家企业', input_type: 'entity_picker', entity_type: 'organization', required: true, options: [{ id: 'org_authorized', label: '已授权企业' }] },
      ],
    };
    render(<QuestionGroupBlock block={block} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByRole('button', { name: '按工期' }));
    fireEvent.change(screen.getByRole('spinbutton', { name: '交付时间' }), { target: { value: '12' } });
    fireEvent.click(screen.getByRole('radio', { name: '已授权企业' }));
    fireEvent.click(screen.getByRole('button', { name: '统一发送' }));

    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ answers: [
      expect.objectContaining({ question_id: 'schedule', value: expect.objectContaining({ duration: 12, unit: 'business_day' }) }),
      expect.objectContaining({ question_id: 'organization', value: { entity_refs: [{ type: 'organization', id: 'org_authorized' }] } }),
    ] }));
  });

  it('hands an entity picker without authorized options to the real form instead of creating a dead end', () => {
    const onSubmit = vi.fn();
    const block: QuestionGroupBlockType = {
      schema_version: '1.0', block_id: 'block_question_handoff', block_version: 1, type: 'question_group', status: 'pending',
      title: '企业选择', description: '', submit_label: '继续',
      questions: [{ id: 'organization', label: '代表哪家企业', input_type: 'entity_picker', entity_type: 'organization', required: true }],
    };
    render(<QuestionGroupBlock block={block} onSubmit={onSubmit} />);

    expect(screen.getByText(/当前未收到可选的已授权企业/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '继续' }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ answers: [] }));
  });
});

function renderDrawer(entry: string, service?: KaiAssistantService) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <DrawerHarness service={service} />
    </MemoryRouter>,
  );
}

function DrawerHarness({ service }: { service?: KaiAssistantService }) {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  return (
    <>
      <KaiAssistantDrawer sidebarCollapsed={collapsed} onToggleSidebar={() => setCollapsed((value) => !value)} service={service} />
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

function questionGroupBlock(): StructuredBlock {
  return {
    schema_version: '1.0', block_id: 'block_question_requirement', block_version: 1,
    type: 'question_group', status: 'pending', title: '需求类型', description: '选择后再统一发送。', submit_label: '统一发送',
    questions: [{
      id: 'requirement_type', label: '这次想做什么？', input_type: 'single_choice', required: true,
      options: [{ id: 'website', label: '企业官网', recommended: true }, { id: 'recruitment', label: '招聘流程' }],
    }],
  };
}

function structuredResult(blocks: PlatformAssistantV2StructuredBlock[]): AssistantTurnResult {
  return {
    sessionId: 'session_structured', runId: 'run_requirement', messageId: `message_${crypto.randomUUID()}`,
    assistantText: '我已根据当前页面整理了下一步。', blocks,
    workflow: {
      capability_id: 'requirement.create', capability_version: '1.0.0', state: 'collecting', row_version: 1,
      progress: { completed_required: 1, total_required: 3 },
    },
  };
}

function v2InterviewResult(): AssistantTurnResult {
  const interview: InterviewStateBlockType = {
    schema_version: '2.0', block_id: 'block_interview_brand', block_version: 1,
    type: 'interview_state', status: 'reviewing', title: '需求理解进度', description: '以下信息来自你的原话，未展示内部推理。',
    facts: [{
      key: 'service_goal', label: '服务目标', value: '设计一套品牌视觉', source: 'user_message',
      status: 'confirmed', confidence: 1, hard_fact: true, editable: true, edit_action_id: 'edit_service_goal',
    }],
    classification: { category_id: 'brand-design', name: '品牌设计', confidence: 0.89, status: 'needs_confirmation' },
    missing_information: [{ key: 'visual_style', label: '视觉风格', severity: 'blocking', reason: '用于确定创意方向。' }],
    readiness: { ready: false, blocking_fields: ['visual_style'] },
  };
  const question: AdaptiveQuestionGroupBlock = {
    schema_version: '2.0', block_id: 'block_adaptive_style', block_version: 1,
    type: 'question_group', status: 'pending', title: '继续补充关键信息', description: '可选择快捷答案，也可自行输入。',
    submit_label: '统一发送', allow_free_text: true,
    questions: [{
      id: 'visual_style', label: '期望视觉风格', input_type: 'single_choice', required: true,
      options: [{ id: 'modern', label: '现代简约' }, { id: 'warm', label: '温暖亲和' }],
      allow_custom: true, allow_uncertain: true,
    }],
  };
  return {
    sessionId: 'session_structured', runId: 'run_requirement', messageId: `message_v2_${crypto.randomUUID()}`,
    assistantText: '我先总结已确认信息，再补一个关键问题。', blocks: [interview, question],
    workflow: {
      capability_id: 'requirement.create', capability_version: '2.0.0', state: 'collecting', row_version: 2,
      progress: { completed_required: 1, total_required: 2 },
    },
  };
}

function guidanceResult(): AssistantTurnResult {
  return {
    sessionId: 'session_structured', runId: null, messageId: `message_guidance_${crypto.randomUUID()}`,
    assistantText: '我已根据你有权查看的当前页面整理了引导。',
    blocks: [
      {
        schema_version: '1.0', block_id: 'block_guidance_entity', block_version: 1,
        type: 'entity_summary', status: 'succeeded', title: '当前订单摘要', description: '仅显示已授权数据。',
        entity_ref: { type: 'order', id: 'order_dynamic' }, fields: [{ key: 'todo', label: '待办', value: '检查材料' }], allowed_action_ids: [],
      },
      {
        schema_version: '1.0', block_id: 'block_guidance_link', block_version: 1,
        type: 'deep_link', status: 'pending', title: '前往订单', description: '使用已登记的安全路由。',
        route_id: 'enterprise.order.list', route_params: {}, label: '打开订单列表',
      },
      {
        schema_version: '1.0', block_id: 'block_guidance_notice', block_version: 1,
        type: 'notice', status: 'pending', title: '操作提示', description: '', tone: 'info', code: 'BUSINESS_CONFIRMATION_REQUIRED',
        message: '你仍需在业务页确认', actions: [],
      },
    ],
    workflow: null,
  };
}

function directDraftResult(draftId = 'reqdraft_auto_fill_001'): AssistantTurnResult {
  return {
    sessionId: 'session_structured', runId: 'run_requirement', messageId: `message_direct_${crypto.randomUUID()}`,
    assistantText: '我已扩写需求并自动填入发布表单。',
    blocks: [{
      schema_version: '1.0', block_id: 'block_requirement_auto_fill', block_version: 1,
      type: 'deep_link', status: 'pending', title: 'AI 已扩写并填入需求',
      description: '请在真实需求页确认或修改。', route_id: 'enterprise.requirement.create',
      route_params: { draftId }, label: '检查并修改 AI 草稿',
    }],
    workflow: {
      capability_id: 'requirement.create', capability_version: '2.0.0', state: 'reviewing', row_version: 3,
      progress: { completed_required: 5, total_required: 7 },
    },
  };
}

function completedWorkflowResult(): AssistantTurnResult {
  return {
    sessionId: 'session_structured', runId: 'run_completed', runState: 'completed',
    messageId: `message_completed_${crypto.randomUUID()}`,
    assistantText: '历史需求已经完成',
    blocks: [{
      schema_version: '1.0', block_id: 'block_completed_history', block_version: 1,
      type: 'notice', status: 'succeeded', title: '历史需求已经完成', description: '',
      tone: 'success', code: 'WORKFLOW_COMPLETED', message: '可以保留查看，也可以开始一个新需求。',
      actions: [{ id: 'workflow.resume', label: '恢复旧流程', style: 'secondary' }],
    }],
    workflow: {
      capability_id: 'requirement.create', capability_version: '2.0.0', state: 'completed', row_version: 9,
      progress: { completed_required: 13, total_required: 13 },
    },
  };
}

function mockAssistantService(firstResult: AssistantTurnResult): KaiAssistantService {
  const completed: AssistantTurnResult = {
    ...firstResult,
    messageId: `message_completed_${crypto.randomUUID()}`,
    assistantText: '已保存本组回答。',
    blocks: [{
      schema_version: '1.0', block_id: 'block_notice_saved', block_version: 1, type: 'notice', status: 'succeeded',
      title: '回答已保存', description: '', tone: 'success', code: 'ANSWERS_SAVED', message: '已进入下一步。', actions: [],
    }],
  };
  return {
    sendTurn: vi.fn().mockResolvedValue(firstResult),
    submitAnswers: vi.fn().mockResolvedValue(completed),
    resumeRun: vi.fn().mockResolvedValue(completed),
    cancelRun: vi.fn().mockResolvedValue({ ...completed, runId: null, workflow: { ...completed.workflow!, state: 'cancelled' } }),
  };
}

function allBlockTypes(): unknown[] {
  return [
    {
      schema_version: '1.0', block_id: 'block_intent_create', block_version: 1, type: 'intent_confirmation', status: 'pending',
      title: '请确认你的意图', description: '开小花不会自动执行交易操作。', allow_free_text: true,
      options: [{ id: 'create', label: '创建需求' }, { id: 'learn', label: '了解流程' }],
    },
    questionGroupBlock(),
    {
      schema_version: '1.0', block_id: 'block_draft_requirement', block_version: 1, type: 'draft_preview', status: 'reviewing',
      title: '需求草稿', description: '请检查 AI 扩写的内容。', draft_id: 'draft_requirement', draft_version: 1, summary: '企业官网设计与开发',
      sections: [{ id: 'basic', title: '基础信息', fields: [{ key: 'title', label: '标题', value: '企业官网', source: 'user_message', editable: true, needs_confirmation: false }] }],
      missing_fields: [], actions: [{ id: 'edit', label: '继续修改', style: 'secondary' }],
    },
    {
      schema_version: '1.0', block_id: 'block_result_saved', block_version: 1, type: 'action_result', status: 'succeeded',
      title: '保存结果', description: '', action_id: 'save_draft', result_status: 'succeeded', result_code: 'DRAFT_SAVED', message: '草稿已保存',
    },
    {
      schema_version: '1.0', block_id: 'block_entity_requirement', block_version: 1, type: 'entity_summary', status: 'succeeded',
      title: '当前需求', description: '', entity_ref: { type: 'requirement', id: 'requirement_safe' }, fields: [{ key: 'status', label: '状态', value: '草稿' }], allowed_action_ids: ['read'],
    },
    {
      schema_version: '1.0', block_id: 'block_link_order', block_version: 1, type: 'deep_link', status: 'pending',
      title: '前往需求详情', description: '只能打开白名单路由。', route_id: 'enterprise.order.workspace', route_params: { orderId: 'order_safe', tab: 'materials' }, label: '打开订单',
    },
    {
      schema_version: '1.0', block_id: 'block_notice_tip', block_version: 1, type: 'notice', status: 'pending',
      title: '温馨提示', description: '', tone: 'info', code: 'REVIEW_REQUIRED', message: '发布前请检查。', actions: [],
    },
    { type: 'html_widget', html: '<img src=x onerror=alert(1)>' },
  ];
}
