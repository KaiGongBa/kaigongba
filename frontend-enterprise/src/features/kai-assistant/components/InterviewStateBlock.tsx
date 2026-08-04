import { AlertTriangle, CheckCircle2, CircleHelp, LockKeyhole, Tags } from 'lucide-react';

import type {
  InterviewClassificationStatus,
  InterviewFactStatus,
  InterviewStateBlock as InterviewStateBlockType,
  JsonValue,
} from '../protocol';
import { BlockHeading } from './QuestionGroupBlock';

export function InterviewStateBlock({ block }: { block: InterviewStateBlockType }) {
  const collected = block.facts.filter((fact) => fact.status !== 'superseded').length;
  const total = collected + block.missing_information.length;
  const progress = total > 0 ? Math.round((collected / total) * 100) : block.readiness.ready ? 100 : 0;

  return (
    <section className={`kai-block kai-interview-state is-${block.status}`} aria-label={block.title}>
      <BlockHeading title={block.title} description={block.description} status={block.status} />

      <section className="kai-interview-section" aria-label="已收集信息">
        <header><span><CheckCircle2 /><strong>已收集信息</strong></span><small>{collected} 项</small></header>
        {block.facts.length === 0
          ? <p className="kai-interview-empty">还没有可确认的事实，可直接在下方用自然语言补充。</p>
          : <dl className="kai-interview-facts">
            {block.facts.map((fact) => (
              <div key={`${fact.key}-${fact.status}`} className={`is-${fact.status}`}>
                <dt>
                  <span>{fact.label}{fact.hard_fact && <em className="is-hard"><LockKeyhole />硬事实</em>}</span>
                  <small><SourceBadge source={fact.source} /><FactStatusBadge status={fact.status} />{fact.editable && <em className="is-editable">可修改</em>}</small>
                </dt>
                <dd>{formatValue(fact.value)}</dd>
              </div>
            ))}
          </dl>}
      </section>

      <section className="kai-interview-classification" aria-label="分类建议">
        <Tags />
        <span>
          <small>分类建议</small>
          <strong>{block.classification.name || '暂未匹配到分类'}</strong>
          <em>{classificationLabel(block.classification.status)} · 置信度 {Math.round(block.classification.confidence * 100)}%</em>
        </span>
        {block.classification.status === 'needs_confirmation' && <b>待确认</b>}
      </section>

      {block.missing_information.length > 0 && (
        <section className="kai-interview-missing" aria-label="还需补充">
          <header><AlertTriangle /><strong>还需补充</strong></header>
          {block.missing_information.map((item) => (
            <div key={item.key} className={`is-${item.severity}`}>
              <span><b>{item.label}</b><small>{item.reason}</small></span>
              <em>{missingSeverityLabel(item.severity)}</em>
            </div>
          ))}
        </section>
      )}

      <footer className={`kai-interview-readiness ${block.readiness.ready ? 'is-ready' : ''}`}>
        <span><CircleHelp /><strong>{block.readiness.ready ? '信息已齐备' : '需求澄清进度'}</strong><small>{progress}%</small></span>
        <div className="kai-interview-progress" role="progressbar" aria-label={`访谈信息进度 ${progress}%`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><i style={{ width: `${progress}%` }} /></div>
        <p>{block.readiness.ready ? '可以进入草稿检查，真实发布仍需在业务页确认。' : `还有 ${block.readiness.blocking_fields.length} 个阻塞项，可回答下方问题或直接输入补充。`}</p>
      </footer>
    </section>
  );
}

function SourceBadge({ source }: { source: string }) {
  const labels: Record<string, string> = {
    user_message: '用户原话', user_choice: '用户选择', user_edit: '用户修改',
    attachment_extraction: '附件提取', existing_record: '已授权数据', ai_expansion: 'AI 扩写', system_default: '平台默认',
  };
  return <em className={`kai-interview-source is-${source}`}>{labels[source] || source}</em>;
}

function FactStatusBadge({ status }: { status: InterviewFactStatus }) {
  return <em className={`kai-interview-fact-status is-${status}`}>{({
    candidate: '候选', confirmed: '已确认', conflict: '有冲突', superseded: '已更新',
  } as Record<InterviewFactStatus, string>)[status]}</em>;
}

function classificationLabel(status: InterviewClassificationStatus) {
  return ({
    matched: '已匹配', suggested: 'AI 建议', needs_confirmation: '需你确认', unmatched: '暂未匹配',
  } as Record<InterviewClassificationStatus, string>)[status];
}

function missingSeverityLabel(severity: 'blocking' | 'warning' | 'info') {
  return { blocking: '必填', warning: '建议', info: '可选' }[severity];
}

function formatValue(value: JsonValue): string {
  if (value === null) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.map(formatValue).join('、');
  return Object.entries(value).map(([key, item]) => `${key}：${formatValue(item)}`).join('；');
}
