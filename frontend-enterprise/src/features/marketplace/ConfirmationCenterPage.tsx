import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileCheck2,
  FileText,
  MessageSquareText,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

import { MarketplaceHeader, MarketplaceState } from './components';
import { marketplaceRepository } from './repository';
import type { ActionItem } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type Filter = 'all' | 'high' | 'quote' | 'agreement' | 'order';

export default function ConfirmationCenterPage() {
  const navigate = useNavigate();
  const organization = useMarketplaceOrganization();
  const [filter, setFilter] = useState<Filter>('all');
  const [keyword, setKeyword] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const resource = useMarketplaceResource(
    async () => {
      if (!organization.selected) throw new Error('请先选择当前企业');
      return marketplaceRepository.listActionItems(organization.selected.id);
    },
    `confirmation-center:${organization.selected?.id || 'none'}`,
  );
  const items = useMemo(() => (resource.data?.items || []).filter((item) => {
    if (filter === 'high' && item.riskLevel !== 'high') return false;
    if (filter === 'quote' && item.category !== 'quote') return false;
    if (filter === 'agreement' && item.category !== 'agreement') return false;
    if (filter === 'order' && ['quote', 'agreement'].includes(item.category)) return false;
    const needle = keyword.trim().toLocaleLowerCase();
    return !needle || `${item.title} ${item.summary}`.toLocaleLowerCase().includes(needle);
  }), [filter, keyword, resource.data?.items]);
  const selected = items.find((item) => item.id === selectedId) || items[0];

  return (
    <main className="marketplace-page confirmation-center-page">
      <MarketplaceHeader
        title="待确认中心"
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={<button type="button" className="marketplace-secondary-button" onClick={resource.reload}><RefreshCw />刷新</button>}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />
      {resource.data && (
        <>
          <section className="confirmation-intro"><div><small>交易协作</small><h1>统一确认队列</h1><p>集中处理 AI 报价、协议、订单变更、材料和验收事项。所有确认均写入真实业务记录。</p></div><span><ShieldCheck />结构化确认，不依赖聊天文字</span></section>
          <section className="confirmation-stat-row">
            <Stat label="全部待处理" value={resource.data.counts.all || 0} icon={<FileCheck2 />} />
            <Stat label="今日到期" value={resource.data.counts.today || 0} icon={<Clock3 />} tone="orange" />
            <Stat label="已经逾期" value={resource.data.counts.overdue || 0} icon={<AlertTriangle />} tone="red" />
            <Stat label="高风险事项" value={resource.data.counts.highRisk || 0} icon={<ShieldCheck />} tone="purple" />
          </section>
          <section className="confirmation-toolbar">
            <div className="confirmation-filters">
              {([['all', '全部'], ['high', '高风险'], ['quote', '报价'], ['agreement', '协议'], ['order', '订单履约']] as Array<[Filter, string]>).map(([value, label]) => (
                <button type="button" key={value} className={filter === value ? 'is-active' : ''} onClick={() => setFilter(value)}>{label}</button>
              ))}
            </div>
            <label><Search /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索确认事项" /></label>
          </section>
          <div className="confirmation-workspace">
            <section className="confirmation-list">
              {!items.length && <div className="collaboration-empty"><CheckCircle2 /><strong>当前没有待确认事项</strong><span>新的报价、协议、变更或验收事项会出现在这里。</span></div>}
              {items.map((item) => (
                <button type="button" key={item.id} className={selected?.id === item.id ? 'is-selected' : ''} onClick={() => setSelectedId(item.id)}>
                  <i className={`is-${item.riskLevel}`}>{actionIcon(item.category)}</i>
                  <span><small>{categoryText(item.category)} · {roleText(item.actingRole)}</small><strong>{item.title}</strong><em>{item.summary || '请进入业务详情完成结构化确认'}</em><time>{item.dueAt ? `截止 ${formatDateTime(item.dueAt)}` : `创建于 ${formatDateTime(item.createdAt)}`}</time></span>
                  <ChevronRight />
                </button>
              ))}
            </section>
            <aside className="confirmation-detail">
              {selected ? (
                <>
                  <header><i className={`is-${selected.riskLevel}`}>{actionIcon(selected.category)}</i><div><small>{categoryText(selected.category)}</small><h2>{selected.title}</h2><p>{selected.summary || '该事项需要当前企业的有权成员完成结构化确认。'}</p></div></header>
                  <dl>
                    <div><dt>办理身份</dt><dd>{roleText(selected.actingRole)}</dd></div>
                    <div><dt>风险等级</dt><dd><em className={`is-${selected.riskLevel}`}>{riskText(selected.riskLevel)}</em></dd></div>
                    <div><dt>业务类型</dt><dd>{categoryText(selected.category)}</dd></div>
                    <div><dt>截止时间</dt><dd>{selected.dueAt ? formatDateTime(selected.dueAt) : '未设置'}</dd></div>
                  </dl>
                  <div className="confirmation-rule-card"><ShieldCheck /><span><strong>结构化确认规则</strong><p>进入详情页核对业务快照后确认。聊天消息、口头沟通或附件本身不能替代确认动作。</p></span></div>
                  <button type="button" className="confirmation-primary-action" onClick={() => navigate(selected.route)}>进入详情办理 <ChevronRight /></button>
                </>
              ) : <div className="collaboration-empty"><Sparkles /><strong>选择一项待办</strong><span>右侧将展示权限、风险和办理入口。</span></div>}
            </aside>
          </div>
        </>
      )}
    </main>
  );
}

function Stat({ label, value, icon, tone = 'blue' }: { label: string; value: number; icon: ReactNode; tone?: string }) {
  return <article className={`is-${tone}`}><i>{icon}</i><span><small>{label}</small><strong>{value}</strong></span></article>;
}

function actionIcon(category: string) {
  if (category === 'quote') return <Sparkles />;
  if (category === 'agreement') return <FileText />;
  if (category === 'material') return <MessageSquareText />;
  if (category === 'acceptance') return <CheckCircle2 />;
  return <FileCheck2 />;
}
function categoryText(value: string) { return { quote: 'AI 报价', agreement: '合作协议', material: '补充材料', acceptance: '交付验收', order_change: '订单变更', order_cancel: '订单取消', finance: '资金复核' }[value] || value; }
function roleText(value: string) { return { provider_manager: '乙方管理员', manager: '企业负责人', buyer_manager: '甲方负责人', member: '项目成员', finance: '平台财务' }[value] || value; }
function riskText(value: string) { return { normal: '常规', medium: '关注', high: '高风险' }[value] || value; }
function formatDateTime(value: string) { return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value)); }
