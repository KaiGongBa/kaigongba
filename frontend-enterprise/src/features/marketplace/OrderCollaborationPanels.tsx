import {
  AlertTriangle,
  Check,
  Clock3,
  Download,
  FileText,
  MessageSquareText,
  Paperclip,
  RefreshCw,
  Send,
  ShieldCheck,
  UploadCloud,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import { notify } from '@/components/ui/app-toast';

import { marketplaceRepository } from './repository';
import type { OrderCancellation, OrderChange, OrderFile } from './types';
import { useMarketplaceResource } from './useMarketplaceResource';

type CollaborationPanelProps = {
  orderId: string;
  organizationId: string;
  milestoneId: string;
  heldAmount: string;
  onBusinessChanged: () => void;
};

export function OrderCommunicationPanel({
  orderId,
  organizationId,
  milestoneId,
}: CollaborationPanelProps) {
  const [content, setContent] = useState('');
  const [attachment, setAttachment] = useState<File>();
  const [working, setWorking] = useState(false);
  const markedRef = useRef('');
  const resource = useMarketplaceResource(
    () => marketplaceRepository.listOrderMessages(orderId, organizationId),
    `order-messages:${orderId}:${organizationId}`,
  );
  const messageItems = resource.data?.items || [];
  const lastMessage = messageItems[messageItems.length - 1];

  useEffect(() => {
    if (!lastMessage || !resource.data?.unreadCount || markedRef.current === lastMessage.id) return;
    markedRef.current = lastMessage.id;
    void marketplaceRepository.markOrderMessagesRead(orderId, organizationId, lastMessage.id)
      .then(() => resource.reload())
      .catch(() => undefined);
  }, [lastMessage?.id, orderId, organizationId, resource.data?.unreadCount]);

  async function sendMessage() {
    if (!content.trim() && !attachment) {
      notify.error('请输入消息或选择附件');
      return;
    }
    setWorking(true);
    try {
      const fileIds: string[] = [];
      if (attachment) {
        const uploaded = await marketplaceRepository.uploadOrderFile(
          orderId,
          organizationId,
          milestoneId,
          'message',
          attachment,
        );
        fileIds.push(uploaded.id);
      }
      await marketplaceRepository.createOrderMessage(orderId, organizationId, {
        content: content.trim(),
        attachmentFileIds: fileIds,
        milestoneId,
      });
      setContent('');
      setAttachment(undefined);
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '消息发送失败');
    } finally {
      setWorking(false);
    }
  }

  async function download(file: { id: string; filename: string }) {
    try {
      const blob = await marketplaceRepository.downloadOrderFile(file.id, organizationId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = file.filename;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '文件下载失败');
    }
  }

  return (
    <section className="collaboration-message-shell">
      <header>
        <div>
          <h2>订单专属沟通</h2>
          <p>沟通内容、附件和系统事件按订单隔离并永久留痕；报价、变更与验收仍需结构化确认。</p>
        </div>
        <button type="button" onClick={resource.reload}><RefreshCw />刷新</button>
      </header>
      {resource.loading && <div className="collaboration-empty">正在加载沟通记录…</div>}
      {resource.error && <div className="collaboration-empty is-error">{resource.error}</div>}
      <div className="collaboration-message-list">
        {resource.data?.items.length === 0 && (
          <div className="collaboration-empty"><MessageSquareText /><strong>尚无订单消息</strong><span>双方可在这里共享履约信息和订单附件。</span></div>
        )}
        {resource.data?.items.map((message) => (
          <article
            key={message.id}
            className={message.messageType === 'system' ? 'is-system' : message.mine ? 'is-mine' : ''}
          >
            {message.messageType === 'system' ? (
              <div className="collaboration-system-message"><ShieldCheck />{message.content}<time>{formatDateTime(message.createdAt)}</time></div>
            ) : (
              <>
                <div className="collaboration-message-meta">
                  <strong>{message.mine ? '我' : message.senderName}</strong>
                  <span>{partyText(message.senderRole)} · {formatDateTime(message.createdAt)}</span>
                </div>
                <div className="collaboration-message-bubble">
                  {message.content && <p>{message.content}</p>}
                  {message.attachments.map((file) => (
                    <button type="button" key={file.id} onClick={() => void download(file)}>
                      <FileText /><span><strong>{file.filename}</strong><small>{formatBytes(file.sizeBytes)}</small></span><Download />
                    </button>
                  ))}
                </div>
              </>
            )}
          </article>
        ))}
      </div>
      <footer className="collaboration-composer">
        {attachment && (
          <div className="collaboration-attachment-chip"><Paperclip /><span>{attachment.name}</span><button type="button" onClick={() => setAttachment(undefined)}><X /></button></div>
        )}
        <textarea
          value={content}
          onChange={(event) => setContent(event.target.value)}
          placeholder="输入订单沟通内容。涉及范围、金额、工期或验收的事项，请使用“变更与取消”。"
          maxLength={5000}
        />
        <div>
          <label><Paperclip />添加附件<input type="file" onChange={(event) => setAttachment(event.target.files?.[0])} /></label>
          <span>{content.length}/5000</span>
          <button type="button" disabled={working} onClick={() => void sendMessage()}><Send />发送消息</button>
        </div>
      </footer>
    </section>
  );
}

export function OrderChangePanel({
  orderId,
  organizationId,
  milestoneId,
  heldAmount,
  onBusinessChanged,
}: CollaborationPanelProps) {
  const [mode, setMode] = useState<'none' | 'change' | 'cancel'>('none');
  const [working, setWorking] = useState(false);
  const [title, setTitle] = useState('');
  const [reason, setReason] = useState('');
  const [scopeText, setScopeText] = useState('');
  const [deliverableText, setDeliverableText] = useState('');
  const [amountDelta, setAmountDelta] = useState('0');
  const [durationDelta, setDurationDelta] = useState('0');
  const [cancelCategory, setCancelCategory] = useState('双方协商取消');
  const [cancelReason, setCancelReason] = useState('');
  const [refundAmount, setRefundAmount] = useState(heldAmount);
  const [comments, setComments] = useState<Record<string, string>>({});
  const changes = useMarketplaceResource(
    () => marketplaceRepository.listOrderChanges(orderId, organizationId),
    `order-changes:${orderId}:${organizationId}`,
  );
  const cancellations = useMarketplaceResource(
    () => marketplaceRepository.listOrderCancellations(orderId, organizationId),
    `order-cancellations:${orderId}:${organizationId}`,
  );
  const hasActive = useMemo(
    () => Boolean(changes.data?.some((item) => ['pending_counterparty', 'approved_pending_finance'].includes(item.status))
      || cancellations.data?.some((item) => ['pending_counterparty', 'awaiting_platform_review'].includes(item.status))),
    [changes.data, cancellations.data],
  );

  function reload() {
    changes.reload();
    cancellations.reload();
    onBusinessChanged();
  }

  async function createChange() {
    if (!title.trim() || !reason.trim()) {
      notify.error('请填写变更标题和原因');
      return;
    }
    setWorking(true);
    try {
      await marketplaceRepository.createOrderChange(orderId, {
        organizationId,
        milestoneId,
        title: title.trim(),
        reason: reason.trim(),
        scopeChanges: splitLines(scopeText),
        deliverableChanges: splitLines(deliverableText),
        amountDelta: amountDelta || '0',
        durationDeltaDays: Number(durationDelta || 0),
      });
      notify.success('订单变更已发给相对方确认');
      setTitle(''); setReason(''); setScopeText(''); setDeliverableText(''); setAmountDelta('0'); setDurationDelta('0'); setMode('none');
      reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '变更提交失败');
    } finally {
      setWorking(false);
    }
  }

  async function createCancellation() {
    if (!cancelReason.trim()) {
      notify.error('请填写取消原因和具体说明');
      return;
    }
    if (!window.confirm('确认发起订单取消申请？相对方同意后还需平台复核演示退款。')) return;
    setWorking(true);
    try {
      await marketplaceRepository.createOrderCancellation(orderId, organizationId, cancelCategory, cancelReason.trim(), refundAmount || '0');
      notify.success('订单取消申请已提交');
      setMode('none'); setCancelReason('');
      reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '取消申请提交失败');
    } finally {
      setWorking(false);
    }
  }

  async function decideChange(item: OrderChange, decision: 'approved' | 'rejected') {
    if (!window.confirm(decision === 'approved' ? '确认同意这份结构化订单变更？' : '确认拒绝这份订单变更？')) return;
    await runDecision(
      () => marketplaceRepository.decideOrderChange(item.id, organizationId, decision, comments[item.id] || ''),
      decision === 'approved' ? '变更已同意' : '变更已拒绝',
    );
  }

  async function decideCancellation(item: OrderCancellation, decision: 'approved' | 'rejected') {
    if (!window.confirm(decision === 'approved' ? '确认同意取消？同意后资金保持冻结并等待平台复核。' : '确认拒绝取消申请？')) return;
    await runDecision(
      () => marketplaceRepository.decideOrderCancellation(item.id, organizationId, decision, comments[item.id] || ''),
      decision === 'approved' ? '已同意，等待平台复核' : '取消申请已拒绝',
    );
  }

  async function runDecision(action: () => Promise<unknown>, success: string) {
    setWorking(true);
    try {
      await action();
      notify.success(success);
      reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '确认失败');
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="collaboration-change-layout">
      <section className="collaboration-change-main">
        <header className="collaboration-section-head">
          <div><h2>订单变更</h2><p>范围、交付物、金额和工期必须通过结构化申请与双方确认，历史版本不可覆盖。</p></div>
          <button type="button" disabled={hasActive} onClick={() => setMode(mode === 'change' ? 'none' : 'change')}>发起变更</button>
        </header>
        {mode === 'change' && (
          <div className="collaboration-structured-form">
            <div className="collaboration-form-grid">
              <label className="is-wide"><span>变更标题 *</span><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：增加一轮业务访谈并顺延交付" /></label>
              <label className="is-wide"><span>变更原因 *</span><textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明原约定、变化原因和预期结果" /></label>
              <label><span>范围变化（每行一项）</span><textarea value={scopeText} onChange={(event) => setScopeText(event.target.value)} placeholder="新增管理层访谈\n新增竞品分析" /></label>
              <label><span>交付物变化（每行一项）</span><textarea value={deliverableText} onChange={(event) => setDeliverableText(event.target.value)} placeholder="新增访谈纪要\n报告增加竞品章节" /></label>
              <label><span>金额调整（元）</span><input type="number" step="0.01" value={amountDelta} onChange={(event) => setAmountDelta(event.target.value)} /></label>
              <label><span>工期调整（天）</span><input type="number" value={durationDelta} onChange={(event) => setDurationDelta(event.target.value)} /></label>
            </div>
            <div className="collaboration-form-notice"><ShieldCheck />金额不为 0 时，双方同意后还需平台完成演示金额调整；接入真实支付后将替换为真实补款/退款流程。</div>
            <footer><button type="button" onClick={() => setMode('none')}>取消</button><button type="button" className="is-primary" disabled={working} onClick={() => void createChange()}>提交变更申请</button></footer>
          </div>
        )}
        <ChangeList items={changes.data || []} comments={comments} working={working} onComment={(id, value) => setComments((all) => ({ ...all, [id]: value }))} onDecide={decideChange} />
      </section>

      <aside className="collaboration-cancel-side">
        <header><div><h2>订单取消</h2><p>不能通过聊天直接取消。双方确认后由平台复核资金结果。</p></div><AlertTriangle /></header>
        <dl><div><dt>当前托管金额</dt><dd>¥ {money(heldAmount)}</dd></div><div><dt>资金环境</dt><dd><em>演示支付</em></dd></div></dl>
        <button type="button" className="collaboration-danger-button" disabled={hasActive} onClick={() => setMode(mode === 'cancel' ? 'none' : 'cancel')}>申请取消订单</button>
        {mode === 'cancel' && (
          <div className="collaboration-cancel-form">
            <label><span>取消类型</span><select value={cancelCategory} onChange={(event) => setCancelCategory(event.target.value)}><option>双方协商取消</option><option>需求发生变化</option><option>无法继续履约</option><option>其他</option></select></label>
            <label><span>具体原因 *</span><textarea value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} /></label>
            <label><span>申请演示退款金额</span><input type="number" min="0" max={heldAmount} step="0.01" value={refundAmount} onChange={(event) => setRefundAmount(event.target.value)} /></label>
            <footer><button type="button" onClick={() => setMode('none')}>返回</button><button type="button" disabled={working} onClick={() => void createCancellation()}>提交申请</button></footer>
          </div>
        )}
        <CancellationList items={cancellations.data || []} comments={comments} working={working} onComment={(id, value) => setComments((all) => ({ ...all, [id]: value }))} onDecide={decideCancellation} />
      </aside>
    </div>
  );
}

function ChangeList({ items, comments, working, onComment, onDecide }: { items: OrderChange[]; comments: Record<string, string>; working: boolean; onComment: (id: string, value: string) => void; onDecide: (item: OrderChange, decision: 'approved' | 'rejected') => void }) {
  if (!items.length) return <div className="collaboration-empty"><FileText /><strong>暂无订单变更</strong><span>订单仍按成交时冻结的服务与报价快照执行。</span></div>;
  return <div className="collaboration-record-list">{items.map((item) => <article key={item.id}>
    <header><div><small>变更 v{item.version}</small><h3>{item.title}</h3><p>{item.reason}</p></div><em className={`is-${item.status}`}>{changeStatus(item.status)}</em></header>
    <div className="collaboration-change-summary"><span><strong>{item.amountDelta.startsWith('-') ? '' : '+'}¥ {money(item.amountDelta)}</strong><small>金额变化</small></span><span><strong>{item.durationDeltaDays > 0 ? '+' : ''}{item.durationDeltaDays} 天</strong><small>工期变化</small></span><span><strong>{item.scopeChanges.length + item.deliverableChanges.length} 项</strong><small>范围与交付物</small></span></div>
    {(item.scopeChanges.length > 0 || item.deliverableChanges.length > 0) && <ul>{[...item.scopeChanges, ...item.deliverableChanges].map((text, index) => <li key={`${item.id}-${index}`}><Check />{text}</li>)}</ul>}
    <footer><span><Clock3 />{item.requestedBy} · {formatDateTime(item.createdAt)}</span>{item.financeStatus !== 'not_required' && <strong>资金：{financeStatus(item.financeStatus)}</strong>}</footer>
    {item.canDecide && <div className="collaboration-decision"><textarea value={comments[item.id] || ''} onChange={(event) => onComment(item.id, event.target.value)} placeholder="填写确认意见（可选）" /><div><button type="button" disabled={working} onClick={() => onDecide(item, 'rejected')}><X />拒绝</button><button type="button" className="is-primary" disabled={working} onClick={() => onDecide(item, 'approved')}><Check />同意变更</button></div></div>}
  </article>)}</div>;
}

function CancellationList({ items, comments, working, onComment, onDecide }: { items: OrderCancellation[]; comments: Record<string, string>; working: boolean; onComment: (id: string, value: string) => void; onDecide: (item: OrderCancellation, decision: 'approved' | 'rejected') => void }) {
  if (!items.length) return null;
  return <div className="collaboration-cancel-records">{items.map((item) => <article key={item.id}><header><strong>{item.reasonCategory}</strong><em className={`is-${item.status}`}>{cancelStatus(item.status)}</em></header><p>{item.reason}</p><dl><div><dt>申请退款</dt><dd>¥ {money(item.requestedRefundAmount)}</dd></div><div><dt>申请人</dt><dd>{item.requestedBy}</dd></div></dl>{item.canDecide && <div className="collaboration-decision"><textarea value={comments[item.id] || ''} onChange={(event) => onComment(item.id, event.target.value)} placeholder="确认意见（可选）" /><div><button type="button" disabled={working} onClick={() => onDecide(item, 'rejected')}>拒绝</button><button type="button" className="is-primary" disabled={working} onClick={() => onDecide(item, 'approved')}>同意并提交平台</button></div></div>}</article>)}</div>;
}

function splitLines(value: string) { return value.split('\n').map((item) => item.trim()).filter(Boolean); }
function partyText(value: string) { return { buyer: '采购方', provider: '服务方', platform: '平台', system: '系统' }[value] || value; }
function changeStatus(value: string) { return { pending_counterparty: '待相对方确认', approved_pending_finance: '待平台金额复核', applied: '已生效', rejected: '已拒绝', rejected_by_platform: '平台未通过' }[value] || value; }
function financeStatus(value: string) { return { pending_demo_adjustment: '待演示金额调整', demo_adjustment_applied: '演示调整已完成', rejected: '平台未通过' }[value] || value; }
function cancelStatus(value: string) { return { pending_counterparty: '待相对方确认', awaiting_platform_review: '待平台复核', cancelled: '已取消', rejected: '相对方拒绝', rejected_by_platform: '平台未通过' }[value] || value; }
function money(value: string) { return Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
function formatBytes(value: number) { if (value < 1024) return `${value} B`; if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`; return `${(value / (1024 * 1024)).toFixed(1)} MB`; }
