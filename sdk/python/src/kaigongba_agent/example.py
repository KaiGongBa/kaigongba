from __future__ import annotations

from typing import Any

from .client import TaskContext


def handle(task: dict[str, Any], context: TaskContext) -> dict[str, Any]:
    """Safe example handler: echoes authorized input without touching local files."""

    context.progress(50, "示例 Agent 正在处理授权输入")
    return {
        "output": {
            "summary": "示例外接 Agent 已完成任务",
            "receivedGoal": task.get("goal", ""),
            "receivedInput": task.get("input", {}),
        }
    }
