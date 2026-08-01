// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import { ServiceSectionTabs, TransactionSectionTabs } from './MarketplaceSectionTabs';

afterEach(cleanup);

describe('marketplace section tabs', () => {
  it('keeps demands, orders and confirmations on their preserved routes', () => {
    renderTabs('/enterprise/transactions', 'transaction');

    fireEvent.click(screen.getByRole('tab', { name: '我的订单' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders?perspective=buyer');

    fireEvent.click(screen.getByRole('tab', { name: '待确认' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/confirmations');

    fireEvent.click(screen.getByRole('tab', { name: '我的需求' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/demands');
  });

  it('separates publishing, quote management and provider delivery without adding identity switching', () => {
    renderTabs('/enterprise/publishing', 'service');

    fireEvent.click(screen.getByRole('tab', { name: '报价管理' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/provider?view=quotes');

    fireEvent.click(screen.getByRole('tab', { name: '服务商工作台' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/provider?view=workbench');

    fireEvent.click(screen.getByRole('tab', { name: '我的发布' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/publishing');
    expect(screen.queryByText('切换乙方身份')).toBeNull();
  });
});

function renderTabs(initialEntry: string, kind: 'transaction' | 'service') {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      {kind === 'transaction' ? <TransactionSectionTabs /> : <ServiceSectionTabs />}
      <LocationOutput />
    </MemoryRouter>,
  );
}

function LocationOutput() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}
