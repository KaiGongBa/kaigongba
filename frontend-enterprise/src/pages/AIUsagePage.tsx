import { useEffect, useMemo, useState } from 'react';

import { api } from '@/api/client';
import type { EnterpriseAuthUser } from '@/auth';
import AppHeader from '@/components/AppHeader';
import StaffdeckIcon from '@/components/StaffdeckIcon';
import { notify } from '@/components/ui/app-toast';
import { Button } from '@/components/ui/button';
import type { AIUsageSummaryRead } from '@/types';

const EMPTY_USAGE: AIUsageSummaryRead = {
  quota: {
    granted_credits: '0',
    reserved_credits: '0',
    consumed_credits: '0',
    available_credits: '0',
    percent_used: 0,
    hard_limit: false,
  },
  totals: {
    request_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
    platform_cost: '0',
    billable_credits: '0',
    byok_tokens: 0,
  },
  trend: [],
  by_agent: [],
};

export default function AIUsagePage({
  currentUser,
  onLogout,
}: {
  currentUser?: EnterpriseAuthUser;
  onLogout?: () => void;
}) {
  const [usage, setUsage] = useState<AIUsageSummaryRead>(EMPTY_USAGE);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    return api
      .get<AIUsageSummaryRead>('/api/ai/usage/summary?days=30')
      .then(setUsage)
      .catch((error) => notify.error(error instanceof Error ? error.message : 'AI 用量加载失败'))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    void load();
  }, []);

  const maxDailyTokens = useMemo(
    () => Math.max(1, ...usage.trend.map((item) => item.total_tokens)),
    [usage.trend],
  );
  const quotaPercent = Math.max(0, Math.min(100, usage.quota.percent_used));

  return (
    <div className="min-h-full box-border px-[48px] pb-[43px] pt-[32px] max-[900px]:px-[16px]">
      <AppHeader onLogout={onLogout} userName={currentUser?.username} title="AI 用量" />

      <div className="mb-[16px] mt-[20px] flex items-center justify-between gap-[12px]">
        <p className="text-[12px] text-[#858b9c]">平台额度、原始 Token 与企业自有模型用量分开记录</p>
        <Button
          variant="outline"
          onClick={() => void load()}
          disabled={loading}
          className="h-[34px] rounded-[10px] border-[#e3e7f1] bg-white px-[16px] text-[12px] text-[#757f9c] hover:bg-[#f6f6f6]"
        >
          <StaffdeckIcon name="refresh" size={14} className={loading ? 'animate-spin' : ''} />
          刷新
        </Button>
      </div>

      <section className="rounded-[20px] bg-white p-[18px] shadow-[0_-4px_16px_rgba(0,0,0,0.05)]">
        <div className="grid grid-cols-4 gap-[14px] max-[1100px]:grid-cols-2 max-[640px]:grid-cols-1">
          <MetricCard label="本期剩余额度" value={formatNumber(usage.quota.available_credits)} suffix="点" />
          <MetricCard label="本期已消耗" value={formatNumber(usage.quota.consumed_credits)} suffix="点" />
          <MetricCard label="平台模型 Token" value={formatCompact(usage.totals.total_tokens - usage.totals.byok_tokens)} />
          <MetricCard label="企业自有模型 Token" value={formatCompact(usage.totals.byok_tokens)} />
        </div>

        <div className="mt-[18px] rounded-[14px] border border-[#e7eaf0] bg-[#f8f9fb] px-[16px] py-[14px]">
          <div className="flex items-center justify-between text-[12px]">
            <strong className="font-medium text-[#303541]">本期平台额度</strong>
            <span className="text-[#757f9c]">
              {usage.quota.account_id ? `${quotaPercent}% 已使用` : '尚未分配额度'}
            </span>
          </div>
          <div className="mt-[9px] h-[8px] overflow-hidden rounded-full bg-[#e9edf4]">
            <div
              className="h-full rounded-full bg-[#1a71ff] transition-[width]"
              style={{ width: `${quotaPercent}%` }}
            />
          </div>
          <div className="mt-[8px] flex justify-between text-[10px] text-[#858b9c]">
            <span>已用 {formatNumber(usage.quota.consumed_credits)} 点</span>
            <span>总额 {formatNumber(usage.quota.granted_credits)} 点</span>
          </div>
        </div>

        <div className="mt-[24px] grid grid-cols-[minmax(0,1.35fr)_minmax(360px,1fr)] gap-[18px] max-[980px]:grid-cols-1">
          <div className="rounded-[16px] border border-[#e7eaf0] p-[16px]">
            <div className="flex items-center justify-between">
              <strong className="text-[13px] font-medium text-[#303541]">近 30 天用量趋势</strong>
              <span className="text-[10px] text-[#858b9c]">原始 Token</span>
            </div>
            <div className="mt-[16px] flex h-[180px] items-end gap-[6px] border-b border-[#edf0f5] px-[2px]">
              {usage.trend.length ? usage.trend.map((item) => (
                <div key={item.date} className="group flex min-w-0 flex-1 items-end self-stretch" title={`${item.date} · ${item.total_tokens} Token`}>
                  <div
                    className="mt-auto w-full min-w-[4px] rounded-t-[4px] bg-[#cfe0ff] transition-colors group-hover:bg-[#1a71ff]"
                    style={{ height: `${Math.max(4, item.total_tokens / maxDailyTokens * 100)}%` }}
                  />
                </div>
              )) : (
                <div className="m-auto text-[12px] text-[#a0a6b3]">暂无调用记录</div>
              )}
            </div>
          </div>

          <div className="rounded-[16px] border border-[#e7eaf0] p-[16px]">
            <strong className="text-[13px] font-medium text-[#303541]">费用与请求</strong>
            <dl className="mt-[14px] grid grid-cols-2 gap-[12px]">
              <SmallMetric label="调用次数" value={usage.totals.request_count.toLocaleString()} />
              <SmallMetric label="总 Token" value={formatCompact(usage.totals.total_tokens)} />
              <SmallMetric label="平台成本" value={`¥ ${formatNumber(usage.totals.platform_cost)}`} />
              <SmallMetric label="计费点数" value={formatNumber(usage.totals.billable_credits)} />
            </dl>
          </div>
        </div>

        <div className="mt-[24px] overflow-hidden rounded-[16px] border border-[#e7eaf0]">
          <div className="grid grid-cols-[minmax(180px,1fr)_140px_140px_140px] bg-[#f8f9fb] px-[16px] py-[10px] text-[11px] text-[#757f9c] max-[720px]:grid-cols-[1fr_100px]">
            <span>数字员工</span><span>调用次数</span><span className="max-[720px]:hidden">Token</span><span className="max-[720px]:hidden">计费点数</span>
          </div>
          {usage.by_agent.length ? usage.by_agent.map((item) => (
            <div key={item.agent_id || 'none'} className="grid grid-cols-[minmax(180px,1fr)_140px_140px_140px] items-center border-t border-[#edf0f5] px-[16px] py-[12px] text-[12px] text-[#464c5e] max-[720px]:grid-cols-[1fr_100px]">
              <strong className="truncate font-medium text-[#18181a]">{item.agent_name}</strong>
              <span>{item.request_count.toLocaleString()}</span>
              <span className="max-[720px]:hidden">{formatCompact(item.total_tokens)}</span>
              <span className="max-[720px]:hidden">{formatNumber(item.billable_credits)}</span>
            </div>
          )) : (
            <div className="border-t border-[#edf0f5] px-[16px] py-[28px] text-center text-[12px] text-[#a0a6b3]">暂无员工用量</div>
          )}
        </div>
      </section>
    </div>
  );
}

function MetricCard({ label, value, suffix }: { label: string; value: string; suffix?: string }) {
  return (
    <article className="rounded-[16px] bg-[#f6f6f6] px-[18px] py-[16px]">
      <p className="text-[11px] text-[#757f9c]">{label}</p>
      <p className="mt-[8px] text-[24px] font-semibold tracking-[-0.02em] text-[#18181a]">
        {value}{suffix && <small className="ml-[4px] text-[11px] font-normal text-[#858b9c]">{suffix}</small>}
      </p>
    </article>
  );
}

function SmallMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[12px] bg-[#f8f9fb] px-[12px] py-[11px]">
      <dt className="text-[10px] text-[#858b9c]">{label}</dt>
      <dd className="mt-[5px] text-[16px] font-medium text-[#18181a]">{value}</dd>
    </div>
  );
}

function formatCompact(value: number): string {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 2 }).format(value || 0);
}

function formatNumber(value: string): string {
  const parsed = Number(value || 0);
  return Number.isFinite(parsed) ? parsed.toLocaleString('zh-CN', { maximumFractionDigits: 4 }) : '0';
}
