import type { ChatAttachmentKind, ChatAttachmentRead } from '@/types';
import type { AssistantRequirementFormSeed, RequirementInput } from './types';

export type DemandFormState = {
  title: string;
  categoryId?: string;
  category: string;
  description: string;
  budgetMin: string;
  budgetMax: string;
  deadline: string;
  visibility: RequirementInput['visibility'];
  confidentialityLevel: RequirementInput['confidentiality_level'];
  inviteLimit: number;
  deliverables: Array<{ name: string; format: string; required: boolean }>;
  criteria: string[];
  attachments: DemandAttachment[];
};

export type DemandAttachment = ChatAttachmentRead & {
  file_id?: string;
  sha256?: string;
};

export const EMPTY_DEMAND_FORM: DemandFormState = {
  title: '',
  categoryId: undefined,
  category: '',
  description: '',
  budgetMin: '',
  budgetMax: '',
  deadline: '',
  visibility: 'invited_providers',
  confidentialityLevel: 'standard',
  inviteLimit: 5,
  deliverables: [],
  criteria: [],
  attachments: [],
};

export function mergeNonEmptyRequirementSeed(
  current: DemandFormState,
  seed: AssistantRequirementFormSeed,
): DemandFormState {
  const seededCategory = nonEmptyText(seed.category);
  const seededCategoryId = nonEmptyText(seed.category_id);
  return {
    title: nonEmptyText(seed.title) ?? current.title,
    categoryId: seededCategory
      ? seededCategoryId
      : current.categoryId,
    category: seededCategory ?? current.category,
    description: nonEmptyText(seed.description) ?? current.description,
    budgetMin: nonEmptyText(seed.budget_min_amount) ?? current.budgetMin,
    budgetMax: nonEmptyText(seed.budget_max_amount) ?? current.budgetMax,
    deadline: toLocalDateTimeValue(seed.desired_delivery_at) ?? current.deadline,
    visibility: seed.visibility ?? current.visibility,
    confidentialityLevel: seed.confidentiality_level ?? current.confidentialityLevel,
    inviteLimit: typeof seed.invite_limit === 'number' && seed.invite_limit > 0
      ? seed.invite_limit
      : current.inviteLimit,
    deliverables: mapDeliverables(seed.deliverables) ?? current.deliverables,
    criteria: nonEmptyStrings(seed.acceptance_criteria) ?? current.criteria,
    attachments: mapAttachments(seed.attachments) ?? current.attachments,
  };
}

function nonEmptyText(value: string | null | undefined) {
  if (typeof value !== 'string') return undefined;
  return value.trim() ? value : undefined;
}

function nonEmptyStrings(value: string[] | null | undefined) {
  if (!Array.isArray(value)) return undefined;
  const clean = value.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()));
  return clean.length ? clean : undefined;
}

function mapDeliverables(value: Array<Record<string, unknown>> | null | undefined) {
  if (!Array.isArray(value)) return undefined;
  const rows = value.flatMap((item) => {
    if (typeof item.name !== 'string' || !item.name.trim()) return [];
    return [{
      name: item.name,
      format: normalizeFormat(item.format),
      required: typeof item.required === 'boolean' ? item.required : true,
    }];
  });
  return rows.length ? rows : undefined;
}

function normalizeFormat(value: unknown) {
  if (typeof value !== 'string' || !value.trim()) return '.docx';
  const normalized = value.trim().toLocaleLowerCase().replace(/^\./, '');
  if (normalized === 'pptx') return '.pptx';
  if (normalized === 'ppt') return '.ppt';
  if (normalized === 'xlsx') return '.xlsx';
  if (normalized === 'docx') return '.docx';
  if (normalized === 'pdf') return '.pdf';
  if (normalized === 'link' || normalized === '链接') return '链接';
  return value;
}

function mapAttachments(value: Array<Record<string, unknown>> | null | undefined) {
  if (!Array.isArray(value)) return undefined;
  const rows = value.flatMap((item) => {
    const id = textValue(item.id) ?? textValue(item.file_id);
    const filename = textValue(item.filename) ?? textValue(item.name);
    const contentType = textValue(item.content_type);
    const size = typeof item.size === 'number' ? item.size : undefined;
    if (!id || !filename || !contentType || size === undefined || size < 0) return [];
    const kind = attachmentKind(item.kind, contentType);
    return [{
      id,
      file_id: textValue(item.file_id),
      filename,
      content_type: contentType,
      size,
      kind,
      sha256: textValue(item.sha256),
      data_url: typeof item.data_url === 'string' ? item.data_url : null,
    } satisfies DemandAttachment];
  });
  return rows.length ? rows : undefined;
}

function textValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

function attachmentKind(value: unknown, contentType: string): ChatAttachmentKind {
  if (value === 'text' || value === 'pdf' || value === 'image' || value === 'binary') return value;
  if (contentType === 'application/pdf') return 'pdf';
  if (contentType.startsWith('image/')) return 'image';
  if (contentType.startsWith('text/')) return 'text';
  return 'binary';
}

function toLocalDateTimeValue(value: string | null | undefined) {
  const clean = nonEmptyText(value);
  if (!clean) return undefined;
  // datetime-local accepts a timezone-free `YYYY-MM-DDTHH:mm` value. The
  // transaction form intentionally preserves the supplied business wall clock.
  const match = clean.match(/^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})/);
  return match?.[1];
}
