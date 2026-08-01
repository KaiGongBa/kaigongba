import { ArrowLeft, Check, CheckCircle2, CircleMinus, FileCheck2, ShieldCheck, Sparkles } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

export default function QuoteComparePage() {
  const navigate = useNavigate();
  const { requirementId = '' } = useParams();
  const organization = useMarketplaceOrganization();
  const [selectedId, setSelectedId] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [buyerNote, setBuyerNote] = useState('');
  const [working, setWorking] = useState(false);
  const resource = useMarketplaceResource(
    async () => {
      if (!organization.selected) throw new Error('请先选择采购企业');
      const [requirement, quotes] = await Promise.all([
        marketplaceRepository.getRequirement(requirementId, organization.selected.id),
        marketplaceRepository.listRequirementQuotes(requirementId, organization.selected.id),
      ]);
      return { requirement, quotes };
    },
    `quote-compare:${requirementId}:${organization.selected?.id || 'none'}`,
  );
  const requirement = resource.data?.requirement;
  const quotes = resource.data?.quotes || [];
  const alreadySelected = Boolean(requirement?.selectedQuoteId && requirement.agreementId);
  const selected = quotes.find((quote) => quote.id === selectedId) || null;
  const recommended = useMemo(() => [...quotes].sort((a, b) => {
    const matchA = requirement?.matches.find((item) => item.providerOrganizationId === a.providerOrganizationId)?.score || 0;
    const matchB = requirement?.matches.find((item) => item.providerOrganizationId === b.providerOrganizationId)?.score || 0;
    return matchB - matchA || Number(a.currentVersion.totalAmount) - Number(b.currentVersion.totalAmount);
  })[0], [quotes, requirement?.matches]);

  useEffect(() => {
    if (requirement?.selectedQuoteId) setSelectedId(requirement.selectedQuoteId);
  }, [requirement?.selectedQuoteId]);

  async function choose() {
    if (!selected || !organization.selected || !acknowledged) {
      notify.error('请选择报价并确认已阅读服务范围、排除项和验收标准');
      return;
    }
    if (!window.confirm(`确认选择“${selected.providerName}”的报价并生成合作协议？其他有效报价将被标记为未选中。`)) return;
    setWorking(true);
    try {
      const agreement = await marketplaceRepository.selectQuote(requirementId, organization.selected.id, selected.id, buyerNote);
      notify.success('已完成选标，合作协议已按冻结快照生成');
      navigate(`/enterprise/agreements/${agreement.id}`);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '选标失败');
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="marketplace-page marketplace-management-page transaction-page transaction-compare-page">
      <MarketplaceHeader
        breadcrumb={<button type="button" className="marketplace-breadcrumb" onClick={() => navigate(`/enterprise/demands/${requirementId}`)}><ArrowLeft /><strong>我的需求</strong><span>/ {requirement?.code || requirementId} / 报价比较</span></button>}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {requirement && (
        <>
          <section className="transaction-compare-hero"><div><h1>{requirement.title} <span className="marketplace-status is-published">收到 {quotes.length} 份报价</span></h1><p>预算范围：¥{money(requirement.budgetMinAmount)}–¥{money(requirement.budgetMaxAmount)}　期望完成：{requirement.desiredDeliveryAt ? formatDateTime(requirement.desiredDeliveryAt) : '-' }　需求版本：v{requirement.currentVersion.version}</p></div><button type="button" className="marketplace-secondary-button" onClick={() => navigate(`/enterprise/demands/${requirement.id}`)}>返回需求详情</button></section>
          {quotes.length === 0 ? <div className="marketplace-inline-empty"><FileCheck2 /><strong>还没有可比较的有效报价</strong><span>只有经服务方管理员确认并发送的报价会出现在这里。</span></div> : (
            <div className="transaction-compare-layout">
              <section className="transaction-card transaction-comparison">
                <div className="marketplace-card-heading"><div><h2>{quotes.length} 份有效报价</h2><p>所有价格和服务范围均由服务方确认；AI 只提供信息对比参考。</p></div></div>
                <div className="transaction-comparison-grid" style={{ '--quote-count': quotes.length } as React.CSSProperties}>
                  <div className="transaction-comparison-labels"><strong>比较维度</strong><span>总报价（含税）</span><span>报价有效期至</span><span>预计完成工期</span><span>服务范围</span><span>排除项</span><span>交付物与里程碑</span><span>修改次数</span><span>验收标准</span><span>报价版本</span></div>
                  {quotes.map((quote) => (
                    <label className={`transaction-comparison-column ${selectedId === quote.id ? 'is-selected' : ''}`} key={quote.id}>
                      <header><div><strong>{quote.serviceName}{quote.status === 'selected' && <em className="marketplace-status is-published">已中选</em>}</strong><small>{quote.providerName} <ShieldCheck /></small></div><input type="radio" name="quote" checked={selectedId === quote.id} disabled={alreadySelected} onChange={() => setSelectedId(quote.id)} /></header>
                      <span className="is-price">¥{money(quote.currentVersion.totalAmount)}</span>
                      <span>{formatDateTime(quote.currentVersion.validUntil)}</span>
                      <span>{quote.currentVersion.deliveryDays} 个工作日</span>
                      <span>{quote.currentVersion.serviceScope.map((item) => <i key={item}><Check />{item}</i>)}</span>
                      <span>{quote.currentVersion.exclusions.map((item) => <i className="is-exclusion" key={item}><CircleMinus />{item}</i>)}</span>
                      <span>{quote.currentVersion.milestones.map((item) => <i key={item.name}>{item.name}　¥{money(item.amount)}</i>)}</span>
                      <span>{quote.currentVersion.includedRevisions} 次</span>
                      <span>{quote.currentVersion.acceptanceCriteria.map((item) => <i key={item}><Check />{item}</i>)}</span>
                      <span>v{quote.currentVersion.version} · {quote.sentAt ? formatDateTime(quote.sentAt) : '-'}</span>
                    </label>
                  ))}
                </div>
                <div className="transaction-warning">服务商报价存在差异，请重点关注服务范围、排除项、验收标准与工期是否满足需求。</div>
                <label className="transaction-buyer-note"><span>采购备注（仅企业内部可见）</span><textarea value={buyerNote} maxLength={500} disabled={alreadySelected} onChange={(event) => setBuyerNote(event.target.value)} placeholder={alreadySelected ? '选标已完成，决策记录已冻结' : '记录内部评审意见、价格方案或风险关注点'} /></label>
              </section>
              <aside className="transaction-side-stack">
                <section className="transaction-card transaction-decision-card"><h2>决策参考 <span className="marketplace-status is-published">AI 推荐</span></h2>{recommended ? <><div className="transaction-score"><strong>{requirement.matches.find((item) => item.providerOrganizationId === recommended.providerOrganizationId)?.score || 85}</strong><span>/ 100<br />综合匹配分</span></div><ul>{requirement.matches.find((item) => item.providerOrganizationId === recommended.providerOrganizationId)?.reasons.map((reason) => <li key={reason}>{reason}</li>) || <li>价格、工期和服务范围综合匹配</li>}</ul><div className="transaction-ai-recommendation"><Sparkles /><p>AI 建议：优先考虑 <strong>{recommended.serviceName}</strong><small>仅供参考，需人工确认</small></p></div></> : null}</section>
              </aside>
            </div>
          )}
          {quotes.length > 0 && <footer className="transaction-sticky-action"><div><span>{alreadySelected ? '已中选：' : '已选择：'}</span><strong>{selected?.serviceName || '尚未选择'}</strong>{selected && <b>¥{money(selected.currentVersion.totalAmount)}</b>}</div>{alreadySelected ? <><span className="transaction-success"><CheckCircle2 />选标结果与报价快照已冻结</span><button type="button" className="marketplace-submit-button" onClick={() => navigate(`/enterprise/agreements/${requirement.agreementId}`)}><FileCheck2 />查看合作协议</button></> : <><label><input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />我已阅读服务范围、排除项和验收标准</label><button type="button" className="marketplace-submit-button" disabled={!selected || !acknowledged || working} onClick={() => void choose()}><FileCheck2 />选定并生成协议</button></>}</footer>}
        </>
      )}
    </main>
  );
}

function money(value: string) { return Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
