import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Circle,
  Code2,
  FileArchive,
  LoaderCircle,
  UploadCloud,
  Save,
  Send,
  ShieldCheck,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { SkillDraftInput } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

const defaultInputSchema = JSON.stringify([
  {
    name: 'input',
    type: 'object',
    required: true,
    description: '当前调用的结构化输入',
    example: '{}',
  },
], null, 2);
const defaultOutputSchema = JSON.stringify([
  {
    name: 'result',
    type: 'object',
    required: true,
    description: 'Skill 结构化执行结果',
    example: '{}',
  },
], null, 2);
const defaultPermissions = JSON.stringify([
  {
    key: 'read_task_input',
    label: '读取本次任务输入',
    level: 'allow',
    detail: '仅允许读取当前调用明确授权的数据',
  },
], null, 2);

const emptyForm = {
  name: '',
  category: '企业服务',
  description: '',
  version: 'v1.0.0',
  visibility: 'public' as 'public' | 'private',
  runtime: '外部 Agent' as SkillDraftInput['runtime'],
  language: 'Python',
  weight: '轻量' as SkillDraftInput['weight'],
  price: '0',
  priceUnit: '次',
  sourceUri: '',
  packageDigest: '',
  packageVersionId: '',
  packageStatus: '',
  packageScanStatus: '',
  packageRiskLevel: '',
  packageSlug: '',
  entrypoint: 'main.py',
  inputSchema: defaultInputSchema,
  outputSchema: defaultOutputSchema,
  permissions: defaultPermissions,
  networkPolicy: '无公网访问',
  retentionPolicy: '任务结束后立即清理',
  webhookUrl: '',
  changeSummary: '创建 Skill 草稿',
};

export default function PublishSkillPage() {
  const navigate = useNavigate();
  const { skillId = 'new' } = useParams();
  const isNew = skillId === 'new';
  const organization = useMarketplaceOrganization();
  const [form, setForm] = useState(emptyForm);
  const [savedId, setSavedId] = useState(isNew ? '' : skillId);
  const [editorStatus, setEditorStatus] = useState('draft');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [schemaError, setSchemaError] = useState('');

  const editor = useMarketplaceResource(
    () => !isNew && organization.selected
      ? marketplaceRepository.getSkillEditor(skillId, organization.selected.id)
      : Promise.resolve(null),
    `publish-skill-editor:${skillId}:${organization.selected?.id || 'none'}`,
  );

  useEffect(() => {
    if (!editor.data) return;
    const data = editor.data.data as Record<string, unknown>;
    setEditorStatus(editor.data.status);
    setForm({
      name: String(data.name || ''),
      category: String(data.category || ''),
      description: String(data.description || ''),
      version: String(data.version || editor.data.version),
      visibility: data.visibility === 'private' ? 'private' : 'public',
      runtime: data.runtime === '远程 API' ? '远程 API' : data.runtime === '平台托管' ? '平台托管' : '外部 Agent',
      language: String(data.language || 'Python'),
      weight: data.weight === '标准' ? '标准' : '轻量',
      price: String(data.price ?? 0),
      priceUnit: String(data.priceUnit || '次'),
      sourceUri: String(data.sourceUri || ''),
      packageDigest: String(data.packageDigest || ''),
      packageVersionId: String(data.packageVersionId || ''),
      packageStatus: String(data.packageStatus || ''),
      packageScanStatus: String(data.packageScanStatus || ''),
      packageRiskLevel: String(data.packageRiskLevel || ''),
      packageSlug: slugify(String(data.name || '')),
      entrypoint: String(data.entrypoint || ''),
      inputSchema: JSON.stringify(data.inputSchema || [], null, 2),
      outputSchema: JSON.stringify(data.outputSchema || [], null, 2),
      permissions: JSON.stringify(data.permissions || [], null, 2),
      networkPolicy: String(data.networkPolicy || '无公网访问'),
      retentionPolicy: String(data.retentionPolicy || '任务结束后立即清理'),
      webhookUrl: String(data.webhookUrl || ''),
      changeSummary: String(data.changeSummary || '更新 Skill 版本'),
    });
  }, [editor.data]);

  const checks = useMemo(() => {
    const digestValid = /^(sha256:)?[a-fA-F0-9]{64}$/.test(form.packageDigest);
    const packageReady = form.runtime === '远程 API'
      ? Boolean(form.sourceUri.trim() && digestValid)
      : Boolean(form.packageVersionId && form.packageScanStatus === 'passed');
    return [
      { label: '基本资料完整', ok: Boolean(form.name.trim() && form.category && form.description.trim()) },
      { label: form.runtime === '远程 API' ? '远程地址与 SHA-256 已填写' : '真实包已上传且安全扫描通过', ok: packageReady },
      { label: '入口点和运行时已声明', ok: Boolean(form.entrypoint.trim() && form.runtime) },
      { label: '输入输出 Schema 可解析', ok: schemasValid(form.inputSchema, form.outputSchema, form.permissions) },
      { label: '权限与数据保留策略已声明', ok: Boolean(form.permissions.trim() && form.retentionPolicy.trim()) },
    ];
  }, [form]);
  const ready = checks.every((item) => item.ok);
  const canSubmit = ready && (form.runtime === '远程 API' || form.packageStatus === 'approved');
  const readonly = editorStatus === 'pending_review';

  function payload(): SkillDraftInput {
    if (!organization.selected) throw new Error('请先选择企业');
    try {
      setSchemaError('');
      return {
        organization_id: organization.selected.id,
        name: form.name,
        category: form.category,
        description: form.description,
        version: form.version,
        visibility: form.visibility,
        runtime: form.runtime,
        language: form.language,
        weight: form.weight,
        price: Number(form.price),
        price_unit: form.priceUnit,
        source_uri: form.sourceUri,
        package_digest: form.packageDigest,
        package_version_id: form.packageVersionId || undefined,
        entrypoint: form.entrypoint,
        input_schema: JSON.parse(form.inputSchema) as Array<Record<string, unknown>>,
        output_schema: JSON.parse(form.outputSchema) as Array<Record<string, unknown>>,
        permissions: JSON.parse(form.permissions) as Array<Record<string, unknown>>,
        network_policy: form.networkPolicy,
        retention_policy: form.retentionPolicy,
        webhook_url: form.webhookUrl || undefined,
        change_summary: form.changeSummary,
      };
    } catch {
      setSchemaError('Schema 或权限清单不是有效 JSON');
      throw new Error('请修正 JSON 配置');
    }
  }

  async function uploadPackage(file: File) {
    if (!organization.selected) {
      notify.error('请先选择发布企业');
      return;
    }
    if (!form.name.trim() || !form.version.trim() || !form.entrypoint.trim()) {
      notify.error('请先填写 Skill 名称、版本号和入口点');
      return;
    }
    setUploading(true);
    try {
      const permissionItems = JSON.parse(form.permissions) as Array<Record<string, unknown>>;
      const inputSchema = JSON.parse(form.inputSchema) as Array<Record<string, unknown>>;
      const outputSchema = JSON.parse(form.outputSchema) as Array<Record<string, unknown>>;
      const result = await marketplaceRepository.uploadSkillPackage({
        organizationId: organization.selected.id,
        slug: form.packageSlug || slugify(form.name),
        name: form.name,
        version: form.version,
        runtime: form.language.toLowerCase().includes('node') ? 'node' : 'python',
        entrypoint: form.entrypoint,
        manifest: { input_schema: inputSchema, output_schema: outputSchema },
        permissions: {
          items: permissionItems,
          network: form.networkPolicy.includes('无公网') ? 'deny' : 'review',
        },
        executionPolicy: form.runtime === '平台托管' ? 'hosted' : 'external',
        file,
      });
      setForm((current) => ({
        ...current,
        sourceUri: result.sourceUri,
        packageDigest: result.digest,
        packageVersionId: result.id,
        packageStatus: result.status,
        packageScanStatus: result.scanStatus,
        packageRiskLevel: result.riskLevel,
      }));
      if (result.scanStatus === 'passed') notify.success('Skill 包已上传并通过静态安全扫描');
      else notify.error('Skill 包安全扫描未通过，请查看扫描结果后修复');
    } catch (error) {
      notify.error(error instanceof Error ? error.message : 'Skill 包上传失败');
    } finally {
      setUploading(false);
    }
  }

  async function saveDraft(showNotice = true) {
    if (!ready) {
      notify.error('请先补齐发布前检查中的必填信息');
      return null;
    }
    setSaving(true);
    try {
      const input = payload();
      const result = savedId
        ? await marketplaceRepository.updateSkillDraft(savedId, input)
        : await marketplaceRepository.createSkillDraft(input);
      setSavedId(result.id);
      setEditorStatus(result.status);
      if (showNotice) notify.success('Skill 草稿已保存');
      if (isNew) navigate(`/enterprise/publishing/skills/${result.id}`, { replace: true });
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
    if (!draft || !organization.selected) return;
    setSaving(true);
    try {
      await marketplaceRepository.submitSkillReview(draft.id, organization.selected.id);
      setEditorStatus('pending_review');
      notify.success('Skill 已提交安全与市场审核');
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
        breadcrumb={<button type="button" className="marketplace-breadcrumb" onClick={() => navigate('/enterprise/publishing')}><ArrowLeft />我的发布 / <strong>{isNew ? '发布Skill' : form.name || '编辑Skill'}</strong></button>}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={<button type="button" className="marketplace-secondary-button" disabled={saving || readonly} onClick={() => void saveDraft()}><Save />保存草稿</button>}
      />

      <div className="marketplace-stepper">
        {['基本信息', '接口与版本', '权限清单', '测试验证', '定价与协议', '提交审核'].map((step, index) => <span className={index <= 1 ? 'is-active' : ''} key={step}><b>{index + 1}</b>{step}</span>)}
      </div>

      <MarketplaceState loading={!isNew && editor.loading} error={editor.error} onRetry={editor.reload} />

      {(isNew || !editor.loading) && (
        <div className="marketplace-skill-editor-layout">
          <section className="marketplace-editor-main">
            {readonly && <div className="marketplace-review-banner"><ShieldCheck />该版本正在平台进行安全与市场审核，暂不可修改。</div>}
            <EditorSection title="接口与版本配置" subtitle="每次提交审核都会冻结版本、包摘要和权限清单">
              <div className="marketplace-form-grid marketplace-form-grid--three">
                <Field label="Skill 名称 *" value={form.name} disabled={readonly} onChange={(value) => setForm({ ...form, name: value })} />
                <Field label="分类 *" value={form.category} disabled={readonly} onChange={(value) => setForm({ ...form, category: value })} />
                <Field label="版本号 *" value={form.version} disabled={readonly} onChange={(value) => setForm({ ...form, version: value })} />
              </div>
              <label><span>一句话介绍 *</span><textarea disabled={readonly} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
              <div className="marketplace-form-grid">
                <label><span>运行方式</span><select disabled={readonly || Boolean(form.packageVersionId)} value={form.runtime} onChange={(event) => setForm({ ...form, runtime: event.target.value as SkillDraftInput['runtime'] })}><option value="外部 Agent">外部 Agent（推荐）</option><option value="远程 API">远程 API</option><option value="平台托管">平台托管（需启用沙箱）</option></select></label>
                <label><span>可见范围</span><select disabled={readonly} value={form.visibility} onChange={(event) => setForm({ ...form, visibility: event.target.value as 'public' | 'private' })}><option value="public">公开市场</option><option value="private">企业私有</option></select></label>
              </div>
              <div className="marketplace-package-box">
                <FileArchive />
                <div><strong>{form.runtime === '远程 API' ? '远程 API 来源' : '不可变 Skill ZIP 包'}</strong><small>{form.runtime === '远程 API' ? '登记可审计来源与摘要，不把外部 Agent 源码搬到平台执行。' : '由服务端计算 SHA-256、写入私有对象存储并执行安全扫描。'}</small></div>
              </div>
              {form.runtime !== '远程 API' && !form.packageVersionId && <div className="marketplace-form-grid"><Field label="包标识 *" value={form.packageSlug} disabled={readonly} placeholder="document-organizer" onChange={(value) => setForm({ ...form, packageSlug: slugify(value) })} /><label className="marketplace-package-upload"><span>Skill ZIP 包 *</span><input type="file" accept=".zip,application/zip" disabled={readonly || uploading} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadPackage(file); event.target.value = ''; }} /><b>{uploading ? <><LoaderCircle className="is-spinning" />正在上传并扫描</> : <><UploadCloud />选择 ZIP 并扫描</>}</b></label></div>}
              {form.runtime === '远程 API' && <Field label="来源地址 *" value={form.sourceUri} disabled={readonly} placeholder="https://agent.example.com/skill-manifest" onChange={(value) => setForm({ ...form, sourceUri: value })} />}
              {form.packageVersionId && <div className={`marketplace-review-banner ${form.packageScanStatus === 'passed' ? '' : 'is-error'}`}><ShieldCheck /><span>固定包 {form.packageDigest.slice(0, 12)}… · 扫描 {packageStatusText(form.packageScanStatus)} · 风险 {riskText(form.packageRiskLevel)} · 审核 {packageStatusText(form.packageStatus)}</span></div>}
              <div className="marketplace-form-grid">
                <Field label="包摘要（SHA-256）*" value={form.packageDigest} disabled={readonly || form.runtime !== '远程 API'} placeholder="上传后由服务端生成" onChange={(value) => setForm({ ...form, packageDigest: value })} />
                <Field label="入口点 *" value={form.entrypoint} disabled={readonly} onChange={(value) => setForm({ ...form, entrypoint: value })} />
              </div>
            </EditorSection>

            <EditorSection title="输入输出 Schema" subtitle="使用 JSON 数组声明字段名、类型、必填、描述和示例">
              {schemaError && <p className="marketplace-form-error">{schemaError}</p>}
              <div className="marketplace-form-grid">
                <label><span>输入 Schema *</span><textarea className="is-code" disabled={readonly} value={form.inputSchema} onChange={(event) => setForm({ ...form, inputSchema: event.target.value })} /></label>
                <label><span>输出 Schema *</span><textarea className="is-code" disabled={readonly} value={form.outputSchema} onChange={(event) => setForm({ ...form, outputSchema: event.target.value })} /></label>
              </div>
            </EditorSection>

            <EditorSection title="权限、安全与回调">
              <label><span>权限清单 JSON *</span><textarea className="is-code" disabled={readonly} value={form.permissions} onChange={(event) => setForm({ ...form, permissions: event.target.value })} /></label>
              <div className="marketplace-form-grid marketplace-form-grid--three">
                <Field label="网络策略" value={form.networkPolicy} disabled={readonly} onChange={(value) => setForm({ ...form, networkPolicy: value })} />
                <Field label="数据保留策略" value={form.retentionPolicy} disabled={readonly} onChange={(value) => setForm({ ...form, retentionPolicy: value })} />
                <Field label="Webhook（可选）" value={form.webhookUrl} disabled={readonly} onChange={(value) => setForm({ ...form, webhookUrl: value })} />
              </div>
              <div className="marketplace-form-grid marketplace-form-grid--three">
                <Field label="价格（元）" type="number" value={form.price} disabled={readonly} onChange={(value) => setForm({ ...form, price: value })} />
                <Field label="计价单位" value={form.priceUnit} disabled={readonly} onChange={(value) => setForm({ ...form, priceUnit: value })} />
                <Field label="版本变更摘要" value={form.changeSummary} disabled={readonly} onChange={(value) => setForm({ ...form, changeSummary: value })} />
              </div>
            </EditorSection>
          </section>

          <aside className="marketplace-editor-review">
            <section className="marketplace-management-card">
              <h2>发布预览</h2>
              <div className="marketplace-preview-card is-skill"><span><Code2 /></span><h3>{form.name || '未命名 Skill'}</h3><p>{organization.selected?.name || '当前企业'}</p><small>{form.description || '填写介绍后将在市场展示。'}</small><strong>{Number(form.price) === 0 ? '免费' : `¥${form.price}/${form.priceUnit}`}</strong></div>
            </section>
            <section className="marketplace-management-card marketplace-checklist">
              <h2>安全审核规格检查</h2>
              {checks.map((check) => <p className={check.ok ? 'is-ready' : ''} key={check.label}>{check.ok ? <CheckCircle2 /> : <Circle />}{check.label}</p>)}
              {form.runtime === '远程 API' && <div className="marketplace-risk-warning"><AlertTriangle />远程 API 将进入高风险审核，平台会核验网络白名单和数据范围。</div>}
              {form.packageVersionId && form.packageStatus !== 'approved' && <div className="marketplace-risk-warning"><AlertTriangle />固定包需先由平台完成包安全审核，之后才能提交市场上架审核。</div>}
            </section>
            <button type="button" className="marketplace-submit-button" disabled={!canSubmit || saving || readonly} onClick={() => void submitReview()}><Send />{readonly ? '平台审核中' : form.packageVersionId && form.packageStatus !== 'approved' ? '等待包安全审核' : '提交安全与市场审核'}</button>
            <p className="marketplace-submit-hint">审核通过前可以保存草稿，但不能被搜索、安装或执行。</p>
          </aside>
        </div>
      )}
    </main>
  );
}

function EditorSection({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return <section className="marketplace-management-card marketplace-editor-section"><div className="marketplace-card-heading"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div></div>{children}</section>;
}

function Field({ label, value, onChange, type = 'text', disabled, placeholder }: { label: string; value: string; onChange: (value: string) => void; type?: string; disabled?: boolean; placeholder?: string }) {
  return <label><span>{label}</span><input type={type} min={type === 'number' ? 0 : undefined} disabled={disabled} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>;
}

function schemasValid(...values: string[]) {
  try {
    return values.every((value) => Array.isArray(JSON.parse(value)));
  } catch {
    return false;
  }
}

function slugify(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 120);
}

function packageStatusText(value: string) {
  return ({ passed: '通过', failed: '未通过', pending_review: '待平台审核', pending_security_review: '待安全复核', approved: '已通过', rejected: '未通过' } as Record<string, string>)[value] || value || '待上传';
}

function riskText(value: string) {
  return ({ low: '低', medium: '中', high: '高' } as Record<string, string>)[value] || value || '-';
}
