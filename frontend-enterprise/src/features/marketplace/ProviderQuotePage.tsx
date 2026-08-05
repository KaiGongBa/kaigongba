import { ArrowLeft, Check, CheckCircle2, Clock3, FileText, LockKeyhole, RefreshCw, Send, Sparkles, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { Quote } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type MilestoneForm = {
  name: string;
  description: string;
  input_materials: string[];
  deliverables: string[];
  duration_days: number;
  acceptance_criteria: string[];
  amount: string;
};

export default function ProviderQuotePage() {
  const navigate = useNavigate();
  const { quoteId = '' } = useParams();
  const organization = useMarketplaceOrganization();
  const resource = useMarketplaceResource(
    async () => {
      if (!organization.selected) throw new Error('请先选择服务商企业');
      const quote = await marketplaceRepository.getQuote(quoteId, organization.selected.id);
      const requirement = await marketplaceRepository.getRequirement(quote.requirementId, organization.selected.id);
      return { quote, requirement };
    },
    `provider-quote:${quoteId}:${organization.selected?.id || 'none'}`,
  );
  const quote = resource.data?.quote;
  const requirement = resource.data?.requirement;
  const currentVersion = quote?.currentVersion;
  const [totalAmount, setTotalAmount] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [deliveryDays, setDeliveryDays] = useState(1);
  const [revisions, setRevisions] = useState(1);
  const [scope, setScope] = useState('');
  const [exclusions, setExclusions] = useState('');
  const [criteria, setCriteria] = useState('');
  const [terms, setTerms] = useState('');
  const [milestones, setMilestones] = useState<MilestoneForm[]>([]);
  const [acknowledged, setAcknowledged] = useState(false);
  const [working, setWorking] = useState(false);

  useEffect(() => {
    if (!quote?.currentVersion) return;
    const version = quote.currentVersion;
    setTotalAmount(version.totalAmount);
    setValidUntil(toLocalInput(version.validUntil));
    setDeliveryDays(version.deliveryDays);
    setRevisions(version.includedRevisions);
    setScope(version.serviceScope.join('\n'));
    setExclusions(version.exclusions.join('\n'));
    setCriteria(version.acceptanceCriteria.join('\n'));
    setTerms(version.additionalTerms);
    setMilestones(version.milestones.map((item) => ({ ...item })));
  }, [quote]);

  const milestoneTotal = useMemo(() => milestones.reduce((sum, item) => sum + Number(item.amount || 0), 0), [milestones]);
  const validation = {
    amount: Number(totalAmount) > 0,
    valid: Boolean(validUntil && new Date(validUntil) > new Date()),
    milestones: milestones.length > 0 && Math.abs(milestoneTotal - Number(totalAmount)) < 0.01,
    scope: Boolean(scope.trim()),
    criteria: Boolean(criteria.trim()),
  };
  const ready = Object.values(validation).every(Boolean);
  const statusText = quote ? quoteStatusText(quote) : '';
  const confirmedQuote = quote && ['sent', 'selected', 'rejected'].includes(quote.status);
  const bannerText = quote?.status === 'selected'
    ? `报价 v${currentVersion?.version || '-'} 已由服务方确认并被采购方选中；合作协议已按冻结快照生成`
    : confirmedQuote
      ? `报价 v${currentVersion?.version || '-'} 已由服务方管理员确认并发送，当前版本不可直接修改`
      : quote
        ? quoteGenerationBanner(quote.status, quote.requirementVersion)
        : '';

  function payload() {
    if (!organization.selected) return null;
    return {
      organization_id: organization.selected.id,
      total_amount: totalAmount,
      // Preserve the provider-entered local wall-clock value for the API's
      // naive datetime field.
      valid_until: validUntil,
      delivery_days: deliveryDays,
      included_revisions: revisions,
      service_scope: lines(scope),
      exclusions: lines(exclusions),
      milestones,
      acceptance_criteria: lines(criteria),
      additional_terms: terms,
    };
  }

  async function saveDraft(): Promise<Quote | null> {
    if (!quote || !ready) {
      notify.error('请完成报价校验，确保里程碑金额与总价一致');
      return null;
    }
    const input = payload();
    if (!input) return null;
    setWorking(true);
    try {
      const updated = await marketplaceRepository.updateQuote(quote.id, input);
      notify.success(`报价 v${updated.currentVersion?.version || '-'} 已保存，等待服务方确认`);
      resource.reload();
      return updated;
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '保存报价失败');
      return null;
    } finally {
      setWorking(false);
    }
  }

  async function confirmSend() {
    if (!quote || !organization.selected || !ready || !acknowledged) {
      notify.error('请完成报价校验并勾选服务方确认声明');
      return;
    }
    if (!window.confirm('确认以当前企业身份发送该报价？发送后采购方将看到范围、价格、工期、里程碑和验收标准。')) return;
    setWorking(true);
    try {
      let current = quote;
      if (formChanged(quote)) {
        const input = payload();
        if (!input) return;
        current = await marketplaceRepository.updateQuote(quote.id, input);
      }
      const sent = await marketplaceRepository.confirmAndSendQuote(current.id, organization.selected.id);
      notify.success(`报价 v${sent.currentVersion?.version || '-'} 已确认并发送`);
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '发送报价失败');
    } finally {
      setWorking(false);
    }
  }

  function formChanged(current: Quote) {
    const version = current.currentVersion;
    if (!version) return false;
    return totalAmount !== version.totalAmount
      || deliveryDays !== version.deliveryDays
      || revisions !== version.includedRevisions
      || lines(scope).join('|') !== version.serviceScope.join('|')
      || milestones.some((item, index) => item.amount !== version.milestones[index]?.amount);
  }

  return (
    <main className="marketplace-page marketplace-management-page transaction-page">
      <MarketplaceHeader
        breadcrumb={<button type="button" className="marketplace-breadcrumb" onClick={() => navigate('/enterprise/provider')}><ArrowLeft /><strong>服务商工作台</strong><span>/ {quote?.status === 'selected' ? '已中选' : quote?.status === 'sent' ? '已报价' : '待报价'} / {quote?.requirementCode || quoteId}</span></button>}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {quote && requirement && !currentVersion && (
        <section className="marketplace-management-card provider-queue-card">
          <div className="transaction-ai-banner"><Sparkles /><span>{bannerText}</span></div>
          <div className="marketplace-inline-empty compact">
            <Clock3 />
            <strong>{statusText}</strong>
            <span>{quote.status === 'needs_clarification' ? '请先查看需求与澄清材料，补齐信息后系统会重新排队。' : quote.status === 'failed' ? '生成任务已记录失败原因并将自动重试，不会向采购方发送。' : '报价草案仅对当前服务方可见，生成后需负责人人工确认。'}</span>
            <button type="button" className="marketplace-link-button" onClick={() => navigate(`/enterprise/demands/${quote.requirementId}`)}><FileText />查看需求与澄清</button>
          </div>
        </section>
      )}
      {quote && requirement && currentVersion && (
        <>
          <div className="transaction-ai-banner"><Sparkles /><span>{bannerText}</span><button type="button" disabled={working} onClick={() => navigate(`/enterprise/demands/${quote.requirementId}`)}><FileText />查看生成依据</button></div>
          <div className="transaction-quote-layout">
            <div className="transaction-form-stack">
              <section className="transaction-card">
                <div className="marketplace-card-heading"><div><h2>报价范围</h2><p><span className={`marketplace-status ${quote.status === 'selected' ? 'is-published' : 'is-pending_review'}`}>{statusText}</span></p></div></div>
                <div className="transaction-quote-metrics"><label><span>总报价（含税）</span><b>¥ <input type="number" min="0" value={totalAmount} disabled={!quote.canEdit} onChange={(event) => setTotalAmount(event.target.value)} /></b></label><label><span>报价有效至</span><input type="datetime-local" value={validUntil} disabled={!quote.canEdit} onChange={(event) => setValidUntil(event.target.value)} /></label><label><span>预计完成工期</span><b><input type="number" min="1" value={deliveryDays} disabled={!quote.canEdit} onChange={(event) => setDeliveryDays(Number(event.target.value))} /> 个工作日</b></label></div>
                <div className="marketplace-form-grid"><label><span>包含的服务</span><textarea value={scope} disabled={!quote.canEdit} onChange={(event) => setScope(event.target.value)} /></label><label><span>排除项</span><textarea value={exclusions} disabled={!quote.canEdit} onChange={(event) => setExclusions(event.target.value)} /></label></div>
              </section>
              <section className="transaction-card">
                <h2>里程碑与交付</h2>
                <div className="transaction-milestone-table">
                  <header><span>里程碑</span><span>工作内容</span><span>交付成果</span><span>工期</span><span>报价</span><span /></header>
                  {milestones.map((item, index) => <div key={`${item.name}-${index}`}><strong>{index + 1}. <input value={item.name} disabled={!quote.canEdit} onChange={(event) => setMilestones((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, name: event.target.value } : row))} /></strong><textarea value={item.description} disabled={!quote.canEdit} onChange={(event) => setMilestones((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, description: event.target.value } : row))} /><textarea value={item.deliverables.join('\n')} disabled={!quote.canEdit} onChange={(event) => setMilestones((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, deliverables: lines(event.target.value) } : row))} /><label><input type="number" min="1" value={item.duration_days} disabled={!quote.canEdit} onChange={(event) => setMilestones((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, duration_days: Number(event.target.value) } : row))} />天</label><label>¥<input type="number" min="0" value={item.amount} disabled={!quote.canEdit} onChange={(event) => setMilestones((rows) => rows.map((row, rowIndex) => rowIndex === index ? { ...row, amount: event.target.value } : row))} /></label>{quote.canEdit ? <button type="button" aria-label="删除里程碑" onClick={() => setMilestones((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}><Trash2 /></button> : <span />}</div>)}
                  <footer><span>里程碑小计</span><strong>¥{milestoneTotal.toFixed(2)}</strong><span className={validation.milestones ? 'is-valid' : 'is-invalid'}>{validation.milestones ? <><Check />与总价一致</> : '与总价不一致'}</span></footer>
                </div>
                <div className="marketplace-form-grid"><label><span>包含修改次数</span><input type="number" min="0" value={revisions} disabled={!quote.canEdit} onChange={(event) => setRevisions(Number(event.target.value))} /></label><label><span>验收标准</span><textarea value={criteria} disabled={!quote.canEdit} onChange={(event) => setCriteria(event.target.value)} /></label></div>
                <label><span>其他条款补充</span><textarea value={terms} disabled={!quote.canEdit} onChange={(event) => setTerms(event.target.value)} /></label>
              </section>
              <section className="transaction-card transaction-privacy-note"><LockKeyhole /><div><strong>内部信息，仅本企业可见</strong><p>生成依据、内部成本、提示词、知识库和 Skill 配置不会向采购方展示。</p></div></section>
            </div>
            <aside className="transaction-side-stack">
              <section className="transaction-card"><h2>需求快照 <span className="marketplace-status is-published">需求 v{requirement.currentVersion.version}</span></h2><dl className="transaction-definition-list"><div><dt>预算范围</dt><dd>¥{money(requirement.budgetMinAmount)}–¥{money(requirement.budgetMaxAmount)}</dd></div><div><dt>期望完成</dt><dd>{requirement.desiredDeliveryAt ? formatDateTime(requirement.desiredDeliveryAt) : '-'}</dd></div><div><dt>交付物</dt><dd>{requirement.currentVersion.deliverables.map((item) => String(item.name || '')).join('、')}</dd></div></dl><button type="button" className="marketplace-link-button" onClick={() => navigate(`/enterprise/demands/${requirement.id}`)}>查看全部需求与澄清</button></section>
              <section className="transaction-card"><h2>报价校验</h2><div className="transaction-validation-list">{Object.entries({ '必填字段已完成': ready, '报价金额在预算范围内': Number(totalAmount) >= Number(requirement.budgetMinAmount) && Number(totalAmount) <= Number(requirement.budgetMaxAmount), '里程碑合计与总报价一致': validation.milestones, '验收标准已填写': validation.criteria }).map(([label, valid]) => <p className={valid ? 'is-valid' : 'is-invalid'} key={label}>{valid ? <CheckCircle2 /> : <Clock3 />}{label}</p>)}</div></section>
              <section className="transaction-card"><h2>报价版本</h2>{quote.versions.map((version) => <div className="transaction-version-row" key={version.id}><RefreshCw /><div><strong>报价 v{version.version}{version.id === currentVersion.id ? '（当前）' : ''}</strong><small>{version.generationMethod === 'provider_revision' ? '服务方修订' : 'AI 生成草案'} · {formatDateTime(version.createdAt)}</small></div></div>)}</section>
              {quote.canConfirm && <section className="transaction-card transaction-confirm-card"><label><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />我已核对范围、价格、工期和验收标准，并代表服务方确认。</label><button type="button" className="marketplace-submit-button" disabled={working || !ready || !acknowledged} onClick={() => void confirmSend()}><Send />确认并发送报价</button><button type="button" className="marketplace-secondary-button" disabled={working || !ready} onClick={() => void saveDraft()}>保存新版本</button></section>}
              {confirmedQuote && <section className="transaction-card"><span className="transaction-success"><CheckCircle2 />报价已由 {quote.confirmedBy} 于 {quote.confirmedAt ? formatDateTime(quote.confirmedAt) : '-'} 确认并发送{quote.status === 'selected' ? '，并已被采购方选中' : ''}</span></section>}
            </aside>
          </div>
        </>
      )}
    </main>
  );
}

function lines(value: string) { return value.split('\n').map((item) => item.trim()).filter(Boolean); }
function toLocalInput(value: string) { const date = new Date(value); const offset = date.getTimezoneOffset() * 60000; return new Date(date.getTime() - offset).toISOString().slice(0, 16); }
function money(value: string) { return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
function quoteStatusText(quote: Quote) {
  const version = quote.currentVersion?.version;
  return {
    queued: '报价草案已排队',
    generating: 'AI 正在生成报价草案',
    ai_draft: `草稿 v${version || '-'}`,
    pending_provider_confirmation: `待确认 v${version || '-'}`,
    needs_clarification: '需要补充需求信息',
    failed: '生成失败，系统将重试',
    sent: '已发送',
    selected: '已中选',
    rejected: '未中选',
    withdrawn: '已撤回',
  }[quote.status] || quote.status;
}
function quoteGenerationBanner(status: string, requirementVersion: number) {
  if (status === 'needs_clarification') return '需求信息尚不足以生成可确认的报价草案。';
  if (status === 'failed') return 'AI 报价草案生成失败，任务将按退避策略重试。';
  if (status === 'generating') return `AI 正在根据需求版本 v${requirementVersion} 生成报价草案。`;
  if (status === 'queued') return `需求版本 v${requirementVersion} 的报价草案已进入生成队列。`;
  return `AI 已根据需求版本 v${requirementVersion} 和服务版本生成草案；发送前必须由服务方管理员确认。`;
}
