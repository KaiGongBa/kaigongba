import {
  Bot,
  ClipboardList,
  ExternalLink,
  FileCheck2,
  FileText,
  Handshake,
  Headphones,
  HelpCircle,
  PackageCheck,
  Scale,
} from 'lucide-react';
import type { ReactNode } from 'react';

import { buildSafePlatformAssistantUrl } from '../routeRegistry';

type HelpDestination = Readonly<{
  id: string;
  title: string;
  description: string;
  routeId: string;
  routeParams?: Readonly<Record<string, string>>;
  unavailableMessage?: string;
  icon: ReactNode;
}>;

const HELP_DESTINATIONS: readonly HelpDestination[] = [
  {
    id: 'projects', title: '项目与 AI 员工',
    description: '按项目或 AI 员工查看进度、SOP 和阶段性交付。',
    routeId: 'workspace.project_center.projects', icon: <Bot />,
  },
  {
    id: 'orders', title: '订单',
    description: '查看采购与服务订单、里程碑、待办和付款状态。',
    routeId: 'enterprise.order.list', icon: <ClipboardList />,
  },
  {
    id: 'requirements', title: '需求',
    description: '查看或发布需求，跟进匹配、澄清与选标。',
    routeId: 'enterprise.requirement.list', icon: <FileText />,
  },
  {
    id: 'quotes', title: '报价',
    description: '查看服务方的报价邀请、AI 建议和待确认报价。',
    routeId: 'enterprise.provider.quotes', icon: <Handshake />,
  },
  {
    id: 'agreements', title: '合同与协议',
    description: '查看成交后的协议快照与双方确认状态。',
    routeId: 'enterprise.agreement.list',
    unavailableMessage: '当前版本没有合同总列表，请从关联订单或待办进入具体协议。',
    icon: <FileCheck2 />,
  },
  {
    id: 'deliveries', title: '交付与验收',
    description: '查看交付版本、修改申请和验收记录。',
    routeId: 'enterprise.deliverable.list',
    unavailableMessage: '交付物必须从有权查看的具体订单进入，当前版本不提供跨订单直达。',
    icon: <PackageCheck />,
  },
  {
    id: 'disputes', title: '平台争议处理',
    description: '查看举证、调解、裁决、复核和申诉进度。',
    routeId: 'enterprise.dispute.list',
    unavailableMessage: '争议页需要已授权的案件编号，请从相关订单或待办进入。',
    icon: <Scale />,
  },
] as const;

export function AssistantHelpPanel({
  onNavigate,
  onRequestHumanSupport,
}: {
  onNavigate: (route: string) => void;
  onRequestHumanSupport: () => void;
}) {
  return (
    <section className="kai-assistant-panel kai-assistant-help" role="tabpanel" aria-label="开小花使用帮助">
      <div className="kai-assistant-scroll">
        <div className="kai-assistant-intro">
          <HelpCircle />
          <div><h2>你想完成什么？</h2><p>开小花只会生成已登记业务路由；合同、交付和争议等详情仍需校验你的真实业务权限。</p></div>
        </div>
        <div className="kai-help-list">
          {HELP_DESTINATIONS.map((item) => {
            const route = buildSafePlatformAssistantUrl(item.routeId, item.routeParams);
            return (
              <button
                type="button"
                key={item.id}
                className={route ? '' : 'is-unavailable'}
                disabled={!route}
                aria-describedby={route ? undefined : `kai-help-unavailable-${item.id}`}
                onClick={() => route && onNavigate(route)}
              >
                <i>{item.icon}</i>
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.description}</small>
                  {!route && <em id={`kai-help-unavailable-${item.id}`}>当前版本不可直达：{item.unavailableMessage || '暂无可安全直达的页面。'}</em>}
                </span>
                {route ? <ExternalLink /> : <span className="kai-help-disabled-label">需从业务上下文进入</span>}
              </button>
            );
          })}
        </div>

        <section className="kai-human-support-entry" aria-label="人工客服">
          <Headphones />
          <span><strong>还需要人工帮助？</strong><small>先整理所在页面、问题说明和相关业务编号，不会自动创建工单。</small></span>
          <button type="button" onClick={onRequestHumanSupport}>联系人工客服</button>
        </section>
      </div>
    </section>
  );
}
