// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./ProviderWorkbenchPage', () => ({ default: () => <div data-testid="quote-workbench">报价管理真实队列</div> }));
vi.mock('./ServiceOrderWorkbenchPage', () => ({ default: () => <div data-testid="service-order-workbench">服务方真实订单</div> }));

import ProviderWorkspacePage from './ProviderWorkspacePage';

afterEach(cleanup);

describe('provider workspace routing', () => {
  it('keeps the legacy provider route on quote management', () => {
    renderPage('/enterprise/provider');
    expect(screen.getByTestId('quote-workbench')).toBeTruthy();
  });

  it('uses the provider-order workbench only for the explicit workbench view', () => {
    renderPage('/enterprise/provider?view=workbench');
    expect(screen.getByTestId('service-order-workbench')).toBeTruthy();
    expect(screen.queryByTestId('quote-workbench')).toBeNull();
  });
});

function renderPage(entry: string) {
  render(<MemoryRouter initialEntries={[entry]}><ProviderWorkspacePage /></MemoryRouter>);
}
