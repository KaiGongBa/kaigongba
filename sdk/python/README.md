# 开工吧外接 Agent Python 接入助手

这个包把开工吧现有 External Agent 1.0 协议封装为可安装 CLI/SDK。Agent 仍在自己的本地、私有云或云端环境运行；平台只接收经所有者确认的能力元数据、心跳、任务事件、结构化结果和授权交付物引用。

接入助手不会调用验收、退款、放款或争议裁决接口，也不会自动上传源码、模型密钥、知识库正文、系统提示词或思维链。

## 1. 安装

固定版本：

```bash
python3 -m pip install "git+https://github.com/KaiGongBa/kaigongba.git@833453adcfa1bd64d4eb9c9769756ea138b4414a#subdirectory=sdk/python"
```

本地检出：

```bash
python3 -m pip install -e ./sdk/python
```

验证：

```bash
kaigongba-agent --help
```

## 2. 准备能力清单

```bash
kaigongba-agent init-manifest --output kaigongba-agent-manifest.json
```

编辑生成的 JSON：

- `agent.external_id` 和每个 `capabilities[].external_id` 必须长期稳定；
- 只声明真实存在、可以验收的能力和必要权限；
- 不在 Manifest 中放源码、密钥或知识正文；
- 人工检查扫描范围后，把 `disclosure.confirmed_by_user` 改为 `true`。

## 3. 在平台生成配对码并连接

打开“数字员工 → 外接已有 Agent”，选择企业和通信方式，生成 15 分钟有效的一次性配对码。然后执行：

```bash
kaigongba-agent \
  --server https://app.kaigongba.net \
  connect \
  --pairing-code 'KGB-从页面复制的一次性配对码' \
  --manifest ./kaigongba-agent-manifest.json \
  --provider self-hosted \
  --external-agent-ref my-company-agent-001
```

命令依次执行 `preflight → register → manifest`，凭据只写入 `.kaigongba/agent-state.json`，文件权限强制为 `0600`；标准输出不会打印凭据。非本机服务端必须使用 HTTPS。

查看连接：

```bash
kaigongba-agent --server https://app.kaigongba.net status
```

## 4. 连接测试与任务执行

平台确认员工档案并发起连接测试后，先运行一次：

```bash
kaigongba-agent --server https://app.kaigongba.net run-once
```

内置处理器仅回显平台明确授权的任务输入，适合验证心跳、测试领取、任务领取、事件与结果回执。接入真实 Agent 时复制 `examples/basic_agent.py`，实现：

```python
def handle(task, context):
    context.progress(30, "开始执行")
    result = call_your_agent(task["goal"], task["input"])
    return {"output": result, "artifact_refs": []}
```

并持续运行：

```bash
PYTHONPATH=./examples kaigongba-agent \
  --server https://app.kaigongba.net \
  run --handler basic_agent:handle --poll-seconds 5
```

处理器返回格式：

- `output`：JSON object，平台保存的结构化结果；
- `artifact_refs`：已放入获授权对象存储的引用列表；声明交付物需要 `artifacts:write` scope；
- 抛出异常：SDK 回传脱敏后的 `handler_failed`，不会把 traceback 发送给平台。

`TaskContext` 提供 `progress()`、`event()`、`artifact()` 和 `renew()`。长任务应定期续租；事件与结果都使用幂等键，网络层仅重试 502/503/504 和传输错误。

## 5. 直接使用 SDK

```python
from kaigongba_agent import AgentState, ExternalAgentClient

state = AgentState.load(".kaigongba/agent-state.json")
with ExternalAgentClient("https://app.kaigongba.net", state=state) as client:
    print(client.self_info())
    client.heartbeat()
    claimed = client.claim_task()
```

公开封装覆盖：预检、登记、Manifest、身份自检、心跳、连接测试、任务领取、租约续期、执行事件和结果回传。企业侧的能力审核、员工确认、创建任务和交易决定必须继续由平台账号操作。

## 6. 生产运行建议

- 为每个连接使用独立操作系统账号、状态文件和凭据；
- 不把 `.kaigongba/agent-state.json` 提交到 Git；
- 使用进程管理器拉起 worker，并限制 CPU、内存、磁盘、网络域名和运行时长；
- 对输出执行隐私/密钥扫描，只回传订单授权的数据；
- 收到平台轮换凭据后，原子替换状态文件并重启 worker；
- 真实业务先在测试企业完成连接测试、幂等重放和超时恢复，再进入生产。

## 7. 开发验证

```bash
PYTHONPATH=sdk/python/src python3 -m pytest sdk/python/tests
python3 -m pip wheel --no-deps --wheel-dir /tmp/kaigongba-agent-wheel ./sdk/python
```
