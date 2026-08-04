// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';

import AiEmployeeDetailPage from './AiEmployeeDetailPage';
import AiEmployeeMarketPage from './AiEmployeeMarketPage';
import SkillDetailPage from './SkillDetailPage';
import SkillMarketPage from './SkillMarketPage';

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe('marketplace data integrity', () => {
  it('does not present seeded service ratings, orders, SLA, or provider placeholders as real data', async () => {
    renderRoute(
      '/enterprise/market/agents/contract-review',
      '/enterprise/market/agents/:employeeId',
      <AiEmployeeDetailPage />,
    );

    expect(await screen.findByRole('heading', { name: '合同审查专员' })).toBeTruthy();
    expect(screen.getByText('评价（0）')).toBeTruthy();
    expect(screen.getByText('暂无真实订单数据')).toBeTruthy();
    expect(screen.queryByText('评价（128）')).toBeNull();
    expect(screen.queryByText('北京星云科技有限公司 · 已验证订单')).toBeNull();
    expect(screen.queryByText('不满意可申请退款')).toBeNull();
    expect(screen.queryByRole('button', { name: /查看主页/ })).toBeNull();

    fireEvent.click(screen.getByText('评价（0）'));
    expect(screen.getByText('暂无已验证订单评价')).toBeTruthy();
  });

  it('uses service contract facts in cards when real performance metrics are unavailable', async () => {
    renderRoute('/enterprise/market/agents', '/enterprise/market/agents', <AiEmployeeMarketPage />);

    expect(await screen.findByRole('heading', { name: '合同审查专员' })).toBeTruthy();
    expect(screen.getAllByText('交付形式').length).toBeGreaterThan(0);
    expect(screen.getAllByText('预计交付').length).toBeGreaterThan(0);
    expect(screen.queryByText('评分最高')).toBeNull();
    expect(screen.queryByText('成交最多')).toBeNull();
  });

  it('shows an honest empty state for Skill reviews and removes unfinished provider links', async () => {
    renderRoute(
      '/enterprise/market/skills/contract-structure-parser',
      '/enterprise/market/skills/:skillId',
      <SkillDetailPage />,
    );

    expect(await screen.findByRole('heading', { name: '合同条款结构化解析' })).toBeTruthy();
    expect(screen.getByText('评价（0）')).toBeTruthy();
    expect(screen.queryByText('评价（128）')).toBeNull();
    expect(screen.queryByText('法务团队 · 已验证调用')).toBeNull();
    expect(screen.queryByRole('button', { name: /查看发布方主页/ })).toBeNull();

    fireEvent.click(screen.getByText('评价（0）'));
    expect(screen.getByText('暂无已验证调用评价')).toBeTruthy();
  });

  it('does not expose placeholder security rules or unverified fixture counts', async () => {
    renderRoute('/enterprise/market/skills', '/enterprise/market/skills', <SkillMarketPage />);

    expect(await screen.findByRole('heading', { name: '合同条款结构化解析' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: '查看安全规则' })).toBeNull();
    expect(screen.queryByText('评分最高')).toBeNull();
    expect(screen.queryByText('安装最多')).toBeNull();
    expect(screen.queryByText(/1,268 安装/)).toBeNull();
  });
});

function renderRoute(entry: string, path: string, element: React.ReactNode) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path={path} element={element} />
      </Routes>
    </MemoryRouter>,
  );
}
