import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  CircleAlert,
  ExternalLink,
  FileCheck2,
  Info,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  XCircle,
} from 'lucide-react';
import { useState } from 'react';

import type {
  AnswerSubmission,
  BlockAction,
  DraftPreviewBlock,
  IntentConfirmationBlock,
  JsonValue,
  StructuredBlock,
} from '../protocol';
import { safeParseStructuredBlockV2 } from '../protocol';
import { buildSafePlatformAssistantUrl } from '../routeRegistry';
import { InterviewStateBlock } from './InterviewStateBlock';
import { BlockHeading, QuestionGroupBlock } from './QuestionGroupBlock';

export type StructuredBlockAction = Readonly<{
  block: StructuredBlock;
  actionId: string;
  label: string;
}>;

export function StructuredBlockRenderer({
  block: unsafeBlock,
  disabled,
  onSubmitAnswers,
  onAction,
  onNavigate,
}: {
  block: unknown;
  disabled?: boolean;
  onSubmitAnswers: (submission: Pick<AnswerSubmission, 'block_id' | 'block_version' | 'answers'>) => void;
  onAction: (action: StructuredBlockAction) => void;
  onNavigate: (url: string) => void;
}) {
  const block = safeParseStructuredBlockV2(unsafeBlock);
  if (block.type === 'interview_state') {
    return <InterviewStateBlock block={block} />;
  }
  if (block.type === 'question_group') {
    return <QuestionGroupBlock block={block} disabled={disabled} onSubmit={onSubmitAnswers} />;
  }
  if (block.type === 'intent_confirmation') {
    return <IntentBlock block={block} disabled={disabled} onAction={onAction} />;
  }
  if (block.type === 'draft_preview') {
    return <DraftBlock block={block} disabled={disabled} onAction={onAction} />;
  }
  if (block.type === 'action_result') {
    const ResultIcon = block.result_status === 'succeeded' ? CheckCircle2 : block.result_status === 'failed' ? XCircle : ShieldAlert;
    return (
      <section className={`kai-block kai-result-block is-${block.result_status}`}>
        <BlockHeading title={block.title} description={block.description} status={block.status} />
        <div className="kai-result-message"><ResultIcon /><span><strong>{block.message}</strong><small>{block.result_code}</small></span></div>
        <BlockActions block={block} actions={block.actions || []} disabled={disabled} onAction={onAction} />
      </section>
    );
  }
  if (block.type === 'entity_summary') {
    return (
      <section className="kai-block kai-entity-block">
        <BlockHeading title={block.title} description={block.description} status={block.status} />
        <dl>{block.fields.map((field) => <div key={field.key}><dt>{field.label}</dt><dd>{formatValue(field.value)}</dd></div>)}</dl>
        {block.allowed_action_ids.length > 0 && (
          <div className="kai-entity-actions">{block.allowed_action_ids.map((actionId) => <button type="button" key={actionId} disabled={disabled} onClick={() => onAction({ block, actionId, label: actionId })}>{actionLabel(actionId)}<ArrowRight /></button>)}</div>
        )}
      </section>
    );
  }
  if (block.type === 'deep_link') {
    const url = buildSafePlatformAssistantUrl(block.route_id, block.route_params);
    return (
      <section className={`kai-block kai-link-block ${url ? '' : 'is-disabled'}`}>
        <BlockHeading title={block.title} description={block.description} status={url ? block.status : 'disabled'} />
        {url ? <button type="button" disabled={disabled || block.status === 'disabled'} onClick={() => onNavigate(url)}><ExternalLink />{block.label}</button> : <p role="alert"><ShieldAlert />该入口未通过平台路由白名单，已阻止跳转。</p>}
      </section>
    );
  }
  const NoticeIcon = block.tone === 'success' ? CheckCircle2 : block.tone === 'error' ? CircleAlert : block.tone === 'warning' ? AlertTriangle : block.code.includes('UNSUPPORTED') || block.code.includes('INVALID') ? ShieldAlert : Info;
  return (
    <section className={`kai-block kai-notice-block is-${block.tone}`} role={block.tone === 'error' ? 'alert' : 'status'}>
      <div className="kai-notice-copy"><NoticeIcon /><span><strong>{block.title}</strong>{block.description && <em>{block.description}</em>}<p>{block.message}</p><small>{block.code}</small></span></div>
      <BlockActions block={block} actions={block.actions} disabled={disabled} onAction={onAction} />
    </section>
  );
}

function IntentBlock({ block, disabled, onAction }: { block: IntentConfirmationBlock; disabled?: boolean; onAction: (action: StructuredBlockAction) => void }) {
  const [selected, setSelected] = useState('');
  const locked = disabled || block.status !== 'pending';
  return (
    <section className="kai-block kai-intent-block">
      <BlockHeading title={block.title} description={block.description} status={block.status} />
      <div className="kai-intent-options">
        {block.options.map((option) => <button type="button" key={option.id} className={selected === option.id ? 'is-selected' : ''} disabled={locked || option.disabled} onClick={() => setSelected(option.id)}><span><strong>{option.label}{option.recommended && <small>建议</small>}</strong>{option.description && <em>{option.description}</em>}</span>{selected === option.id && <Check />}</button>)}
      </div>
      <button type="button" className="kai-block-primary" disabled={locked || !selected} onClick={() => { const option = block.options.find((item) => item.id === selected); if (option) onAction({ block, actionId: `intent:${option.id}`, label: option.label }); }}><Sparkles />确认意图</button>
      {block.allow_free_text && <p className="kai-block-hint">也可在下方输入框直接补充。</p>}
    </section>
  );
}

function DraftBlock({ block, disabled, onAction }: { block: DraftPreviewBlock; disabled?: boolean; onAction: (action: StructuredBlockAction) => void }) {
  return (
    <section className="kai-block kai-draft-block">
      <BlockHeading title={block.title} description={block.description} status={block.status} />
      <div className="kai-draft-summary"><FileCheck2 /><p>{block.summary}</p><span>v{block.draft_version}</span></div>
      {block.sections.map((section) => (
        <section key={section.id} className="kai-draft-section"><h4>{section.title}</h4><dl>{section.fields.map((field) => <div key={field.key}><dt>{field.label}<SourceBadge source={field.source} />{field.needs_confirmation && <small>待确认</small>}</dt><dd>{formatValue(field.value)}</dd></div>)}</dl></section>
      ))}
      {block.missing_fields.length > 0 && <div className="kai-draft-missing"><strong><AlertTriangle />发布前还需补充</strong>{block.missing_fields.map((field) => <p key={field.key} className={`is-${field.severity}`}><b>{field.label}</b><span>{field.reason}</span></p>)}</div>}
      <BlockActions block={block} actions={block.actions} disabled={disabled} onAction={onAction} />
      <p className="kai-block-hint">仅保存草稿；真实发布仍需在需求页检查并确认。</p>
    </section>
  );
}

function BlockActions({ block, actions, disabled, onAction }: { block: StructuredBlock; actions: BlockAction[]; disabled?: boolean; onAction: (action: StructuredBlockAction) => void }) {
  if (!actions.length) return null;
  return <div className="kai-block-actions">{actions.map((action) => <button type="button" key={action.id} className={`is-${action.style}`} disabled={disabled || action.disabled} title={action.disabled_reason} onClick={() => onAction({ block, actionId: action.id, label: action.label })}>{action.id.includes('retry') || action.id.includes('resume') ? <RotateCcw /> : null}{action.label}</button>)}</div>;
}

function SourceBadge({ source }: { source: string }) {
  return <em className={`kai-source is-${source}`}>{({ user_message: '用户原话', user_choice: '用户选择', user_edit: '用户修改', attachment_extraction: '附件提取', existing_record: '已授权数据', ai_expansion: 'AI 扩写', system_default: '平台默认' } as Record<string, string>)[source] || source}</em>;
}

function formatValue(value: JsonValue): string {
  if (value === null) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.map(formatValue).join('、');
  return Object.entries(value).map(([key, item]) => `${key}：${formatValue(item)}`).join('；');
}

function actionLabel(actionId: string) {
  const final = actionId.split('.').pop() || actionId;
  return ({ read: '查看详情', open: '打开', edit: '继续修改', retry: '重试', resume: '继续' } as Record<string, string>)[final] || '查看可用操作';
}
