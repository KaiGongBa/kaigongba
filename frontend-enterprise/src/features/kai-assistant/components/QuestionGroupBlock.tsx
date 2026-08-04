import { Check, CircleHelp, Send } from 'lucide-react';
import { useMemo, useState } from 'react';

import type {
  AdaptiveQuestionGroupBlock,
  AnswerSubmission,
  AnswerValue,
  QuestionGroupBlock as QuestionGroupBlockType,
  StructuredQuestion,
} from '../protocol';

type LocalAnswer =
  | { kind: 'options'; optionIds: string[]; customText?: string }
  | { kind: 'text'; text: string }
  | { kind: 'money'; minimum: string; maximum: string }
  | { kind: 'date'; date: string }
  | { kind: 'duration'; duration: string; unit: 'hour' | 'calendar_day' | 'business_day' | 'week' }
  | { kind: 'entity'; entityRefs: Array<{ type: string; id: string }> }
  | { kind: 'boolean'; value: boolean | null }
  | { kind: 'uncertain' };

type DurationUnit = Extract<LocalAnswer, { kind: 'duration' }>['unit'];

export function QuestionGroupBlock({
  block,
  disabled,
  onSubmit,
}: {
  block: QuestionGroupBlockType | AdaptiveQuestionGroupBlock;
  disabled?: boolean;
  onSubmit: (submission: Pick<AnswerSubmission, 'block_id' | 'block_version' | 'answers'>) => void;
}) {
  const [answers, setAnswers] = useState<Record<string, LocalAnswer>>({});
  const missing = useMemo(
    () => block.questions.filter((question) => (
      question.required && !requiresBusinessPage(question) && !complete(question, answers[question.id])
    )),
    [answers, block.questions],
  );
  const locked = disabled || block.status !== 'pending';

  function submit() {
    if (missing.length || locked) return;
    const now = new Date().toISOString();
    onSubmit({
      block_id: block.block_id,
      block_version: block.block_version,
      answers: block.questions.flatMap((question) => {
        const answer = answers[question.id];
        const value = answerValue(answer);
        return value ? [{ question_id: question.id, value, client_updated_at: now }] : [];
      }),
    });
  }

  return (
    <section className="kai-block kai-question-block" aria-label={block.title}>
      <BlockHeading title={block.title} description={block.description} status={block.status} />
      <div className="kai-question-list">
        {block.questions.map((question, index) => (
          <QuestionField
            key={question.id}
            number={index + 1}
            question={question}
            value={answers[question.id]}
            disabled={locked}
            onChange={(value) => setAnswers((current) => ({ ...current, [question.id]: value }))}
          />
        ))}
      </div>
      <footer className="kai-question-submit">
        <span aria-live="polite">
          {locked
            ? '本组答案已提交，不会覆盖历史记录。'
            : missing.length
              ? `还需回答 ${missing.length} 个必填问题`
              : '答案会一次提交，提交前仍可修改。'}
          {block.schema_version === '2.0' && block.allow_free_text && <small>也可在下方对话框用自然语言补充</small>}
        </span>
        <button type="button" disabled={locked || missing.length > 0} onClick={submit}>
          {locked ? <Check /> : <Send />}{locked ? '已提交' : block.submit_label}
        </button>
      </footer>
    </section>
  );
}

function QuestionField({
  question,
  number,
  value,
  disabled,
  onChange,
}: {
  question: StructuredQuestion;
  number: number;
  value?: LocalAnswer;
  disabled: boolean;
  onChange: (value: LocalAnswer) => void;
}) {
  const selected = value?.kind === 'options' ? value.optionIds : [];
  const optionMode = question.input_type === 'single_choice' || question.input_type === 'multi_choice';

  function selectOption(optionId: string) {
    const multiple = question.input_type === 'multi_choice';
    let next = multiple
      ? selected.includes(optionId)
        ? selected.filter((id) => id !== optionId)
        : [...selected, optionId]
      : [optionId];
    const mutuallyExclusive = new Set(question.mutually_exclusive_option_ids || []);
    if (mutuallyExclusive.has(optionId)) next = [optionId];
    else next = next.filter((id) => !mutuallyExclusive.has(id));
    if (question.max_selections) next = next.slice(-question.max_selections);
    onChange({
      kind: 'options',
      optionIds: next,
      customText: value?.kind === 'options' ? value.customText : undefined,
    });
  }

  return (
    <fieldset className="kai-question" disabled={disabled}>
      <legend><b>{number}</b><span>{question.label}{question.required && <em>*</em>}</span></legend>
      {question.help_text && <p><CircleHelp />{question.help_text}</p>}
      {optionMode && (
        <>
          <div className="kai-question-options">
            {(question.options || []).map((option) => (
              <label key={option.id} className={selected.includes(option.id) ? 'is-selected' : ''}>
                <input
                  type={question.input_type === 'multi_choice' ? 'checkbox' : 'radio'}
                  name={question.id}
                  checked={selected.includes(option.id)}
                  disabled={disabled || option.disabled}
                  onChange={() => selectOption(option.id)}
                />
                <span><strong>{option.label}{option.recommended && <small>建议</small>}</strong>{option.description && <em>{option.description}</em>}{option.disabled_reason && <em>{option.disabled_reason}</em>}</span>
                <Check />
              </label>
            ))}
          </div>
          {question.allow_custom && (
            <label className="kai-question-custom">
              <span>其他答案</span>
              <input
                aria-label={`${question.label}自定义答案`}
                type="text"
                placeholder="输入你的补充答案"
                value={value?.kind === 'options' ? value.customText || '' : ''}
                onChange={(event) => onChange({
                  kind: 'options',
                  optionIds: selected,
                  customText: event.target.value,
                })}
              />
            </label>
          )}
        </>
      )}
      {(question.input_type === 'short_text' || question.input_type === 'long_text') && (
        question.input_type === 'long_text'
          ? <textarea aria-label={question.label} minLength={question.min_length} maxLength={question.max_length} value={value?.kind === 'text' ? value.text : ''} onChange={(event) => onChange({ kind: 'text', text: event.target.value })} />
          : <input aria-label={question.label} type="text" minLength={question.min_length} maxLength={question.max_length} value={value?.kind === 'text' ? value.text : ''} onChange={(event) => onChange({ kind: 'text', text: event.target.value })} />
      )}
      {question.input_type === 'money_range' && (
        <div className="kai-question-range">
          <label>预算下限<input aria-label={`${question.label}下限`} type="number" min="0" value={value?.kind === 'money' ? value.minimum : ''} onChange={(event) => onChange({ kind: 'money', minimum: event.target.value, maximum: value?.kind === 'money' ? value.maximum : '' })} /></label>
          <span>至</span>
          <label>预算上限<input aria-label={`${question.label}上限`} type="number" min="0" value={value?.kind === 'money' ? value.maximum : ''} onChange={(event) => onChange({ kind: 'money', minimum: value?.kind === 'money' ? value.minimum : '', maximum: event.target.value })} /></label>
          <b>CNY</b>
        </div>
      )}
      {question.input_type === 'date' && (
        <input aria-label={question.label} type="date" value={value?.kind === 'date' ? value.date : ''} onChange={(event) => onChange({ kind: 'date', date: event.target.value })} />
      )}
      {question.input_type === 'date_or_duration' && (
        <div className="kai-date-or-duration">
          <div className="kai-question-mode" role="group" aria-label={`${question.label}回答方式`}>
            <button type="button" className={value?.kind !== 'duration' ? 'is-selected' : ''} onClick={() => onChange({ kind: 'date', date: value?.kind === 'date' ? value.date : '' })}>指定日期</button>
            <button type="button" className={value?.kind === 'duration' ? 'is-selected' : ''} onClick={() => onChange({ kind: 'duration', duration: '', unit: 'business_day' })}>按工期</button>
          </div>
          {value?.kind === 'duration'
            ? <DurationInput question={question} value={value} onChange={onChange} />
            : <input aria-label={question.label} type="date" value={value?.kind === 'date' ? value.date : ''} onChange={(event) => onChange({ kind: 'date', date: event.target.value })} />}
        </div>
      )}
      {question.input_type === 'duration' && (
        <DurationInput question={question} value={value?.kind === 'duration' ? value : undefined} onChange={onChange} />
      )}
      {question.input_type === 'boolean' && (
        <div className="kai-question-options is-compact">
          {[[true, '是'], [false, '否']].map(([optionValue, label]) => (
            <label key={String(optionValue)} className={value?.kind === 'boolean' && value.value === optionValue ? 'is-selected' : ''}>
              <input type="radio" name={question.id} checked={value?.kind === 'boolean' && value.value === optionValue} onChange={() => onChange({ kind: 'boolean', value: optionValue as boolean })} />
              <span><strong>{label}</strong></span><Check />
            </label>
          ))}
        </div>
      )}
      {question.input_type === 'entity_picker' && question.options?.length ? (
        <div className="kai-question-options">
          {question.options.map((option) => {
            const selectedEntity = value?.kind === 'entity' && value.entityRefs.some((entity) => entity.id === option.id);
            return (
              <label key={option.id} className={selectedEntity ? 'is-selected' : ''}>
                <input
                  type="radio"
                  name={question.id}
                  checked={selectedEntity}
                  disabled={disabled || option.disabled}
                  onChange={() => onChange({ kind: 'entity', entityRefs: [{ type: question.entity_type || 'organization', id: option.id }] })}
                />
                <span><strong>{option.label}</strong>{option.description && <em>{option.description}</em>}</span>
                {selectedEntity && <Check />}
              </label>
            );
          })}
        </div>
      ) : null}
      {(question.input_type === 'attachment' || (question.input_type === 'entity_picker' && !question.options?.length)) && (
        <div className="kai-question-unavailable">
          <strong>需要到真实业务表单完成</strong>
          <span>{question.input_type === 'attachment' ? '请在需求表单中上传并扫描附件，开小花不会伪造附件答案。' : '当前未收到可选的已授权企业，本项不在抽屉中生成不可回答控件。'}</span>
        </div>
      )}
      {question.allow_uncertain && !disabled && (
        <label className={`kai-question-uncertain ${value?.kind === 'uncertain' ? 'is-selected' : ''}`}>
          <input type="checkbox" checked={value?.kind === 'uncertain'} onChange={() => onChange(value?.kind === 'uncertain' ? emptyAnswer(question) : { kind: 'uncertain' })} />
          还不确定，请开小花给建议（不作为硬事实）
        </label>
      )}
    </fieldset>
  );
}

function DurationInput({
  question,
  value,
  onChange,
}: {
  question: StructuredQuestion;
  value?: Extract<LocalAnswer, { kind: 'duration' }>;
  onChange: (value: LocalAnswer) => void;
}) {
  return (
    <div className="kai-question-duration">
      <input aria-label={question.label} type="number" min="1" value={value?.duration || ''} onChange={(event) => onChange({ kind: 'duration', duration: event.target.value, unit: value?.unit || 'business_day' })} />
      <select aria-label={`${question.label}单位`} value={value?.unit || 'business_day'} onChange={(event) => onChange({ kind: 'duration', duration: value?.duration || '', unit: event.target.value as DurationUnit })}>
        <option value="hour">小时</option><option value="calendar_day">自然日</option><option value="business_day">工作日</option><option value="week">周</option>
      </select>
    </div>
  );
}

export function BlockHeading({ title, description, status }: { title: string; description: string; status: string }) {
  return <header className="kai-block-heading"><div><h3>{title}</h3>{description && <p>{description}</p>}</div><span className={`is-${status}`}>{statusLabel(status)}</span></header>;
}

function complete(question: StructuredQuestion, answer?: LocalAnswer) {
  if (!answer) return false;
  if (answer.kind === 'uncertain') return Boolean(question.allow_uncertain);
  if (answer.kind === 'options') return answer.optionIds.length > 0 || Boolean(answer.customText?.trim());
  if (answer.kind === 'text') return answer.text.trim().length >= (question.min_length || 1);
  if (answer.kind === 'money') return Number(answer.maximum) >= Number(answer.minimum) && Number(answer.maximum) > 0;
  if (answer.kind === 'date') return Boolean(answer.date);
  if (answer.kind === 'duration') return Number(answer.duration) > 0;
  if (answer.kind === 'entity') return answer.entityRefs.length > 0;
  if (answer.kind === 'boolean') return answer.value !== null;
  return false;
}

function answerValue(answer?: LocalAnswer): AnswerValue | null {
  if (!answer) return null;
  if (answer.kind === 'uncertain') return { uncertain: true };
  if (answer.kind === 'options') {
    const customText = answer.customText?.trim();
    return answer.optionIds.length || customText
      ? { option_ids: answer.optionIds, ...(customText ? { custom_text: customText } : {}) }
      : null;
  }
  if (answer.kind === 'text') return answer.text.trim() ? { text: answer.text.trim() } : null;
  if (answer.kind === 'money') return { minimum: answer.minimum, maximum: answer.maximum, currency: 'CNY' };
  if (answer.kind === 'date') return { date: answer.date, timezone: timeZone() };
  if (answer.kind === 'duration') return { duration: Number(answer.duration), unit: answer.unit, timezone: timeZone() };
  if (answer.kind === 'entity') return { entity_refs: answer.entityRefs };
  if (answer.kind === 'boolean' && answer.value !== null) return { boolean: answer.value };
  return null;
}

function requiresBusinessPage(question: StructuredQuestion) {
  return question.input_type === 'attachment'
    || (question.input_type === 'entity_picker' && !question.options?.length);
}

function emptyAnswer(question: StructuredQuestion): LocalAnswer {
  if (question.input_type === 'single_choice' || question.input_type === 'multi_choice') {
    return { kind: 'options', optionIds: [] };
  }
  return { kind: 'text', text: '' };
}

function statusLabel(value: string) {
  return ({ pending: '待回答', submitted: '已提交', reviewing: '待检查', succeeded: '已完成', failed: '失败', blocked: '需处理', disabled: '不可用', superseded: '已更新' } as Record<string, string>)[value] || value;
}

function timeZone() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai';
}
