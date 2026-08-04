import { describe, expect, it } from 'vitest';

import {
  PLATFORM_ASSISTANT_ROUTES,
  buildSafePlatformAssistantUrl,
  matchPlatformAssistantRoute,
} from './routeRegistry';

describe('platform assistant route registry', () => {
  it('covers all registered page and overlay contexts without duplicate ids', () => {
    expect(PLATFORM_ASSISTANT_ROUTES.length).toBeGreaterThanOrEqual(21);
    expect(new Set(PLATFORM_ASSISTANT_ROUTES.map((route) => route.routeId)).size)
      .toBe(PLATFORM_ASSISTANT_ROUTES.length);
  });

  it('preserves the existing project center view semantics', () => {
    expect(matchPlatformAssistantRoute('/workspace/gallery')?.route.routeId)
      .toBe('workspace.project_center.agents');
    expect(matchPlatformAssistantRoute('/workspace/gallery', '?view=agents')?.route.routeId)
      .toBe('workspace.project_center.agents');
    expect(matchPlatformAssistantRoute('/workspace/gallery', '?view=projects')?.route.routeId)
      .toBe('workspace.project_center.projects');
  });

  it('preserves the existing provider workspace semantics', () => {
    expect(matchPlatformAssistantRoute('/enterprise/provider')?.route.routeId)
      .toBe('enterprise.provider.quotes');
    expect(matchPlatformAssistantRoute('/enterprise/provider', '?view=quotes')?.route.routeId)
      .toBe('enterprise.provider.quotes');
    expect(matchPlatformAssistantRoute('/enterprise/provider', '?view=workbench')?.route.routeId)
      .toBe('enterprise.provider.workbench');
  });

  it('matches specific routes and extracts only declared entity references', () => {
    const order = matchPlatformAssistantRoute('/enterprise/orders/order%2Fencoded', '?tab=deliverables');
    const create = matchPlatformAssistantRoute('/enterprise/demands/new');
    expect(order?.route.routeId).toBe('enterprise.order.workspace');
    expect(order?.pathParameters).toEqual({ orderId: 'order/encoded' });
    expect(create?.route.routeId).toBe('enterprise.requirement.create');
    expect(matchPlatformAssistantRoute('/enterprise/orders')).toMatchObject({
      route: { routeId: 'enterprise.order.list' },
    });
    expect(matchPlatformAssistantRoute('/enterprise/demands/requirement_1/quotes')).toMatchObject({
      route: { routeId: 'enterprise.requirement.quotes' },
      pathParameters: { requirementId: 'requirement_1' },
    });
    expect(matchPlatformAssistantRoute('/enterprise/orders/order_1/deliverables/deliverable_1')).toMatchObject({
      route: { routeId: 'enterprise.order.deliverable' },
      pathParameters: { orderId: 'order_1', deliverableId: 'deliverable_1' },
    });
    expect(matchPlatformAssistantRoute('/enterprise/disputes/dispute_1')?.route.routeId)
      .toBe('enterprise.dispute.detail');
    expect(matchPlatformAssistantRoute('/enterprise/payments/payment_1')?.route.routeId)
      .toBe('enterprise.payment.detail');
  });

  it('generates only controlled deep links and encodes path values', () => {
    expect(buildSafePlatformAssistantUrl('enterprise.order.workspace', {
      orderId: 'order/with spaces',
      tab: 'deliverables',
    })).toBe('/enterprise/orders/order%2Fwith%20spaces?tab=deliverables');
    expect(buildSafePlatformAssistantUrl('workspace.project_center.projects'))
      .toBe('/workspace/gallery?view=projects');
    expect(buildSafePlatformAssistantUrl('enterprise.provider.quotes'))
      .toBe('/enterprise/provider?view=quotes');
    expect(buildSafePlatformAssistantUrl('enterprise.requirement.create', { draftId: 'draft_1' }))
      .toBe('/enterprise/demands/new?draftId=draft_1');
    expect(buildSafePlatformAssistantUrl('enterprise.order.deliverable', {
      orderId: 'order_1',
      deliverableId: 'deliverable_1',
    })).toBe('/enterprise/orders/order_1/deliverables/deliverable_1');
  });

  it('fails closed for arbitrary routes, URLs, params and overlay routes', () => {
    expect(buildSafePlatformAssistantUrl('https://evil.example')).toBeNull();
    expect(buildSafePlatformAssistantUrl('assistant.chat')).toBeNull();
    expect(buildSafePlatformAssistantUrl('enterprise.order.workspace', {})).toBeNull();
    expect(buildSafePlatformAssistantUrl('enterprise.order.workspace', {
      orderId: 'order_1',
      redirect: 'https://evil.example',
    })).toBeNull();
    expect(buildSafePlatformAssistantUrl('workspace.project_center.projects', { view: 'agents' }))
      .toBeNull();
  });
});
