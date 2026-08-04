// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import type { InterviewStateBlock as InterviewStateBlockType } from '../protocol';
import { InterviewStateBlock } from './InterviewStateBlock';

afterEach(cleanup);

describe('InterviewStateBlock', () => {
  it('shows fact provenance and confidence states without exposing model reasoning', () => {
    render(<InterviewStateBlock block={interviewState()} />);

    expect(screen.getByText('已收集信息')).toBeTruthy();
    expect(screen.getByText('用户原话')).toBeTruthy();
    expect(screen.getByText('候选')).toBeTruthy();
    expect(screen.getByText('有冲突')).toBeTruthy();
    expect(screen.getByText('硬事实')).toBeTruthy();
    expect(screen.getByText('品牌设计')).toBeTruthy();
    expect(screen.getByText(/需你确认 · 置信度 82%/)).toBeTruthy();
    expect(screen.getByText('预算范围')).toBeTruthy();
    expect(screen.getByRole('progressbar', { name: /访谈信息进度/ }).getAttribute('aria-valuenow')).toBe('67');
    expect(screen.queryByText(/思考过程|推理链|chain of thought/i)).toBeNull();
  });
});

function interviewState(): InterviewStateBlockType {
  return {
    schema_version: '2.0', block_id: 'block_interview_component', block_version: 1,
    type: 'interview_state', status: 'reviewing', title: '需求理解进度', description: '只展示可验证事实。',
    facts: [
      {
        key: 'goal', label: '服务目标', value: '完成品牌升级', source: 'user_message', status: 'candidate',
        confidence: 0.95, hard_fact: true, editable: true, edit_action_id: 'edit_goal',
      },
      {
        key: 'audience', label: '目标受众', value: '企业客户 / 年轻用户', source: 'ai_expansion', status: 'conflict',
        confidence: 0.62, hard_fact: false, editable: true, edit_action_id: 'edit_audience',
      },
    ],
    classification: { category_id: 'brand-design', name: '品牌设计', confidence: 0.82, status: 'needs_confirmation' },
    missing_information: [{ key: 'budget', label: '预算范围', severity: 'blocking', reason: '用于筛选合适服务商。' }],
    readiness: { ready: false, blocking_fields: ['budget'] },
  };
}
