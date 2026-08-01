import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  Building2,
  CheckCircle2,
  Clock3,
  Copy,
  MailPlus,
  Search,
  ShieldCheck,
  Trash2,
  UserRoundCog,
} from 'lucide-react';
import { notify } from '@/components/ui/app-toast';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui';
import { MarketplaceHeader, MarketplaceState, MarketTabs } from './components';
import { marketplaceRepository } from './repository';
import type { OrganizationDetail, OrganizationMember } from './types';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';
import { useMarketplaceResource } from './useMarketplaceResource';

type OrganizationTab = 'profile' | 'members' | 'roles' | 'invitations' | 'security';

const roleLabels: Record<string, string> = {
  owner: '企业负责人',
  admin: '企业管理员',
  service_admin: '服务管理员',
  delivery_member: '交付人员',
  finance_reviewer: '财务复核',
  member: '企业成员',
};

export default function OrganizationTeamPage() {
  const organization = useMarketplaceOrganization();
  const [tab, setTab] = useState<OrganizationTab>('members');
  const [keyword, setKeyword] = useState('');
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('delivery_member');
  const [inviteScope, setInviteScope] = useState('assigned_orders');
  const [inviteCode, setInviteCode] = useState('');
  const [saving, setSaving] = useState(false);
  const [profile, setProfile] = useState({
    name: '',
    legalName: '',
    organizationType: 'company',
    unifiedCreditCode: '',
    contactName: '',
    contactPhone: '',
    contactEmail: '',
  });
  const resource = useMarketplaceResource(
    () => organization.selected
      ? marketplaceRepository.getOrganization(organization.selected.id)
      : Promise.reject(new Error('请先选择企业')),
    `organization-detail:${organization.selected?.id || 'none'}`,
  );
  const detail = resource.data;
  const canManage = Boolean(
    detail?.currentUserRoles.some((role) => ['owner', 'admin', 'enterprise_owner', 'service_admin'].includes(role)),
  );

  useEffect(() => {
    if (!detail) return;
    setProfile({
      name: detail.name,
      legalName: detail.legalName || '',
      organizationType: detail.organizationType,
      unifiedCreditCode: detail.unifiedCreditCode || '',
      contactName: detail.contactName || '',
      contactPhone: detail.contactPhone || '',
      contactEmail: detail.contactEmail || '',
    });
  }, [detail]);

  const filteredMembers = useMemo(() => {
    const needle = keyword.trim().toLocaleLowerCase();
    return (detail?.members || []).filter((member) => (
      !needle
      || `${member.displayName} ${member.username} ${member.roles.join(' ')}`.toLocaleLowerCase().includes(needle)
    ));
  }, [detail?.members, keyword]);

  async function saveProfile() {
    if (!detail || !profile.name.trim()) return;
    setSaving(true);
    try {
      await marketplaceRepository.updateOrganization(detail.id, {
        name: profile.name,
        legal_name: profile.legalName || null,
        organization_type: profile.organizationType,
        unified_credit_code: profile.unifiedCreditCode || null,
        contact_name: profile.contactName || null,
        contact_phone: profile.contactPhone || null,
        contact_email: profile.contactEmail || null,
      });
      notify.success('企业资料已保存');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  async function sendInvitation() {
    if (!detail || !inviteEmail.trim()) {
      notify.error('请输入邀请邮箱');
      return;
    }
    setSaving(true);
    try {
      const created = await marketplaceRepository.createInvitation(detail.id, {
        invitee_email: inviteEmail,
        roles: [inviteRole],
        data_scope: { mode: inviteScope },
      });
      setInviteCode(created.acceptanceCode || '');
      notify.success('邀请已创建');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '邀请失败');
    } finally {
      setSaving(false);
    }
  }

  async function changeMemberRole(member: OrganizationMember, role: string) {
    if (!detail) return;
    try {
      await marketplaceRepository.updateOrganizationMember(detail.id, member.id, {
        roles: [role],
        data_scope: member.dataScope,
      });
      notify.success('成员角色已更新');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '更新失败');
    }
  }

  async function removeMember(member: OrganizationMember) {
    if (!detail || !window.confirm(`确认将“${member.displayName}”移出当前企业？`)) return;
    try {
      await marketplaceRepository.removeOrganizationMember(detail.id, member.id);
      notify.success('成员已移除');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '移除失败');
    }
  }

  async function cancelInvitation(invitationId: string) {
    if (!detail || !window.confirm('确认取消这条成员邀请？')) return;
    try {
      await marketplaceRepository.cancelInvitation(detail.id, invitationId);
      notify.success('邀请已取消');
      resource.reload();
    } catch (error) {
      notify.error(error instanceof Error ? error.message : '取消失败');
    }
  }

  return (
    <main className="marketplace-page marketplace-management-page">
      <MarketplaceHeader
        title="企业与团队"
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
        action={canManage ? (
          <button type="button" className="marketplace-primary-button" onClick={() => {
            setInviteCode('');
            setInviteOpen(true);
          }}>
            <MailPlus />邀请成员
          </button>
        ) : null}
      />

      <MarketTabs
        items={[
          { value: 'profile', label: '企业资料' },
          { value: 'members', label: `成员 ${detail?.members.length || 0}` },
          { value: 'roles', label: '角色与权限' },
          { value: 'invitations', label: '邀请记录' },
          { value: 'security', label: '安全设置' },
        ]}
        value={tab}
        onChange={setTab}
      />

      <MarketplaceState loading={resource.loading} error={resource.error} onRetry={resource.reload} />

      {!resource.loading && detail && (
        <>
          <OrganizationSummary detail={detail} />
          {tab === 'profile' && (
            <section className="marketplace-management-card marketplace-profile-form">
              <div className="marketplace-card-heading">
                <div><h2>企业资料</h2><p>这些资料用于服务商审核、合同主体和平台联系。</p></div>
                {canManage && <button type="button" className="marketplace-primary-button" disabled={saving} onClick={() => void saveProfile()}>{saving ? '保存中…' : '保存资料'}</button>}
              </div>
              <div className="marketplace-form-grid">
                <Field label="企业简称" value={profile.name} onChange={(value) => setProfile({ ...profile, name: value })} disabled={!canManage} />
                <Field label="企业法定名称" value={profile.legalName} onChange={(value) => setProfile({ ...profile, legalName: value })} disabled={!canManage} />
                <Field label="统一社会信用代码" value={profile.unifiedCreditCode} onChange={(value) => setProfile({ ...profile, unifiedCreditCode: value })} disabled={!canManage} />
                <Field label="企业联系人" value={profile.contactName} onChange={(value) => setProfile({ ...profile, contactName: value })} disabled={!canManage} />
                <Field label="联系电话" value={profile.contactPhone} onChange={(value) => setProfile({ ...profile, contactPhone: value })} disabled={!canManage} />
                <Field label="联系邮箱" value={profile.contactEmail} onChange={(value) => setProfile({ ...profile, contactEmail: value })} disabled={!canManage} />
              </div>
            </section>
          )}

          {tab === 'members' && (
            <section className="marketplace-management-card">
              <div className="marketplace-card-heading">
                <div><h2>企业成员</h2><p>角色与数据范围共同决定成员可以查看和处理的业务。</p></div>
                <label className="marketplace-small-search"><Search /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索成员" /></label>
              </div>
              <div className="marketplace-table-wrap">
                <table className="marketplace-data-table">
                  <thead><tr><th>成员</th><th>企业角色</th><th>数据范围</th><th>状态</th><th>加入时间</th><th>操作</th></tr></thead>
                  <tbody>
                    {filteredMembers.map((member) => (
                      <tr key={member.id}>
                        <td><div className="marketplace-member"><span>{member.displayName.slice(0, 1).toUpperCase()}</span><div><strong>{member.displayName}</strong><small>{member.username}</small></div></div></td>
                        <td>
                          {canManage && !member.roles.includes('owner') ? (
                            <select value={member.roles[0]} onChange={(event) => void changeMemberRole(member, event.target.value)}>
                              {Object.entries(roleLabels).filter(([role]) => role !== 'owner').map(([role, label]) => <option value={role} key={role}>{label}</option>)}
                            </select>
                          ) : member.roles.map((role) => roleLabels[role] || role).join('、')}
                        </td>
                        <td>{scopeLabel(member.dataScope)}</td>
                        <td><span className="marketplace-online-dot" />在线</td>
                        <td>{formatDate(member.joinedAt)}</td>
                        <td>{canManage && !member.roles.includes('owner') && <button type="button" className="marketplace-danger-link" onClick={() => void removeMember(member)}><Trash2 />移除</button>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {tab === 'roles' && <RoleMatrix />}

          {tab === 'invitations' && (
            <section className="marketplace-management-card">
              <div className="marketplace-card-heading"><div><h2>邀请记录</h2><p>邀请链接默认 14 天有效，取消后立即失效。</p></div></div>
              <div className="marketplace-table-wrap">
                <table className="marketplace-data-table">
                  <thead><tr><th>邀请邮箱</th><th>角色</th><th>数据范围</th><th>状态</th><th>有效期</th><th>操作</th></tr></thead>
                  <tbody>
                    {detail.invitations.map((invitation) => (
                      <tr key={invitation.id}>
                        <td>{invitation.inviteeEmail}</td>
                        <td>{invitation.roles.map((role) => roleLabels[role] || role).join('、')}</td>
                        <td>{scopeLabel(invitation.dataScope)}</td>
                        <td><span className={`marketplace-status is-${invitation.status}`}>{invitation.status === 'pending' ? '待接受' : invitation.status}</span></td>
                        <td>{formatDate(invitation.expiresAt)}</td>
                        <td>{invitation.status === 'pending' && canManage && <button type="button" className="marketplace-danger-link" onClick={() => void cancelInvitation(invitation.id)}>取消</button>}</td>
                      </tr>
                    ))}
                    {detail.invitations.length === 0 && <tr><td colSpan={6}>暂无邀请记录</td></tr>}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {tab === 'security' && (
            <section className="marketplace-security-grid">
              <SecurityCard icon={<ShieldCheck />} title="敏感操作二次确认" text="负责人变更、成员移除、服务下架与审核提交均需再次确认。" />
              <SecurityCard icon={<UserRoundCog />} title="最小权限" text="成员权限由企业角色与订单数据范围共同控制，不共享超级管理员账号。" />
              <SecurityCard icon={<Clock3 />} title="操作留痕" text="企业资料、邀请、成员角色和发布审核操作均写入审计日志。" />
            </section>
          )}
        </>
      )}

      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent className="marketplace-dialog">
          <DialogTitle>邀请成员</DialogTitle>
          {!inviteCode ? (
            <>
              <label><span>邮箱地址 *</span><input value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} placeholder="member@example.com" /></label>
              <div className="marketplace-form-grid">
                <label><span>分配角色</span><select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)}>{Object.entries(roleLabels).filter(([role]) => role !== 'owner').map(([role, label]) => <option value={role} key={role}>{label}</option>)}</select></label>
                <label><span>数据范围</span><select value={inviteScope} onChange={(event) => setInviteScope(event.target.value)}><option value="all_orders">全部订单</option><option value="assigned_orders">指定订单</option><option value="my_tasks">仅本人任务</option></select></label>
              </div>
              <div className="marketplace-dialog-actions">
                <button type="button" onClick={() => setInviteOpen(false)}>取消</button>
                <button type="button" className="marketplace-primary-button" disabled={saving} onClick={() => void sendInvitation()}>{saving ? '创建中…' : '创建邀请'}</button>
              </div>
            </>
          ) : (
            <div className="marketplace-invite-result">
              <CheckCircle2 />
              <strong>邀请已创建</strong>
              <p>当前未接入邮件渠道，请将一次性接受码安全发送给受邀成员。</p>
              <code>{inviteCode}</code>
              <button type="button" className="marketplace-secondary-button" onClick={() => {
                void navigator.clipboard.writeText(inviteCode);
                notify.success('接受码已复制');
              }}><Copy />复制接受码</button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </main>
  );
}

function OrganizationSummary({ detail }: { detail: OrganizationDetail }) {
  return (
    <section className="marketplace-organization-summary">
      <span className="marketplace-organization-summary__logo"><Building2 /></span>
      <div><small>当前企业</small><h2>{detail.name}</h2><p>{detail.legalName || '尚未填写企业法定名称'}</p></div>
      <dl><div><dt>认证状态</dt><dd>{detail.verificationStatus === 'verified' ? <><CheckCircle2 />已认证</> : '待认证'}</dd></div><div><dt>企业负责人</dt><dd>{detail.members.find((member) => member.userId === detail.ownerUserId)?.displayName || '-'}</dd></div><div><dt>服务商身份</dt><dd>{detail.provider?.status === 'active' ? '已启用' : detail.providerApplication?.status === 'pending_review' ? '审核中' : '未入驻'}</dd></div></dl>
    </section>
  );
}

function Field({ label, value, onChange, disabled }: { label: string; value: string; onChange: (value: string) => void; disabled?: boolean }) {
  return <label><span>{label}</span><input value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} /></label>;
}

function RoleMatrix() {
  const permissions = ['企业资料', '成员管理', 'AI员工配置', '服务发布', '报价确认', '订单交付', '验收与争议'];
  const roles = ['企业负责人', '企业成员', '服务管理员', '交付人员', '财务复核'];
  return (
    <section className="marketplace-management-card">
      <div className="marketplace-card-heading"><div><h2>角色与权限矩阵</h2><p>后端仍会对每次请求重新校验企业成员、角色与数据范围。</p></div></div>
      <div className="marketplace-table-wrap"><table className="marketplace-data-table"><thead><tr><th>资源 / 操作</th>{roles.map((role) => <th key={role}>{role}</th>)}</tr></thead><tbody>{permissions.map((permission, rowIndex) => <tr key={permission}><td>{permission}</td>{roles.map((role, columnIndex) => <td key={role}>{columnIndex === 0 || (columnIndex === 2 && [2, 3, 4, 5].includes(rowIndex)) || (columnIndex === 3 && rowIndex === 5) || (columnIndex === 4 && [4, 6].includes(rowIndex)) ? '管理/确认' : rowIndex === 0 ? '查看' : '无权限'}</td>)}</tr>)}</tbody></table></div>
    </section>
  );
}

function SecurityCard({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return <article className="marketplace-management-card marketplace-security-card"><span>{icon}</span><strong>{title}</strong><p>{text}</p></article>;
}

function scopeLabel(scope: Record<string, unknown>) {
  return { all_orders: '全部订单', assigned_orders: '指定订单', my_tasks: '仅本人任务' }[String(scope.mode)] || '自定义范围';
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value));
}
