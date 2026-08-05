"""Run with: kaigongba-agent run --handler basic_agent:handle"""

from typing import Any

from kaigongba_agent import TaskContext


def handle(task: dict[str, Any], context: TaskContext) -> dict[str, Any]:
    context.progress(30, "已读取平台授权的任务输入")
    # Replace this section with the real Agent invocation. Never return local secrets.
    result = {"summary": "外部 Agent 执行完成", "goal": task.get("goal", "")}
    context.progress(90, "正在整理结构化结果")
    return {"output": result, "artifact_refs": []}
