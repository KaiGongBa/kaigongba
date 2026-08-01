import { ArrowLeft, Check, FileText, LockKeyhole, Paperclip, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { useMemo, useState, type ChangeEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { TENANT_ID, uploadChatAttachments } from '@/api/client';
import type { ChatAttachmentRead } from '@/types';
import { MarketplaceHeader } from './components';
import { marketplaceRepository } from './repository';
import type { RequirementInput } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';

type DeliverableRow = { name: string; format: string; required: boolean };

const initialDeliverables: DeliverableRow[] = [
  { name: '风险清单（含风险等级与建议）', format: '.xlsx', required: true },
  { name: '带批注修订稿（显示修改痕迹）', format: '.docx', required: true },
  { name: '审查报告（结论与建议）', format: '.pdf', required: true },
];

export default function DemandCreatePage() {
  const navigate = useNavigate();
  const organization = useMarketplaceOrganization();
  const [title, setTitle] = useState('审查软件采购合同并提供修订稿');
  const [category, setCategory] = useState('法律 / 合同审查');
  const [description, setDescription] = useState('我司拟采购一套客户管理系统（SaaS 版），供应商已提供合同草案。请对合同条款进行审查，识别潜在风险与不合理条款，依据采购管理制度提出修改建议，并输出带批注修订稿与审查报告。');
  const [budgetMin, setBudgetMin] = useState('300');
  const [budgetMax, setBudgetMax] = useState('500');
  const [deadline, setDeadline] = useState('2026-08-20T18:00');
  const [visibility, setVisibility] = useState<RequirementInput['visibility']>('invited_providers');
  const [inviteLimit, setInviteLimit] = useState(5);
  const [deliverables, setDeliverables] = useState<DeliverableRow[]>(initialDeliverables);
  const [criteria, setCriteria] = useState([
    '风险识别不少于 15 项，覆盖合同核心条款并提供依据。',
    '每项风险包含条款位置、风险描述、影响评估与修改建议。',
    '修订稿保留原合同结构，使用批注或修订模式标注修改内容。',
    '审查报告不少于 2000 字，包含总体结论与关键建议。',
  ]);
  const [attachments, setAttachments] = useState<ChatAttachmentRead[]>([]);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const completeness = useMemo(() => {
    const checks = [title.length >= 4, category.length >= 2, description.length >= 20, Number(budgetMax) > 0, deadline, deliverables.length > 0, criteria.length > 0];
    return Math.round((checks.filter(Boolean).length / checks.length) * 100);
  }, [category, criteria.length, deadline, deliverables.length, description.length, budgetMax, title.length]);

  async function onFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    setUploading(true);
    try {
      const uploaded = await uploadChatAttachments<ChatAttachmentRead[]>(TENANT_ID, files);
      setAttachments((items) => [...items, ...uploaded]);
      notify.success(`已上传 ${uploaded.length} 个材料`);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '材料上传失败');
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  }

  function buildInput(): RequirementInput | null {
    if (!organization.selected) {
      notify.error('请先选择发布企业');
      return null;
    }
    if (completeness < 100) {
      notify.error('请完整填写需求、预算、交付物和验收标准');
      return null;
    }
    return {
      organization_id: organization.selected.id,
      title,
      category,
      description,
      budget_min_amount: budgetMin,
      budget_max_amount: budgetMax,
      // Keep the business deadline as the user's local wall-clock time. The
      // transaction API stores naive datetimes, so converting to UTC here
      // would make the value render eight hours earlier on the next screen.
      desired_delivery_at: deadline,
      visibility,
      invite_limit: inviteLimit,
      deliverables,
      acceptance_criteria: criteria,
      attachments: attachments.map((item) => ({
        id: item.id,
        name: item.filename,
        content_type: item.content_type,
        size: item.size,
        kind: item.kind,
        data_url: item.data_url,
        visibility,
      })),
    };
  }

  async function save(publish: boolean) {
    const input = buildInput();
    if (!input) return;
    if (publish && !window.confirm('确认发布需求并由平台执行 AI 匹配、向候选服务商发送邀请？')) return;
    setSaving(true);
    try {
      const created = await marketplaceRepository.createRequirement(input);
      const result = publish
        ? await marketplaceRepository.publishRequirement(created.id, input.organization_id)
        : created;
      notify.success(publish ? `需求已发布，已邀请 ${result.invitationCount} 家服务商` : '需求草稿已保存');
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
      <div className="transaction-editor-layout">
        <div className="transaction-form-stack">
          <section className="transaction-card">
            <h2>需求基本信息</h2>
            <label><span>需求标题 *</span><input value={title} maxLength={100} onChange={(event) => setTitle(event.target.value)} /></label>
            <div className="marketplace-form-grid">
              <label><span>业务分类 *</span><select value={category} onChange={(event) => setCategory(event.target.value)}><option>法律 / 合同审查</option><option>IT 运维</option><option>财务分析</option><option>人才招聘</option><option>客户服务</option><option>投标文件</option></select></label>
              <label><span>保密级别 *</span><select value={visibility} onChange={(event) => setVisibility(event.target.value as RequirementInput['visibility'])}><option value="invited_providers">仅受邀服务方可见</option><option value="enterprise">企业内部</option><option value="public">公开</option></select></label>
            </div>
            <label><span>详细描述 *</span><textarea value={description} maxLength={5000} onChange={(event) => setDescription(event.target.value)} /></label>
            <div className="transaction-upload">
              <div><strong>输入材料</strong><small>支持文档、PDF、表格、图片；材料随需求版本冻结。</small></div>
              <label className="marketplace-secondary-button"><Paperclip />{uploading ? '上传中…' : '添加附件'}<input type="file" multiple hidden disabled={uploading} onChange={(event) => void onFiles(event)} /></label>
            </div>
            {attachments.map((item) => <div className="transaction-file-row" key={item.id}><FileText /><span><strong>{item.filename}</strong><small>{formatBytes(item.size)}</small></span><Check /><button type="button" aria-label="移除附件" onClick={() => setAttachments((rows) => rows.filter((row) => row.id !== item.id))}><Trash2 /></button></div>)}
          </section>
          <section className="transaction-card">
            <h2>期望交付物</h2>
            <div className="transaction-deliverable-table">
              {deliverables.map((item, index) => <div key={`${item.name}-${index}`}><b>{index + 1}</b><input value={item.name} onChange={(event) => setDeliverables((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, name: event.target.value } : row))} /><select value={item.format} onChange={(event) => setDeliverables((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, format: event.target.value } : row))}><option>.xlsx</option><option>.docx</option><option>.pdf</option><option>链接</option></select><label><input type="checkbox" checked={item.required} onChange={(event) => setDeliverables((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, required: event.target.checked } : row))} />必需</label><button type="button" onClick={() => setDeliverables((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}><Trash2 /></button></div>)}
            </div>
            <button type="button" className="marketplace-link-button" onClick={() => setDeliverables((items) => [...items, { name: '', format: '.docx', required: true }])}><Plus />添加交付物</button>
          </section>
          <section className="transaction-card">
            <h2>验收要求</h2>
            {criteria.map((item, index) => <div className="transaction-criterion" key={index}><Check /><input value={item} onChange={(event) => setCriteria((rows) => rows.map((row, rowIndex) => rowIndex === index ? event.target.value : row))} /><button type="button" onClick={() => setCriteria((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}><Trash2 /></button></div>)}
            <button type="button" className="marketplace-link-button" onClick={() => setCriteria((items) => [...items, ''])}><Plus />添加验收要求</button>
          </section>
        </div>
        <aside className="transaction-side-stack">
          <section className="transaction-card">
            <h2>信息完整度 <ShieldCheck /></h2>
            <strong className="transaction-completeness">{completeness}%</strong>
            <div className="transaction-progress"><span style={{ width: `${completeness}%` }} /></div>
            <small>{completeness === 100 ? '需求信息已完整，可以发布' : '请继续补充必填信息'}</small>
          </section>
          <section className="transaction-card transaction-budget-card">
            <h2>预算与邀请设置</h2>
            <div className="marketplace-form-grid"><label><span>预算下限</span><input type="number" min="0" value={budgetMin} onChange={(event) => setBudgetMin(event.target.value)} /></label><label><span>预算上限</span><input type="number" min="1" value={budgetMax} onChange={(event) => setBudgetMax(event.target.value)} /></label></div>
            <label><span>期望完成时间</span><input type="datetime-local" value={deadline} onChange={(event) => setDeadline(event.target.value)} /></label>
            <label><span>最多邀请服务商</span><input type="number" min="1" max="20" value={inviteLimit} onChange={(event) => setInviteLimit(Number(event.target.value))} /></label>
            <button type="button" className="marketplace-submit-button" disabled={saving} onClick={() => void save(true)}>{saving ? '发布中…' : '预览并发布'}</button>
            <button type="button" className="marketplace-secondary-button" disabled={saving} onClick={() => void save(false)}>保存草稿</button>
          </section>
          <section className="transaction-card transaction-privacy-note"><LockKeyhole /><div><strong>AI 隐私与安全</strong><p>材料只提供给受邀服务方；内部提示词、知识库、密钥和成本不会向采购方公开。</p></div></section>
        </aside>
      </div>
    </main>
  );
}

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))}KB`;
  return `${(value / 1024 / 1024).toFixed(1)}MB`;
}
