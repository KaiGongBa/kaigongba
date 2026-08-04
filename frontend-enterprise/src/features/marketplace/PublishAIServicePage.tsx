import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  Circle,
  Save,
  Send,
  Workflow,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { AIServiceDraftInput, MarketplaceInstallTarget } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

const emptyForm = {
  agentProfileId: '',
  name: '',
  category: '企业服务',
  description: '',
  version: 'v1.0.0',
  visibility: 'public' as 'public' | 'private',
  price: '199',
  priceUnit: '次',
  averageMinutes: '60',
  includedRevisions: '1',
  deliveryFormat: '报告' as AIServiceDraftInput['delivery_format'],
  serviceScope: '需求分析\n结构化处理\n结果报告',
  exclusions: '线下驻场\n未经授权的外部系统访问',
  deliverableName: '服务交付报告',
  deliverableFormat: 'PDF',
  acceptanceCriteria: '交付内容覆盖约定服务范围\n报告结构完整且可以正常打开',
  sopVersion: '',
  dataPermissions: '只读本次任务附件\n仅写入订单交付目录',
  changeSummary: '创建服务草稿',
};

export default function PublishAIServicePage() {
  const navigate = useNavigate();
  const { serviceId = 'new' } = useParams();
  const isNew = serviceId === 'new';
  const organization = useMarketplaceOrganization();
  const [form, setForm] = useState(emptyForm);
  const [editorStatus, setEditorStatus] = useState('draft');
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState(isNew ? '' : serviceId);

  const targets = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.listInstallTargets(organization.selected.id)
      : Promise.resolve([]),
    `publish-service-targets:${organization.selected?.id || 'none'}`,
  );
  const editor = useMarketplaceResource(
    () => !isNew && organization.selected
      ? marketplaceRepository.getAIServiceEditor(serviceId, organization.selected.id)
      : Promise.resolve(null),
    `publish-service-editor:${serviceId}:${organization.selected?.id || 'none'}`,
  );

  useEffect(() => {
    if (!form.agentProfileId && targets.data?.length) {
      setForm((current) => ({ ...current, agentProfileId: targets.data?.[0]?.id || '' }));
    }
  }, [form.agentProfileId, targets.data]);

  useEffect(() => {
    if (!editor.data) return;
    const data = editor.data.data as Record<string, unknown>;
    const deliverable = (data.deliverables as Array<Record<string, string>> | undefined)?.[0];
    setEditorStatus(editor.data.status);
    setForm({
      agentProfileId: String(data.agentProfileId || ''),
      name: String(data.name || ''),
      category: String(data.category || '企业服务'),
      description: String(data.description || ''),
      version: String(data.version || editor.data.version),
      visibility: data.visibility === 'private' ? 'private' : 'public',
      price: String(data.price ?? 0),
      priceUnit: String(data.priceUnit || '次'),
      averageMinutes: String(data.averageMinutes || 60),
      includedRevisions: String(data.includedRevisions || 0),
      deliveryFormat: (data.deliveryFormat || '报告') as AIServiceDraftInput['delivery_format'],
      serviceScope: joinLines(data.serviceScope),
      exclusions: joinLines(data.exclusions),
      deliverableName: deliverable?.name || '服务交付报告',
      deliverableFormat: deliverable?.format || 'PDF',
      acceptanceCriteria: joinLines(data.acceptanceCriteria),
      sopVersion: String(data.sopVersion || ''),
      dataPermissions: joinLines(data.dataPermissions),
      changeSummary: String(data.changeSummary || '更新服务版本'),
    });
  }, [editor.data]);

  const checks = useMemo(() => [
    { label: '已绑定当前企业的 AI 员工', ok: Boolean(form.agentProfileId) },
    { label: '服务名称、分类与说明完整', ok: Boolean(form.name.trim() && form.category && form.description.trim()) },
    { label: '服务范围与排除项已声明', ok: Boolean(lines(form.serviceScope).length && lines(form.exclusions).length) },
    { label: '交付物与验收标准完整', ok: Boolean(form.deliverableName.trim() && lines(form.acceptanceCriteria).length) },
    { label: '价格、工期和修改次数有效', ok: Number(form.price) >= 0 && Number(form.averageMinutes) > 0 && Number(form.includedRevisions) >= 0 },
  ], [form]);
  const ready = checks.every((item) => item.ok);
  const selectedAgent = (targets.data || []).find((agent) => agent.id === form.agentProfileId);
  const readonly = editorStatus === 'pending_review';

  function payload(): AIServiceDraftInput {
    if (!organization.selected) throw new Error('请先选择企业');
    return {
      organization_id: organization.selected.id,
      agent_profile_id: form.agentProfileId,
      name: form.name,
      category: form.category,
      description: form.description,
      version: form.version,
      visibility: form.visibility,
      price: Number(form.price),
      price_unit: form.priceUnit,
      average_minutes: Number(form.averageMinutes),
      included_revisions: Number(form.includedRevisions),
      delivery_format: form.deliveryFormat,
      service_scope: lines(form.serviceScope),
      exclusions: lines(form.exclusions),
      deliverables: [{ name: form.deliverableName, format: form.deliverableFormat, size: '20MB以内' }],
      acceptance_criteria: lines(form.acceptanceCriteria),
      cases: [],
      sop_version: form.sopVersion || undefined,
      data_permissions: lines(form.dataPermissions),
      change_summary: form.changeSummary,
    };
  }

  async function saveDraft(showNotice = true) {
    if (!ready) {
      notify.error('请先补齐发布前检查中的必填信息');
      return null;
    }
    setSaving(true);
    try {
      const result = savedId
        ? await marketplaceRepository.updateAIServiceDraft(savedId, payload())
        : await marketplaceRepository.createAIServiceDraft(payload());
      setSavedId(result.id);
      setEditorStatus(result.status);
      if (showNotice) notify.success('服务草稿已保存');
      if (isNew) navigate(`/enterprise/publishing/services/${result.id}`, { replace: true });
      return result;
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '保存失败');
      return null;
    } finally {
      setSaving(false);
    }
  }

  async function submitReview() {
    const draft = await saveDraft(false);
    const targetId = draft?.id || savedId;
    if (!draft || !targetId || !organization.selected) return;
    setSaving(true);
    try {
      await marketplaceRepository.submitAIServiceReview(targetId, organization.selected.id);
      setEditorStatus('pending_review');
      notify.success('服务版本已提交平台审核');
      navigate('/enterprise/publishing');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '提交审核失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="marketplace-page marketplace-management-page">
      <MarketplaceHeader
        breadcrumb={<button type="button" className="marketplace-breadcrumb" onClick={() => navigate('/enterprise/publishing')}><ArrowLeft />我的发布 / <strong>{isNew ? '发布AI员工服务' : form.name || '编辑服务'}</strong></button>}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={<button type="button" className="marketplace-secondary-button" disabled={saving || readonly} onClick={() => void saveDraft()}><Save />保存草稿</button>}
      />

      <div className="marketplace-stepper">
        {['绑定AI员工', '服务信息', '范围与价格', '交付与验收', 'SOP与权限', '预览提交'].map((step, index) => <span className={index === 0 ? 'is-active' : ''} key={step}><b>{index + 1}</b>{step}</span>)}
      </div>

      <MarketplaceState loading={targets.loading || (!isNew && editor.loading)} error={targets.error || editor.error} onRetry={() => { targets.reload(); editor.reload(); }} />

      {!targets.loading && (isNew || !editor.loading) && (
        <div className="marketplace-editor-layout">
          <aside className="marketplace-editor-sidebar">
            <h2>选择已有AI员工</h2>
            <p>发布只创建商业包装，不修改原员工配置。</p>
            {(targets.data || []).map((agent) => <AgentOption agent={agent} selected={form.agentProfileId === agent.id} onClick={() => !readonly && setForm({ ...form, agentProfileId: agent.id })} key={agent.id} />)}
            {(targets.data || []).length === 0 && <div className="marketplace-inline-empty compact"><Bot /><span>当前企业暂无可发布的 AI 员工</span></div>}
            {selectedAgent && <div className="marketplace-agent-config-summary"><strong>{selectedAgent.name}</strong><span>员工档案、任务、记忆、知识库、技能、SOP 与工具继续在原 StaffDeck 工作区维护。</span></div>}
          </aside>

          <section className="marketplace-editor-main">
            {readonly && <div className="marketplace-review-banner"><ClockIcon />该版本正在平台审核，审核完成前不可修改。</div>}
            <EditorSection title="商业服务基本信息" subtitle="创建独立商业包装，不影响员工原配置">
              <div className="marketplace-form-grid">
                <Field label="商业服务名称 *" value={form.name} disabled={readonly} onChange={(value) => setForm({ ...form, name: value })} />
                <Field label="服务分类 *" value={form.category} disabled={readonly} onChange={(value) => setForm({ ...form, category: value })} />
                <Field label="公开版本 *" value={form.version} disabled={readonly} onChange={(value) => setForm({ ...form, version: value })} />
                <label><span>可见范围</span><select disabled={readonly} value={form.visibility} onChange={(event) => setForm({ ...form, visibility: event.target.value as 'public' | 'private' })}><option value="public">公开市场</option><option value="private">企业私有</option></select></label>
              </div>
              <label><span>服务简介 *</span><textarea disabled={readonly} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} placeholder="说明客户问题、处理方式和最终价值" /></label>
            </EditorSection>

            <EditorSection title="价格与交付范围" subtitle="成交订单会冻结当前版本">
              <div className="marketplace-form-grid marketplace-form-grid--four">
                <Field label="价格（元）" type="number" value={form.price} disabled={readonly} onChange={(value) => setForm({ ...form, price: value })} />
                <Field label="计价单位" value={form.priceUnit} disabled={readonly} onChange={(value) => setForm({ ...form, priceUnit: value })} />
                <Field label="预计交付（分钟）" type="number" value={form.averageMinutes} disabled={readonly} onChange={(value) => setForm({ ...form, averageMinutes: value })} />
                <Field label="免费修改次数" type="number" value={form.includedRevisions} disabled={readonly} onChange={(value) => setForm({ ...form, includedRevisions: value })} />
              </div>
              <div className="marketplace-form-grid">
                <label><span>包含范围（每行一项）</span><textarea disabled={readonly} value={form.serviceScope} onChange={(event) => setForm({ ...form, serviceScope: event.target.value })} /></label>
                <label><span>不包含范围（每行一项）</span><textarea disabled={readonly} value={form.exclusions} onChange={(event) => setForm({ ...form, exclusions: event.target.value })} /></label>
              </div>
            </EditorSection>

            <EditorSection title="交付物与验收标准">
              <div className="marketplace-form-grid">
                <Field label="交付物名称" value={form.deliverableName} disabled={readonly} onChange={(value) => setForm({ ...form, deliverableName: value })} />
                <Field label="交付格式" value={form.deliverableFormat} disabled={readonly} onChange={(value) => setForm({ ...form, deliverableFormat: value })} />
                <label><span>验收标准（每行一项）</span><textarea disabled={readonly} value={form.acceptanceCriteria} onChange={(event) => setForm({ ...form, acceptanceCriteria: event.target.value })} /></label>
                <label><span>数据权限（每行一项）</span><textarea disabled={readonly} value={form.dataPermissions} onChange={(event) => setForm({ ...form, dataPermissions: event.target.value })} /></label>
              </div>
              <div className="marketplace-form-grid">
                <Field label="冻结 SOP 版本（可选）" value={form.sopVersion} disabled={readonly} onChange={(value) => setForm({ ...form, sopVersion: value })} placeholder="例如 v1.3" />
                <Field label="版本变更摘要" value={form.changeSummary} disabled={readonly} onChange={(value) => setForm({ ...form, changeSummary: value })} />
              </div>
            </EditorSection>
          </section>

          <aside className="marketplace-editor-review">
            <section className="marketplace-management-card">
              <h2>市场卡片预览</h2>
              <div className="marketplace-preview-card"><span><Bot /></span><h3>{form.name || '未命名AI员工服务'}</h3><p>{selectedAgent?.name || '尚未绑定AI员工'}</p><small>{form.description || '填写服务介绍后将在市场展示。'}</small><strong>¥{Number(form.price || 0)}/{form.priceUnit}</strong></div>
            </section>
            <section className="marketplace-management-card marketplace-checklist">
              <h2>发布前检查</h2>
              {checks.map((check) => <p className={check.ok ? 'is-ready' : ''} key={check.label}>{check.ok ? <CheckCircle2 /> : <Circle />}{check.label}</p>)}
            </section>
            <button type="button" className="marketplace-submit-button" disabled={!ready || saving || readonly} onClick={() => void submitReview()}><Send />{readonly ? '平台审核中' : '提交平台审核'}</button>
            <p className="marketplace-submit-hint">AI 服务审核通过后才会进入公开市场；已成交订单继续引用历史快照。</p>
          </aside>
        </div>
      )}
    </main>
  );
}

function AgentOption({ agent, selected, onClick }: { agent: MarketplaceInstallTarget; selected: boolean; onClick: () => void }) {
  return <button type="button" className={`marketplace-agent-option ${selected ? 'is-selected' : ''}`} onClick={onClick}><span><Bot /></span><div><strong>{agent.name}</strong><small>{agent.description || '开工吧AI员工'}</small></div>{selected && <CheckCircle2 />}</button>;
}

function EditorSection({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return <section className="marketplace-management-card marketplace-editor-section"><div className="marketplace-card-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div></div>{children}</section>;
}

function Field({ label, value, onChange, type = 'text', disabled, placeholder }: { label: string; value: string; onChange: (value: string) => void; type?: string; disabled?: boolean; placeholder?: string }) {
  return <label><span>{label}</span><input type={type} min={type === 'number' ? 0 : undefined} disabled={disabled} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function ClockIcon() {
  return <Workflow />;
}

function lines(value: string) {
  return value.split('\n').map((item) => item.trim()).filter(Boolean);
}

function joinLines(value: unknown) {
  return Array.isArray(value) ? value.map(String).join('\n') : '';
}
