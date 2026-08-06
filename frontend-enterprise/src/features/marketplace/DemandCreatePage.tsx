import { ArrowLeft, Check, FileText, LockKeyhole, Paperclip, PencilLine, Plus, ShieldCheck, Sparkles, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { TENANT_ID, uploadChatAttachments } from '@/api/client';
import type { ChatAttachmentRead } from '@/types';
import { MarketplaceHeader } from './components';
import { openKaiAssistant } from '@/features/kai-assistant/assistantEvents';
import { EMPTY_DEMAND_FORM, mergeNonEmptyRequirementSeed, type DemandFormState } from './demandDraftSeed';
import { marketplaceRepository } from './repository';
import type { AssistantRequirementDraftResponse, RequirementInput, ServiceCategory } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';

type DraftLoadState = 'idle' | 'loading' | 'ready' | 'error';
type CategoryLoadState = 'loading' | 'ready' | 'error';
type EditableField = keyof DemandFormState;
type PublishField = 'title' | 'category' | 'description' | 'budgetMax' | 'deadline' | 'deliverables' | 'criteria';
type PublishError = { field: PublishField; label: string; message: string };
const REQUIREMENT_DRAFT_ID = /^reqdraft_[A-Za-z0-9_-]{8,120}$/;

export default function DemandCreatePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const organization = useMarketplaceOrganization();
  const [form, setForm] = useState<DemandFormState>(() => ({
    ...EMPTY_DEMAND_FORM,
    deliverables: [],
    criteria: [],
    attachments: [],
  }));
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draftLoadState, setDraftLoadState] = useState<DraftLoadState>('idle');
  const [draftError, setDraftError] = useState('');
  const [draftResponse, setDraftResponse] = useState<AssistantRequirementDraftResponse | null>(null);
  const [appliedDraftVersion, setAppliedDraftVersion] = useState<number | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [serviceCategories, setServiceCategories] = useState<ServiceCategory[]>([]);
  const [categoryLoadState, setCategoryLoadState] = useState<CategoryLoadState>('loading');
  const [aiBrief, setAiBrief] = useState('');
  const [validationErrors, setValidationErrors] = useState<PublishError[]>([]);
  const editedFields = useRef(new Set<EditableField>());
  const appliedDraftIds = useRef(new Set<string>());
  const draftId = searchParams.get('draftId')?.trim() || '';
  const {
    title,
    categoryId,
    category,
    description,
    budgetMin,
    budgetMax,
    deadline,
    visibility,
    confidentialityLevel,
    inviteLimit,
    deliverables,
    criteria,
    attachments,
  } = form;
  const publishErrors = useMemo(() => requirementPublishErrors(form), [form]);
  const completeness = Math.round(((7 - publishErrors.length) / 7) * 100);
  const activeCategories = useMemo(
    () => serviceCategories.filter((item) => item.status === 'active'),
    [serviceCategories],
  );
  const categoryGroups = useMemo(() => buildCategoryGroups(activeCategories), [activeCategories]);
  const useLegacyCategoryFallback = categoryLoadState !== 'ready' || activeCategories.length === 0;

  useEffect(() => {
    let active = true;
    setCategoryLoadState('loading');
    void marketplaceRepository.listServiceCategories()
      .then((categories) => {
        if (!active) return;
        setServiceCategories(categories.filter((item) => item.status === 'active'));
        setCategoryLoadState('ready');
      })
      .catch(() => {
        if (!active) return;
        setServiceCategories([]);
        setCategoryLoadState('error');
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!draftId) {
      setDraftLoadState('idle');
      setDraftError('');
      setDraftResponse(null);
      return;
    }
    if (!REQUIREMENT_DRAFT_ID.test(draftId)) {
      setDraftLoadState('error');
      setDraftError('开小花草稿链接无效，请从原对话重新打开。');
      setDraftResponse(null);
      return;
    }
    let active = true;
    setDraftLoadState('loading');
    setDraftError('');
    void marketplaceRepository.getAssistantRequirementDraft(draftId)
      .then((response) => {
        if (!active) return;
        if (!isValidAssistantRequirementDraft(response, draftId)) {
          throw new Error('开小花草稿数据验证失败');
        }
        setDraftResponse(response);
        setDraftLoadState('ready');
        if (appliedDraftIds.current.has(draftId)) return;
        appliedDraftIds.current.add(draftId);
        setAppliedDraftVersion(response.draft.draft_version);
        setForm((current) => preserveUserEdits(
          current,
          mergeNonEmptyRequirementSeed(current, response.form_seed),
          editedFields.current,
        ));
      })
      .catch((error: unknown) => {
        if (!active) return;
        setDraftLoadState('error');
        setDraftError(error instanceof Error ? error.message : '无法读取开小花需求草稿');
      });
    return () => {
      active = false;
    };
  }, [draftId, loadAttempt]);

  function editField<K extends EditableField>(field: K, value: DemandFormState[K]) {
    editedFields.current.add(field);
    setValidationErrors((current) => current.filter((item) => item.field !== field));
    setForm((current) => ({ ...current, [field]: value }));
  }

  function editCategory(value: string) {
    const catalogCategory = activeCategories.find((item) => item.id === value);
    editedFields.current.add('category');
    editedFields.current.add('categoryId');
    setValidationErrors((current) => current.filter((item) => item.field !== 'category'));
    setForm((current) => catalogCategory
      ? { ...current, categoryId: catalogCategory.id, category: catalogCategory.name }
      : { ...current, categoryId: undefined, category: value });
  }

  function reviewAssistantField(field: string) {
    focusPublishField(({
      title: 'title',
      category: 'category',
      schedule: 'deadline',
      budget_min: 'budgetMax',
      budget_max: 'budgetMax',
      deliverables: 'deliverables',
      acceptance_criteria: 'criteria',
    } as Partial<Record<string, PublishField>>)[field] || 'description');
  }

  async function onFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    setUploading(true);
    try {
      const uploaded = await uploadChatAttachments<ChatAttachmentRead[]>(TENANT_ID, files);
      editedFields.current.add('attachments');
      setForm((current) => ({ ...current, attachments: [...current.attachments, ...uploaded] }));
      notify.success(`已上传 ${uploaded.length} 个材料`);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '材料上传失败');
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  }

  function buildInput(publish: boolean): RequirementInput | null {
    if (!organization.selected) {
      notify.error('请先选择发布企业');
      return null;
    }
    const draftOrganizationId = draftResponse?.form_seed.organization_id;
    if (draftId && draftOrganizationId && draftOrganizationId !== organization.selected.id) {
      notify.error('开小花草稿所属企业与当前发布企业不一致，请先切换到草稿所属企业');
      return null;
    }
    if (publish && publishErrors.length > 0) {
      setValidationErrors(publishErrors);
      notify.error(`还有 ${publishErrors.length} 项发布信息需要补充`);
      focusPublishField(publishErrors[0].field);
      return null;
    }
    const hasDraftContent = Boolean(
      title.trim() || description.trim() || category.trim() || deliverables.length || criteria.length || attachments.length,
    );
    if (!publish && !hasDraftContent) {
      notify.error('请至少填写需求标题或需求描述后再保存草稿');
      return null;
    }
    return {
      organization_id: organization.selected.id,
      title,
      category_id: categoryId || undefined,
      category,
      description,
      budget_min_amount: budgetMin || '0.00',
      budget_max_amount: budgetMax || '0.00',
      // Keep the business deadline as the user's local wall-clock time. The
      // transaction API stores naive datetimes, so converting to UTC here
      // would make the value render eight hours earlier on the next screen.
      desired_delivery_at: deadline || null,
      visibility,
      confidentiality_level: confidentialityLevel,
      invite_limit: inviteLimit,
      deliverables: deliverables.filter((item) => item.name.trim()),
      acceptance_criteria: criteria.filter((item) => item.trim()),
      attachments: attachments.map((item) => item.file_id ? {
        file_id: item.file_id,
        filename: item.filename,
        content_type: item.content_type,
        size: item.size,
        sha256: item.sha256,
      } : {
        id: item.id,
        name: item.filename,
        content_type: item.content_type,
        size: item.size,
        kind: item.kind,
        data_url: item.data_url,
        visibility,
      }),
    };
  }

  async function save(publish: boolean) {
    const input = buildInput(publish);
    if (!input) return;
    if (publish && !window.confirm('确认发布需求并由平台执行 AI 匹配、向候选服务商发送邀请？')) return;
    setSaving(true);
    try {
      const created = await marketplaceRepository.createRequirement(input);
      let handoffWarning = '';
      if (draftId && draftResponse && appliedDraftVersion !== null) {
        try {
          await marketplaceRepository.auditAssistantRequirementHandoff(draftId, {
            protocol_version: '1.0',
            draft_version: appliedDraftVersion,
            transaction_requirement_id: created.id,
            requirement_write: input,
            idempotency_key: `req-handoff-${draftId}-${appliedDraftVersion}-${created.id}`,
          });
        } catch (error) {
          handoffWarning = error instanceof Error ? error.message : '交接审计记录失败';
        }
      }
      const result = publish
        ? await marketplaceRepository.publishRequirement(created.id, input.organization_id)
        : created;
      notify.success(publish ? `需求已发布，已邀请 ${result.invitationCount} 家服务商` : '需求草稿已保存');
      if (handoffWarning) {
        notify.warning(`需求已${publish ? '发布' : '保存'}，但开小花交接审计未写入：${handoffWarning}`);
      }
      navigate(`/enterprise/demands/${result.id}`);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '保存需求失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="marketplace-page marketplace-management-page transaction-page">
      <MarketplaceHeader
        breadcrumb={<button type="button" className="marketplace-breadcrumb" onClick={() => navigate('/enterprise/demands')}><ArrowLeft /><strong>发布需求</strong><span>平台 AI 将匹配合适服务方，报价需服务方确认</span></button>}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <div className="transaction-steps"><span className="is-active"><b>1</b>描述需求</span><span><b>2</b>交付与验收</span><span><b>3</b>预算与周期</span><span><b>4</b>预览发布</span></div>
      <section className="transaction-ai-workspace" aria-labelledby="ai-requirement-entry-title">
        <span className="sr-only" id="ai-requirement-entry-title">AI 需求解析与自动填表</span>
        <div className="transaction-ai-composer">
          <span className="transaction-ai-requirement-icon" aria-hidden="true"><Sparkles /></span>
          <label className="transaction-ai-composer-field">
            <span className="sr-only">自然语言描述需求</span>
            <textarea
              aria-label="自然语言描述需求"
              value={aiBrief}
              maxLength={1000}
              placeholder="描述你想完成的任务，例如：为制造业客户制作一份面向投资人的融资路演 PPT，两周内交付。"
              onChange={(event) => setAiBrief(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="transaction-ai-analyze-button"
            disabled={!aiBrief.trim()}
            onClick={() => openKaiAssistant({
              view: 'chat',
              autoSend: true,
              startNewWorkflow: true,
              entrypoint: 'requirement.create',
              prompt: `我想发布一个需求：${aiBrief.trim()}。请直接分析所属行业、内容要求、交付规范和验收标准，主动扩写为完整可编辑草稿并填入需求表单。不要让我重复填写已能合理生成的软性内容；只对无法安全推断的硬信息保留待确认。`,
            })}
          >AI 解析</button>
        </div>
        {draftId ? (
          <AssistantDraftStatus
            state={draftLoadState}
            error={draftError}
            response={draftResponse}
            appliedVersion={appliedDraftVersion}
            onRetry={() => setLoadAttempt((value) => value + 1)}
            onReview={() => focusPublishField('title')}
            onEditField={reviewAssistantField}
          />
        ) : null}
      </section>
      <div className="transaction-editor-layout">
        <div className="transaction-form-stack">
          {validationErrors.length > 0 ? (
            <section className="transaction-validation-summary" role="alert" aria-labelledby="publish-validation-title">
              <div><strong id="publish-validation-title">还不能发布，请补充以下信息</strong><small>草稿仍然可以保存。</small></div>
              <ul>{validationErrors.map((item) => <li key={item.field}><button type="button" onClick={() => focusPublishField(item.field)}>{item.label}：{item.message}</button></li>)}</ul>
            </section>
          ) : null}
          <section className="transaction-card" data-publish-field="title">
            <h2>需求基本信息</h2>
            <label><span>需求标题 *</span><input aria-invalid={hasError(validationErrors, 'title')} value={title} maxLength={100} onChange={(event) => editField('title', event.target.value)} />{errorText(validationErrors, 'title')}</label>
            <div className="marketplace-form-grid">
              <label data-publish-field="category">
                <span>业务分类 *</span>
                <select aria-label="业务分类 *" aria-invalid={hasError(validationErrors, 'category')} value={categoryId || category} onChange={(event) => editCategory(event.target.value)}>
                  <option value="">请选择业务分类</option>
                  {categoryGroups.map((group) => (
                    <optgroup key={group.root.id} label={group.root.name}>
                      {group.options.map(({ category: item, depth }) => (
                        <option key={item.id} value={item.id}>{depth ? `${'　'.repeat(depth - 1)}↳ ${item.name}` : item.name}</option>
                      ))}
                    </optgroup>
                  ))}
                  {useLegacyCategoryFallback
                    ? LEGACY_CATEGORIES.map((item) => <option key={item} value={item}>{item}</option>)
                    : <optgroup label="兼容分类（无目录 ID）">
                      {LEGACY_CATEGORIES.map((item) => <option key={item} value={item}>{item}</option>)}
                    </optgroup>}
                  {categoryId && !activeCategories.some((item) => item.id === categoryId)
                    ? <option value={categoryId}>{category}</option>
                    : null}
                  {category && !categoryId && !LEGACY_CATEGORIES.includes(category)
                    ? <option value={category}>{category}</option>
                    : null}
                </select>
                {errorText(validationErrors, 'category')}
                {categoryLoadState === 'error' ? <small role="status">分类目录暂时不可用，已保留当前分类并启用兼容选项。</small> : null}
              </label>
              <label><span>可见范围 *</span><select value={visibility} onChange={(event) => editField('visibility', event.target.value as RequirementInput['visibility'])}><option value="invited_providers">仅受邀服务方可见</option><option value="enterprise">企业内部</option><option value="public">公开</option></select></label>
              <label><span>保密等级 *</span><select value={confidentialityLevel} onChange={(event) => editField('confidentialityLevel', event.target.value as RequirementInput['confidentiality_level'])}><option value="standard">标准</option><option value="confidential">保密</option><option value="highly_confidential">高度保密</option></select></label>
            </div>
            <label data-publish-field="description"><span>详细描述 *</span><textarea aria-invalid={hasError(validationErrors, 'description')} value={description} maxLength={5000} onChange={(event) => editField('description', event.target.value)} />{errorText(validationErrors, 'description')}</label>
            <div className="transaction-upload">
              <div><strong>输入材料</strong><small>支持文档、PDF、表格、图片；材料随需求版本冻结。</small></div>
              <label className="marketplace-secondary-button"><Paperclip />{uploading ? '上传中…' : '添加附件'}<input type="file" multiple hidden disabled={uploading} onChange={(event) => void onFiles(event)} /></label>
            </div>
            {attachments.map((item) => <div className="transaction-file-row" key={item.id}><FileText /><span><strong>{item.filename}</strong><small>{formatBytes(item.size)}</small></span><Check /><button type="button" aria-label="移除附件" onClick={() => editField('attachments', attachments.filter((row) => row.id !== item.id))}><Trash2 /></button></div>)}
          </section>
          <section className="transaction-card" data-publish-field="deliverables">
            <h2>期望交付物</h2>
            <div className="transaction-deliverable-table">
              {deliverables.map((item, index) => <div key={`${item.name}-${index}`}><b>{index + 1}</b><input value={item.name} onChange={(event) => editField('deliverables', deliverables.map((row, rowIndex) => rowIndex === index ? { ...row, name: event.target.value } : row))} /><select value={item.format} onChange={(event) => editField('deliverables', deliverables.map((row, rowIndex) => rowIndex === index ? { ...row, format: event.target.value } : row))}><option>.pptx</option><option>.ppt</option><option>.xlsx</option><option>.docx</option><option>.pdf</option><option>链接</option>{!KNOWN_FORMATS.has(item.format) ? <option value={item.format}>{item.format}</option> : null}</select><label><input type="checkbox" checked={item.required} onChange={(event) => editField('deliverables', deliverables.map((row, rowIndex) => rowIndex === index ? { ...row, required: event.target.checked } : row))} />必需</label><button type="button" onClick={() => editField('deliverables', deliverables.filter((_, rowIndex) => rowIndex !== index))}><Trash2 /></button></div>)}
            </div>
            <button type="button" className="marketplace-link-button" onClick={() => editField('deliverables', [...deliverables, { name: '', format: '.docx', required: true }])}><Plus />添加交付物</button>
            {errorText(validationErrors, 'deliverables')}
          </section>
          <section className="transaction-card" data-publish-field="criteria">
            <h2>验收要求</h2>
            {criteria.map((item, index) => <div className="transaction-criterion" key={index}><Check /><input value={item} onChange={(event) => editField('criteria', criteria.map((row, rowIndex) => rowIndex === index ? event.target.value : row))} /><button type="button" onClick={() => editField('criteria', criteria.filter((_, rowIndex) => rowIndex !== index))}><Trash2 /></button></div>)}
            <button type="button" className="marketplace-link-button" onClick={() => editField('criteria', [...criteria, ''])}><Plus />添加验收要求</button>
            {errorText(validationErrors, 'criteria')}
          </section>
        </div>
        <aside className="transaction-side-stack">
          <section className="transaction-card">
            <h2>信息完整度 <ShieldCheck /></h2>
            <strong className="transaction-completeness">{completeness}%</strong>
            <div className="transaction-progress"><span style={{ width: `${completeness}%` }} /></div>
            <small>{completeness === 100 ? '需求信息已完整，可以发布' : '请继续补充必填信息'}</small>
            {publishErrors.length > 0 ? <ul className="transaction-missing-list">{publishErrors.map((item) => <li key={item.field}>{item.label}</li>)}</ul> : null}
          </section>
          <section className="transaction-card transaction-budget-card">
            <h2>预算与邀请设置</h2>
            <div className="marketplace-form-grid"><label><span>预算下限</span><input type="number" min="0" value={budgetMin} onChange={(event) => editField('budgetMin', event.target.value)} /></label><label data-publish-field="budgetMax"><span>预算上限</span><input aria-invalid={hasError(validationErrors, 'budgetMax')} type="number" min="1" value={budgetMax} onChange={(event) => editField('budgetMax', event.target.value)} />{errorText(validationErrors, 'budgetMax')}</label></div>
            <label data-publish-field="deadline"><span>期望完成时间</span><input aria-invalid={hasError(validationErrors, 'deadline')} type="datetime-local" value={deadline} onChange={(event) => editField('deadline', event.target.value)} />{errorText(validationErrors, 'deadline')}</label>
            <label><span>最多邀请服务商</span><input type="number" min="1" max="20" value={inviteLimit} onChange={(event) => editField('inviteLimit', Number(event.target.value))} /></label>
            <button type="button" className="marketplace-submit-button" disabled={saving} onClick={() => void save(true)}>{saving ? '发布中…' : '预览并发布'}</button>
            <button type="button" className="marketplace-secondary-button" disabled={saving} onClick={() => void save(false)}>保存草稿</button>
          </section>
          <section className="transaction-card transaction-privacy-note"><LockKeyhole /><div><strong>AI 隐私与安全</strong><p>材料只提供给受邀服务方；内部提示词、知识库、密钥和成本不会向采购方公开。</p></div></section>
        </aside>
      </div>
    </main>
  );
}

const LEGACY_CATEGORIES = ['法律 / 合同审查', 'IT 运维', '财务分析', '人才招聘', '客户服务', '投标文件'];
const KNOWN_FORMATS = new Set(['.pptx', '.ppt', '.xlsx', '.docx', '.pdf', '链接']);

function requirementPublishErrors(form: DemandFormState): PublishError[] {
  const checks: Array<[PublishField, string, boolean, string]> = [
    ['title', '需求标题', form.title.trim().length >= 4, '至少填写 4 个字符'],
    ['category', '业务分类', form.category.trim().length >= 2, '请选择平台业务分类'],
    ['description', '详细描述', form.description.trim().length >= 20, '至少填写 20 个字符'],
    ['budgetMax', '预算上限', Number(form.budgetMax) > 0, '请填写有效预算上限'],
    ['deadline', '期望完成时间', Boolean(form.deadline), '请选择期望完成时间'],
    ['deliverables', '期望交付物', form.deliverables.some((item) => item.name.trim()), '至少添加一个有名称的交付物'],
    ['criteria', '验收要求', form.criteria.some((item) => item.trim()), '至少添加一项验收要求'],
  ];
  return checks
    .filter(([, , complete]) => !complete)
    .map(([field, label, , message]) => ({ field, label, message }));
}

function hasError(errors: PublishError[], field: PublishField) {
  return errors.some((item) => item.field === field);
}

function errorText(errors: PublishError[], field: PublishField) {
  const error = errors.find((item) => item.field === field);
  return error ? <small className="transaction-field-error">{error.message}</small> : null;
}

function focusPublishField(field: PublishField) {
  requestAnimationFrame(() => {
    const container = document.querySelector<HTMLElement>(`[data-publish-field="${field}"]`);
    if (typeof container?.scrollIntoView === 'function') {
      container.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    (container?.matches('input, textarea, select, button')
      ? container
      : container?.querySelector<HTMLElement>('input, textarea, select, button'))?.focus();
  });
}

function buildCategoryGroups(categories: ServiceCategory[]) {
  const sorted = [...categories].sort(compareCategory);
  const byParent = new Map<string | null, ServiceCategory[]>();
  const byId = new Map(sorted.map((item) => [item.id, item]));
  sorted.forEach((item) => {
    const parentId = item.parentId && byId.has(item.parentId) ? item.parentId : null;
    byParent.set(parentId, [...(byParent.get(parentId) || []), item]);
  });
  const roots = byParent.get(null) || [];
  return roots.map((root) => ({
    root,
    options: flattenCategoryBranch(root, byParent),
  }));
}

function flattenCategoryBranch(
  category: ServiceCategory,
  byParent: ReadonlyMap<string | null, ServiceCategory[]>,
  depth = 0,
): Array<{ category: ServiceCategory; depth: number }> {
  return [
    { category, depth },
    ...(byParent.get(category.id) || []).flatMap((child) => flattenCategoryBranch(child, byParent, depth + 1)),
  ];
}

function compareCategory(left: ServiceCategory, right: ServiceCategory) {
  return left.sortOrder - right.sortOrder || left.name.localeCompare(right.name, 'zh-CN');
}

function isValidAssistantRequirementDraft(
  value: AssistantRequirementDraftResponse,
  expectedDraftId: string,
) {
  return value?.protocol_version === '1.0'
    && value.draft?.draft_id === expectedDraftId
    && Number.isInteger(value.draft.draft_version)
    && value.draft.draft_version > 0
    && Array.isArray(value.draft.missing_fields)
    && Boolean(value.form_seed && typeof value.form_seed === 'object')
    && Array.isArray(value.warnings)
    && Array.isArray(value.handoff?.blockers);
}

function preserveUserEdits(
  current: DemandFormState,
  seeded: DemandFormState,
  edited: ReadonlySet<EditableField>,
) {
  const next = { ...seeded };
  edited.forEach((field) => {
    // Each field is restored from the same DemandFormState shape. Keeping this
    // assignment here makes a delayed or retried draft request unable to erase
    // input the user has already changed.
    Object.assign(next, { [field]: current[field] });
  });
  return next;
}

function AssistantDraftStatus({
  state,
  error,
  response,
  appliedVersion,
  onRetry,
  onReview,
  onEditField,
}: {
  state: DraftLoadState;
  error: string;
  response: AssistantRequirementDraftResponse | null;
  appliedVersion: number | null;
  onRetry: () => void;
  onReview: () => void;
  onEditField: (field: string) => void;
}) {
  if (state === 'loading') {
    return <section className="transaction-ai-readiness is-status-only" aria-live="polite"><Sparkles /><div><strong>正在读取 AI 草稿</strong><p>解析结果准备好后会自动填入下方表单。</p></div></section>;
  }
  if (state === 'error') {
    return <section className="transaction-ai-readiness is-status-only is-error" role="alert"><div><strong>AI 草稿读取失败</strong><p>{error}；你可以继续手工填写，或重试读取。</p></div><button type="button" className="marketplace-secondary-button" onClick={onRetry}>重试</button></section>;
  }
  if (state !== 'ready' || !response) return null;
  const latestVersion = response.draft.draft_version;
  const versionChanged = appliedVersion !== null && latestVersion !== appliedVersion;
  const warnings = response.warnings || [];
  const recognized = assistantRecognizedItems(response);
  const expanded = assistantExpandedSummary(response);
  const pending = assistantPendingItems(response);
  const filledCount = assistantFilledFieldCount(response);
  return (
    <section className="transaction-ai-readiness" aria-live="polite">
      <span className="sr-only">开小花需求草稿 v{appliedVersion ?? latestVersion}</span>
      <div className="transaction-ai-result-group is-recognized">
        <strong>AI 已识别</strong>
        <div className="transaction-ai-fact-list">
          {recognized.map((item) => (
            <button type="button" key={`${item.field}-${item.value}`} onClick={() => onEditField(item.field)} aria-label={`修改${item.label}：${item.value}`}>
              <span>{item.value}</span><PencilLine />
            </button>
          ))}
        </div>
      </div>
      <div className="transaction-ai-result-group is-expanded">
        <strong>AI 已扩写</strong>
        <p>{expanded || '已根据行业规范补全服务范围、交付物与验收要求'}</p>
      </div>
      <div className="transaction-ai-result-group is-pending">
        <strong>仍需确认</strong>
        <div>{pending.length ? pending.map((item) => (
          <button type="button" key={`${item.field}-${item.label}`} onClick={() => onEditField(item.field)}>{item.label}</button>
        )) : <span className="is-complete">无需补充</span>}</div>
      </div>
      <div className="transaction-ai-result-group is-action">
        <strong>已自动填入 {filledCount} 项</strong>
        <button type="button" onClick={onReview}>检查已填表单</button>
        <button type="button" className="transaction-ai-text-button" onClick={onReview}>查看完整草稿</button>
      </div>
      {versionChanged || warnings.length ? (
        <div className="transaction-ai-result-notes">
          {versionChanged ? <p>检测到 v{latestVersion}，为保护你当前编辑的内容，未自动覆盖。</p> : null}
          {warnings.map((item) => <p key={`${item.field}-${item.code}`}>{item.message}</p>)}
        </div>
      ) : null}
    </section>
  );
}

type AssistantDraftDisplayItem = { field: string; label: string; value: string };

function assistantRecognizedItems(response: AssistantRequirementDraftResponse): AssistantDraftDisplayItem[] {
  const directSources = new Set(['user_message', 'user_choice', 'user_edit', 'attachment_extraction']);
  const preferred = ['title', 'category', 'target_audience', 'use_scenario', 'schedule']
    .flatMap((field) => {
      const value = assistantDraftFieldValue(response, field);
      return value ? [{ field, label: requirementDraftFieldLabel(field), value }] : [];
    });
  const direct = Object.entries(response.field_sources)
    .filter(([, source]) => directSources.has(source.source))
    .filter(([field]) => !preferred.some((item) => item.field === field))
    .flatMap(([field]) => {
      const value = assistantDraftFieldValue(response, field);
      return value ? [{ field, label: requirementDraftFieldLabel(field), value }] : [];
    });
  return [...preferred, ...direct].slice(0, 4);
}

function assistantExpandedSummary(response: AssistantRequirementDraftResponse) {
  const priorityFields = ['service_scope', 'deliverables', 'acceptance_criteria', 'goal', 'background', 'risks'];
  const expandedFields = priorityFields.filter((field) => response.field_sources[field]?.source === 'ai_expansion');
  const fields = expandedFields.length ? expandedFields : priorityFields;
  const fragments = fields.flatMap((field) => assistantDraftFieldFragments(response, field));
  return truncateText([...new Set(fragments)].slice(0, 6).join('、'), 150);
}

function assistantPendingItems(response: AssistantRequirementDraftResponse) {
  const excluded = new Set(['currency', 'visibility', 'invite_limit', 'confidentiality_level', 'budget_min']);
  const issueFields = [...response.warnings, ...response.handoff.blockers].map((item) => (
    item.field === 'desired_delivery_at' || item.message.includes('desired_delivery_at') || item.message.includes('相对工期')
      ? 'schedule'
      : item.field
  ));
  const fields = [...(response.draft.missing_fields || []), ...issueFields]
    .filter((item) => !item.startsWith('field_source:'))
    .map((item) => item.replace('confirmation:', ''))
    .filter((item) => !excluded.has(item));
  const normalized = fields.map((field) => field === 'budget_max'
    ? { field, label: '预算范围' }
    : { field, label: requirementDraftFieldLabel(field) });
  return normalized
    .filter((item, index) => normalized.findIndex((candidate) => candidate.label === item.label) === index)
    .slice(0, 3);
}

function assistantFilledFieldCount(response: AssistantRequirementDraftResponse) {
  const seed = response.form_seed;
  return [
    seed.title,
    seed.category,
    seed.description,
    seed.budget_min_amount || seed.budget_max_amount,
    seed.desired_delivery_at,
    seed.deliverables?.length,
    seed.acceptance_criteria?.length,
    seed.attachments?.length,
  ].filter(Boolean).length;
}

function assistantDraftFieldValue(response: AssistantRequirementDraftResponse, field: string) {
  const fragments = assistantDraftFieldFragments(response, field);
  return truncateText(fragments.join('、'), 34);
}

function assistantDraftFieldFragments(response: AssistantRequirementDraftResponse, field: string): string[] {
  const value = response.draft[field] ?? ({
    title: response.form_seed.title,
    category: response.form_seed.category,
    schedule: response.form_seed.desired_delivery_at,
    deliverables: response.form_seed.deliverables,
    acceptance_criteria: response.form_seed.acceptance_criteria,
  } as Record<string, unknown>)[field];
  if (typeof value === 'string') return value.trim() ? [formatAssistantDraftText(field, value)] : [];
  if (typeof value === 'number') return [String(value)];
  if (Array.isArray(value)) {
    return value.flatMap((item) => {
      if (typeof item === 'string') return item.trim() ? [item.trim()] : [];
      if (item && typeof item === 'object' && 'name' in item && typeof item.name === 'string') return [item.name];
      return [];
    });
  }
  if (value && typeof value === 'object' && 'kind' in value) {
    const schedule = value as { kind?: unknown; local_datetime?: unknown; duration?: unknown; unit?: unknown };
    if (schedule.kind === 'deadline' && typeof schedule.local_datetime === 'string') return [formatAssistantDraftText('schedule', schedule.local_datetime)];
    if (schedule.kind === 'duration' && typeof schedule.duration === 'number') {
      const unit = ({ hour: '小时', calendar_day: '天', business_day: '个工作日', week: '周' } as Record<string, string>)[String(schedule.unit)] || '';
      return [`${schedule.duration}${unit}`];
    }
  }
  return [];
}

function formatAssistantDraftText(field: string, value: string) {
  if (field !== 'schedule') return value;
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[1]}年${Number(match[2])}月${Number(match[3])}日` : value;
}

function truncateText(value: string, maximum: number) {
  return value.length > maximum ? `${value.slice(0, maximum - 1)}…` : value;
}

function requirementDraftFieldLabel(value: string) {
  const key = value.replace('confirmation:', '').replace('field_source:', '');
  return ({
    organization_id: '发布企业', title: '需求标题', category: '业务分类', background: '项目背景',
    goal: '项目目标', target_audience: '目标受众', use_scenario: '使用场景',
    target_audience_or_use_scenario: '目标受众或使用场景', service_scope: '服务范围',
    exclusions: '排除项', risks: '风险与规范', dependencies: '依赖材料', budget_min: '预算下限',
    budget_max: '预算上限', schedule: '期望完成时间', visibility: '可见范围', invite_limit: '邀请数量',
    desired_delivery_at: '期望完成时间',
    confidentiality_level: '保密等级', deliverables: '交付物', acceptance_criteria: '验收标准', attachments: '附件',
  } as Record<string, string>)[key] || key;
}

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))}KB`;
  return `${(value / 1024 / 1024).toFixed(1)}MB`;
}
