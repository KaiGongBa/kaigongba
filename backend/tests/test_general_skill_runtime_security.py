import json

from app.db.models import GeneralSkill
from app.general_skills.runner import GeneralSkillRunner
from app.general_skills.schema import GeneralSkillExecutionPlan


def test_general_skill_child_process_does_not_inherit_application_secrets(monkeypatch) -> None:
    secrets = {
        "APP_SECRET": "app-secret-value",
        "INTERNAL_SERVICE_SECRET": "internal-secret-value",
        "DATABASE_URL": "postgresql://secret-database",
        "DEMO_MODEL_API_KEY": "model-secret-value",
        "CHANNEL_SECRET": "channel-secret-value",
        "HTTP_PROXY": "http://secret-proxy",
        "HTTPS_PROXY": "http://secret-proxy",
    }
    for key, value in secrets.items():
        monkeypatch.setenv(key, value)

    skill = GeneralSkill(
        tenant_id="tenant_security",
        slug="environment-audit",
        name="运行环境审计",
        skill_markdown="# 运行环境审计",
        status="published",
    )
    plan = GeneralSkillExecutionPlan(
        runtime="python",
        code=(
            "import json, os\n"
            f"keys = {json.dumps(list(secrets))}\n"
            "print(json.dumps({'success': True, 'values': {k: os.getenv(k) for k in keys}}))\n"
        ),
    )

    stdout, stderr, result = GeneralSkillRunner()._execute_plan(
        skill,
        "检查环境",
        plan,
        "user_security",
        [],
    )

    assert stderr == ""
    assert stdout
    assert result["success"] is True
    assert result["values"] == {key: None for key in secrets}
