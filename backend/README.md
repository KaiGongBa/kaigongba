# Backend

FastAPI backend for the Skill Agent Loop MVP.

## Run

From the repository root, prefer:

```bash
scripts/dev_up.sh
```

For backend-only debugging:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
.venv/bin/uvicorn single_port_app:app --host 127.0.0.1 --port 5173
```

Swagger UI: `http://localhost:5173/docs`

## Database migrations and Marketplace data

SQLite remains the default local database. PostgreSQL is supported through
`psycopg` 3; both `postgres://...` and `postgresql://...` URLs are normalized to
the SQLAlchemy `postgresql+psycopg://...` driver.

Run the Alembic migration before starting a new environment:

```bash
cd backend
.venv/bin/python -m app.db.migrate
```

The Marketplace pages use persisted API data by default. To write the repeatable
development seed into the same real tables used by the application:

```bash
cd backend
.venv/bin/python -m app.marketplace.seed
```

`MARKETPLACE_SEED_ENABLED=true` may be used for local startup only. Keep it
`false` in production; production Marketplace records must be created by business
workflows, not by development seed data.

Phase 3B adds persisted organization profiles, member roles and invitations,
provider onboarding, AI service/Skill draft versions, review submissions and
platform review decisions. A submitted version is frozen for review and only
becomes visible in the public Marketplace after an administrator approves it.
All of these transitions write Marketplace audit records.

`CORS_ORIGINS` controls the allowed frontend origins. The root `scripts/dev_up.sh`
sets the local single-port origin by default and can add a public tunnel origin with
`PUBLIC_APP_ORIGIN`.

## 手机号与短信验证登录

管理员先在「账号管理」为用户绑定手机号。默认登录流程为「手机号 →
短信验证码 → 密码」；找回密码使用独立用途的短信验证码。旧账号在绑定前
仍可从登录页的「使用账号密码登录」进入。

本地开发默认 `SMS_PROVIDER=console`，验证码只会在开发环境的 API 响应中以
`debug_code` 返回，不写入日志。预发和生产环境的 `console` 投递会被拒绝，
需要配置已审核的阿里云短信签名和两个验证码模板（模板变量名均为 `code`）：

```dotenv
SMS_PROVIDER="aliyun"
SMS_ALIYUN_ACCESS_KEY_ID="<RAM 用户 AccessKey ID>"
SMS_ALIYUN_ACCESS_KEY_SECRET="<RAM 用户 AccessKey Secret>"
SMS_ALIYUN_SIGN_NAME="开工吧"
SMS_ALIYUN_LOGIN_TEMPLATE_CODE="SMS_xxx"
SMS_ALIYUN_RESET_TEMPLATE_CODE="SMS_yyy"
```

正式部署前执行数据库迁移，为 `users` 补充手机号唯一绑定，并创建验证码
挑战表：

```bash
.venv/bin/python -m app.db.migrate
```

## General Skill Code Runtime

通用技能生成的 Python/Bash runner 不直接依赖系统 Python。运行时按以下顺序选择环境：

1. `GENERAL_SKILL_RUNTIME_PYTHON` 指定的 Python；
2. `GENERAL_SKILL_RUNTIME_VENV` 指定虚拟环境中的 Python；
3. `backend/.venv/bin/python`；
4. 自动创建 `backend/.runtime_venv`。

`GENERAL_SKILL_RUNTIME_PACKAGES` 默认安装/校验 `requests,httpx`，用于通用 API
访问。需要文档解析或数据处理时可以扩展为：

```bash
GENERAL_SKILL_RUNTIME_PACKAGES="requests,httpx,beautifulsoup4,lxml,pypdf,python-docx,pandas,numpy,python-dateutil"
```

如果部署环境禁止自动安装依赖，设置：

```bash
GENERAL_SKILL_RUNTIME_AUTO_INSTALL="false"
GENERAL_SKILL_RUNTIME_PYTHON="/path/to/prepared/venv/bin/python"
```

## Demo Seed

Startup seeds:

- `tenant_demo`
- refund skill `after_sales_refund`
- exchange skill `after_sales_exchange`
- mock HTTP tool `order.query`

Set `DEMO_MODEL_API_KEY` before first startup if you want a default model config to be created automatically.
