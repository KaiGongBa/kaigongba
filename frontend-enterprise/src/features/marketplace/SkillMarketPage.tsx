import { useMemo, useState } from 'react';
import {
  ChevronLeft,
  ChevronRight,
  CloudUpload,
  Download,
  ShieldCheck,
  Star,
  X,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { notify } from '@/components/ui/app-toast';
import { EnterpriseRoute } from '@/enums/routes';
import {
  FilterSelect,
  formatCompactCount,
  MarketplaceHeader,
  MarketplaceState,
  MarketTabs,
  SkillGlyph,
  VerificationBadge,
} from './components';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';
import type { MarketplaceSkill } from './types';

type SkillTab = 'recommended' | 'all' | 'installed' | 'private' | 'mine';

const tabs: Array<{ value: SkillTab; label: string }> = [
  { value: 'recommended', label: '推荐' },
  { value: 'all', label: '全部Skill' },
  { value: 'installed', label: '已安装' },
  { value: 'private', label: '企业私有' },
  { value: 'mine', label: '我的发布' },
];

const pageSize = 9;

export default function SkillMarketPage() {
  const navigate = useNavigate();
  const organization = useMarketplaceOrganization();
  const [keyword, setKeyword] = useState('');
  const [tab, setTab] = useState<SkillTab>('recommended');
  const [category, setCategory] = useState('all');
  const [runtime, setRuntime] = useState('all');
  const [verification, setVerification] = useState('all');
  const [price, setPrice] = useState('all');
  const [permission, setPermission] = useState('all');
  const [sort, setSort] = useState('recommended');
  const [page, setPage] = useState(1);
  const [bannerOpen, setBannerOpen] = useState(true);
  const [installingId, setInstallingId] = useState('');
  const [installedIds, setInstalledIds] = useState<Set<string>>(new Set());

  const resource = useMarketplaceResource(
    () => marketplaceRepository.listSkills({
      organizationId: organization.selected?.id,
    }),
    `skills:${organization.selected?.id || 'all'}`,
  );
  const installTargetsResource = useMarketplaceResource(
    () => marketplaceRepository.listInstallTargets(organization.selected?.id || ''),
    `marketplace-install-targets:${organization.selected?.id || 'none'}`,
  );

  const filtered = useMemo(() => {
    let items = (resource.data?.items || []).map((item) => ({
      ...item,
      installed: item.installed || installedIds.has(item.id),
    }));
    items = items.filter((item) => {
      const haystack = `${item.name} ${item.provider} ${item.category} ${item.description}`.toLocaleLowerCase();
      if (keyword.trim() && !haystack.includes(keyword.trim().toLocaleLowerCase())) return false;
      if (category !== 'all' && item.category !== category) return false;
      if (runtime !== 'all' && item.runtime !== runtime) return false;
      if (verification !== 'all' && item.verification !== verification) return false;
      if (permission !== 'all' && !item.permissionTags.includes(permission)) return false;
      if (price === 'free' && item.price !== 0) return false;
      if (price === 'under-100' && !(item.price > 0 && item.price < 100)) return false;
      if (tab === 'installed' && !item.installed) return false;
      if (tab === 'private' && !item.private) return false;
      if (tab === 'mine' && !item.mine) return false;
      return true;
    });
    if (sort === 'rating') items = [...items].sort((a, b) => (b.rating || 0) - (a.rating || 0));
    if (sort === 'installs') items = [...items].sort((a, b) => b.installs - a.installs);
    if (sort === 'price-low') items = [...items].sort((a, b) => a.price - b.price);
    return items;
  }, [category, installedIds, keyword, permission, price, resource.data?.items, runtime, sort, tab, verification]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const visibleItems = filtered.slice((Math.min(page, totalPages) - 1) * pageSize, Math.min(page, totalPages) * pageSize);
  const hasReviews = (resource.data?.items || []).some((item) => (item.reviewCount || 0) > 0);
  const hasVerifiedInstallCounts = (resource.data?.items || []).some((item) => item.installCountVerified);

  async function install(skill: MarketplaceSkill) {
    if (skill.verification === 'pending') {
      notify.warning('该 Skill 尚未通过安全验证，暂不可安装');
      return;
    }
    if (skill.installed || installedIds.has(skill.id)) {
      navigate(`${EnterpriseRoute.SkillMarket}/${skill.id}`);
      return;
    }
    const targetAgent = installTargetsResource.data?.[0];
    if (!targetAgent) {
      notify.warning('当前账号没有可管理的 AI 员工，请先创建 AI 员工');
      return;
    }
    if (!organization.selected) {
      notify.warning('请先选择当前企业');
      return;
    }
    setInstallingId(skill.id);
    try {
      await marketplaceRepository.installSkill(
        skill.id,
        targetAgent.id,
        skill.version,
        organization.selected.id,
      );
      setInstalledIds((current) => new Set(current).add(skill.id));
      notify.success(`${skill.name} 已安装到 ${targetAgent.name}`);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '安装失败');
    } finally {
      setInstallingId('');
    }
  }

  return (
    <main className="marketplace-page marketplace-page--listing">
      <MarketplaceHeader
        title="Skill市场"
        searchValue={keyword}
        onSearchChange={(value) => {
          setKeyword(value);
          setPage(1);
        }}
        searchPlaceholder="搜索Skill名称、能力或发布者"
        action={(
          <button type="button" className="marketplace-primary-button marketplace-header-publish" onClick={() => navigate(EnterpriseRoute.Publishing)}>
            <CloudUpload />发布Skill
          </button>
        )}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />

      <MarketTabs
        items={tabs}
        value={tab}
        onChange={(value) => {
          setTab(value);
          setPage(1);
        }}
      />

      <div className="marketplace-toolbar">
        <div className="marketplace-toolbar__filters">
          <FilterSelect
            label="分类"
            value={category}
            onChange={(value) => { setCategory(value); setPage(1); }}
            options={[
              { value: 'all', label: '全部分类' },
              { value: '法务', label: '法务' },
              { value: '交易', label: '交易' },
              { value: '数据', label: '数据' },
              { value: '招聘', label: '招聘' },
              { value: '运维', label: '运维' },
            ]}
          />
          <FilterSelect
            label="运行方式"
            value={runtime}
            onChange={(value) => { setRuntime(value); setPage(1); }}
            options={[
              { value: 'all', label: '运行方式' },
              { value: '平台托管', label: '平台托管' },
              { value: '远程 API', label: '远程 API' },
            ]}
          />
          <FilterSelect
            label="验证级别"
            value={verification}
            onChange={(value) => { setVerification(value); setPage(1); }}
            options={[
              { value: 'all', label: '验证级别' },
              { value: 'verified', label: '平台已验证' },
              { value: 'official', label: '官方' },
              { value: 'pending', label: '待安全验证' },
            ]}
          />
          <FilterSelect
            label="价格"
            value={price}
            onChange={(value) => { setPrice(value); setPage(1); }}
            options={[
              { value: 'all', label: '价格' },
              { value: 'free', label: '免费' },
              { value: 'under-100', label: '付费' },
            ]}
          />
          <FilterSelect
            label="数据权限"
            value={permission}
            onChange={(value) => { setPermission(value); setPage(1); }}
            options={[
              { value: 'all', label: '数据权限' },
              { value: '读本次附件', label: '读本次附件' },
              { value: '限定网络', label: '限定网络' },
              { value: '不写入持久化', label: '不写入持久化' },
            ]}
          />
        </div>
        <FilterSelect
          label="排序"
          value={sort}
          onChange={setSort}
          options={[
            { value: 'recommended', label: '综合排序' },
            ...(hasReviews ? [{ value: 'rating', label: '评分最高' }] : []),
            ...(hasVerifiedInstallCounts ? [{ value: 'installs', label: '安装最多' }] : []),
            { value: 'price-low', label: '价格最低' },
          ]}
        />
      </div>

      {bannerOpen && (
        <div className="skill-security-banner">
          <ShieldCheck />
          <span>开放发布，分级运行；未验证 Skill 不可接触订单数据与生产密钥</span>
          <button type="button" aria-label="关闭提示" onClick={() => setBannerOpen(false)}><X /></button>
        </div>
      )}

      <MarketplaceState
        loading={resource.loading}
        error={resource.error}
        empty={!resource.loading && !resource.error && visibleItems.length === 0}
        onRetry={resource.reload}
      />

      {!resource.loading && !resource.error && visibleItems.length > 0 && (
        <div className="skill-grid">
          {visibleItems.map((skill) => {
            const installed = skill.installed || installedIds.has(skill.id);
            return (
              <article className="skill-card" key={skill.id}>
                <div className="skill-card__header">
                  <SkillGlyph icon={skill.icon} tone={skill.iconTone} />
                  <div>
                    <div className="skill-card__title">
                      <h2>{skill.name}</h2>
                      <VerificationBadge state={skill.verification} />
                    </div>
                    <p>{skill.provider}<span>{skill.version}</span></p>
                  </div>
                </div>
                <p className="skill-card__description">{skill.description}</p>
                <div className="skill-card__meta">
                  <span>{skill.runtime}</span>
                  <span>{skill.language}</span>
                  <span>{skill.weight}</span>
                </div>
                <div className="skill-card__numbers">
                  <span className="marketplace-price"><strong>{skill.price === 0 ? '免费' : `¥${skill.price}`}</strong>{skill.price > 0 && <i>/{skill.priceUnit}</i>}</span>
                  {skill.installCountVerified && <span><Download />{formatCompactCount(skill.installs)} 安装</span>}
                  {(skill.reviewCount || 0) > 0 && skill.rating !== null && <span><Star />{skill.rating.toFixed(1)}</span>}
                </div>
                <div className="skill-card__permissions">
                  {skill.permissionTags.map((tag) => <span key={tag}>{tag}</span>)}
                </div>
                <div className="skill-card__actions">
                  <button type="button" className="marketplace-secondary-button" onClick={() => navigate(`${EnterpriseRoute.SkillMarket}/${skill.id}`)}>查看详情</button>
                  <button
                    type="button"
                    className="marketplace-primary-button"
                    disabled={skill.verification === 'pending' || installingId === skill.id}
                    onClick={() => void install(skill)}
                  >
                    {installingId === skill.id ? '安装中…' : installed ? '已安装' : skill.verification === 'pending' ? '申请试用' : '安装'}
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <footer className="marketplace-pagination">
        <span>共 {filtered.length || resource.data?.total || 0} 个Skill</span>
        <div>
          <button type="button" aria-label="上一页" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}><ChevronLeft /></button>
          {Array.from({ length: Math.min(5, totalPages) }, (_, index) => index + 1).map((value) => (
            <button type="button" className={value === page ? 'is-active' : ''} key={value} onClick={() => setPage(value)}>{value}</button>
          ))}
          {totalPages > 5 && <span>…</span>}
          <button type="button" aria-label="下一页" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}><ChevronRight /></button>
        </div>
      </footer>
    </main>
  );
}
