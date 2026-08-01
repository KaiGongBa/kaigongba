import { Bell, CheckCheck, ChevronRight, Inbox } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { notify } from '@/components/ui/app-toast';

import { marketplaceRepository } from './repository';
import type { CollaborationNotification } from './types';
import { useMarketplaceResource } from './useMarketplaceResource';

export default function MarketplaceNotifications({ organizationId }: { organizationId?: string }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const resource = useMarketplaceResource(
    () => marketplaceRepository.listCollaborationNotifications(organizationId),
    `collaboration-notifications:${organizationId || 'all'}`,
  );

  async function openNotification(item: CollaborationNotification) {
    try {
      if (item.status === 'unread') {
        await marketplaceRepository.markCollaborationNotificationsRead([item.id]);
      }
      setOpen(false);
      resource.reload();
      if (item.route) navigate(item.route);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '通知处理失败');
    }
  }

  async function markAllRead() {
    try {
      await marketplaceRepository.markCollaborationNotificationsRead([], true);
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '通知处理失败');
    }
  }

  return (
    <div className="marketplace-notification-wrap">
      <button type="button" className="marketplace-icon-button" aria-label="通知" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <Bell aria-hidden="true" />
        {(resource.data?.unreadCount || 0) > 0 && <span>{Math.min(resource.data?.unreadCount || 0, 99)}</span>}
      </button>
      {open && (
        <div className="marketplace-notification-popover">
          <header><div><strong>消息通知</strong><small>{resource.data?.unreadCount || 0} 条未读</small></div>{Boolean(resource.data?.unreadCount) && <button type="button" onClick={() => void markAllRead()}><CheckCheck />全部已读</button>}</header>
          <div>
            {resource.loading && <p className="marketplace-notification-empty">正在读取通知…</p>}
            {!resource.loading && !resource.data?.items.length && <p className="marketplace-notification-empty"><Inbox />暂无业务通知</p>}
            {resource.data?.items.slice(0, 12).map((item) => (
              <button type="button" key={item.id} className={item.status === 'unread' ? 'is-unread' : ''} onClick={() => void openNotification(item)}>
                <i className={`is-${item.riskLevel}`} />
                <span><strong>{item.title}</strong><em>{item.body}</em><small>{formatDateTime(item.createdAt)}</small></span>
                <ChevronRight />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}
