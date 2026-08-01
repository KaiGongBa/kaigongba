import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Bot,
  BriefcaseBusiness,
  Building2,
  Check,
  ChevronDown,
  CircleAlert,
  FileSearch2,
  FileText,
  LoaderCircle,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
  TableProperties,
  Tag,
  Users,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import type {
  MarketplaceOrganization,
  MarketplaceSkill,
  MarketplaceVerification,
} from './types';
import MarketplaceNotifications from './MarketplaceNotifications';

export function MarketplaceHeader({
  title,
  searchValue,
  searchPlaceholder,
  onSearchChange,
  action,
  breadcrumb,
  organizations = [],
  selectedOrganizationId = '',
  organizationLoading = false,
  onOrganizationChange,
  hideOrganization = false,
}: {
  title?: string;
  searchValue?: string;
  searchPlaceholder?: string;
  onSearchChange?: (value: string) => void;
  action?: ReactNode;
  breadcrumb?: ReactNode;
  organizations?: MarketplaceOrganization[];
  selectedOrganizationId?: string;
  organizationLoading?: boolean;
  onOrganizationChange?: (organizationId: string) => void;
  hideOrganization?: boolean;
}) {
  const navigate = useNavigate();
  return (
    <header className="marketplace-header">
      <div className="marketplace-header__main">
        <div className="min-w-0">
          {breadcrumb || <h1>{title}</h1>}
        </div>
        {onSearchChange && (
          <label className="marketplace-search">
            <Search aria-hidden="true" />
            <input
              value={searchValue}
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder={searchPlaceholder}
              aria-label={searchPlaceholder || '搜索'}
            />
          </label>
        )}
        <div className="marketplace-header__actions">
          {action}
          {!hideOrganization && <label className="marketplace-organization">
            <Building2 aria-hidden="true" />
            <select
              value={selectedOrganizationId}
              disabled={organizationLoading || organizations.length === 0}
              aria-label="切换当前企业"
              onChange={(event) => onOrganizationChange?.(event.target.value)}
            >
              {organizations.length === 0 && (
                <option value="">
                  {organizationLoading ? '正在读取企业…' : '未加入企业'}
                </option>
              )}
              {organizations.map((organization) => (
                <option value={organization.id} key={organization.id}>
                  {organization.name}
                </option>
              ))}
            </select>
            <ChevronDown aria-hidden="true" />
          </label>}
          <MarketplaceNotifications organizationId={selectedOrganizationId || undefined} />
          <button type="button" className="marketplace-avatar" aria-label="账号菜单" onClick={() => navigate('/enterprise/accounts/organization')}>A</button>
        </div>
      </div>
    </header>
  );
}

export function MarketTabs<T extends string>({
  items,
  value,
  onChange,
}: {
  items: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="marketplace-tabs" role="tablist">
      {items.map((item) => (
        <button
          type="button"
          role="tab"
          aria-selected={item.value === value}
          key={item.value}
          className={cn('marketplace-tab', item.value === value && 'is-active')}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

export function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="marketplace-filter">
      <span className="sr-only">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option value={option.value} key={option.value}>{option.label}</option>
        ))}
      </select>
      <ChevronDown aria-hidden="true" />
    </label>
  );
}

export function VerificationBadge({
  state,
  compact = false,
}: {
  state: MarketplaceVerification | 'verified-service';
  compact?: boolean;
}) {
  if (state === 'pending') {
    return <span className="verification-badge is-pending"><CircleAlert />待安全验证</span>;
  }
  const label = state === 'official' ? '官方' : '平台已验证';
  return (
    <span
      className={cn('verification-badge', compact && 'is-compact', state === 'official' && 'is-official')}
      aria-label={compact ? label : undefined}
      title={compact ? label : undefined}
    >
      <ShieldCheck />
      {!compact && label}
    </span>
  );
}

export function MarketplaceState({
  loading,
  error,
  empty,
  onRetry,
}: {
  loading: boolean;
  error?: string;
  empty?: boolean;
  onRetry?: () => void;
}) {
  if (loading) {
    return (
      <div className="marketplace-state" role="status">
        <LoaderCircle className="animate-spin" />
        <span>正在加载市场数据…</span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="marketplace-state is-error" role="alert">
        <CircleAlert />
        <strong>加载失败</strong>
        <span>{error}</span>
        {onRetry && <button type="button" onClick={onRetry}>重新加载</button>}
      </div>
    );
  }
  if (empty) {
    return (
      <div className="marketplace-state">
        <FileSearch2 />
        <strong>没有找到匹配结果</strong>
        <span>请调整搜索词或筛选条件。</span>
      </div>
    );
  }
  return null;
}

export function MarketplaceNotice({
  children,
  action,
}: {
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="marketplace-notice">
      <span className="marketplace-notice__icon"><Sparkles aria-hidden="true" /></span>
      <div>{children}</div>
      {action}
    </div>
  );
}

export function Rating({ value, count }: { value: number; count?: number }) {
  return (
    <span className="marketplace-rating">
      <Star aria-hidden="true" />
      <strong>{value.toFixed(1)}</strong>
      {count !== undefined && <span>（{count.toLocaleString()}条评价）</span>}
    </span>
  );
}

const skillIconMap = {
  document: FileText,
  robot: Bot,
  sheet: TableProperties,
  search: Search,
  people: Users,
  tag: Tag,
} satisfies Record<MarketplaceSkill['icon'], typeof FileText>;

export function SkillGlyph({
  icon,
  tone,
  size = 'md',
}: {
  icon: MarketplaceSkill['icon'];
  tone: MarketplaceSkill['iconTone'];
  size?: 'md' | 'lg';
}) {
  const Icon = skillIconMap[icon];
  return (
    <span className={cn('skill-glyph', `is-${tone}`, size === 'lg' && 'is-large')}>
      <Icon aria-hidden="true" />
    </span>
  );
}

export function PermissionTag({ children }: { children: ReactNode }) {
  return <span className="permission-tag"><Check aria-hidden="true" />{children}</span>;
}

export function MarketSectionTitle({
  title,
  action,
}: {
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="market-section-title">
      <h2>{title}</h2>
      {action}
    </div>
  );
}

export function CompactStat({
  value,
  label,
}: {
  value: ReactNode;
  label: string;
}) {
  return (
    <span className="compact-stat">
      <strong>{value}</strong>
      <small>{label}</small>
    </span>
  );
}

export function ProviderMark({ name }: { name: string }) {
  return (
    <span className="provider-mark" aria-hidden="true">
      <BriefcaseBusiness />
      <small>{name.slice(0, 4)}</small>
    </span>
  );
}

export function formatCompactCount(value: number) {
  if (value >= 10_000) return `${(value / 10_000).toFixed(1)}万`;
  return value.toLocaleString();
}
