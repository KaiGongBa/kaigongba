import type { PageContext, PageEntityRef, PageUiState } from './protocol';
import {
  matchPlatformAssistantRoute,
  type AssistantOverlayRouteId,
  type PlatformAssistantRouteId,
} from './routeRegistry';

export type LocationLike = Readonly<{
  pathname: string;
  search?: string;
}>;

export type PageContextOptions = Readonly<{
  pageInstanceId?: string;
  organizationId?: string | null;
  contextVersion?: number;
  dirty?: boolean;
  activeTab?: string;
  view?: string;
  perspective?: PageUiState['perspective'];
}>;

export type RegisteredPageContext = PageContext<PlatformAssistantRouteId>;

export function collectPageContext(
  location: LocationLike,
  options: PageContextOptions = {},
): RegisteredPageContext | null {
  const match = matchPlatformAssistantRoute(location.pathname, location.search);
  if (!match) return null;
  const search = new URLSearchParams(normalizeSearch(location.search));
  const uiState = collectUiState(search, match.route.allowedQueryParams, options);
  const entityRefs = collectEntityRefs(match, search, options.organizationId);
  return {
    page_instance_id: validPageInstanceId(options.pageInstanceId)
      ? options.pageInstanceId
      : createPageInstanceId(),
    route_id: match.route.routeId as PlatformAssistantRouteId,
    pathname: normalizePathname(location.pathname),
    entity_refs: entityRefs,
    ui_state: uiState,
    context_version: validContextVersion(options.contextVersion) ? options.contextVersion : 1,
  };
}

/**
 * Opening the assistant on a registered page does not replace that page's
 * route or entities. The overlay route is used only as a safe fallback on a
 * page that is not yet in the context registry.
 */
export function collectAssistantOverlayPageContext(
  location: LocationLike,
  overlay: AssistantOverlayRouteId,
  options: PageContextOptions = {},
): RegisteredPageContext {
  const underlying = collectPageContext(location, options);
  if (underlying) return underlying;
  const organization = validEntityId(options.organizationId)
    ? [{ type: 'organization' as const, id: options.organizationId }]
    : [];
  return {
    page_instance_id: validPageInstanceId(options.pageInstanceId)
      ? options.pageInstanceId
      : createPageInstanceId(),
    route_id: overlay,
    pathname: normalizePathname(location.pathname),
    entity_refs: organization,
    ui_state: collectUiState(new URLSearchParams(), [], options),
    context_version: validContextVersion(options.contextVersion) ? options.contextVersion : 1,
  };
}

export function inheritAssistantOverlayPageContext(
  context: RegisteredPageContext,
): RegisteredPageContext {
  return {
    ...context,
    entity_refs: context.entity_refs.map((entity) => ({ ...entity })),
    ui_state: { ...context.ui_state },
  };
}

export function createPageInstanceId(): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) return `page_${randomUuid.replace(/-/g, '_')}`;
  const fallback = `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 14)}`;
  return `page_${fallback.padEnd(8, '0')}`;
}

function collectEntityRefs(
  match: NonNullable<ReturnType<typeof matchPlatformAssistantRoute>>,
  search: URLSearchParams,
  organizationId: string | null | undefined,
): PageEntityRef[] {
  const result: PageEntityRef[] = [];
  if (validEntityId(organizationId)) {
    result.push({ type: 'organization', id: organizationId });
  }
  for (const binding of match.route.entityRefs) {
    const id = binding.source === 'path'
      ? match.pathParameters[binding.parameter]
      : search.get(binding.parameter);
    if (validEntityId(id)) result.push({ type: binding.type, id });
  }
  return result.filter(
    (entity, index, all) => all.findIndex((candidate) => (
      candidate.type === entity.type && candidate.id === entity.id
    )) === index,
  ).slice(0, 8);
}

function collectUiState(
  search: URLSearchParams,
  allowedQueryParams: readonly string[],
  options: PageContextOptions,
): PageUiState {
  const allowed = new Set(allowedQueryParams);
  const activeTab = cleanUiValue(options.activeTab ?? (allowed.has('tab') ? search.get('tab') : null));
  const view = cleanUiValue(options.view ?? (allowed.has('view') ? search.get('view') : null));
  const queryPerspective = allowed.has('perspective') ? search.get('perspective') : null;
  const perspective = validPerspective(options.perspective)
    ? options.perspective
    : validPerspective(queryPerspective)
      ? queryPerspective
      : undefined;
  return {
    ...(activeTab ? { active_tab: activeTab } : {}),
    ...(view ? { view } : {}),
    ...(perspective ? { perspective } : {}),
    ...(typeof options.dirty === 'boolean' ? { dirty: options.dirty } : {}),
  };
}

function normalizeSearch(search: string | undefined): string {
  if (!search) return '';
  return search.startsWith('?') ? search.slice(1) : search;
}

function normalizePathname(pathname: string): string {
  if (!pathname.startsWith('/') || pathname.startsWith('//')) return '/';
  const safe = pathname.split(/[?#]/, 1)[0].replace(/\0/g, '').slice(0, 500);
  return safe || '/';
}

function cleanUiValue(value: string | null | undefined): string | undefined {
  const clean = value?.trim();
  return clean ? clean.slice(0, 80) : undefined;
}

function validPerspective(value: unknown): value is NonNullable<PageUiState['perspective']> {
  return value === 'buyer' || value === 'provider' || value === 'internal';
}

function validEntityId(value: unknown): value is string {
  return typeof value === 'string' && value.length >= 1 && value.length <= 160;
}

function validContextVersion(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 1;
}

function validPageInstanceId(value: unknown): value is string {
  return typeof value === 'string' && /^page_[A-Za-z0-9_-]{8,120}$/.test(value);
}
