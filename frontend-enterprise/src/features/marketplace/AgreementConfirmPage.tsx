import { ArrowLeft, Check, CheckCircle2, Clock3, Download, FileClock, FileText, ShieldCheck } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui';
import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

export default function AgreementConfirmPage() {
  const navigate = useNavigate();
  const { agreementId = '' } = useParams();
  const organization = useMarketplaceOrganization();
  const [read, setRead] = useState(false);
  const [working, setWorking] = useState(false);
  const [changeOpen, setChangeOpen] = useState(false);
  const [changeReason, setChangeReason] = useState('');
  const resource = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.getAgreement(agreementId, organization.selected.id)
      : Promise.reject(new Error('请切换到协议签约企业')),
    `agreement:${agreementId}:${organization.selected?.id || 'none'}`,
  );
  const agreement = resource.data;
  const requirement = agreement?.snapshot.requirement || {};
  const quote = agreement?.snapshot.quote || {};
  const service = agreement?.snapshot.service || {};
  const milestones = Array.isArray(quote.milestones) ? quote.milestones as Array<Record<string, unknown>> : [];
  const serviceScope = Array.isArray(quote.service_scope) ? quote.service_scope as string[] : [];
  const exclusions = Array.isArray(quote.exclusions) ? quote.exclusions as string[] : [];
  const buyerConfirmation = agreement?.confirmations.find((item) => item.partyRole === 'buyer');
  const providerConfirmation = agreement?.confirmations.find((item) => item.partyRole === 'provider');
  const statement = useMemo(() => agreement
    ? `我已完整阅读并代表${agreement.currentPartyRole === 'buyer' ? '采购方' : '服务方'}同意协议 v${agreement.version}`
    : '', [agreement]);

  async function confirm() {
    if (!agreement || !organization.selected || !read) {
      notify.error('请先完整阅读并勾选协议确认声明');
      return;
    }
    if (!window.confirm(`确认以“${organization.selected.name}”身份同意协议 v${agreement.version}？该结构化确认将写入审计日志。`)) return;
    setWorking(true);
    try {
      const updated = await marketplaceRepository.confirmAgreement(agreement.id, organization.selected.id, statement);
      notify.success(updated.allPartiesConfirmed ? '双方已确认，协议正式生效' : '当前签约方已确认，等待另一方确认');
      setRead(false);
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '协议确认失败');
    } finally {
      setWorking(false);
    }
  }

  async function requestChange() {
    if (!agreement || !organization.selected || changeReason.trim().length < 6) {
      notify.error('请填写具体修改原因');
      return;
    }
    setWorking(true);
    try {
      await marketplaceRepository.requestAgreementChange(agreement.id, organization.selected.id, changeReason);
      notify.success('修改申请已记录，协议暂停确认');
      setChangeOpen(false);
      setChangeReason('');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '提交修改申请失败');
    } finally {
      setWorking(false);
    }
  }

  async function continueToPayment() {
    if (!agreement || !organization.selected) return;
    if (agreement.orderId) {
      navigate('/enterprise/orders');
      return;
    }
    if (
      agreement.paymentOrderId
      && (agreement.paymentStatus === 'pending' || agreement.currentPartyRole === 'provider')
    ) {
      navigate(`/enterprise/payments/${agreement.paymentOrderId}`);
      return;
    }
    if (agreement.currentPartyRole !== 'buyer') {
      notify.info('支付单由采购方创建；服务方可在支付单创建后查看支付状态。');
      return;
    }
    setWorking(true);
    try {
      const payment = await marketplaceRepository.createPaymentOrder(
        agreement.id,
        organization.selected.id,
      );
      notify.success(payment.attempt > 1 ? `新支付单 ${payment.code} 已创建` : `支付单 ${payment.code} 已创建`);
      navigate(`/enterprise/payments/${payment.id}`);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '创建支付单失败');
    } finally {
      setWorking(false);
    }
  }

  return (
    <main className="marketplace-page marketplace-management-page transaction-page">
      <MarketplaceHeader
        breadcrumb={<button type="button" className="marketplace-breadcrumb" onClick={() => navigate('/enterprise/demands')}><ArrowLeft /><strong>合作协议</strong><span>/ {agreement?.code || agreementId}</span></button>}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {agreement && (
        <>
          <div className="transaction-agreement-steps"><span className="is-done"><Check /><b>配置服务</b><small>已完成</small></span><span className={agreement.allPartiesConfirmed ? 'is-done' : 'is-active'}><FileText /><b>确认协议</b><small>{agreement.allPartiesConfirmed ? '双方已确认' : '待双方确认'}</small></span><span className={agreement.orderId ? 'is-done' : agreement.allPartiesConfirmed ? 'is-active' : ''}><Clock3 /><b>支付</b><small>{agreement.paymentStatus ? paymentStatus(agreement.paymentStatus) : '协议生效后开放'}</small></span><span className={agreement.orderId ? 'is-done' : ''}><FileClock /><b>创建订单</b><small>{agreement.orderId ? '订单已创建' : '支付后创建'}</small></span></div>
          <section className="transaction-agreement-header"><div><h1>{agreement.title} <span className={`marketplace-status is-${agreement.status}`}>{agreementStatus(agreement.status)}</span></h1><p>协议编号：{agreement.code}　版本：v{agreement.version}　生成时间：{formatDateTime(agreement.createdAt)}　协议依据：报价 v{String(quote.version || '-')} + 需求 v{String(requirement.version || '-')} + 服务 {String(service.version || '-')}</p></div><span className="transaction-legal-review"><ShieldCheck /><b>{agreement.legalReviewStatus === 'platform_template_reviewed' ? '平台模板已评审' : '待法务复核'}</b><small>{agreement.legalReviewedAt ? formatDate(agreement.legalReviewedAt) : '尚未记录评审时间'}</small></span></section>
          <div className="transaction-agreement-layout">
            <aside className="transaction-agreement-toc">
              <h2>协议目录</h2>{['服务内容概述', '服务范围与排除项', '合作费用与里程碑', '交付与验收', '知识产权与保密', '数据处理与安全', '取消与退款', '平台争议处理', '责任边界'].map((item, index) => <a href={`#agreement-section-${index + 1}`} key={item}>{index + 1}. {item}</a>)}<button type="button" className="marketplace-secondary-button" onClick={() => window.print()}><Download />下载 / 打印 PDF</button><button type="button" className="marketplace-secondary-button"><FileClock />版本历史</button>
            </aside>
            <article className="transaction-agreement-document">
              <h1>AI员工服务合作协议</h1><p>本协议由以下双方于 {formatDateTime(agreement.createdAt)} 通过开工吧平台在线生成。</p><p><strong>采购方（甲方）：{agreement.buyerName}</strong></p><p><strong>服务方（乙方）：{agreement.providerName}</strong></p>
              <section id="agreement-section-1"><h2>1. 服务内容概述</h2><p>乙方通过“{String(service.name || 'AI员工服务')}”完成“{String(requirement.title || '')}”需求，并按照已确认报价范围提供成果。</p></section>
              <section id="agreement-section-2"><h2>2. 服务范围与排除项</h2><h3>服务范围</h3><ul>{serviceScope.map((item) => <li key={item}><CheckCircle2 />{item}</li>)}</ul><h3>排除项</h3><ul>{exclusions.map((item) => <li className="is-exclusion" key={item}>{item}</li>)}</ul></section>
              <section id="agreement-section-3"><h2>3. 合作费用与里程碑</h2><div className="transaction-agreement-price"><strong>总价（含税）：¥{money(String(quote.total_amount || 0))}</strong><span>有效期至：{quote.valid_until ? formatDateTime(String(quote.valid_until)) : '-'}</span></div><table><thead><tr><th>里程碑</th><th>交付内容</th><th>金额（含税）</th><th>交付条件</th></tr></thead><tbody>{milestones.map((item, index) => <tr key={index}><td>{String(item.name || '')}</td><td>{Array.isArray(item.deliverables) ? item.deliverables.join('、') : '-'}</td><td>¥{money(String(item.amount || 0))}</td><td>{Array.isArray(item.acceptance_criteria) ? item.acceptance_criteria.join('；') : '-'}</td></tr>)}</tbody></table></section>
              <section id="agreement-section-4"><h2>4. 交付与验收</h2><p>乙方应按冻结的需求、报价和服务版本交付。甲方通过结构化验收操作确认，不以聊天文字作为验收状态依据。</p></section>
              <section id="agreement-section-5"><h2>5. 知识产权与保密</h2><p>双方仅可在本次合作范围内使用对方提供的材料。乙方内部提示词、知识库、密钥、内部成本和执行配置不向甲方公开。</p></section>
              <section id="agreement-section-6"><h2>6. 数据处理与安全</h2><p>平台按需求可见范围提供材料访问，并记录访问、版本与关键操作审计。临时文件链接和对象权限由订单阶段控制。</p></section>
              <section id="agreement-section-7"><h2>7. 取消与退款</h2><p>支付后取消和退款须通过订单结构化流程，并依据已完成里程碑、双方确认及平台复核结果处理。</p></section>
              <section id="agreement-section-8"><h2>8. 平台争议处理</h2><p>争议由开工吧平台人工处理；AI 仅可整理证据和生成摘要，不得作出裁决、退款或放款决定。</p></section>
              <section id="agreement-section-9"><h2>9. 责任边界</h2><p>本协议的价格、范围、工期、交付物和验收标准来源于已确认快照。任何变更必须生成结构化新版本并由双方重新确认。</p></section>
            </article>
            <aside className="transaction-side-stack">
              <section className="transaction-card"><h2>确认状态</h2><ConfirmationCard title="采购方（甲方）" name={agreement.buyerName} confirmation={buyerConfirmation} /><ConfirmationCard title="服务方（乙方）" name={agreement.providerName} confirmation={providerConfirmation} /></section>
              {!agreement.currentOrganizationConfirmed && ['pending_confirmations', 'partially_confirmed'].includes(agreement.status) && <section className="transaction-card transaction-confirm-card"><h2>身份确认（{agreement.currentPartyRole === 'buyer' ? '采购方' : '服务方'}）</h2><p className="transaction-muted">本次操作使用当前登录账号和企业成员权限完成认证。</p><label><input type="checkbox" checked={read} onChange={(event) => setRead(event.target.checked)} />我已完整阅读并同意本协议 v{agreement.version}</label><button type="button" className="marketplace-submit-button" disabled={!read || working} onClick={() => void confirm()}>确认本协议</button><button type="button" className="marketplace-secondary-button" onClick={() => setChangeOpen(true)}>提出修改</button></section>}
              {agreement.currentOrganizationConfirmed && !agreement.allPartiesConfirmed && <section className="transaction-card"><span className="transaction-success"><CheckCircle2 />当前企业已确认，等待另一方完成确认。</span></section>}
              {agreement.allPartiesConfirmed && <section className="transaction-card"><span className="transaction-success"><CheckCircle2 />双方已确认，协议于 {agreement.activatedAt ? formatDateTime(agreement.activatedAt) : '-'} 生效。</span><p className="transaction-muted">{agreement.orderId ? '演示支付已完成，真实订单与里程碑已经生成。' : agreement.currentPartyRole === 'buyer' ? '现在可创建演示支付单；支付成功后系统将幂等生成真实订单。' : '等待采购方创建支付单并完成支付。'}</p>{(agreement.currentPartyRole === 'buyer' || agreement.paymentOrderId || agreement.orderId) && <button type="button" className="marketplace-submit-button" disabled={working} onClick={() => void continueToPayment()}>{agreement.orderId ? '查看订单' : agreement.paymentOrderId && agreement.paymentStatus === 'pending' ? '进入支付单' : agreement.currentPartyRole === 'buyer' ? '创建演示支付单' : '查看支付状态'}</button>}</section>}
              <section className="transaction-card"><h2>确认与变更说明</h2><ul className="transaction-note-list"><li>确认操作记录账号、企业身份、协议版本、摘要和时间。</li><li>协议发生价格、范围、工期或里程碑变化时，原确认自动失效。</li><li>仅双方均确认后，支付阶段才开放。</li></ul></section>
            </aside>
          </div>
          <Dialog open={changeOpen} onOpenChange={setChangeOpen}><DialogContent className="marketplace-dialog"><DialogTitle>提出协议修改</DialogTitle><p>修改申请将暂停当前版本确认，后续需要生成新版本并由双方重新确认。</p><label><span>修改原因 *</span><textarea value={changeReason} onChange={(event) => setChangeReason(event.target.value)} placeholder="说明需要修改的价格、范围、工期、里程碑或条款" /></label><div className="marketplace-dialog-actions"><button type="button" onClick={() => setChangeOpen(false)}>取消</button><button type="button" className="marketplace-primary-button" disabled={working} onClick={() => void requestChange()}>提交修改申请</button></div></DialogContent></Dialog>
        </>
      )}
    </main>
  );
}

function ConfirmationCard({ title, name, confirmation }: { title: string; name: string; confirmation?: { confirmedBy: string; confirmedAt: string; confirmationStatement: string } }) {
  return <article className={`transaction-party-confirmation ${confirmation ? 'is-confirmed' : ''}`}><header><strong>{title}</strong><span className={`marketplace-status is-${confirmation ? 'approved' : 'pending_review'}`}>{confirmation ? '已确认' : '待确认'}</span></header><p>{name}</p>{confirmation ? <dl><div><dt>确认人</dt><dd>{confirmation.confirmedBy}</dd></div><div><dt>确认时间</dt><dd>{formatDateTime(confirmation.confirmedAt)}</dd></div><div><dt>确认说明</dt><dd>{confirmation.confirmationStatement}</dd></div></dl> : <small>尚未提交结构化确认</small>}</article>;
}
function agreementStatus(value: string) { return { pending_confirmations: '待双方确认', partially_confirmed: '一方已确认', active: '已生效', changes_requested: '修改中' }[value] || value; }
function paymentStatus(value: string) { return { pending: '待支付', succeeded: '支付成功', failed: '支付失败', cancelled: '已取消', timed_out: '已超时' }[value] || value; }
function money(value: string) { return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value)); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
