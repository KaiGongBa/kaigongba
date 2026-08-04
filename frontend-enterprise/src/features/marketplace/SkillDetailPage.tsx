import { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  Check,
  ChevronLeft,
  CircleCheck,
  CircleX,
  Cloud,
  Download,
  FileText,
  LockKeyhole,
  Play,
  ShieldCheck,
  Star,
} from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { notify } from '@/components/ui/app-toast';
import { EnterpriseRoute } from '@/enums/routes';
import {
  MarketplaceHeader,
  MarketplaceState,
  MarketTabs,
  PermissionTag,
  ProviderMark,
  SkillGlyph,
  VerificationBadge,
} from './components';
import { marketplaceRepository } from './repository';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type SkillDetailTab = 'overview' | 'schema' | 'permissions' | 'versions' | 'reviews';

const baseTabs: Array<{ value: SkillDetailTab; label: string }> = [
  { value: 'overview', label: '概览' },
  { value: 'schema', label: '输入输出' },
  { value: 'permissions', label: '权限与安全' },
  { value: 'versions', label: '版本记录' },
  { value: 'reviews', label: '评价' },
];

export default function SkillDetailPage() {
  const navigate = useNavigate();
  const { skillId = '' } = useParams();
  const organization = useMarketplaceOrganization();
  const [tab, setTab] = useState<SkillDetailTab>('overview');
  const [targetAgent, setTargetAgent] = useState('');
  const [version, setVersion] = useState('');
  const [installing, setInstalling] = useState(false);
  const [installed, setInstalled] = useState(false);
  const [trialOpen, setTrialOpen] = useState(false);
  const [trialRan, setTrialRan] = useState(false);

  const resource = useMarketplaceResource(
    () => marketplaceRepository.getSkill(skillId, organization.selected?.id),
    `${skillId}:${organization.selected?.id || 'all'}`,
  );
  const installTargetsResource = useMarketplaceResource(
    () => marketplaceRepository.listInstallTargets(organization.selected?.id || ''),
    `marketplace-install-targets:${organization.selected?.id || 'none'}`,
  );
  const skill = resource.data;
  const agents = installTargetsResource.data || [];
  const selectedVersion = version || skill?.version || '';
  const exampleInput = skill?.inputs[0];
  const trialResultSummary = skill?.outputs.map((field) => field.description).join('、') || '结构化结果';
  const tabs = useMemo(
    () => baseTabs.map((item) => (
      item.value === 'reviews' ? { ...item, label: `评价（${skill?.reviewCount || 0}）` } : item
    )),
    [skill?.reviewCount],
  );
  const permissionSummary = useMemo(
    () => ({
      allow: skill?.permissions.filter((item) => item.level === 'allow').length || 0,
      deny: skill?.permissions.filter((item) => item.level === 'deny').length || 0,
      review: skill?.permissions.filter((item) => item.level === 'review').length || 0,
    }),
    [skill?.permissions],
  );

  useEffect(() => {
    if (!agents.length) {
      setTargetAgent('');
      return;
    }
    setTargetAgent((current) => (
      agents.some((agent) => agent.id === current) ? current : agents[0].id
    ));
  }, [agents]);

  async function install() {
    if (!skill) return;
    if (skill.verification === 'pending') {
      notify.warning('该 Skill 尚未通过安全验证，不能安装到生产员工');
      return;
    }
    if (!targetAgent) {
      notify.warning('当前账号没有可管理的 AI 员工，请先创建 AI 员工');
      return;
    }
    if (!organization.selected) {
      notify.warning('请先选择当前企业');
      return;
    }
    setInstalling(true);
    try {
      await marketplaceRepository.installSkill(
        skill.id,
        targetAgent,
        selectedVersion,
        organization.selected.id,
      );
      setInstalled(true);
      notify.success(`${skill.name} 已安装到 ${agents.find((item) => item.id === targetAgent)?.name}`);
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '安装失败');
    } finally {
      setInstalling(false);
    }
  }

  return (
    <main className="marketplace-page marketplace-page--detail">
      <MarketplaceHeader
        breadcrumb={(
          <button type="button" className="marketplace-breadcrumb" onClick={() => navigate(EnterpriseRoute.SkillMarket)}>
            <ChevronLeft />
            <span>Skill市场</span>
            <i>/</i>
            <strong>{skill?.name || 'Skill详情'}</strong>
          </button>
        )}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />

      {skill && (
        <div className="skill-detail-layout">
          <section className="skill-detail-main">
            <header className="skill-detail-hero">
              <SkillGlyph icon={skill.icon} tone={skill.iconTone} size="lg" />
              <div className="skill-detail-hero__content">
                <div className="skill-detail-hero__title">
                  <h1>{skill.name}</h1>
                  <VerificationBadge state={skill.verification} />
                </div>
                <p>{skill.provider}<span>{skill.category}</span><span>{skill.version}</span></p>
                <div className="skill-detail-hero__stats">
                  {(skill.reviewCount || 0) > 0 && skill.rating !== null && <span><Star />{skill.rating.toFixed(1)}（{skill.reviewCount}条评价）</span>}
                  {skill.installCountVerified && <span><Download />{skill.installs.toLocaleString()} 安装</span>}
                  <span>更新于 {skill.versions[0]?.releasedAt}</span>
                </div>
                <strong>{skill.description}</strong>
              </div>
              <div className="skill-detail-hero__actions">
                <button type="button" className="marketplace-primary-button" onClick={() => void install()}>
                  {installed || skill.installed ? '已安装到AI员工' : '安装到AI员工'}
                </button>
                <button type="button" className="marketplace-secondary-button" onClick={() => { setTrialOpen(true); setTrialRan(false); }}>试运行</button>
              </div>
            </header>

            <MarketTabs items={tabs} value={tab} onChange={setTab} />

            {tab === 'overview' && (
              <div className="skill-detail-stack">
                <section className="marketplace-panel skill-overview-panel">
                  <h2>概览</h2>
                  <p>{skill.description} 运行时仅使用本次调用明确授权的数据，并按已发布的输入输出 Schema 返回可追溯结果。</p>
                  <h3>适用场景</h3>
                  <div className="skill-scenarios">
                    {skill.scenarios.map((item) => <PermissionTag key={item}>{item}</PermissionTag>)}
                  </div>
                  <h3>输入与输出</h3>
                  <div className="schema-pair">
                    <div>
                      <h4>输入（Input）</h4>
                      {skill.inputs.map((field) => (
                        <p key={field.name}><FileText /><span><strong>{field.description}</strong><small>{field.required ? '必填' : '可选'}　{field.example}</small></span></p>
                      ))}
                    </div>
                    <ArrowRight />
                    <div>
                      <h4>输出（Output）</h4>
                      {skill.outputs.map((field) => (
                        <p key={field.name}><CircleCheck /><span><strong>{field.description}</strong><small>{field.example}</small></span></p>
                      ))}
                    </div>
                  </div>
                  <h3>执行示例</h3>
                  <div className="execution-example">
                    <div>
                      <strong>输入</strong>
                      {skill.inputs.map((field) => (
                        <p key={field.name}>
                          <FileText />
                          {field.example}
                          <span>{field.description} · {field.required ? '必填' : '可选'}</span>
                        </p>
                      ))}
                    </div>
                    <ArrowRight />
                    <div>
                      <strong>输出（部分）</strong>
                      {skill.outputs.map((field) => (
                        <p key={field.name}><Check />{field.description} <i>查看</i></p>
                      ))}
                    </div>
                  </div>
                </section>
                <section className="marketplace-panel">
                  <h2>版本记录</h2>
                  <div className="version-list">
                    {skill.versions.map((item) => (
                      <div key={item.version}><strong>{item.version}</strong>{item.current && <span>当前版本</span>}<time>{item.releasedAt}</time><p>{item.summary}</p></div>
                    ))}
                  </div>
                </section>
              </div>
            )}

            {tab === 'schema' && (
              <section className="marketplace-panel service-tab-panel">
                <h2>输入输出 Schema</h2>
                <SchemaTable title="输入" fields={skill.inputs} />
                <SchemaTable title="输出" fields={skill.outputs} />
              </section>
            )}

            {tab === 'permissions' && (
              <section className="marketplace-panel service-tab-panel">
                <h2>权限清单</h2>
                <p>安装前必须明确授权。权限变更会生成新版本并要求重新确认。</p>
                <div className="permission-detail-list">
                  {skill.permissions.map((item) => (
                    <div key={item.key}>
                      {item.level === 'allow' ? <CircleCheck /> : item.level === 'deny' ? <CircleX /> : <ShieldCheck />}
                      <span><strong>{item.label}</strong><small>{item.detail}</small></span>
                      <em className={`is-${item.level}`}>{item.level === 'allow' ? '允许' : item.level === 'deny' ? '禁止' : '需复核'}</em>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {tab === 'versions' && (
              <section className="marketplace-panel service-tab-panel">
                <h2>版本记录</h2>
                <div className="version-list">
                  {skill.versions.map((item) => (
                    <div key={item.version}><strong>{item.version}</strong>{item.current && <span>当前版本</span>}<time>{item.releasedAt}</time><p>{item.summary}</p></div>
                  ))}
                </div>
              </section>
            )}

            {tab === 'reviews' && (
              <section className="marketplace-panel service-tab-panel">
                <h2>已验证调用评价</h2>
                <div className="marketplace-review-empty" role="status">
                  <Star />
                  <strong>暂无已验证调用评价</strong>
                  <span>完成真实调用并提交评价后，记录会显示在这里。</span>
                </div>
              </section>
            )}
          </section>

          <aside className="skill-detail-aside">
            <section className="marketplace-panel skill-install-card">
              <h2>安装配置</h2>
              <p><span>运行方式</span><strong><Cloud />{skill.runtime}</strong></p>
              <p><span>计费方式</span><strong className="is-price">{skill.price === 0 ? '免费' : `¥${skill.price}/${skill.priceUnit}`}</strong></p>
              <label>
                <span>目标AI员工</span>
                <select
                  value={targetAgent}
                  disabled={installTargetsResource.loading || agents.length === 0}
                  onChange={(event) => setTargetAgent(event.target.value)}
                >
                  {agents.length === 0 && (
                    <option value="">
                      {installTargetsResource.loading ? '正在读取可安装员工…' : '暂无可安装员工'}
                    </option>
                  )}
                  {agents.map((agent) => <option value={agent.id} key={agent.id}>{agent.name}</option>)}
                </select>
              </label>
              <label>
                <span>安装版本</span>
                <select value={selectedVersion} onChange={(event) => setVersion(event.target.value)}>
                  {skill.versions.map((item) => <option value={item.version} key={item.version}>{item.version}</option>)}
                </select>
              </label>
              <button type="button" className="marketplace-primary-button is-wide" disabled={installing || skill.verification === 'pending' || !targetAgent} onClick={() => void install()}>
                {installing ? '安装中…' : installed || skill.installed ? '重新安装到AI员工' : '安装到AI员工'}
              </button>
              <button type="button" className="marketplace-secondary-button is-wide" onClick={() => { setTrialOpen(true); setTrialRan(false); }}>试运行（不产生费用）</button>
            </section>

            <section className="marketplace-panel skill-security-card">
              <h2>权限与安全</h2>
              <div className="permission-summary">
                <span><CircleCheck />允许 {permissionSummary.allow}</span>
                <span><CircleX />禁止 {permissionSummary.deny}</span>
                <span><ShieldCheck />需复核 {permissionSummary.review}</span>
              </div>
              {skill.permissions.map((item) => (
                <button type="button" key={item.key} onClick={() => setTab('permissions')}>
                  <span>{item.label}</span>
                  <em className={`is-${item.level}`}>{item.level === 'allow' ? '允许' : item.level === 'deny' ? '禁止' : '需复核'}</em>
                  <ArrowRight />
                </button>
              ))}
            </section>

            <section className="marketplace-panel skill-security-description">
              <h2>安全说明</h2>
              <p><span>网络访问白名单</span><strong>{skill.networkPolicy}</strong></p>
              <p><span>数据保留策略</span><strong>{skill.retentionPolicy}</strong></p>
              <p><span>包摘要（SHA-256）</span><strong><CircleCheck />{skill.digest}</strong></p>
              <p><span>最后安全审查</span><strong>{skill.auditedAt}</strong></p>
              <p><span>审查人</span><strong>{skill.auditor}</strong></p>
            </section>

            <section className="marketplace-panel provider-trust-card">
              <h2>发布方</h2>
              <div>
                <ProviderMark name={skill.provider} />
                <span><strong>{skill.provider}</strong><small>发布方信息来源于当前 Skill 上架记录。</small></span>
              </div>
            </section>
          </aside>
        </div>
      )}

      <Dialog open={trialOpen} onOpenChange={setTrialOpen}>
        <DialogContent className="max-w-[620px]">
          <DialogHeader>
            <DialogTitle>试运行：{skill?.name}</DialogTitle>
            <DialogDescription>试运行使用隔离环境，不写入生产订单，不产生费用。</DialogDescription>
          </DialogHeader>
          <div className="skill-trial-dialog">
            <label>
              <span>测试文件</span>
              <button type="button">
                <FileText />
                {exampleInput?.example || '示例输入'}
                <small>{exampleInput?.description || '测试数据'}</small>
              </button>
            </label>
            {trialRan ? (
              <div className="skill-trial-result">
                <CircleCheck />
                <span>
                  <strong>执行成功，用时 6.2 秒</strong>
                  <small>已生成{trialResultSummary}；执行范围符合当前权限声明与网络策略。</small>
                </span>
              </div>
            ) : (
              <div className="skill-trial-empty"><LockKeyhole />等待在隔离环境中执行</div>
            )}
          </div>
          <DialogFooter>
            <button type="button" className="marketplace-secondary-button" onClick={() => setTrialOpen(false)}>关闭</button>
            <button type="button" className="marketplace-primary-button" onClick={() => setTrialRan(true)}><Play />{trialRan ? '重新运行' : '开始试运行'}</button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}

function SchemaTable({
  title,
  fields,
}: {
  title: string;
  fields: Array<{ name: string; type: string; required: boolean; description: string; example: string }>;
}) {
  return (
    <div className="schema-table">
      <h3>{title}</h3>
      <table>
        <thead><tr><th>字段名</th><th>类型</th><th>必填</th><th>描述</th><th>示例</th></tr></thead>
        <tbody>
          {fields.map((field) => (
            <tr key={field.name}><td>{field.name}</td><td>{field.type}</td><td>{field.required ? '是' : '否'}</td><td>{field.description}</td><td>{field.example}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
