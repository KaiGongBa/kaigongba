import { describe, expect, it } from 'vitest';
import { EMPTY_DEMAND_FORM, mergeNonEmptyRequirementSeed } from './demandDraftSeed';

describe('assistant requirement form seed', () => {
  it('maps only usable values and keeps existing values for empty seed fields', () => {
    const result = mergeNonEmptyRequirementSeed(
      { ...EMPTY_DEMAND_FORM, title: '已有标题', description: '已有描述' },
      {
        title: '  ',
        category_id: 'hr-consulting',
        category: '人力资源咨询',
        description: null,
        desired_delivery_at: '2026-09-02T18:30:00+08:00',
        deliverables: [{ name: '招聘流程诊断报告', format: 'PDF', required: true }],
        acceptance_criteria: ['', '报告包含问题优先级'],
      },
    );

    expect(result.title).toBe('已有标题');
    expect(result.description).toBe('已有描述');
    expect(result.category).toBe('人力资源咨询');
    expect(result.categoryId).toBe('hr-consulting');
    expect(result.deadline).toBe('2026-09-02T18:30');
    expect(result.deliverables).toEqual([
      { name: '招聘流程诊断报告', format: '.pdf', required: true },
    ]);
    expect(result.criteria).toEqual(['报告包含问题优先级']);
  });

  it('clears a stale category ID when a seed only supplies a legacy category name', () => {
    const result = mergeNonEmptyRequirementSeed(
      { ...EMPTY_DEMAND_FORM, categoryId: 'catalog-old', category: '旧目录分类' },
      { category: '历史自定义分类', category_id: null },
    );

    expect(result.category).toBe('历史自定义分类');
    expect(result.categoryId).toBeUndefined();
  });

  it('normalizes presentation formats from the assistant handoff', () => {
    const result = mergeNonEmptyRequirementSeed(EMPTY_DEMAND_FORM, {
      deliverables: [
        { name: '融资路演源文件', format: 'PPTX', required: true },
      ],
    });

    expect(result.deliverables).toEqual([
      { name: '融资路演源文件', format: '.pptx', required: true },
    ]);
  });

  it('keeps verified business attachment identity for the transaction handoff', () => {
    const result = mergeNonEmptyRequirementSeed(EMPTY_DEMAND_FORM, {
      attachments: [{
        file_id: 'reqfile_verified001',
        filename: '需求材料.pdf',
        content_type: 'application/pdf',
        size: 2048,
        sha256: 'a'.repeat(64),
      }],
    });

    expect(result.attachments[0]).toMatchObject({
      id: 'reqfile_verified001',
      file_id: 'reqfile_verified001',
      filename: '需求材料.pdf',
      sha256: 'a'.repeat(64),
    });
  });
});
