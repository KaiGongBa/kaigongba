import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  FileSearch2,
  Filter,
  ShieldAlert,
  ShieldCheck,
  X,
  XCircle,
} from 'lucide-react';
import { notify } from '@/components/ui/app-toast';
import { FilterSelect, MarketplaceState, MarketTabs } from './components';
import { marketplaceRepository } from './repository';
import type { MarketplaceReview } from './types';
import { useMarketplaceResource } from './useMarketplaceResource';

type ReviewTab = 'all' | 'provider_application' | 'ai_service' | 'skill' | 'skill_package';

const targetLabels = {
  provider_application: '服务商入驻',
  ai_service: 'AI员工服务',
  skill: 'Skill',
};

const statusLabels: Record<string, string> = {
  pending_review: '待审核',
  approved: '已通过',
  changes_requested: '补充材料',
  rejected: '审核不通过',
  disabled: '已禁用',
};

export default function MarketReviewPage() {
  const [tab, setTab] = useState<ReviewTab>('all');
  const [status, setStatus] = useState('all');
  const [risk, setRisk] = useState('all');
  const [selectedId, setSelectedId] = useState('');
  const [comment, setComment] = useState('');
  const [deciding, setDeciding] = useState(false);
  const resource = useMarketplaceResource(
    () => marketplaceRepository.listMarketReviews(),
    'market-review-list',
  );
  const reviews = useMemo(() => (resource.data || []).filter((review) => (
    (tab === 'all' || (tab !== 'skill_package' && review.targetType === tab))
    && (status === 'all' || review.status === status)
    && (risk === 'all' || review.riskLevel === risk)
  )), [resource.data, risk, status, tab]);

  useEffect(() => {
    if (!reviews.some((review) => review.id === selectedId)) {
      setSelectedId(reviews[0]?.id || '');
    }
  }, [reviews, selectedId]);

  const selected = reviews.find((review) => review.id === selectedId) || null;
  const counts = {
    pending: (resource.data || []).filter((item) => item.status === 'pending_review').length,
    highRisk: (resource.data || []).filter((item) => item.status === 'pending_review' && item.riskLevel === 'high').length,
    changes: (resource.data || []).filter((item) => item.status === 'changes_requested').length,
    reviewed: (resource.data || []).filter((item) => item.status === 'approved').length,
  };

  async function decide(action: 'approve' | 'request_changes' | 'reject' | 'disable') {
    if (!selected || comment.trim().length < 2) {
      notify.error('请填写至少 2 个字符的审核意见');
      return;
    }
    const actionName = { approve: '通过', request_changes: '要求补充', reject: '不通过', disable: '禁用' }[action];
    if (!window.confirm(`确认执行“${actionName}”审核决定？该操作将写入审计日志。`)) return;
    setDeciding(true);
    try {
      await marketplaceRepository.decideMarketReview(selected.id, action, comment);
      notify.success(`审核决定已保存：${actionName}`);
      setComment('');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '审核操作失败');
    } finally {
      setDeciding(false);
    }
  }

  return (
    <main className="marketplace-page marketplace-management-page marketplace-review-page">
      <header className="marketplace-admin-header">
        <div><h1>市场审核</h1><p>审核服务商入驻、AI 员工商业服务和第三方 Skill。</p></div>
        <span className="marketplace-reviewer"><ShieldCheck />平台安全与运营审核</span>
      </header>

      <MarketTabs
        items={[
          { value: 'all', label: `全部 ${resource.data?.length || 0}` },
          { value: 'provider_application', label: `服务商入驻 ${(resource.data || []).filter((item) => item.targetType === 'provider_application').length}` },
          { value: 'ai_service', label: `AI员工服务 ${(resource.data || []).filter((item) => item.targetType === 'ai_service').length}` },
          { value: 'skill', label: `Skill ${(resource.data || []).filter((item) => item.targetType === 'skill').length}` },
          { value: 'skill_package', label: 'Skill 包安全审核' },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === 'skill_package' && <SkillPackageReviewPanel />}
      {tab !== 'skill_package' && <>
      <section className="marketplace-stat-grid">
        <ReviewStat label="待初审" value={counts.pending} icon={<FileSearch2 />} tone="blue" />
        <ReviewStat label="高风险待审" value={counts.highRisk} icon={<ShieldAlert />} tone="orange" />
        <ReviewStat label="补充材料" value={counts.changes} icon={<Clock3 />} tone="gray" />
        <ReviewStat label="已通过" value={counts.reviewed} icon={<CheckCircle2 />} tone="green" />
      </section>

      <div className="marketplace-review-layout">
        <section className="marketplace-management-card marketplace-review-list">
          <div className="marketplace-review-toolbar">
            <FilterSelect label="状态" value={status} onChange={setStatus} options={[{ value: 'all', label: '全部状态' }, { value: 'pending_review', label: '待审核' }, { value: 'changes_requested', label: '补充材料' }, { value: 'approved', label: '已通过' }, { value: 'rejected', label: '审核不通过' }]} />
            <FilterSelect label="风险" value={risk} onChange={setRisk} options={[{ value: 'all', label: '全部风险' }, { value: 'high', label: '高风险' }, { value: 'medium', label: '中风险' }, { value: 'low', label: '低风险' }]} />
            <button type="button" className="marketplace-secondary-button" onClick={() => { setStatus('all'); setRisk('all'); }}><Filter />清除筛选</button>
          </div>
          <MarketplaceState loading={resource.loading} error={resource.error} empty={!reviews.length} onRetry={resource.reload} />
          {!resource.loading && reviews.length > 0 && (
            <div className="marketplace-table-wrap">
              <table className="marketplace-data-table">
                <thead><tr><th>提交ID</th><th>类型</th><th>名称</th><th>发布者</th><th>版本</th><th>风险</th><th>提交时间</th><th>状态</th></tr></thead>
                <tbody>
                  {reviews.map((review) => (
                    <tr className={review.id === selectedId ? 'is-selected' : ''} key={review.id} onClick={() => setSelectedId(review.id)}>
                      <td><code>{review.id.slice(-8)}</code></td>
                      <td>{targetLabels[review.targetType]}</td>
                      <td><strong>{review.targetName}</strong></td>
                      <td>{review.organizationName}</td>
                      <td>{review.version}</td>
                      <td><span className={`marketplace-risk is-${review.riskLevel}`}>{riskLabel(review.riskLevel)}</span></td>
                      <td>{formatDateTime(review.submittedAt)}</td>
                      <td><span className={`marketplace-status is-${review.status}`}>{statusLabels[review.status] || review.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <aside className="marketplace-review-detail">
          {selected ? (
            <>
              <header><div><span>{targetLabels[selected.targetType]}</span><h2>{selected.targetName}</h2><p>{selected.organizationName} · {selected.version}</p></div><button type="button" aria-label="关闭详情" onClick={() => setSelectedId('')}><X /></button></header>
              <div className="marketplace-review-meta"><p><span>提交人</span><strong>{selected.submittedBy}</strong></p><p><span>风险等级</span><strong>{riskLabel(selected.riskLevel)}</strong></p><p><span>提交时间</span><strong>{formatDateTime(selected.submittedAt)}</strong></p><p><span>当前状态</span><strong>{statusLabels[selected.status] || selected.status}</strong></p></div>
              <ReviewSnapshot review={selected} />
              {selected.reviewerComment && <section className="marketplace-review-comment"><h3>最近审核意见</h3><p>{selected.reviewerComment}</p></section>}
              {(selected.status === 'pending_review' || selected.status === 'approved') && (
                <section className="marketplace-review-decision">
                  <h3>审核决定</h3>
                  <textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="填写核验结论、需要补充的材料或不通过原因" />
                  {selected.status === 'pending_review' ? (
                    <div className="marketplace-decision-buttons">
                      <button type="button" className="is-approve" disabled={deciding} onClick={() => void decide('approve')}><CheckCircle2 />通过并发布</button>
                      <button type="button" disabled={deciding} onClick={() => void decide('request_changes')}><AlertCircle />要求补充</button>
                      <button type="button" className="is-reject" disabled={deciding} onClick={() => void decide('reject')}><XCircle />审核不通过</button>
                    </div>
                  ) : <button type="button" className="marketplace-danger-button" disabled={deciding} onClick={() => void decide('disable')}><XCircle />禁用已通过版本</button>}
                </section>
              )}
            </>
          ) : <div className="marketplace-inline-empty"><FileSearch2 /><strong>选择一条审核单</strong><span>右侧将显示版本快照、权限声明和审核操作。</span></div>}
        </aside>
      </div>
      </>}
    </main>
  );
}

function SkillPackageReviewPanel() {
  const [selectedId, setSelectedId] = useState('');
  const [comment, setComment] = useState('');
  const [working, setWorking] = useState(false);
  const resource = useMarketplaceResource(
    () => marketplaceRepository.listSkillPackages(),
    'skill-package-review-list',
  );
  const packages = resource.data || [];
  useEffect(() => {
    if (!packages.some((item) => item.id === selectedId)) setSelectedId(packages[0]?.id || '');
  }, [packages, selectedId]);
  const selected = packages.find((item) => item.id === selectedId) || null;

  async function decide(decision: 'approved' | 'rejected') {
    if (!selected || comment.trim().length < 2) {
      notify.error('请填写至少 2 个字符的审核意见');
      return;
    }
    const stage = selected.status === 'pending_security_review' ? 'security' : 'platform';
    if (!window.confirm(`确认${decision === 'approved' ? '通过' : '拒绝'}该不可变包版本？`)) return;
    setWorking(true);
    try {
      await marketplaceRepository.reviewSkillPackage(selected.id, stage, decision, comment.trim());
      notify.success(stage === 'security' && decision === 'approved' ? '安全复核通过，已转交另一名管理员终审' : '包审核决定已记录');
      setComment('');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '包审核失败');
    } finally {
      setWorking(false);
    }
  }

  return (
    <>
      <section className="marketplace-stat-grid">
        <ReviewStat label="待安全复核" value={packages.filter((item) => item.status === 'pending_security_review').length} icon={<ShieldAlert />} tone="orange" />
        <ReviewStat label="待平台审核" value={packages.filter((item) => item.status === 'pending_review').length} icon={<FileSearch2 />} tone="blue" />
        <ReviewStat label="扫描未通过" value={packages.filter((item) => item.scanStatus === 'failed').length} icon={<XCircle />} tone="gray" />
        <ReviewStat label="已审核通过" value={packages.filter((item) => item.status === 'approved').length} icon={<CheckCircle2 />} tone="green" />
      </section>
      <div className="marketplace-review-layout">
        <section className="marketplace-management-card marketplace-review-list">
          <MarketplaceState loading={resource.loading} error={resource.error} empty={!packages.length} onRetry={resource.reload} />
          {!resource.loading && packages.length > 0 && <div className="marketplace-table-wrap"><table className="marketplace-data-table"><thead><tr><th>固定版本</th><th>Skill</th><th>运行</th><th>大小</th><th>扫描</th><th>风险</th><th>审核状态</th></tr></thead><tbody>{packages.map((item) => <tr className={item.id === selectedId ? 'is-selected' : ''} key={item.id} onClick={() => setSelectedId(item.id)}><td><code>{item.version}</code></td><td><strong>{item.name}</strong><small>{item.slug}</small></td><td>{item.executionPolicy === 'hosted' ? '平台托管' : item.executionPolicy === 'external' ? '外部 Agent' : '仅登记'}</td><td>{formatBytes(item.sizeBytes)}</td><td>{packageStatus(item.scanStatus)}</td><td><span className={`marketplace-risk is-${item.riskLevel}`}>{riskLabel(item.riskLevel)}</span></td><td><span className={`marketplace-status is-${item.status}`}>{packageStatus(item.status)}</span></td></tr>)}</tbody></table></div>}
        </section>
        <aside className="marketplace-review-detail">
          {selected ? <><header><div><span>不可变 Skill 包</span><h2>{selected.name}</h2><p>{selected.slug} · {selected.version}</p></div></header><div className="marketplace-review-meta"><p><span>SHA-256</span><strong title={selected.digest}>{selected.digest.slice(0, 16)}…</strong></p><p><span>文件</span><strong>{selected.originalFilename}</strong></p><p><span>风险等级</span><strong>{riskLabel(selected.riskLevel)}</strong></p><p><span>执行策略</span><strong>{selected.executionPolicy}</strong></p></div><section className="marketplace-review-snapshot"><h3>自动扫描报告</h3><dl><div><dt>扫描器</dt><dd>{String(selected.scanReport.scanner_version || '-')}</dd></div><div><dt>文件数</dt><dd>{String(selected.scanReport.file_count || 0)}</dd></div><div><dt>错误</dt><dd>{renderValue(selected.scanReport.errors || [])}</dd></div><div><dt>警告</dt><dd>{renderValue(selected.scanReport.warnings || [])}</dd></div><div><dt>代码信号</dt><dd>{renderValue(selected.scanReport.signals || [])}</dd></div></dl><details><summary>查看权限、Manifest 与完整扫描结果</summary><pre>{JSON.stringify({ permissions: selected.permissions, manifest: selected.manifest, scan: selected.scanReport }, null, 2)}</pre></details></section>{['pending_security_review', 'pending_review'].includes(selected.status) && selected.scanStatus === 'passed' && <section className="marketplace-review-decision"><h3>{selected.status === 'pending_security_review' ? '独立安全复核' : '平台终审'}</h3><textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="记录摘要核验、权限边界、扫描告警和执行策略结论" /><div className="marketplace-decision-buttons"><button type="button" className="is-approve" disabled={working} onClick={() => void decide('approved')}><CheckCircle2 />审核通过</button><button type="button" className="is-reject" disabled={working} onClick={() => void decide('rejected')}><XCircle />审核不通过</button></div></section>}</> : <div className="marketplace-inline-empty"><FileSearch2 /><strong>选择一个 Skill 包</strong><span>查看服务端摘要、安全扫描和权限风险。</span></div>}
        </aside>
      </div>
    </>
  );
}

function ReviewSnapshot({ review }: { review: MarketplaceReview }) {
  const snapshot = review.snapshot;
  const permissions = normalizePermissions(snapshot.permissions);
  return (
    <section className="marketplace-review-snapshot">
      <h3>提交快照</h3>
      <dl>
        {Object.entries(snapshot).filter(([key]) => !['snapshot', 'permissions', 'input_schema', 'output_schema', 'manifest', 'profile', 'cases'].includes(key)).map(([key, value]) => (
          <div key={key}><dt>{fieldLabel(key)}</dt><dd>{renderValue(value)}</dd></div>
        ))}
      </dl>
      {permissions.length > 0 && <div className="marketplace-review-permissions"><strong>权限清单</strong>{permissions.map((permission, index) => <span key={index}>{renderValue(permission)}</span>)}</div>}
      <details><summary>查看完整不可变提交快照</summary><pre>{JSON.stringify(snapshot, null, 2)}</pre></details>
    </section>
  );
}

function ReviewStat({ label, value, icon, tone }: { label: string; value: number; icon: ReactNode; tone: string }) {
  return <article className="marketplace-stat-card"><span className={`marketplace-stat-card__icon is-${tone}`}>{icon}</span><span><small>{label}</small><strong>{value}</strong></span></article>;
}

function renderValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => typeof item === 'string' ? item : JSON.stringify(item)).join('；');
  if (value && typeof value === 'object') return JSON.stringify(value);
  return String(value ?? '-');
}

function normalizePermissions(value: unknown): unknown[] {
  if (Array.isArray(value)) return value.flatMap((item) => normalizePermissions(item));
  if (typeof value === 'string') {
    try {
      return normalizePermissions(JSON.parse(value));
    } catch {
      return value.trim() ? [value] : [];
    }
  }
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([key, item]) => {
      const values = normalizePermissions(item);
      return values.length ? values.map((entry) => `${fieldLabel(key)}：${renderValue(entry)}`) : [];
    });
  }
  return value == null ? [] : [value];
}

function fieldLabel(key: string) {
  return { name: '名称', category: '分类', description: '说明', version: '版本', runtime: '运行时', visibility: '可见范围', price: '价格', organization_name: '企业' }[key] || key;
}

function riskLabel(value: string) {
  return { high: '高', medium: '中', low: '低' }[value] || value;
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}

function packageStatus(value: string) {
  return ({ pending_security_review: '待安全复核', pending_review: '待平台审核', approved: '已通过', rejected: '未通过', scan_failed: '扫描未通过', passed: '通过', failed: '未通过', not_required: '历史登记' } as Record<string, string>)[value] || value;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
