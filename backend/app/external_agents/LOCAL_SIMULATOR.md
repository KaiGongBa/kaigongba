# 本地外接 Agent 协议模拟器

`local_simulator.py` 是一个只调用公开 HTTP 协议的可重复验收工具，不读写平台数据库，也不具备验收、支付、退款或放款权限。

## 使用步骤

1. 企业负责人在平台创建一次性外接 Agent 配对码。
2. 在 `backend` 目录登记模拟 Agent 并提交 Manifest：

   ```bash
   .venv/bin/python -m app.external_agents.local_simulator \
     --base-url http://127.0.0.1:8000 \
     --state-file .data/external-agent-simulator.json \
     enroll --pairing-code 'KGB-...'
   ```

3. 企业负责人在平台审核 Manifest，选择“受控文档交付”能力，确认导入草稿并发起连接测试。
4. 执行一次心跳、连接测试和任务轮询：

   ```bash
   .venv/bin/python -m app.external_agents.local_simulator \
     --base-url http://127.0.0.1:8000 \
     --state-file .data/external-agent-simulator.json \
     run-once
   ```

5. 持续轮询：

   ```bash
   .venv/bin/python -m app.external_agents.local_simulator \
     --base-url http://127.0.0.1:8000 \
     --state-file .data/external-agent-simulator.json \
     run --poll-seconds 5
   ```

状态文件包含只返回一次的 Agent 凭据，模拟器会将文件权限设为 `0600`，且不会把凭据输出到终端。不要将该文件提交到 Git。

## 模拟覆盖

- 配对预检、登记凭据和 Manifest 提交。
- 心跳和连接测试回应。
- 轮询领取、开始、进度、阶段性制品和最终结果回传。
- 结果回执重放幂等验证。
- 502/503/504 和连接中断的有限指数退避重试。

“文件回传”在当前协议中是平台对象引用，不是直接上传文件字节。真实第三方联调前，还需接入受任务和租户约束的预签名上传与对象归属校验。
