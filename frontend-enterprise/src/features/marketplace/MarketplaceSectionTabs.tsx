import { useLocation, useNavigate } from 'react-router-dom';

import './workspace-section-tabs.css';

type SectionTab = { label: string; route: string; selected: boolean };

export function TransactionSectionTabs() {
  const location = useLocation();
  const tabs: SectionTab[] = [
    { label: '总览', route: '/enterprise/transactions', selected: location.pathname === '/enterprise/transactions' },
    { label: '我的需求', route: '/enterprise/demands', selected: location.pathname.startsWith('/enterprise/demands') },
    { label: '我的订单', route: '/enterprise/orders?perspective=buyer', selected: isOrderWorkspacePath(location.pathname) },
    { label: '待确认', route: '/enterprise/confirmations', selected: location.pathname.startsWith('/enterprise/confirmations') },
  ];
  return <SectionTabs ariaLabel="交易中心导航" tabs={tabs} />;
}

export function ServiceSectionTabs() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  const providerView = params.get('view') === 'workbench' ? 'workbench' : 'quotes';
  const tabs: SectionTab[] = [
    { label: '我的发布', route: '/enterprise/publishing', selected: location.pathname.startsWith('/enterprise/publishing') },
    { label: '报价管理', route: '/enterprise/provider?view=quotes', selected: location.pathname.startsWith('/enterprise/provider') && (location.pathname.includes('/quotes/') || providerView === 'quotes') },
    { label: '服务商工作台', route: '/enterprise/provider?view=workbench', selected: location.pathname === '/enterprise/provider' && providerView === 'workbench' },
  ];
  return <SectionTabs ariaLabel="服务经营导航" tabs={tabs} />;
}

function SectionTabs({ ariaLabel, tabs }: { ariaLabel: string; tabs: SectionTab[] }) {
  const navigate = useNavigate();
  return (
    <nav className="workspace-section-tabs" role="tablist" aria-label={ariaLabel}>
      {tabs.map((tab) => (
        <button
          type="button"
          role="tab"
          aria-selected={tab.selected}
          className={tab.selected ? 'is-active' : ''}
          key={tab.label}
          onClick={() => navigate(tab.route)}
        >
          {tab.label}
        </button>
      ))}
    </nav>
  );
}

function isOrderWorkspacePath(pathname: string) {
  return pathname.startsWith('/enterprise/orders')
    || pathname.startsWith('/enterprise/payments')
    || pathname.startsWith('/enterprise/agreements')
    || pathname.startsWith('/enterprise/disputes');
}
