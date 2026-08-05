// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AssistantRequirementDraftResponse } from './types';
import { OPEN_KAI_ASSISTANT_EVENT } from '@/features/kai-assistant/assistantEvents';

const mocks = vi.hoisted(() => ({
  listCategories: vi.fn(),
  getDraft: vi.fn(),
  create: vi.fn(),
  publish: vi.fn(),
  handoff: vi.fn(),
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
  notifyWarning: vi.fn(),
}));

vi.mock('./components', () => ({
  MarketplaceHeader: () => <header>市场页头</header>,
}));

vi.mock('./useMarketplaceOrganization', () => ({
  useMarketplaceOrganization: () => ({
    organizations: [{ id: 'org-buyer', name: '测试企业' }],
    selected: { id: 'org-buyer', name: '测试企业' },
    loading: false,
    error: '',
    selectOrganization: vi.fn(),
  }),
}));

vi.mock('@/components/ui/app-toast', () => ({
  notify: {
    success: mocks.notifySuccess,
    error: mocks.notifyError,
    warning: mocks.notifyWarning,
  },
}));

vi.mock('@/api/client', () => ({
  TENANT_ID: 'tenant-test',
  uploadChatAttachments: vi.fn(),
}));

vi.mock('./repository', () => ({
  marketplaceRepository: {
    listServiceCategories: mocks.listCategories,
    getAssistantRequirementDraft: mocks.getDraft,
    createRequirement: mocks.create,
    publishRequirement: mocks.publish,
    auditAssistantRequirementHandoff: mocks.handoff,
  },
}));

import DemandCreatePage from './DemandCreatePage';

const DRAFT_ID = 'reqdraft_12345678';

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  mocks.listCategories.mockResolvedValue(categoryCatalog());
  mocks.create.mockResolvedValue({ id: 'requirement-1', invitationCount: 0 });
  mocks.publish.mockResolvedValue({ id: 'requirement-1', invitationCount: 3 });
  mocks.handoff.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('demand create assistant handoff', () => {
  it('loads the active service catalogue and displays its parent-child hierarchy', async () => {
    renderPage('/enterprise/demands/new');

    expect(await screen.findByRole('group', { name: '设计与创意' })).toBeTruthy();
    expect(screen.getByRole('option', { name: '↳ 演示文稿设计' })).toBeTruthy();
    expect(mocks.listCategories).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('option', { name: '已停用分类' })).toBeNull();
  });

  it('starts the ordinary manual flow with an empty form and no draft request', () => {
    renderPage('/enterprise/demands/new');

    expect(input('需求标题 *').value).toBe('');
    expect(input('详细描述 *').value).toBe('');
    expect(input('预算下限').value).toBe('');
    expect(input('预算上限').value).toBe('');
    expect(screen.queryByText('风险清单（含风险等级与建议）')).toBeNull();
    expect(mocks.getDraft).not.toHaveBeenCalled();
  });

  it('starts adaptive requirement analysis from a natural-language brief', async () => {
    const user = userEvent.setup();
    const openRequest = vi.fn();
    window.addEventListener(OPEN_KAI_ASSISTANT_EVENT, openRequest);
    renderPage('/enterprise/demands/new');

    await user.type(screen.getByLabelText('自然语言描述需求'), '两周后做一份融资路演PPT，我已经有商业计划书');
    await user.click(screen.getByRole('button', { name: /让开小花分析/ }));

    expect(openRequest).toHaveBeenCalledTimes(1);
    const event = openRequest.mock.calls[0]?.[0] as CustomEvent<{ prompt: string; autoSend: boolean; startNewWorkflow: boolean }>;
    expect(event.detail.prompt).toContain('融资路演PPT');
    expect(event.detail.prompt).toContain('只追问最关键的 1 到 3 个问题');
    expect(event.detail.autoSend).toBe(true);
    expect(event.detail.startNewWorkflow).toBe(true);
    window.removeEventListener(OPEN_KAI_ASSISTANT_EVENT, openRequest);
  });

  it('saves an incomplete transaction draft without weakening publish validation', async () => {
    const user = userEvent.setup();
    renderPage('/enterprise/demands/new');

    await user.type(input('需求标题 *'), '融资路演PPT');
    await user.type(input('详细描述 *'), '先保存当前想法，后续由开小花继续访谈和完善。');
    await user.click(screen.getByRole('button', { name: '保存草稿' }));

    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      title: '融资路演PPT',
      budget_min_amount: '0.00',
      budget_max_amount: '0.00',
      desired_delivery_at: null,
      deliverables: [],
      acceptance_criteria: [],
    })));
    expect(mocks.publish).not.toHaveBeenCalled();
  });

  it('lists and locates every missing publish field instead of showing a generic error', async () => {
    const user = userEvent.setup();
    renderPage('/enterprise/demands/new');

    await user.type(input('需求标题 *'), '融资路演PPT');
    await user.click(screen.getByRole('button', { name: '预览并发布' }));

    expect(mocks.create).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('业务分类');
    expect(screen.getByRole('alert').textContent).toContain('详细描述');
    expect(screen.getByRole('alert').textContent).toContain('预算上限');
    expect(screen.getByRole('alert').textContent).toContain('期望交付物');
    expect(mocks.notifyError).toHaveBeenCalledWith(expect.stringContaining('项发布信息需要补充'));
  });

  it('loads non-empty form seed values and displays version, missing fields and warnings', async () => {
    mocks.getDraft.mockResolvedValue(draftResponse());
    renderPage(`/enterprise/demands/new?draftId=${DRAFT_ID}`);

    expect(await screen.findByText('开小花需求草稿 v2')).toBeTruthy();
    expect(input('需求标题 *').value).toBe('招聘流程诊断与岗位说明书优化');
    expect(select('业务分类 *').value).toBe('hr-consulting');
    expect(select('业务分类 *').selectedOptions[0]?.textContent).toBe('↳ 人力资源咨询');
    expect(input('预算上限').value).toBe('5000.00');
    expect(input('期望完成时间').value).toBe('2026-09-02T18:30');
    expect(input('保密等级 *').value).toBe('confidential');
    expect(screen.getByDisplayValue('招聘流程诊断报告')).toBeTruthy();
    expect(screen.getByText('依赖材料')).toBeTruthy();
    expect(screen.getByText('工期需要再确认')).toBeTruthy();
  });

  it('does not overwrite a user edit made while the draft request is in flight', async () => {
    let resolveDraft!: (value: AssistantRequirementDraftResponse) => void;
    mocks.getDraft.mockReturnValue(new Promise((resolve) => { resolveDraft = resolve; }));
    const user = userEvent.setup();
    renderPage(`/enterprise/demands/new?draftId=${DRAFT_ID}`);

    await user.type(input('需求标题 *'), '用户自己填写的标题');
    resolveDraft(draftResponse());

    await screen.findByText('开小花需求草稿 v2');
    expect(input('需求标题 *').value).toBe('用户自己填写的标题');
    expect(input('预算上限').value).toBe('5000.00');
  });

  it('keeps the manual form available and retries a missing or unauthorized draft', async () => {
    mocks.getDraft
      .mockRejectedValueOnce(new Error('草稿不存在或无权访问'))
      .mockResolvedValueOnce(draftResponse());
    const user = userEvent.setup();
    renderPage(`/enterprise/demands/new?draftId=${DRAFT_ID}`);

    expect(await screen.findByText(/草稿不存在或无权访问/)).toBeTruthy();
    await user.type(input('需求标题 *'), '手工备用标题');
    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(await screen.findByText('开小花需求草稿 v2')).toBeTruthy();
    expect(input('需求标题 *').value).toBe('手工备用标题');
    expect(mocks.getDraft).toHaveBeenCalledTimes(2);
  });

  it('preserves the original manual save and publish calls', async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage('/enterprise/demands/new');
    fillCompleteManualForm();

    await user.click(screen.getByRole('button', { name: '保存草稿' }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.publish).not.toHaveBeenCalled();

    unmount();
    vi.clearAllMocks();
    mocks.create.mockResolvedValue({ id: 'requirement-2', invitationCount: 0 });
    mocks.publish.mockResolvedValue({ id: 'requirement-2', invitationCount: 3 });
    renderPage('/enterprise/demands/new');
    fillCompleteManualForm();

    await user.click(screen.getByRole('button', { name: '预览并发布' }));
    await waitFor(() => expect(mocks.publish).toHaveBeenCalledWith('requirement-2', 'org-buyer'));
    expect(window.confirm).toHaveBeenCalled();
  });

  it('submits the category ID and name from an assistant draft, then clears the ID for a legacy choice', async () => {
    mocks.getDraft.mockResolvedValue(draftResponse({ missing_fields: [] }));
    const { unmount } = renderPage(`/enterprise/demands/new?draftId=${DRAFT_ID}`);
    await screen.findByText('开小花需求草稿 v2');

    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      category_id: 'hr-consulting',
      category: '人力资源咨询',
    })));

    unmount();
    vi.clearAllMocks();
    mocks.listCategories.mockResolvedValue(categoryCatalog());
    mocks.getDraft.mockResolvedValue(draftResponse({ missing_fields: [] }));
    mocks.create.mockResolvedValue({ id: 'requirement-legacy', invitationCount: 0 });
    mocks.handoff.mockResolvedValue(undefined);
    renderPage(`/enterprise/demands/new?draftId=${DRAFT_ID}`);
    await screen.findByText('开小花需求草稿 v2');

    fireEvent.change(input('业务分类 *'), { target: { value: '法律 / 合同审查' } });
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({
      category_id: undefined,
      category: '法律 / 合同审查',
    })));
  });

  it('keeps the draft category and legacy options when the catalogue API fails', async () => {
    mocks.listCategories.mockRejectedValue(new Error('目录暂时不可用'));
    mocks.getDraft.mockResolvedValue(draftResponse());
    renderPage(`/enterprise/demands/new?draftId=${DRAFT_ID}`);

    expect(await screen.findByText('开小花需求草稿 v2')).toBeTruthy();
    expect(await screen.findByText('分类目录暂时不可用，已保留当前分类并启用兼容选项。')).toBeTruthy();
    expect(select('业务分类 *').value).toBe('hr-consulting');
    expect(select('业务分类 *').selectedOptions[0]?.textContent).toBe('人力资源咨询');
    expect(screen.getByRole('option', { name: '法律 / 合同审查' })).toBeTruthy();
    expect(screen.getByRole('button', { name: '保存草稿' }).hasAttribute('disabled')).toBe(false);
  });

  it('treats handoff audit as best effort after a real requirement is created', async () => {
    mocks.getDraft.mockResolvedValue(draftResponse({ missing_fields: [] }));
    mocks.handoff.mockRejectedValue(new Error('审计服务暂时不可用'));
    renderPage(`/enterprise/demands/new?draftId=${DRAFT_ID}`);
    await screen.findByText('开小花需求草稿 v2');

    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }));

    await waitFor(() => expect(mocks.handoff).toHaveBeenCalledWith(
      DRAFT_ID,
      expect.objectContaining({
        protocol_version: '1.0',
        draft_version: 2,
        transaction_requirement_id: 'requirement-1',
        requirement_write: expect.objectContaining({
          organization_id: 'org-buyer',
          confidentiality_level: 'confidential',
        }),
      }),
    ));
    expect(mocks.notifySuccess).toHaveBeenCalledWith('需求草稿已保存');
    expect(mocks.notifyWarning).toHaveBeenCalledWith(expect.stringContaining('审计服务暂时不可用'));
    expect(mocks.notifyError).not.toHaveBeenCalled();
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/demands/requirement-1');
  });
});

function draftResponse(
  draftOverrides: Partial<AssistantRequirementDraftResponse['draft']> = {},
): AssistantRequirementDraftResponse {
  return {
    protocol_version: '1.0',
    draft: {
      draft_id: DRAFT_ID,
      draft_version: 2,
      missing_fields: ['依赖材料'],
      ...draftOverrides,
    },
    field_sources: {},
    draft_meta: { row_version: 2, status: 'reviewing', updated_at: '2026-08-04T10:00:00Z' },
    form_seed: {
      organization_id: 'org-buyer',
      title: '招聘流程诊断与岗位说明书优化',
      category_id: 'hr-consulting',
      category: '人力资源咨询',
      description: '当前招聘周期较长，需要诊断流程并输出可执行的优化方案。',
      budget_min_amount: '3000.00',
      budget_max_amount: '5000.00',
      desired_delivery_at: '2026-09-02T18:30:00+08:00',
      visibility: 'invited_providers',
      confidentiality_level: 'confidential',
      invite_limit: 5,
      deliverables: [{ name: '招聘流程诊断报告', format: 'PDF', required: true }],
      acceptance_criteria: ['报告覆盖现状、问题、优先级与改进方案'],
    },
    warnings: [{ field: 'desired_delivery_at', code: 'SCHEDULE_REVIEW', message: '工期需要再确认' }],
    handoff: { can_handoff: true, blockers: [] },
  };
}

function fillCompleteManualForm() {
  fireEvent.change(input('需求标题 *'), { target: { value: '企业合同智能审查项目' } });
  fireEvent.change(input('业务分类 *'), { target: { value: '法律 / 合同审查' } });
  fireEvent.change(input('详细描述 *'), { target: { value: '需要对企业采购合同进行完整风险识别，并输出带批注的修订稿。' } });
  fireEvent.change(input('预算下限'), { target: { value: '3000' } });
  fireEvent.change(input('预算上限'), { target: { value: '5000' } });
  fireEvent.change(input('期望完成时间'), { target: { value: '2026-09-02T18:30' } });
  fireEvent.click(screen.getByRole('button', { name: /添加交付物/ }));
  fireEvent.change(document.querySelector('.transaction-deliverable-table input:not([type="checkbox"])') as HTMLInputElement, { target: { value: '合同风险审查报告' } });
  fireEvent.click(screen.getByRole('button', { name: /添加验收要求/ }));
  fireEvent.change(document.querySelector('.transaction-criterion input') as HTMLInputElement, { target: { value: '报告需覆盖所有核心合同条款' } });
}

function categoryCatalog() {
  const base = {
    description: '', aliases: [], exampleTasks: [], requiredFacets: [], status: 'active' as const,
    version: 1, createdAt: '2026-08-04T10:00:00Z', updatedAt: '2026-08-04T10:00:00Z',
  };
  return [
    { ...base, id: 'design', name: '设计与创意', parentId: null, sortOrder: 10 },
    { ...base, id: 'presentation-design', name: '演示文稿设计', parentId: 'design', sortOrder: 20 },
    { ...base, id: 'business-services', name: '企业服务', parentId: null, sortOrder: 30 },
    { ...base, id: 'hr-consulting', name: '人力资源咨询', parentId: 'business-services', sortOrder: 31 },
    { ...base, id: 'legal-contract-review', name: '法律 / 合同审查', parentId: 'business-services', sortOrder: 32 },
    { ...base, id: 'inactive-hidden', name: '已停用分类', parentId: null, status: 'inactive' as const, sortOrder: 99 },
  ];
}

function input(label: string) {
  return screen.getByLabelText(label) as HTMLInputElement;
}

function select(label: string) {
  return screen.getByLabelText(label) as HTMLSelectElement;
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderPage(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <DemandCreatePage />
      <LocationProbe />
    </MemoryRouter>,
  );
}
