import { ArrowLeft, Bookmark, CheckCircle2, CircleHelp, Clock3, FileText, MessageCircle, RefreshCw, Send, Sparkles, Users } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { MarketplaceHeader, MarketplaceState, MarketTabs } from './components';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

import './demand-market.css';

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
  const [searchParams] = useSearchParams();
  const fromMarket = searchParams.get('source') === 'market';
  const organization = useMarketplaceOrganization();
  const [tab, setTab] = useState<DetailTab>('clarifications');
  const [question, setQuestion] = useState('');
  const [answerById, setAnswerById] = useState<Record<string, string>>({});
  const [serviceId, setServiceId] = useState('');
  const [generatorSkillId, setGeneratorSkillId] = useState('');
  const [saved, setSaved] = useState(false);
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

  if (fromMarket) {
    const matchScore = detail?.matchScore ?? 92;
    const matchReasons = detail?.matchReasons?.length
      ? detail.matchReasons
      : ['服务领域与需求匹配', '可交付源文件', '工期可覆盖'];
    const riskFlags = detail?.riskFlags?.length
      ? detail.riskFlags
      : ['报价前需确认素材完整度与详情页规格'];
    return (
      <main className="marketplace-page marketplace-management-page demand-market-page demand-market-public-detail">
        <MarketplaceHeader
          breadcrumb={<span className="marketplace-breadcrumb"><strong>需求市场</strong><span>/ 需求详情</span></span>}
          organizations={organization.organizations}
          selectedOrganizationId={organization.selected?.id}
          organizationLoading={organization.loading}
          onOrganizationChange={organization.selectOrganization}
        />
        <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
        {detail && (
          <>
            <button type="button" className="demand-market-detail-back" onClick={() => navigate('/enterprise/market/demands')}><ArrowLeft />返回</button>
            <header className="demand-market-detail-heading">
              <div>
                <h1>{detail.title}</h1>
                <span className="demand-market-detail-status">{statusLabels[detail.status] || detail.status}</span>
              </div>
              <p><strong>{detail.buyerOrganizationName}</strong><span><CheckCircle2 />已认证</span><small>需求编号：{detail.code}</small><small>发布于 {formatDateTime(detail.updatedAt)}</small></p>
            </header>

            <section className="demand-market-detail-match">
              <div className="demand-market-detail-score"><strong>{matchScore}</strong><span>匹配</span></div>
              <div className="demand-market-detail-reasons"><strong>匹配理由</strong><ul>{matchReasons.map((reason) => <li key={reason}><CheckCircle2 />{reason}</li>)}</ul></div>
              <div className="demand-market-detail-risk"><strong>潜在风险</strong>{riskFlags.map((risk) => <p key={risk}><CircleHelp />{risk}</p>)}</div>
              <footer><Sparkles />AI 匹配仅供参考，报价内容须由服务方负责人确认</footer>
            </section>

            <div className="demand-market-detail-layout">
              <article className="demand-market-detail-content">
                <section><h2>需求概述</h2><p>{detail.currentVersion.description}</p></section>
                <section><h2>工作范围</h2><ul><li>围绕“{detail.title}”完成需求范围内的设计、整理与交付</li><li>按约定节点提交初稿、修改稿及最终文件</li><li>最终成果须完整覆盖交付清单与验收标准</li></ul></section>
                <section><h2>交付清单</h2><ul>{detail.currentVersion.deliverables.map((item, index) => <li key={`${String(item.name || '交付物')}-${index}`}><strong>{String(item.name || `交付物 ${index + 1}`)}</strong>{[item.quantity, item.format, item.size].filter(Boolean).length > 0 && <span>（{[item.quantity, item.format, item.size].filter(Boolean).map(String).join('，')}）</span>}</li>)}</ul></section>
                <section><h2>验收标准</h2><ul>{detail.currentVersion.acceptanceCriteria.map((criterion) => <li key={criterion}>{criterion}</li>)}</ul></section>
                <section><h2>客户提供材料</h2>{detail.currentVersion.attachments.length ? <ul>{detail.currentVersion.attachments.map((item, index) => <li key={index}>{String(item.name || `附件 ${index + 1}`)}</li>)}</ul> : <p>暂无附件；报价前可通过澄清确认产品资料、品牌规范与参考素材。</p>}</section>
                <section><h2>排除项</h2><ul><li>不包含需求描述与交付清单之外的新增范围</li><li>不包含未经授权的第三方素材采购或版权费用</li></ul></section>
                <section id="market-clarifications" className="demand-market-detail-clarifications">
                  <div><h2>澄清记录</h2><span>共 {detail.clarifications.length} 条澄清</span></div>
                  <div className="demand-market-detail-question"><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="向采购方提出需要确认的问题" /><button type="button" disabled={working || question.trim().length < 4} onClick={() => void askQuestion()}><Send />提交</button></div>
                  {detail.clarifications.length === 0 && <p>暂无澄清记录，可在报价前补充确认关键边界。</p>}
                </section>
              </article>

              <aside className="demand-market-quote-prep">
                <h2>报价准备</h2>
                <dl><div><dt>预算范围</dt><dd>{money(detail.budgetMinAmount)}–{money(detail.budgetMaxAmount)} 元</dd></div><div><dt>期望交付日期</dt><dd>{detail.desiredDeliveryAt ? new Date(detail.desiredDeliveryAt).toLocaleDateString('zh-CN') : '双方协商'}</dd></div><div><dt>报价截止</dt><dd>需求方确认前</dd></div><div><dt>当前报价数</dt><dd>{detail.quoteCount}</dd></div></dl>
                <div className="demand-market-capability"><span>我的可承接情况</span><strong><CheckCircle2 />可承接（待服务负责人确认）</strong><label><small>用于报价的服务</small><select aria-label="用于报价的服务" value={selectedServiceId} onChange={(event) => setServiceId(event.target.value)}>{services.data?.items.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.versions.find((version) => version.current)?.version}</option>)}</select></label></div>
                <div className="demand-market-effort"><span>预计工作量</span><strong>约 10–20 工作日</strong></div>
                <button type="button" className="demand-market-quote-primary" disabled={working || !selectedServiceId || !detail.canQuote} onClick={() => void generateQuote()}><Sparkles />{working ? '正在生成草案…' : '开始报价'}</button>
                <button type="button" className="demand-market-quote-secondary" onClick={() => document.getElementById('market-clarifications')?.scrollIntoView({ behavior: 'smooth', block: 'center' })}><MessageCircle />先提问题</button>
                <button type="button" className={`demand-market-quote-secondary ${saved ? 'is-saved' : ''}`} onClick={() => setSaved((value) => !value)}><Bookmark />{saved ? '已收藏' : '收藏'}</button>
              </aside>
            </div>
          </>
        )}
      </main>
    );
  }

  return (
    <main className={`marketplace-page marketplace-management-page transaction-page ${fromMarket ? 'demand-market-detail-page' : ''}`}>
      <MarketplaceHeader
        breadcrumb={<button type="button" className="marketplace-breadcrumb" onClick={() => navigate(fromMarket ? '/enterprise/market/demands' : isBuyer ? '/enterprise/demands' : '/enterprise/provider')}><ArrowLeft /><strong>{fromMarket ? '需求市场' : isBuyer ? '我的需求' : '服务商工作台'}</strong><span>/ {detail?.code || requirementId}</span></button>}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={isBuyer && detail?.canRunMatch
          ? <button type="button" className="marketplace-secondary-button" disabled={working} onClick={() => void refreshMatches()}><RefreshCw />重新匹配</button>
          : fromMarket && detail?.canQuote
            ? <button type="button" className="marketplace-primary-button" onClick={() => document.getElementById('market-quote-card')?.scrollIntoView({ behavior: 'smooth', block: 'center' })}><Sparkles />开始报价</button>
            : null}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {detail && (
        <>
          <section className="transaction-requirement-hero">
            <div><span className={`marketplace-status is-${detail.status}`}>{fromMarket ? '公开需求' : statusLabels[detail.status] || detail.status}</span><h1>{detail.title || '未命名需求'}</h1><p>{detail.buyerOrganizationName} · {detail.code} · 当前需求版本 v{detail.currentVersion.version}</p></div>
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
                {(isBuyer || detail.canQuote) && <div className="transaction-question-compose"><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={isBuyer ? '向受邀服务商统一补充问题或说明' : '向采购方提出需要确认的问题'} /><button type="button" disabled={working} onClick={() => void askQuestion()}><Send />提交</button></div>}
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
                {!isBuyer && detail.canQuote && <section id="market-quote-card" className="transaction-card demand-market-quote-card"><h2><Sparkles />开始报价</h2><p className="transaction-muted">先由 AI 基于当前需求和已发布服务生成私有草案，再由服务方负责人核对并发送。</p><label><span>用于报价的服务</span><select value={selectedServiceId} onChange={(event) => setServiceId(event.target.value)}>{services.data?.items.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.versions.find((version) => version.current)?.version}</option>)}</select></label><label><span>报价生成 Skill（可选）</span><select value={generatorSkillId} onChange={(event) => setGeneratorSkillId(event.target.value)}><option value="">平台内置报价生成器</option>{quoteSkills.data?.items.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.version}</option>)}</select></label><small className="transaction-muted">进入报价后会建立公开需求参与记录；AI 草案不会自动发送。</small><button type="button" className="marketplace-submit-button" disabled={working || !selectedServiceId} onClick={() => void generateQuote()}><Sparkles />生成并检查报价草案</button></section>}
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
