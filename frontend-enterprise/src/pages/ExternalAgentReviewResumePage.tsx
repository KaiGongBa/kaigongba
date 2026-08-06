import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowLeft, LoaderCircle, RefreshCw } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { api } from '@/api/client';
import { Button } from '@/components/ui/button';

type EnrollmentResume = {
  id: string;
  connectionId?: string;
  workflowStage?: string;
};

export default function ExternalAgentReviewResumePage() {
  const { connectionId = '' } = useParams();
  const navigate = useNavigate();
  const [error, setError] = useState('');

  const resume = useCallback(async () => {
    if (!connectionId) {
      setError('缺少外接 Agent 连接 ID。');
      return;
    }
    setError('');
    try {
      const enrollment = await api.get<EnrollmentResume>(`/api/enterprise/external-agents/${encodeURIComponent(connectionId)}/enrollment`);
      if (!enrollment.id) throw new Error('平台未返回可恢复的配对记录');
      navigate(`/enterprise/agents/external/connect?enrollmentId=${encodeURIComponent(enrollment.id)}`, { replace: true });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '待审核记录加载失败');
    }
  }, [connectionId, navigate]);

  useEffect(() => { void resume(); }, [resume]);

  return <main className="external-agent-enrollment-page">
    <header><button type="button" onClick={() => navigate(`/enterprise/agents/external/${encodeURIComponent(connectionId)}`)}><ArrowLeft />连接详情</button><div><h1>继续审核外接 Agent</h1><p>正在恢复 Manifest 审核、员工档案与连接测试进度。</p></div></header>
    {error ? <section className="external-agent-enrollment-card external-agent-resume-error"><AlertTriangle /><div><h2>无法恢复审核</h2><p>{error}</p><Button onClick={() => void resume()}><RefreshCw />重新加载</Button></div></section> : <div className="external-agent-loading"><LoaderCircle className="is-spinning" />正在恢复审核流程…</div>}
  </main>;
}
