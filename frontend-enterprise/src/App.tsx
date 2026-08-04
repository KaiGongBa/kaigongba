import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { api, isAuthError, TENANT_ID } from "./api/client";
import {
  clearEnterpriseAuthSession,
  getEnterpriseAuthSession,
  isEnterpriseAdmin,
  isGalleryEmployee,
  setEnterpriseAuthSession,
  type EnterpriseAuthSession,
  type EnterpriseAuthUser,
} from "./auth";
import AppSidebar from "./components/AppSidebar";
import OnboardingGuide, { ONBOARDING_SEEN_KEY } from "./components/OnboardingGuide";
import QuickStartGuide, {
  QUICK_START_COMPLETED_EVENT,
  QUICK_START_SEEN_KEY,
} from "./components/QuickStartGuide";
import StaffdeckIcon from "./components/StaffdeckIcon";
import { SidebarProvider } from "@/components/ui/sidebar";
import { EnterpriseRoute } from "./enums/routes";
import {
  employeeBlankMetadata,
  canAccessEmployeeAgent,
  canManageEmployeeAgent,
  canSelectCurrentEmployeeAgent,
  employeeDisplayName,
  employeeDisplayNameWithCreator,
  employeeProfile,
  preferredEmployeeAgent,
} from "./employee";
import AccountManagementLayout, { LegacyOrganizationTeamRedirect } from "./pages/AccountManagementLayout";
import AgentsPage from "./pages/AgentsPage";
import ExternalAgentEnrollmentPage from "./pages/ExternalAgentEnrollmentPage";
import ExternalAgentOperationsPage from "./pages/ExternalAgentOperationsPage";
import ChannelsPage from "./pages/ChannelsPage";
import ConversationWorkspaceShell from "./pages/chat/ConversationWorkspaceShell";
import DashboardPage from "./pages/dashboard/DashboardPage";
import EmptyEmployeeState from "./components/EmptyEmployeeState";
import DistillPage from "./pages/DistillPage";
import GeneralSkillsPage, {
  GeneralSkillEditPage,
  GeneralSkillNewPage,
} from "./pages/GeneralSkillsPage";
import KnowledgeManagePage, { KnowledgeAddPage } from "./pages/KnowledgePage";
import LoginPage from "./pages/LoginPage";
import ModelsPage from "./pages/ModelsPage";
import AIUsagePage from "./pages/AIUsagePage";
import OpenPlatformPage from "./pages/OpenPlatformPage";
import SkillsPage from "./pages/SkillsPage";
import {
  ScheduledTaskEditPage,
  ScheduledTaskNewPage,
} from "./pages/dashboard/ScheduledTasksTab";
import ToolsPage, {
  McpServerEditPage,
  McpServerNewPage,
  ToolEditPage,
  ToolNewPage,
  ToolTestPage,
} from "./pages/ToolsPage";
import { useIsMobile } from "./hooks/use-mobile";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  Input,
  Select as UISelect,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { Button as UIButton } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { notify } from "@/components/ui/app-toast";
import {
  emitAgentScopeChange,
  persistSharedAgentScope,
  readSharedAgentScope,
} from "@/lib/agent-scope-storage";
import { cn } from "@/lib/utils";
import {
  SELECT_TRIGGER_CLASS,
  DIALOG_CANCEL_BUTTON_CLASS,
  DIALOG_FOOTER_CLASS,
  DIALOG_PRIMARY_BUTTON_CLASS,
} from "@/lib/enterprise-ui";
import type { AICapabilityStatusRead, AIModelOptionsRead, AgentProfileRead, ModelConfigRead } from "./types";
import { useI18n } from "./i18n";
import MarketReviewPage from "./features/marketplace/MarketReviewPage";
import TransactionSupervisionPage from "./features/marketplace/TransactionSupervisionPage";
import PlatformDisputesPage from "./features/marketplace/PlatformDisputesPage";
import PlatformDisputeDetailPage from "./features/marketplace/PlatformDisputeDetailPage";
import { isMarketplaceWorkspacePath } from "./features/marketplace/MarketplaceWorkspacePage";
import "./features/marketplace/marketplace.css";
import "./features/marketplace/management.css";
import "./features/marketplace/transaction.css";
import "./features/marketplace/payment-order.css";
import "./features/marketplace/fulfillment.css";
import "./features/marketplace/collaboration.css";
import "./features/marketplace/disputes.css";
import "./features/external-agent.css";

const ENTERPRISE_SIDEBAR_STORAGE_KEY = "ultrarag_enterprise_sidebar_expanded";
const MODEL_CONFIGS_UPDATED_EVENT = "ultrarag-enterprise-model-configs-updated";
const AI_CAPABILITIES_UPDATED_EVENT = "kaigongba-ai-capabilities-updated";
type AgentCreateMode = "copy" | "external" | "blank";

type AgentCreateFormState = {
  name: string;
  description: string;
  roleName: string;
  sourceMode: AgentCreateMode;
  copyFromAgentId: string;
  modelSelectionMode: "auto" | "platform_product" | "enterprise_model";
  modelProductId: string;
  tenantModelConfigId: string;
};

const EMPTY_AGENT_FORM: AgentCreateFormState = {
  name: "",
  description: "",
  roleName: "",
  sourceMode: "copy",
  copyFromAgentId: "",
  modelSelectionMode: "auto",
  modelProductId: "",
  tenantModelConfigId: "",
};

function Shell({
  auth,
  onLogout,
}: {
  auth: EnterpriseAuthSession;
  onLogout: () => void;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const [agents, setAgents] = useState<AgentProfileRead[]>([]);
  const [agentsLoaded, setAgentsLoaded] = useState(false);
  const [selectedAgentId, setSelectedAgentId] = useState(
    () => readSharedAgentScope(),
  );
  const [sidebarExpanded, setSidebarExpanded] = useState(() => {
    const stored = window.localStorage.getItem(ENTERPRISE_SIDEBAR_STORAGE_KEY);
    return stored == null ? true : stored === "1";
  });
  const [agentCreateOpen, setAgentCreateOpen] = useState(false);
  const [agentForm, setAgentForm] =
    useState<AgentCreateFormState>(EMPTY_AGENT_FORM);
  const [modelConfigs, setModelConfigs] = useState<ModelConfigRead[]>([]);
  const [modelConfigsLoaded, setModelConfigsLoaded] = useState(false);
  const [aiCapabilityStatus, setAiCapabilityStatus] = useState<AICapabilityStatusRead | null>(null);
  const [aiCapabilityStatusLoaded, setAiCapabilityStatusLoaded] = useState(false);
  const [modelOptions, setModelOptions] = useState<AIModelOptionsRead>({
    smart_match_available: false,
    platform_models: [],
    enterprise_models: [],
  });
  const [guidesCompleted, setGuidesCompleted] = useState(() => Boolean(
    window.localStorage.getItem(ONBOARDING_SEEN_KEY)
    && window.localStorage.getItem(QUICK_START_SEEN_KEY),
  ));
  const isMobile = useIsMobile();
  const isAdmin = isEnterpriseAdmin(auth.user);
  const accountRoleLabel = isAdmin ? "管理员" : "";
  const isDistillRoute = location.pathname === "/enterprise/skills/distill";
  const isMarketplaceRoute = location.pathname.startsWith(EnterpriseRoute.MarketReview)
    || location.pathname.startsWith(EnterpriseRoute.TransactionSupervision)
    || location.pathname.startsWith(EnterpriseRoute.DisputeManagement);
  const selected = (() => {
    if (location.pathname === "/enterprise") return EnterpriseRoute.Dashboard;
    if (location.pathname.startsWith(EnterpriseRoute.MarketReview)) return EnterpriseRoute.MarketReview;
    if (location.pathname.startsWith(EnterpriseRoute.TransactionSupervision)) return EnterpriseRoute.TransactionSupervision;
    if (location.pathname.startsWith(EnterpriseRoute.DisputeManagement)) return EnterpriseRoute.DisputeManagement;
    if (location.pathname.startsWith("/enterprise/platform")) return EnterpriseRoute.Platform;
    if (location.pathname.startsWith("/enterprise/knowledge")) return EnterpriseRoute.Knowledge;
    if (location.pathname.startsWith("/enterprise/general-skills")) return EnterpriseRoute.GeneralSkills;
    if (location.pathname.startsWith("/enterprise/tools")) return EnterpriseRoute.Tools;
    if (location.pathname.startsWith(EnterpriseRoute.Accounts)) return EnterpriseRoute.Accounts;
    if (location.pathname.startsWith("/enterprise/scheduled-tasks")) return EnterpriseRoute.ScheduledTasks;
    if (isDistillRoute) return EnterpriseRoute.Skills;
    return location.pathname;
  })();
  const isAgentRosterRoute = location.pathname.startsWith("/enterprise/agents");
  const [lastDistillSearch, setLastDistillSearch] = useState(() =>
    isDistillRoute ? location.search : "",
  );
  const distillSearch = isDistillRoute ? location.search : lastDistillSearch;
  const distillSearchParams = useMemo(
    () => new URLSearchParams(distillSearch),
    [distillSearch],
  );

  useEffect(() => {
    if (isDistillRoute) {
      setLastDistillSearch(location.search);
    }
  }, [isDistillRoute, location.search]);

  useEffect(() => {
    loadAgents();
  }, []);

  const loadModelConfigs = useCallback(() => {
    return api
      .get<ModelConfigRead[]>(`/api/enterprise/model-configs?tenant_id=${TENANT_ID}`)
      .then((items) => {
        setModelConfigs(items);
        setModelConfigsLoaded(true);
      })
      .catch(() => {
        setModelConfigs([]);
        setModelConfigsLoaded(false);
      });
  }, []);

  const loadAiCapabilityStatus = useCallback(() => {
    return api
      .get<AICapabilityStatusRead>("/api/ai/capabilities/status")
      .then((status) => {
        setAiCapabilityStatus(status);
        setAiCapabilityStatusLoaded(true);
      })
      .catch(() => {
        setAiCapabilityStatus(null);
        setAiCapabilityStatusLoaded(true);
      });
  }, []);

  useEffect(() => {
    void loadModelConfigs();
    void loadAiCapabilityStatus();
    void api
      .get<AIModelOptionsRead>("/api/ai/models/options")
      .then(setModelOptions)
      .catch(() => setModelOptions({ smart_match_available: false, platform_models: [], enterprise_models: [] }));
  }, [loadAiCapabilityStatus, loadModelConfigs]);

  useEffect(() => {
    const refresh = () => void loadAiCapabilityStatus();
    window.addEventListener(AI_CAPABILITIES_UPDATED_EVENT, refresh);
    return () => window.removeEventListener(AI_CAPABILITIES_UPDATED_EVENT, refresh);
  }, [loadAiCapabilityStatus]);

  useEffect(() => {
    const onModelConfigsUpdated = (event: Event) => {
      const rows = (event as CustomEvent<{ models?: ModelConfigRead[] }>).detail?.models;
      if (rows) {
        setModelConfigs(rows);
        setModelConfigsLoaded(true);
      } else {
        void loadModelConfigs();
      }
      void loadAiCapabilityStatus();
    };
    window.addEventListener(MODEL_CONFIGS_UPDATED_EVENT, onModelConfigsUpdated);
    return () => window.removeEventListener(MODEL_CONFIGS_UPDATED_EVENT, onModelConfigsUpdated);
  }, [loadAiCapabilityStatus, loadModelConfigs]);

  useEffect(() => {
    const onQuickStartCompleted = () => setGuidesCompleted(true);
    window.addEventListener(QUICK_START_COMPLETED_EVENT, onQuickStartCompleted);
    return () => window.removeEventListener(QUICK_START_COMPLETED_EVENT, onQuickStartCompleted);
  }, []);

  // Auto-collapse the sidebar on small screens; restore the saved preference on desktop.
  useEffect(() => {
    if (isMobile) {
      setSidebarExpanded(false);
    } else {
      const stored = window.localStorage.getItem(
        ENTERPRISE_SIDEBAR_STORAGE_KEY,
      );
      setSidebarExpanded(stored == null ? true : stored === "1");
    }
  }, [isMobile]);

  useEffect(() => {
    const onAgentRefresh = () => {
      void loadAgents();
    };
    window.addEventListener(
      "ultrarag-enterprise-agent-scope-refresh",
      onAgentRefresh,
    );
    return () =>
      window.removeEventListener(
        "ultrarag-enterprise-agent-scope-refresh",
        onAgentRefresh,
      );
  }, []);

  useEffect(() => {
    const onScopeChange = (event: Event) => {
      const nextAgentId =
        (event as CustomEvent<{ agentId?: string }>).detail?.agentId ||
        readSharedAgentScope();
      if (nextAgentId) {
        persistSharedAgentScope(nextAgentId, auth.user.id);
        const knownSelectableAgent = agents.some(
          (item) => item.id === nextAgentId && canUseAgentScope(item),
        );
        if (!knownSelectableAgent) void loadAgents(nextAgentId);
      }
      setSelectedAgentId(nextAgentId);
    };
    window.addEventListener(
      "ultrarag-enterprise-agent-scope-change",
      onScopeChange,
    );
    return () =>
      window.removeEventListener(
        "ultrarag-enterprise-agent-scope-change",
        onScopeChange,
    );
  }, [agents, auth.user.id]);

  useEffect(() => {
    if (!selectedAgentId) return;
    persistSharedAgentScope(selectedAgentId, auth.user.id);
    emitAgentScopeChange(selectedAgentId);
  }, [auth.user.id, selectedAgentId]);

  useEffect(() => {
    const onCreateAgent = () => openCreateAgentModal();
    window.addEventListener("ultrarag-enterprise-agent-create", onCreateAgent);
    return () =>
      window.removeEventListener(
        "ultrarag-enterprise-agent-create",
        onCreateAgent,
      );
  }, []);

  function loadAgents(preferredAgentId = "") {
    return api
      .get<AgentProfileRead[]>(`/api/enterprise/agents?tenant_id=${TENANT_ID}`)
      .then((rows) => {
        setAgents(rows);
        const selectableRows = rows.filter((item) => canUseAgentScope(item));
        setSelectedAgentId((current) => {
          const requestedAgentId = preferredAgentId || current;
          if (
            requestedAgentId &&
            selectableRows.some((item) => item.id === requestedAgentId)
          ) {
            return requestedAgentId;
          }
          const manageableRows = selectableRows.filter((item) =>
            canManageEmployeeAgent(item, auth.user),
          );
          const next = isAdmin
            ? preferredEmployeeAgent(selectableRows)?.id || ""
            : preferredEmployeeAgent(manageableRows)?.id ||
              preferredEmployeeAgent(selectableRows)?.id ||
              "";
          return next;
        });
      })
      .catch(() => setAgents([]))
      .finally(() => setAgentsLoaded(true));
  }

  function canUseAgentScope(agent: AgentProfileRead): boolean {
    return canSelectCurrentEmployeeAgent(agent, auth.user, { activeOnly: true });
  }

  function changeAgentScope(agentId: string) {
    setSelectedAgentId(agentId);
  }

  function handleSidebarOpenChange(open: boolean) {
    setSidebarExpanded(open);
    window.localStorage.setItem(
      ENTERPRISE_SIDEBAR_STORAGE_KEY,
      open ? "1" : "0",
    );
  }

  const scopeAgents = agents.filter(canUseAgentScope);
  const hasUsableTenantModelConfig = modelConfigs.some((item) => item.enabled);
  const hasUsablePlatformModel = Boolean(
    aiCapabilityStatus?.capabilities.some(
      (item) => item.capability === "agent_chat" && item.available,
    ),
  );
  const hasUsableModelConfig = hasUsableTenantModelConfig || hasUsablePlatformModel;
  const showModelSetupNotice = guidesCompleted
    && modelConfigsLoaded
    && aiCapabilityStatusLoaded
    && !hasUsableModelConfig;
  const modelSetupNoticeText = isAdmin
    ? t("平台和企业均没有可用模型，数字员工暂不能调用模型。请先配置平台模型或企业自有模型。")
    : t("平台 AI 服务暂不可用，请联系平台管理员。");
  const selectedAgent = scopeAgents.find((item) => item.id === selectedAgentId);
  const sidebarAgent = selectedAgent;
  // Routes that operate on a specific employee; show the empty guide when none exist.
  const EMPLOYEE_SCOPED_PREFIXES = [
    "/enterprise/dashboard",
    "/enterprise/scheduled-tasks",
    "/enterprise/memories",
    "/enterprise/feedback",
    "/enterprise/knowledge",
    "/enterprise/general-skills",
    "/enterprise/skills",
    "/enterprise/tools",
  ];
  const hasEmployees = scopeAgents.some((item) => !item.is_overall);
  const isEmployeeScopedRoute = EMPLOYEE_SCOPED_PREFIXES.some((prefix) =>
    location.pathname.startsWith(prefix),
  );
  const showEmployeeEmptyState =
    agentsLoaded && !hasEmployees && isEmployeeScopedRoute;
  const sourceAgents = agents.filter((item) =>
    canAccessEmployeeAgent(item, auth.user, {
      activeOnly: true,
      includeOverall: isAdmin,
    }),
  );
  const selectedAgentName = selectedAgent
    ? employeeDisplayName(selectedAgent)
    : "未选择";
  const selectedAgentCaption = selectedAgent
    ? selectedAgent.is_overall
      ? "公司广场"
      : employeeProfile(selectedAgent).roleName
    : "-";
  function openCreateAgentModal() {
    setAgentForm({
      ...EMPTY_AGENT_FORM,
      copyFromAgentId: selectedAgentId || sourceAgents[0]?.id || "",
      modelProductId: modelOptions.platform_models.find((item) => item.is_default)?.id || modelOptions.platform_models[0]?.id || "",
      tenantModelConfigId: modelOptions.enterprise_models.find((item) => item.is_default)?.id || modelOptions.enterprise_models[0]?.id || "",
    });
    setAgentCreateOpen(true);
  }

  async function saveAgentCreateModal() {
    if (agentForm.sourceMode === "external") {
      setAgentCreateOpen(false);
      navigate("/enterprise/agents/external/connect");
      return;
    }
    const name = agentForm.name.trim();
    if (!name) {
      notify.error("请填写数字员工姓名");
      return;
    }
    if (agentForm.modelSelectionMode === "platform_product" && !agentForm.modelProductId) {
      notify.error("请选择一个已发布的平台模型");
      return;
    }
    if (agentForm.modelSelectionMode === "enterprise_model" && !agentForm.tenantModelConfigId) {
      notify.error("请选择企业自有模型");
      return;
    }
    const isBlankOnboarding = agentForm.sourceMode === "blank";
    const sourceAgent = agentForm.copyFromAgentId
      ? sourceAgents.find((item) => item.id === agentForm.copyFromAgentId)
      : undefined;
    const sourceMetadata =
      !isBlankOnboarding && sourceAgent?.metadata ? sourceAgent.metadata : {};
    const sourceRoleName =
      sourceAgent && !sourceAgent.is_overall
        ? employeeProfile(sourceAgent).roleName
        : "";
    const roleName =
      agentForm.roleName.trim() ||
      (!isBlankOnboarding ? sourceRoleName : "") ||
      "待补充职位";
    const description =
      agentForm.description.trim() ||
      (!isBlankOnboarding
        ? sourceAgent?.description ||
          String(sourceMetadata.system_prompt_summary || "")
        : "") ||
      "";
    const baseMetadata = {
      ...sourceMetadata,
      system_prompt_summary: description,
      owner_user_id: auth.user.id,
      owner_username: auth.user.username,
      owner_display_name: auth.user.display_name || auth.user.username,
      created_by_user_id: auth.user.id,
      created_by_username: auth.user.username,
      created_by: auth.user.username,
      created_by_display_name: auth.user.display_name || auth.user.username,
      creator_name: auth.user.username,
      role_key: "",
      role_name: roleName,
      onboarded_at: new Date().toISOString().slice(0, 10),
      blank_onboarding: isBlankOnboarding,
    };
    try {
      const created = await api.post<AgentProfileRead>(
        "/api/enterprise/agents",
        {
          tenant_id: TENANT_ID,
          name,
          description,
          source_mode: agentForm.sourceMode,
          copy_from_agent_id:
            agentForm.sourceMode === "copy"
              ? agentForm.copyFromAgentId || undefined
              : undefined,
          metadata: isBlankOnboarding
            ? employeeBlankMetadata(baseMetadata)
            : baseMetadata,
        },
      );
      try {
        await api.put(`/api/ai/agents/${encodeURIComponent(created.id)}/model-policy`, {
          tenant_id: TENANT_ID,
          selection_mode: agentForm.modelSelectionMode,
          model_product_id: agentForm.modelSelectionMode === "platform_product" ? agentForm.modelProductId : undefined,
          tenant_model_config_id: agentForm.modelSelectionMode === "enterprise_model" ? agentForm.tenantModelConfigId : undefined,
          allow_platform_fallback: true,
        });
      } catch (error) {
        notify.warning(error instanceof Error ? `员工已创建，模型策略保存失败：${error.message}` : "员工已创建，模型策略保存失败");
      }
      await loadAgents();
      changeAgentScope(created.id);
      setAgentCreateOpen(false);
      notify.success("数字员工创建成功");
    } catch (error) {
      notify.error(error instanceof Error ? error.message : "创建数字员工失败");
    }
  }

  return (
    <SidebarProvider
      open={sidebarExpanded}
      onOpenChange={handleSidebarOpenChange}
      style={
        {
          "--sidebar-width": "220px",
          "--sidebar-width-icon": "72px",
        } as CSSProperties
      }
      className={`app-shell ${sidebarExpanded ? "sidebar-expanded" : "sidebar-collapsed"} ${isAgentRosterRoute ? "is-agent-roster" : ""}`}
    >
      <AppSidebar
        selected={selected}
        onNavigate={navigate}
        isAdmin={isAdmin}
        sidebarAgent={sidebarAgent}
        scopeAgents={scopeAgents}
        selectedAgentId={selectedAgentId}
        onSelectAgent={(agentId) => {
          if (agentId !== selectedAgentId) changeAgentScope(agentId);
          navigate(EnterpriseRoute.Dashboard);
        }}
        onOpenChat={() => {
          navigate(EnterpriseRoute.Gallery);
        }}
        modelSetupAttention={isAdmin && showModelSetupNotice}
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div
          className={`content flex-1 ${isDistillRoute ? "flex min-h-0 flex-col overflow-hidden p-0!" : ""} ${isMarketplaceRoute ? "marketplace-content" : ""} ${selected === "/enterprise/dashboard" ? "sd1-dashboard-content" : ""} ${selected !== "/enterprise/dashboard" && !isDistillRoute && !isMarketplaceRoute ? "sd1-management-content" : ""}`}
        >
          {showModelSetupNotice && !isMarketplaceRoute && (
            <div className="mx-[24px] mt-[18px] mb-[10px] flex shrink-0 flex-col items-start justify-between gap-[12px] rounded-[12px] border border-[#f3d28b] bg-[#fff8e8] px-[18px] py-[12px] text-[#6f4500] shadow-[0_8px_24px_rgba(92,62,0,0.08)] sm:flex-row sm:items-center">
              <div className="flex min-w-0 items-center gap-[10px]">
                <span className="flex size-[28px] shrink-0 items-center justify-center rounded-[8px] bg-[#ffe7ad] text-[#8a4b00]">
                  <StaffdeckIcon name="model" className="size-[15px]" />
                </span>
                <span className="min-w-0 text-[13px] leading-[20px]">{modelSetupNoticeText}</span>
              </div>
              {isAdmin && (
                <UIButton
                  type="button"
                  size="sm"
                  onClick={() => navigate(EnterpriseRoute.Models)}
                  className="h-[32px] shrink-0 rounded-[8px] bg-[#1a71ff] px-[12px] text-[12px] text-white hover:bg-[#0f5ed7]"
                >
                  {t("去配置")}
                </UIButton>
              )}
            </div>
          )}
          <div
            className={
              isDistillRoute
                ? "persistent-distill active flex min-h-0 flex-1 flex-col"
                : "persistent-distill hidden"
            }
          >
            <DistillPage
              active={isDistillRoute}
              searchParamsOverride={distillSearchParams}
              currentUser={auth.user}
              onLogout={onLogout}
            />
          </div>
          {!isDistillRoute && !isMarketplaceRoute && showEmployeeEmptyState && (
            <EmptyEmployeeState
              isAdmin={isAdmin}
              onCreate={openCreateAgentModal}
              onBrowsePlatform={() => navigate(EnterpriseRoute.Platform)}
            />
          )}
          {!isDistillRoute && (!showEmployeeEmptyState || isMarketplaceRoute) && (
            <Routes>
              <Route
                path="/enterprise"
                element={<Navigate to="/enterprise/dashboard" replace />}
              />
              <Route
                path="/enterprise/platform"
                element={
                  <OpenPlatformPage
                    currentUser={auth.user}
                    isAdmin={isAdmin}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/platform/:kind"
                element={
                  <OpenPlatformPage
                    currentUser={auth.user}
                    isAdmin={isAdmin}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/platform/market-reviews"
                element={
                  isAdmin
                    ? <MarketReviewPage />
                    : <Navigate to={EnterpriseRoute.Publishing} replace />
                }
              />
              <Route
                path="/enterprise/platform/transaction-supervision"
                element={
                  isAdmin
                    ? <TransactionSupervisionPage />
                    : <Navigate to={EnterpriseRoute.Orders} replace />
                }
              />
              <Route
                path="/enterprise/platform/disputes"
                element={
                  isAdmin
                    ? <PlatformDisputesPage />
                    : <Navigate to={EnterpriseRoute.Orders} replace />
                }
              />
              <Route
                path="/enterprise/platform/disputes/:caseId"
                element={
                  isAdmin
                    ? <PlatformDisputeDetailPage />
                    : <Navigate to={EnterpriseRoute.Orders} replace />
                }
              />
              <Route
                path="/enterprise/dashboard"
                element={
                  <DashboardPage
                    currentUser={auth.user}
                    isAdmin={isAdmin}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/agents/external/connect"
                element={<ExternalAgentEnrollmentPage />}
              />
              <Route
                path="/enterprise/agents/external/:connectionId"
                element={<ExternalAgentOperationsPage />}
              />
              <Route
                path="/enterprise/agents"
                element={
                  <AgentsPage
                    currentUser={auth.user}
                    isAdmin={isAdmin}
                    onCreateAgent={openCreateAgentModal}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/memories"
                element={
                  <DashboardPage
                    currentUser={auth.user}
                    isAdmin={isAdmin}
                    profileTab="memories"
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/knowledge"
                element={
                  <KnowledgeManagePage
                    currentUser={auth.user}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/knowledge/new"
                element={
                  <KnowledgeAddPage
                    currentUser={auth.user}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/feedback"
                element={
                  <DashboardPage
                    currentUser={auth.user}
                    isAdmin={isAdmin}
                    profileTab="logs"
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/channels"
                element={
                  <ChannelsPage currentUser={auth.user} onLogout={onLogout} />
                }
              />
              <Route
                path="/enterprise/scheduled-tasks"
                element={
                  <DashboardPage
                    currentUser={auth.user}
                    isAdmin={isAdmin}
                    profileTab="scheduled"
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/scheduled-tasks/new"
                element={
                  <ScheduledTaskNewPage
                    currentUser={auth.user}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/scheduled-tasks/:taskId/edit"
                element={
                  <ScheduledTaskEditPage
                    currentUser={auth.user}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/skills"
                element={
                  <SkillsPage currentUser={auth.user} onLogout={onLogout} />
                }
              />
              <Route
                path="/enterprise/general-skills"
                element={
                  <GeneralSkillsPage
                    currentUser={auth.user}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/general-skills/new"
                element={
                  <GeneralSkillNewPage
                    currentUser={auth.user}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/general-skills/:slug/edit"
                element={
                  <GeneralSkillEditPage
                    currentUser={auth.user}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/accounts/*"
                element={<AccountManagementLayout currentUser={auth.user} onLogout={onLogout} />}
              />
              <Route
                path="/enterprise/organization/team"
                element={<LegacyOrganizationTeamRedirect />}
              />
              <Route
                path="/enterprise/models"
                element={
                  isAdmin ? (
                    <ModelsPage currentUser={auth.user} onLogout={onLogout} />
                  ) : (
                    <Navigate to={EnterpriseRoute.Gallery} replace />
                  )
                }
              />
              <Route
                path="/enterprise/ai-usage"
                element={<AIUsagePage currentUser={auth.user} onLogout={onLogout} />}
              />
              <Route
                path="/enterprise/tools"
                element={
                  <ToolsPage currentUser={auth.user} onLogout={onLogout} />
                }
              />
              <Route
                path="/enterprise/tools/new"
                element={
                  <ToolNewPage currentUser={auth.user} onLogout={onLogout} />
                }
              />
              <Route
                path="/enterprise/tools/mcp/new"
                element={
                  <McpServerNewPage
                    currentUser={auth.user}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/tools/mcp/:serverId/edit"
                element={
                  <McpServerEditPage
                    currentUser={auth.user}
                    onLogout={onLogout}
                  />
                }
              />
              <Route
                path="/enterprise/tools/:toolId/edit"
                element={
                  <ToolEditPage currentUser={auth.user} onLogout={onLogout} />
                }
              />
              <Route
                path="/enterprise/tools/:toolId/test"
                element={
                  <ToolTestPage currentUser={auth.user} onLogout={onLogout} />
                }
              />
              <Route
                path="/enterprise/persona"
                element={<Navigate to="/enterprise/dashboard" replace />}
              />
              <Route
                path="*"
                element={<Navigate to="/enterprise/dashboard" replace />}
              />
            </Routes>
          )}
        </div>
      </div>
      <Dialog open={agentCreateOpen} onOpenChange={setAgentCreateOpen}>
        <DialogContent className="flex max-h-[calc(100dvh-32px)] w-[calc(100%-32px)] flex-col gap-0 overflow-hidden rounded-[16px] p-0 sm:max-w-[520px]">
          <DialogTitle className="shrink-0 px-[24px] py-[16px] text-[16px] font-semibold text-foreground">
            新建数字员工
          </DialogTitle>
          <div className="agent-editor-form min-h-0 flex-1 overflow-y-auto px-[24px] pb-[16px]">
            <label>
              创建方式
              <div className="grid w-full gap-[6px]">
                {[
                  { label: "从广场招募", description: "复制平台内已有数字员工及已授权资源", value: "copy" as const },
                  { label: "外接已有 Agent", description: "连接本地或云端 Agent，后续仍在原环境运行", value: "external" as const },
                  { label: "从空白创建", description: "手工配置一个新的平台数字员工", value: "blank" as const },
                ].map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={cn(
                      "flex flex-col items-start rounded-[9px] border px-[12px] py-[9px] text-left text-[13px] font-medium transition-colors",
                      agentForm.sourceMode === option.value
                        ? "border-[#18181a] bg-[#18181a] text-white"
                        : "border-border text-[#303541] hover:border-[#aeb5c0]",
                    )}
                    onClick={() =>
                      setAgentForm((prev) => ({
                        ...prev,
                        sourceMode: option.value,
                        copyFromAgentId:
                          option.value !== "copy" ? "" : prev.copyFromAgentId,
                      }))
                    }
                  >
                    <span>{option.label}</span><small className={agentForm.sourceMode === option.value ? "text-white/65" : "text-[#858c98]"}>{option.description}</small>
                  </button>
                ))}
              </div>
            </label>
            {agentForm.sourceMode !== "external" && <label>
              职位
              <Input
                value={agentForm.roleName}
                onChange={(event) =>
                  setAgentForm((prev) => ({
                    ...prev,
                    roleName: event.target.value,
                  }))
                }
                placeholder="例如 研发工程师、财务助理"
              />
            </label>}
            <div className="grid content-start gap-[6px]">
            {agentForm.sourceMode === "copy" && (
              <label>
                复制来源
                <UISelect
                  value={agentForm.copyFromAgentId || undefined}
                  onValueChange={(value) =>
                    setAgentForm((prev) => {
                      const nextSource = sourceAgents.find(
                        (item) => item.id === value,
                      );
                      return {
                        ...prev,
                        copyFromAgentId: value,
                        roleName:
                          prev.roleName ||
                          (nextSource && !nextSource.is_overall
                            ? employeeProfile(nextSource).roleName
                            : ""),
                      };
                    })
                  }
                >
                  <SelectTrigger className={cn(SELECT_TRIGGER_CLASS, "w-full")}>
                    <SelectValue placeholder="选择复制来源" />
                  </SelectTrigger>
                  <SelectContent>
                    {sourceAgents.map((agent) => (
                      <SelectItem key={agent.id} value={agent.id}>
                        {agent.is_overall
                          ? "公司广场"
                          : `${employeeDisplayNameWithCreator(agent)} · ${employeeProfile(agent).roleName}${isGalleryEmployee(agent) ? " · 广场" : ""}`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </UISelect>
              </label>
            )}
            {agentForm.sourceMode === "blank" && (
              <div className="agent-definition-note">
                从空白开始创建，不继承任何已有配置。
              </div>
            )}
            {agentForm.sourceMode === "external" && (
              <div className="agent-definition-note">
                下一步将生成一次性配对码。平台默认只接收你确认的能力元数据，不会自动上传源码、知识正文或密钥。
              </div>
            )}
            </div>
            {agentForm.sourceMode !== "external" && <label>
              数字员工姓名
              <Input
                value={agentForm.name}
                onChange={(event) =>
                  setAgentForm((prev) => ({
                    ...prev,
                    name: event.target.value,
                  }))
                }
              />
            </label>}
            {agentForm.sourceMode !== "external" && <label>
              岗位描述
              <Textarea
                rows={3}
                value={agentForm.description}
                onChange={(event) =>
                  setAgentForm((prev) => ({
                    ...prev,
                    description: event.target.value,
                  }))
                }
                placeholder="概括这个数字员工的岗位边界、服务风格和执行重点"
              />
            </label>}
            {agentForm.sourceMode !== "external" && <label>
              模型策略
              <div className="grid grid-cols-3 gap-[6px]">
                {[
                  { value: "auto" as const, label: "智能匹配" },
                  { value: "platform_product" as const, label: "指定平台模型" },
                  { value: "enterprise_model" as const, label: "企业自有模型" },
                ].map((option) => (
                  <button
                    type="button"
                    key={option.value}
                    className={cn(
                      "h-[36px] rounded-[9px] border px-[8px] text-[12px] transition-colors",
                      agentForm.modelSelectionMode === option.value
                        ? "border-[#18181a] bg-[#18181a] text-white"
                        : "border-border bg-white text-[#464c5e] hover:border-[#aeb5c0]",
                    )}
                    onClick={() => setAgentForm((current) => ({ ...current, modelSelectionMode: option.value }))}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </label>}
            {agentForm.sourceMode !== "external" && agentForm.modelSelectionMode === "platform_product" && (
              <label>
                平台模型
                <UISelect
                  value={agentForm.modelProductId || undefined}
                  onValueChange={(value) => setAgentForm((current) => ({ ...current, modelProductId: value }))}
                >
                  <SelectTrigger className={cn(SELECT_TRIGGER_CLASS, "w-full")}>
                    <SelectValue placeholder="选择已发布的平台模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {modelOptions.platform_models.map((model) => (
                      <SelectItem key={model.id} value={model.id}>
                        {model.display_name} · {model.model_family}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </UISelect>
              </label>
            )}
            {agentForm.sourceMode !== "external" && agentForm.modelSelectionMode === "enterprise_model" && (
              <label>
                企业自有模型
                <UISelect
                  value={agentForm.tenantModelConfigId || undefined}
                  onValueChange={(value) => setAgentForm((current) => ({ ...current, tenantModelConfigId: value }))}
                >
                  <SelectTrigger className={cn(SELECT_TRIGGER_CLASS, "w-full")}>
                    <SelectValue placeholder="选择企业自有模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {modelOptions.enterprise_models.map((model) => (
                      <SelectItem key={model.id} value={model.id}>
                        {model.display_name} · {model.description}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </UISelect>
              </label>
            )}
          </div>
          <div className={cn(DIALOG_FOOTER_CLASS, "shrink-0 border-t border-border")}>
            <UIButton
              variant="outline"
              className={DIALOG_CANCEL_BUTTON_CLASS}
              onClick={() => setAgentCreateOpen(false)}
            >
              取消
            </UIButton>
            <UIButton
              className={DIALOG_PRIMARY_BUTTON_CLASS}
              onClick={() => void saveAgentCreateModal()}
            >
              {agentForm.sourceMode === "external" ? "开始连接" : "创建"}
            </UIButton>
          </div>
        </DialogContent>
      </Dialog>
    </SidebarProvider>
  );
}

function AuthedApp({
  auth,
  onLogout,
}: {
  auth: EnterpriseAuthSession;
  onLogout: () => void;
}) {
  const location = useLocation();
  if (location.pathname === "/") {
    return <Navigate to={EnterpriseRoute.Gallery} replace />;
  }
  if (location.pathname === "/chat" || location.pathname === "/chat/") {
    return <Navigate to={EnterpriseRoute.Gallery} replace />;
  }
  if (location.pathname.startsWith("/chat/draft/")) {
    const nextPath = location.pathname.replace(/^\/chat/, EnterpriseRoute.Chat);
    return <Navigate to={`${nextPath}${location.search}`} replace />;
  }
  if (location.pathname.startsWith("/chat/session_")) {
    const nextPath = location.pathname.replace(/^\/chat/, EnterpriseRoute.Chat);
    return <Navigate to={`${nextPath}${location.search}`} replace />;
  }
  if (location.pathname === "/enterprise/chat" || location.pathname === "/enterprise/chat/") {
    return <Navigate to={EnterpriseRoute.Gallery} replace />;
  }
  if (location.pathname.startsWith("/enterprise/chat/draft/")) {
    const nextPath = location.pathname.replace(/^\/enterprise\/chat/, EnterpriseRoute.Chat);
    return <Navigate to={`${nextPath}${location.search}`} replace />;
  }
  if (location.pathname.startsWith("/enterprise/chat/session_")) {
    const nextPath = location.pathname.replace(/^\/enterprise\/chat/, EnterpriseRoute.Chat);
    return <Navigate to={`${nextPath}${location.search}`} replace />;
  }
  if (isMarketplaceWorkspacePath(location.pathname)) {
    return <ConversationWorkspaceShell />;
  }
  if (location.pathname.startsWith(EnterpriseRoute.Workspace)) {
    if (location.pathname === EnterpriseRoute.Workspace) {
      return <Navigate to="/workspace/gallery" replace />;
    }
    return <ConversationWorkspaceShell />;
  }
  return <Shell auth={auth} onLogout={onLogout} />;
}

export default function App() {
  // Subscribe the application tree to locale changes so locale-sensitive dates
  // and computed labels update without remounting or losing form state.
  useI18n();
  const [auth, setAuth] = useState<EnterpriseAuthSession | null>(() =>
    getEnterpriseAuthSession(),
  );
  const [authChecked, setAuthChecked] = useState(() => !auth?.token);

  useEffect(() => {
    if (!auth?.token) {
      setAuthChecked(true);
      return undefined;
    }
    let cancelled = false;
    setAuthChecked(false);
    void api.get<EnterpriseAuthUser>("/api/auth/me")
      .then((user) => {
        if (cancelled) return;
        const refreshed = { token: auth.token, user };
        setEnterpriseAuthSession(refreshed);
        setAuth(refreshed);
        setAuthChecked(true);
      })
      .catch((error) => {
        if (cancelled) return;
        if (isAuthError(error)) {
          clearEnterpriseAuthSession();
          setAuth(null);
        }
        setAuthChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [auth?.token]);

  function logout() {
    clearEnterpriseAuthSession();
    setAuth(null);
    setAuthChecked(true);
  }

  return (
    <TooltipProvider>
      <BrowserRouter>
        <Routes>
          <Route
            path="/*"
            element={
              auth && !authChecked ? null : auth ? (
                <AuthedApp auth={auth} onLogout={logout} />
              ) : (
                <LoginPage onLogin={setAuth} />
              )
            }
          />
        </Routes>
        {auth && authChecked ? <OnboardingGuide /> : null}
        {auth && authChecked ? <QuickStartGuide isAdmin={isEnterpriseAdmin(auth.user)} /> : null}
      </BrowserRouter>
      <Toaster richColors closeButton position="top-center" />
    </TooltipProvider>
  );
}
