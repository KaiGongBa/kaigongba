export type AssistantSurface = 'conversation' | 'marketplace' | 'assistant_overlay';

export type RouteEntityType =
  | 'organization'
  | 'agent'
  | 'requirement'
  | 'requirement_draft'
  | 'quote'
  | 'agreement'
  | 'order'
  | 'milestone'
  | 'deliverable'
  | 'dispute'
  | 'payment_order';

export type RouteEntityBinding = Readonly<{
  type: RouteEntityType;
  source: 'path' | 'query';
  parameter: string;
  required: boolean;
}>;

export type PlatformAssistantRouteDefinition = Readonly<{
  routeId: string;
  pathPattern: string | null;
  surface: AssistantSurface;
  entityRefs: readonly RouteEntityBinding[];
  allowedQueryParams: readonly string[];
  allowedProjections: readonly string[];
  authorization: string;
  safeDeepLink: boolean;
  matchPriority: number;
  canonicalQuery?: Readonly<Record<string, string>>;
}>;

/**
 * Front-end mirror of contracts/platform-assistant/v1/route-context-registry.json.
 *
 * The two duplicate path pairs deliberately preserve the current application
 * semantics: project center defaults to the agent view, and provider workspace
 * defaults to quotes. `canonicalQuery` makes generated links explicit without
 * changing those legacy defaults.
 */
export const PLATFORM_ASSISTANT_ROUTES = [
  {
    routeId: 'enterprise.order.deliverable',
    pathPattern: '/enterprise/orders/:orderId/deliverables/:deliverableId',
    surface: 'marketplace',
    entityRefs: [
      { type: 'order', source: 'path', parameter: 'orderId', required: true },
      { type: 'deliverable', source: 'path', parameter: 'deliverableId', required: true },
    ],
    allowedQueryParams: [],
    allowedProjections: ['order.party_summary', 'deliverable.visible_summary', 'deliverable.visible_versions', 'deliverable.visible_todos'],
    authorization: 'deliverable_visible',
    safeDeepLink: true,
    matchPriority: 520,
  },
  {
    routeId: 'enterprise.requirement.quotes',
    pathPattern: '/enterprise/demands/:requirementId/quotes',
    surface: 'marketplace',
    entityRefs: [{ type: 'requirement', source: 'path', parameter: 'requirementId', required: true }],
    allowedQueryParams: [],
    allowedProjections: ['requirement.detail_summary', 'quote.visible_comparison', 'quote.visible_todos'],
    authorization: 'requirement_visible',
    safeDeepLink: true,
    matchPriority: 510,
  },
  {
    routeId: 'enterprise.provider.quote',
    pathPattern: '/enterprise/provider/quotes/:quoteId',
    surface: 'marketplace',
    entityRefs: [{ type: 'quote', source: 'path', parameter: 'quoteId', required: true }],
    allowedQueryParams: [],
    allowedProjections: ['quote.visible_summary', 'quote.visible_versions', 'quote.visible_todos'],
    authorization: 'requirement_visible',
    safeDeepLink: true,
    matchPriority: 500,
  },
  {
    routeId: 'enterprise.agreement.detail',
    pathPattern: '/enterprise/agreements/:agreementId',
    surface: 'marketplace',
    entityRefs: [{ type: 'agreement', source: 'path', parameter: 'agreementId', required: true }],
    allowedQueryParams: [],
    allowedProjections: ['agreement.party_summary', 'agreement.confirmation_summary', 'agreement.visible_todos'],
    authorization: 'agreement_party',
    safeDeepLink: true,
    matchPriority: 500,
  },
  {
    routeId: 'enterprise.dispute.detail',
    pathPattern: '/enterprise/disputes/:caseId',
    surface: 'marketplace',
    entityRefs: [{ type: 'dispute', source: 'path', parameter: 'caseId', required: true }],
    allowedQueryParams: [],
    allowedProjections: ['dispute.party_summary', 'dispute.visible_timeline', 'dispute.visible_todos'],
    authorization: 'dispute_party',
    safeDeepLink: true,
    matchPriority: 500,
  },
  {
    routeId: 'enterprise.payment.detail',
    pathPattern: '/enterprise/payments/:paymentOrderId',
    surface: 'marketplace',
    entityRefs: [{ type: 'payment_order', source: 'path', parameter: 'paymentOrderId', required: true }],
    allowedQueryParams: [],
    allowedProjections: ['payment.visible_summary', 'payment.visible_timeline', 'payment.visible_todos'],
    authorization: 'order_party',
    safeDeepLink: true,
    matchPriority: 500,
  },
  {
    routeId: 'enterprise.requirement.detail',
    pathPattern: '/enterprise/demands/:requirementId',
    surface: 'marketplace',
    entityRefs: [{ type: 'requirement', source: 'path', parameter: 'requirementId', required: true }],
    allowedQueryParams: [],
    allowedProjections: ['requirement.detail_summary', 'requirement.visible_quotes', 'requirement.visible_todos'],
    authorization: 'requirement_visible',
    safeDeepLink: true,
    matchPriority: 490,
  },
  {
    routeId: 'enterprise.order.workspace',
    pathPattern: '/enterprise/orders/:orderId',
    surface: 'marketplace',
    entityRefs: [{ type: 'order', source: 'path', parameter: 'orderId', required: true }],
    allowedQueryParams: ['tab'],
    allowedProjections: ['order.party_summary', 'order.progress_summary', 'order.visible_todos', 'order.visible_deliverables'],
    authorization: 'order_party',
    safeDeepLink: true,
    matchPriority: 300,
  },
  {
    routeId: 'workspace.project_center.agent',
    pathPattern: '/workspace/projects/agents/:agentId',
    surface: 'conversation',
    entityRefs: [{ type: 'agent', source: 'path', parameter: 'agentId', required: true }],
    allowedQueryParams: [],
    allowedProjections: ['agent.public_status', 'agent.visible_projects', 'agent.visible_progress'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 300,
  },
  {
    routeId: 'workspace.project_center.projects',
    pathPattern: '/workspace/gallery',
    surface: 'conversation',
    entityRefs: [],
    allowedQueryParams: ['view'],
    allowedProjections: ['project.visible_list', 'project.visible_todos'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 220,
    canonicalQuery: { view: 'projects' },
  },
  {
    routeId: 'workspace.project_center.agents',
    pathPattern: '/workspace/gallery',
    surface: 'conversation',
    entityRefs: [],
    allowedQueryParams: ['view'],
    allowedProjections: ['agent.visible_list', 'agent.public_status'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 210,
    canonicalQuery: { view: 'agents' },
  },
  {
    routeId: 'enterprise.transaction.overview',
    pathPattern: '/enterprise/transactions',
    surface: 'marketplace',
    entityRefs: [],
    allowedQueryParams: [],
    allowedProjections: ['transaction.summary', 'transaction.visible_todos'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 200,
  },
  {
    routeId: 'enterprise.requirement.list',
    pathPattern: '/enterprise/demands',
    surface: 'marketplace',
    entityRefs: [],
    allowedQueryParams: ['status'],
    allowedProjections: ['requirement.visible_list', 'requirement.visible_todos'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 200,
  },
  {
    routeId: 'enterprise.requirement.create',
    pathPattern: '/enterprise/demands/new',
    surface: 'marketplace',
    entityRefs: [{ type: 'requirement_draft', source: 'query', parameter: 'draftId', required: false }],
    allowedQueryParams: ['draftId'],
    allowedProjections: ['requirement.assistant_draft', 'organization.selection', 'category.catalog'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 600,
  },
  {
    routeId: 'enterprise.order.list',
    pathPattern: '/enterprise/orders',
    surface: 'marketplace',
    entityRefs: [],
    allowedQueryParams: ['perspective', 'status'],
    allowedProjections: ['order.visible_list', 'order.visible_todos'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 200,
  },
  {
    routeId: 'enterprise.confirmation.list',
    pathPattern: '/enterprise/confirmations',
    surface: 'marketplace',
    entityRefs: [],
    allowedQueryParams: [],
    allowedProjections: ['confirmation.visible_list', 'confirmation.visible_todos'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 200,
  },
  {
    routeId: 'enterprise.publishing.list',
    pathPattern: '/enterprise/publishing',
    surface: 'marketplace',
    entityRefs: [],
    allowedQueryParams: ['type', 'status'],
    allowedProjections: ['publishing.visible_list', 'publishing.visible_todos'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 200,
  },
  {
    routeId: 'enterprise.provider.workbench',
    pathPattern: '/enterprise/provider',
    surface: 'marketplace',
    entityRefs: [],
    allowedQueryParams: ['view'],
    allowedProjections: ['provider.workbench_summary', 'provider.visible_todos'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 220,
    canonicalQuery: { view: 'workbench' },
  },
  {
    routeId: 'enterprise.provider.quotes',
    pathPattern: '/enterprise/provider',
    surface: 'marketplace',
    entityRefs: [],
    allowedQueryParams: ['view'],
    allowedProjections: ['quote.visible_list', 'quote.visible_todos'],
    authorization: 'organization_member',
    safeDeepLink: true,
    matchPriority: 210,
    canonicalQuery: { view: 'quotes' },
  },
  {
    routeId: 'assistant.chat',
    pathPattern: null,
    surface: 'assistant_overlay',
    entityRefs: [],
    allowedQueryParams: [],
    allowedProjections: ['assistant.active_workflow'],
    authorization: 'authenticated',
    safeDeepLink: false,
    matchPriority: 0,
  },
  {
    routeId: 'assistant.notifications',
    pathPattern: null,
    surface: 'assistant_overlay',
    entityRefs: [],
    allowedQueryParams: [],
    allowedProjections: ['notification.visible_list'],
    authorization: 'authenticated',
    safeDeepLink: false,
    matchPriority: 0,
  },
] as const satisfies readonly PlatformAssistantRouteDefinition[];

export type PlatformAssistantRouteId = typeof PLATFORM_ASSISTANT_ROUTES[number]['routeId'];
export type UnderlyingRouteId = Exclude<PlatformAssistantRouteId, 'assistant.chat' | 'assistant.notifications'>;
export type AssistantOverlayRouteId = Extract<PlatformAssistantRouteId, 'assistant.chat' | 'assistant.notifications'>;

export type RouteMatch = Readonly<{
  route: PlatformAssistantRouteDefinition;
  pathParameters: Readonly<Record<string, string>>;
}>;

const ROUTE_BY_ID = new Map<string, PlatformAssistantRouteDefinition>(
  PLATFORM_ASSISTANT_ROUTES.map((route) => [route.routeId, route] as const),
);

export function getPlatformAssistantRoute(routeId: string) {
  return ROUTE_BY_ID.get(routeId) ?? null;
}

export function matchPlatformAssistantRoute(pathname: string, search = ''): RouteMatch | null {
  const safePathname = normalizePathname(pathname);
  if (!safePathname) return null;
  const query = new URLSearchParams(normalizeSearch(search));
  const candidates: RouteMatch[] = [];
  for (const route of PLATFORM_ASSISTANT_ROUTES as readonly PlatformAssistantRouteDefinition[]) {
    if (route.pathPattern === null) continue;
    const pathParameters = matchPathPattern(route.pathPattern, safePathname);
    if (pathParameters) candidates.push({ route, pathParameters });
  }

  if (!candidates.length) return null;
  if (safePathname === '/workspace/gallery') {
    const routeId = query.get('view') === 'projects'
      ? 'workspace.project_center.projects'
      : 'workspace.project_center.agents';
    return candidates.find((candidate) => candidate.route.routeId === routeId) ?? null;
  }
  if (safePathname === '/enterprise/provider') {
    const routeId = query.get('view') === 'workbench'
      ? 'enterprise.provider.workbench'
      : 'enterprise.provider.quotes';
    return candidates.find((candidate) => candidate.route.routeId === routeId) ?? null;
  }
  return candidates.sort((left, right) => right.route.matchPriority - left.route.matchPriority)[0] ?? null;
}

/**
 * Generates links only for registered, explicitly safe routes. All path and
 * query values are encoded, unknown keys fail closed, and overlay routes can
 * never be converted into URLs.
 */
export function buildSafePlatformAssistantUrl(
  routeId: string,
  routeParameters: Readonly<Record<string, string>> = {},
): string | null {
  const route = getPlatformAssistantRoute(routeId);
  if (!route || !route.safeDeepLink || route.pathPattern === null) return null;

  const pathParameterNames = pathParameters(route.pathPattern);
  const allowedKeys = new Set([...pathParameterNames, ...route.allowedQueryParams]);
  if (Object.keys(routeParameters).some((key) => !allowedKeys.has(key))) return null;
  if (Object.values(routeParameters).some((value) => !validParameterValue(value))) return null;

  let pathname: string = route.pathPattern;
  for (const parameterName of pathParameterNames) {
    const value = routeParameters[parameterName];
    if (!validParameterValue(value)) return null;
    pathname = pathname.replace(`:${parameterName}`, encodeURIComponent(value));
  }

  const query = new URLSearchParams();
  for (const [key, canonicalValue] of Object.entries(route.canonicalQuery ?? {})) {
    if (routeParameters[key] !== undefined && routeParameters[key] !== canonicalValue) return null;
    query.set(key, canonicalValue);
  }
  for (const key of route.allowedQueryParams) {
    if (route.canonicalQuery?.[key] !== undefined) continue;
    const value = routeParameters[key];
    if (value !== undefined) query.set(key, value);
  }
  const queryString = query.toString();
  return queryString ? `${pathname}?${queryString}` : pathname;
}

function pathParameters(pathPattern: string): string[] {
  return pathPattern
    .split('/')
    .filter((segment) => segment.startsWith(':'))
    .map((segment) => segment.slice(1));
}

function matchPathPattern(pathPattern: string, pathname: string): Record<string, string> | null {
  const patternSegments = pathPattern.split('/').filter(Boolean);
  const pathSegments = pathname.split('/').filter(Boolean);
  if (patternSegments.length !== pathSegments.length) return null;
  const result: Record<string, string> = {};
  for (let index = 0; index < patternSegments.length; index += 1) {
    const patternSegment = patternSegments[index];
    const pathSegment = pathSegments[index];
    if (patternSegment.startsWith(':')) {
      const decoded = safeDecodeURIComponent(pathSegment);
      if (!validParameterValue(decoded)) return null;
      result[patternSegment.slice(1)] = decoded;
    } else if (patternSegment !== pathSegment) {
      return null;
    }
  }
  return result;
}

function normalizePathname(pathname: string): string | null {
  if (!pathname.startsWith('/') || pathname.startsWith('//') || pathname.length > 500) return null;
  const withoutQuery = pathname.split(/[?#]/, 1)[0];
  if (!withoutQuery || withoutQuery.includes('\0')) return null;
  return withoutQuery.length > 1 && withoutQuery.endsWith('/') ? withoutQuery.slice(0, -1) : withoutQuery;
}

function normalizeSearch(search: string): string {
  return search.startsWith('?') ? search.slice(1) : search;
}

function validParameterValue(value: unknown): value is string {
  return typeof value === 'string' && value.length >= 1 && value.length <= 160 && !value.includes('\0');
}

function safeDecodeURIComponent(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return '';
  }
}
