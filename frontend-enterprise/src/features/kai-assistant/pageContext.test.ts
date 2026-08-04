import { describe, expect, it } from 'vitest';

import {
  collectAssistantOverlayPageContext,
  collectPageContext,
  inheritAssistantOverlayPageContext,
} from './pageContext';

const PAGE_ID = 'page_context_test_001';

describe('platform assistant page context', () => {
  it('collects registered path entities, organization and allowed UI state', () => {
    const context = collectPageContext(
      { pathname: '/enterprise/orders/order_39', search: '?tab=deliverables&redirect=https://evil.example' },
      { pageInstanceId: PAGE_ID, organizationId: 'org_buyer', contextVersion: 7, dirty: true },
    );
    expect(context).toEqual({
      page_instance_id: PAGE_ID,
      route_id: 'enterprise.order.workspace',
      pathname: '/enterprise/orders/order_39',
      entity_refs: [
        { type: 'organization', id: 'org_buyer' },
        { type: 'order', id: 'order_39' },
      ],
      ui_state: { active_tab: 'deliverables', dirty: true },
      context_version: 7,
    });
  });

  it('collects the legacy list filters without accepting undeclared query state', () => {
    const context = collectPageContext(
      { pathname: '/enterprise/orders', search: '?perspective=provider&status=active&view=unsafe' },
      { pageInstanceId: PAGE_ID },
    );
    expect(context?.route_id).toBe('enterprise.order.list');
    expect(context?.ui_state).toEqual({ perspective: 'provider' });
  });

  it('reports draftId as a candidate entity without copying the full query', () => {
    const context = collectPageContext(
      {
        pathname: '/enterprise/demands/new',
        search: '?draftId=assistant_draft_123&redirect=https://evil.example',
      },
      { pageInstanceId: PAGE_ID, organizationId: 'org_buyer' },
    );
    expect(context?.route_id).toBe('enterprise.requirement.create');
    expect(context?.entity_refs).toEqual([
      { type: 'organization', id: 'org_buyer' },
      { type: 'requirement_draft', id: 'assistant_draft_123' },
    ]);
    expect(context?.pathname).toBe('/enterprise/demands/new');
    expect(JSON.stringify(context)).not.toContain('evil.example');
  });

  it('keeps the underlying route when the assistant overlay opens', () => {
    const context = collectAssistantOverlayPageContext(
      { pathname: '/workspace/gallery', search: '?view=projects' },
      'assistant.chat',
      { pageInstanceId: PAGE_ID, organizationId: 'org_1' },
    );
    expect(context.route_id).toBe('workspace.project_center.projects');
    expect(context.pathname).toBe('/workspace/gallery');
    expect(context.ui_state).toEqual({ view: 'projects' });

    const inherited = inheritAssistantOverlayPageContext(context);
    expect(inherited).toEqual(context);
    expect(inherited).not.toBe(context);
  });

  it('uses an overlay route only as fallback on an unregistered page', () => {
    const chat = collectAssistantOverlayPageContext(
      { pathname: '/enterprise/models' },
      'assistant.chat',
      { pageInstanceId: PAGE_ID },
    );
    const notifications = collectAssistantOverlayPageContext(
      { pathname: '/enterprise/models' },
      'assistant.notifications',
      { pageInstanceId: PAGE_ID },
    );
    expect(chat.route_id).toBe('assistant.chat');
    expect(notifications.route_id).toBe('assistant.notifications');
    expect(chat.pathname).toBe('/enterprise/models');
  });

  it('returns null for a page that is not registered when no overlay is active', () => {
    expect(collectPageContext({ pathname: '/enterprise/models' }, { pageInstanceId: PAGE_ID }))
      .toBeNull();
  });
});
