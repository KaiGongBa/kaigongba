import { ArrowLeft, CheckCircle2, CircleHelp, Clock3, FileText, RefreshCw, Send, Sparkles, Users } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { MarketplaceHeader, MarketplaceState, MarketTabs } from './components';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type DetailTab = 'clarifications' | 'quotes' | 'history';

const statusLabels: Record<string, string> = {
  draft: '草稿',
  matching: '匹配中',
  quoting: '报价中',
  agreement_pending: '待签约',
  contracted: '已签约',
};

const lifecycleSteps = ['草稿/发布', '澄清/匹配', '接收报价', '选择服务方'];

function lifecyclePosition(status: string) {
  return ({ draft: 0, matching: 1, quoting: 2, agreement_pending: 3, contracted: 4 } as Record<string, number>)[status] ?? 0;
}

export default function RequirementDetailPage() {
  const navigate = useNavigate();
  const { requirementId = '' } = useParams();
  const organization = useMarketplaceOrganization();
  const [tab, setTab] = useState<DetailTab>('clarifications');
  const [question, setQuestion] = useState('');
  const [answerById, setAnswerById] = useState<Record<string, string>>({});
  const [serviceId, setServiceId] = useState('');
  const [generatorSkillId, setGeneratorSkillId] = useState('');
  const [working, setWorking] = useState(false);
  const resource = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.getRequirement(requirementId, organization.selected.id)
      : Promise.reject(new Error('请先选择企业')),
    `requirement:${requirementId}:${organization.selected?.id || 'none'}`,
  );
  const services = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.listAiServices({ scope: 'mine', organizationId: organization.selected.id })
      : Promise.resolve({ items: [], total: 0 }),
    `requirement-provider-services:${organization.selected?.id || 'none'}`,
  );
  const quoteSkills = useMarketplaceResource(
    () => marketplaceRepository.listSkills({ keyword: '报价' }),
    'published-quote-generator-skills',
  );
  const detail = resource.data;
  const isBuyer = detail?.buyerOrganizationId === organization.selected?.id;
  const selectedServiceId = serviceId || services.data?.items[0]?.id || '';
  const openCount = detail?.clarifications.filter((item) => item.status === 'open').length || 0;

  async function refreshMatches() {
    if (!detail || !organization.selected) return;
    setWorking(true);
    try {
      const updated = await marketplaceRepository.runRequirementMatch(detail.id, organization.selected.id, detail.invitationCount || 5);
      notify.success(`匹配完成，已记录 ${updated.matches.length} 条推荐并发送邀请`);
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '匹配失败');
    } finally {
      setWorking(false);
    }
  }

  async function askQuestion() {
    if (!detail || !organization.selected || question.trim().length < 4) {
      notify.error('请填写完整问题');
      return;
    }
    setWorking(true);
    try {
      await marketplaceRepository.createClarification(detail.id, {
        acting_organization_id: organization.selected.id,
        question,
        responsible_party: isBuyer ? 'provider' : 'buyer',
        visibility: isBuyer ? 'all_invited' : 'invited_provider',
        attachments: [],
      });
      setQuestion('');
      notify.success('澄清问题已提交');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '提交问题失败');
    } finally {
      setWorking(false);
    }
  }

  async function answer(clarificationId: string) {
    if (!organization.selected || !answerById[clarificationId]?.trim()) return;
    setWorking(true);
    try {
      await marketplaceRepository.answerClarification(clarificationId, organization.selected.id, answerById[clarificationId]);
      setAnswerById((values) => ({ ...values, [clarificationId]: '' }));
      notify.success('回复已保存并写入澄清记录');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '回复失败');
    } finally {
      setWorking(false);
    }
  }

  async function generateQuote() {
    if (!detail || !organization.selected || !selectedServiceId) {
      notify.error('当前企业没有可用于报价的已上架服务');
      return;
    }
    setWorking(true);
    try {
      const generatorSkill = quoteSkills.data?.items.find((item) => item.id === generatorSkillId);
      const generatorVersion = generatorSkill?.versions.find((version) => version.current)?.version;
      const quote = await marketplaceRepository.generateQuote(
        detail.id,
        organization.selected.id,
        selectedServiceId,
        generatorSkill?.id,
        generatorVersion,
      );
      notify.success('AI 报价草案已生成，仅当前服务方可见');
      navigate(`/enterprise/provider/quotes/${quote.id}`);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '生成报价失败');
    } finally {
      setWorking(false);
    }
  }

  const visibleMatches = useMemo(() => detail?.matches || [], [detail?.matches]);
  return (
    <main className="marketplace-page marketplace-management-page transaction-page">
      <MarketplaceHeader
        breadcrumb={<button type="button" className="marketplace-breadcrumb" onClick={() => navigate(isBuyer ? '/enterprise/demands' : '/enterprise/provider')}><ArrowLeft /><strong>{isBuyer ? '我的需求' : '服务商工作台'}</strong><span>/ {detail?.code || requirementId}</span></button>}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={isBuyer && detail?.canRunMatch ? <button type="button" className="marketplace-secondary-button" disabled={working} onClick={() => void refreshMatches()}><RefreshCw />重新匹配</button> : null}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {detail && (
        <>
          <section className="transaction-requirement-hero">
            <div><span className={`marketplace-status is-${detail.status}`}>{statusLabels[detail.status] || detail.status}</span><h1>{detail.title || '未命名需求'}</h1><p>{detail.code} · 当前需求版本 v{detail.currentVersion.version}</p></div>
            <dl><div><dt>预算范围</dt><dd>¥{money(detail.budgetMinAmount)}–¥{money(detail.budgetMaxAmount)}</dd></div><div><dt>期望完成</dt><dd>{detail.desiredDeliveryAt ? formatDateTime(detail.desiredDeliveryAt) : '-'}</dd></div><div><dt>邀请服务方</dt><dd>{detail.invitationCount}</dd></div><div><dt>有效报价</dt><dd>{detail.quoteCount}</dd></div></dl>
            <div className="transaction-lifecycle" aria-label="需求交易进度">
              {lifecycleSteps.map((label, index) => {
                const position = lifecyclePosition(detail.status);
                const done = position > index;
                const active = position === index;
                return <span key={label} className={done ? 'is-done' : active ? 'is-active' : ''} aria-current={active ? 'step' : undefined}>{done ? <CheckCircle2 /> : <b>{index + 1}</b>}{label}</span>;
              })}
            </div>
          </section>
          <MarketTabs items={[{ value: 'clarifications', label: `澄清问答 ${detail.clarifications.length}` }, { value: 'quotes', label: `匹配与报价 ${detail.quoteCount}` }, { value: 'history', label: '需求版本' }]} value={tab} onChange={setTab} />
          {tab === 'clarifications' && (
            <div className="transaction-detail-layout">
              <section className="transaction-card">
                <h2>需求范围</h2><dl className="transaction-definition-list"><div><dt>业务分类</dt><dd>{detail.category}</dd></div><div><dt>详细描述</dt><dd>{detail.currentVersion.description}</dd></div><div><dt>交付物</dt><dd>{detail.currentVersion.deliverables.map((item) => String(item.name || '')).join('、')}</dd></div><div><dt>验收标准</dt><dd>{detail.currentVersion.acceptanceCriteria.join('；')}</dd></div></dl>
                <h3>已上传材料</h3>{detail.currentVersion.attachments.length ? detail.currentVersion.attachments.map((item, index) => <div className="transaction-file-row" key={index}><FileText /><span><strong>{String(item.name || '附件')}</strong><small>{String(item.content_type || '')}</small></span><span className="marketplace-status is-published">按范围可见</span></div>) : <p className="transaction-muted">暂无附件</p>}
              </section>
              <section className="transaction-card transaction-thread">
                <div className="marketplace-card-heading"><div><h2>统一补充说明</h2><p>结构化澄清会保留责任方、时间和可见范围。</p></div><span className="marketplace-status is-pending">{openCount} 项待回复</span></div>
                <div className="transaction-question-compose"><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={isBuyer ? '向受邀服务商统一补充问题或说明' : '向采购方提出需要确认的问题'} /><button type="button" disabled={working} onClick={() => void askQuestion()}><Send />提交</button></div>
                {detail.clarifications.length === 0 && <div className="marketplace-inline-empty compact"><CircleHelp /><strong>暂无澄清问题</strong><span>可以直接进入报价，也可以先补充关键边界。</span></div>}
                {detail.clarifications.map((item) => (
                  <article className={`transaction-question is-${item.status}`} key={item.id}>
                    <header><span>{item.status === 'answered' ? '已回复' : '待回复'}</span><b>{item.askedByName}</b><time>{formatDateTime(item.createdAt)}</time></header>
                    <h3>{item.question}</h3>
                    {item.answer ? <div className="transaction-answer"><CheckCircle2 /><p>{item.answer}</p><small>{item.answeredBy} · {item.answeredAt ? formatDateTime(item.answeredAt) : ''}</small></div> : (
                      <div className="transaction-answer-form"><textarea value={answerById[item.id] || ''} onChange={(event) => setAnswerById((values) => ({ ...values, [item.id]: event.target.value }))} placeholder="责任方填写结构化回复" /><button type="button" disabled={working} onClick={() => void answer(item.id)}>回答问题</button></div>
                    )}
                  </article>
                ))}
              </section>
              <aside className="transaction-side-stack">
                <section className="transaction-card"><h2>匹配与报价状态</h2><div className="transaction-mini-stats"><span><b>{detail.invitationCount}</b>已邀请</span><span><b>{detail.quoteCount}</b>已报价</span><span><b>{visibleMatches.filter((item) => item.invitationStatus === 'viewed').length}</b>已查看</span></div>{isBuyer && detail.quoteCount > 0 && <button type="button" className="marketplace-submit-button" onClick={() => navigate(`/enterprise/demands/${detail.id}/quotes`)}>查看报价比较</button>}</section>
                {!isBuyer && detail.canQuote && <section className="transaction-card"><h2><Sparkles />生成 AI 报价草案</h2><p className="transaction-muted">草案只对当前服务方可见，必须由服务方管理员确认后发送。</p><label><span>用于报价的服务</span><select value={selectedServiceId} onChange={(event) => setServiceId(event.target.value)}>{services.data?.items.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.versions.find((version) => version.current)?.version}</option>)}</select></label><label><span>报价生成 Skill（可选）</span><select value={generatorSkillId} onChange={(event) => setGeneratorSkillId(event.target.value)}><option value="">平台内置报价生成器</option>{quoteSkills.data?.items.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.version}</option>)}</select></label><small className="transaction-muted">选择第三方 Skill 时会冻结 Skill ID、版本和生成依据；Skill 仍不能替服务方发送报价。</small><button type="button" className="marketplace-submit-button" disabled={working || !selectedServiceId} onClick={() => void generateQuote()}><Sparkles />生成报价草案</button></section>}
                <section className="transaction-card transaction-privacy-note"><Users /><div><strong>AI 说明</strong><p>AI 仅基于需求信息生成匹配建议和报价草案，不会自动代表服务方报价。</p></div></section>
              </aside>
            </div>
          )}
          {tab === 'quotes' && (
            <section className="transaction-card">
              <div className="marketplace-card-heading"><div><h2>匹配推荐与邀请</h2><p>推荐理由和风险标记由平台记录，最终选择由采购方决定。</p></div>{isBuyer && detail.quoteCount > 0 && <button type="button" className="marketplace-primary-button" onClick={() => navigate(`/enterprise/demands/${detail.id}/quotes`)}>比较 {detail.quoteCount} 份报价</button>}</div>
              <div className="transaction-match-grid">{visibleMatches.map((item) => <article key={item.id}><header><span>{item.score}</span><div><strong>{item.serviceName}</strong><small>{item.providerName}</small></div><span className={`marketplace-status is-${item.invitationStatus}`}>{invitationLabel(item.invitationStatus)}</span></header><ul>{item.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>{item.riskFlags.length > 0 && <p>{item.riskFlags.join('；')}</p>}</article>)}</div>
            </section>
          )}
          {tab === 'history' && <section className="transaction-card"><h2>需求版本</h2><div className="transaction-version-row"><Clock3 /><div><strong>v{detail.currentVersion.version}（当前）</strong><small>{detail.currentVersion.changeSummary} · {detail.currentVersion.createdBy} · {formatDateTime(detail.currentVersion.createdAt)}</small></div><code>{detail.currentVersion.snapshotDigest.slice(0, 16)}</code></div></section>}
        </>
      )}
    </main>
  );
}

function invitationLabel(value?: string) {
  return { invited: '已邀请', viewed: '已查看', quote_submitted: '已报价', declined: '已拒绝' }[value || ''] || '已推荐';
}

function money(value: string) { return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
