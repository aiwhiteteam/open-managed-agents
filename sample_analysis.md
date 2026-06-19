# Open Managed Agents：给 Codex 的 High-Level 研究与实现指南

结论

截至 2026 年 6 月 19 日，如果只能选一种语言：Python 3.12。

更理想的长期形态是：

Python 负责 Agent execution plane / harness worker，TypeScript 负责控制台、前端和面向用户的 SDK。

为什么选 Python

Claude Managed Agents 并不是简单地在 Agent SDK 外面套一层 REST API。它公开了 Agent / Environment / Session / Event 四类核心资源，提供持久化事件历史、SSE 流、可恢复 Session 和隔离 Sandbox。其内部又刻意把三个组件解耦：append-only session log、agent harness、sandbox，从而让 harness 或 sandbox 崩溃后可以重新创建并从事件日志恢复。

OpenAI Agents SDK 的 Python 版本已经提供了实现这套架构最关键的底层能力：

SandboxAgent + Manifest + SandboxRunConfig
Sandbox session、snapshot 和序列化恢复
RunState 序列化与跨进程恢复
流式运行事件
Session 持久化接口
Human-in-the-loop 暂停与恢复
官方文档明确列出的 Temporal、Dapr、Restate、DBOS 等 durable execution 集成
SQLAlchemy 生产级 Session 存储实现

这些能力与你需要构建的 managed runtime 几乎一一对应。

因此，Python 不是因为更适合写 REST API，而是因为它能让你以最短路径完成最难的 execution/runtime 部分。

TypeScript 能不能做

完全可以。OpenAI 官方称 TypeScript Agents SDK 为 production-ready；目前也支持 Sandbox Agent、Session、HITL、Tracing、MCP、序列化 RunState、sandbox session state 和 snapshot。

下面这些条件同时成立时，可以直接选 TypeScript：

团队绝大多数成员只熟悉 TypeScript；
已经使用 NestJS/Fastify、Temporal TypeScript、Prisma 等完整栈；
很重视后端、Web 控制台和用户 SDK 共享 Zod 类型；
愿意自己把 durable workflow、event sourcing 和 worker recovery 做扎实。

否则，针对“先做出一个 OpenAI Managed Agents”的目标，Python 风险更低。

推荐架构
                    ┌─────────────────────┐
Client / SDK ──────▶│ REST + SSE API      │
                    │ FastAPI + Pydantic  │
                    └──────────┬──────────┘
                               │ append event
                    ┌──────────▼──────────┐
                    │ PostgreSQL           │
                    │ Append-only events   │
                    │ agents / sessions    │
                    └──────────┬──────────┘
                               │ wake(session_id)
                    ┌──────────▼──────────┐
                    │ Durable workflow     │
                    │ Temporal / DBOS      │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Python Harness Worker│
                    │ OpenAI Agents SDK    │
                    └──────┬────────┬─────┘
                           │        │
                 ┌─────────▼───┐ ┌──▼────────────┐
                 │ Sandbox      │ │ MCP/Auth Proxy│
                 │ Docker/hosted│ │ Vault/KMS     │
                 └──────────────┘ └───────────────┘

建议栈：

部分  选择
语言  Python 3.12
API FastAPI + Pydantic v2
Agent runtime openai-agents
Durable orchestration Temporal；小规模可以先用 DBOS
主数据库  PostgreSQL
Sandbox 开发  DockerSandboxClient
Sandbox 生产  Hosted sandbox provider 或自建隔离容器
Artifact / snapshot S3-compatible object storage
Event fan-out PostgreSQL LISTEN/NOTIFY、Redis Streams 或 NATS
Secret 管理 Vault/KMS，凭据不进入 sandbox
Observability OpenTelemetry + OpenAI tracing

OpenAI 的 Sandbox API 本身已经把 Agent 定义与具体 Sandbox client 分开，因此本地可以使用 Docker，生产再替换成 hosted provider，而不必重写 Agent 定义。

应该定义的核心对象
AgentDefinition(
    id,
    version,
    model,
    instructions,
    tools,
    handoffs,
    guardrails,
    runtime_version,
)

Environment(
    id,
    sandbox_provider,
    image,
    cpu,
    memory,
    network_policy,
    mounts,
)

Session(
    id,
    agent_id,
    agent_version,
    environment_id,
    status,
    run_state_blob,
    sandbox_state_blob,
    last_event_seq,
)

SessionEvent(
    session_id,
    seq,
    event_type,
    payload,
    created_at,
)

REST 接口可以先做到：

POST /v1/agents
PATCH /v1/agents/{id}
POST /v1/environments

POST /v1/sessions
GET  /v1/sessions/{id}

POST /v1/sessions/{id}/events
GET  /v1/sessions/{id}/events
GET  /v1/sessions/{id}/events/stream

POST /v1/sessions/{id}/cancel
POST /v1/sessions/{id}/resume
Worker 的正确运行方式

每次收到用户事件：

将事件追加到 session_events。
唤醒对应 durable workflow。
对 Session 加 fencing lock，避免两个 worker 同时执行。
加载该 Session 固定的 Agent 版本。
恢复 RunState。
恢复或重新创建 Sandbox session。
调用 Runner.run_streamed()。
把 SDK stream event 转换为你自己的稳定事件格式。
在模型调用、工具调用、approval、handoff 等边界保存 checkpoint。
完成后将状态设为 idle，而不是销毁整个 Session。

OpenAI 的 RunState 可以序列化后在另一个进程恢复，Sandbox 状态也可以通过 session state 或 snapshot 单独恢复，这正适合这种 worker 可随时重启的架构。

三个最重要的设计决定
1. 不要直接暴露 OpenAI SDK 的事件对象

定义自己的版本化协议，例如：

{
  "id": "evt_...",
  "session_id": "sess_...",
  "seq": 104,
  "type": "agent.tool.completed",
  "created_at": "...",
  "data": {
    "tool_call_id": "...",
    "tool_name": "shell",
    "output": "..."
  }
}

SDK event 只是内部适配器。否则 OpenAI SDK 一次字段调整就会破坏你的公开 API。

2. Session 日志和模型 Context 必须分开

保存完整、不可变的 Session event log；每次调用模型时，再根据当前 harness 策略生成 context，可以裁剪、总结或 compact，但不能把 compact 后的上下文当作唯一真相。Claude Managed Agents 也明确把持久 Session 日志和模型 context window 分开。

3. 每个 Session 必须固定运行时版本

至少记录：

agent_definition_version
agents_sdk_version
runtime_image_digest
event_schema_version
sandbox_provider_version

否则长期暂停的 RunState，可能无法在升级后的 Agent graph 或 SDK 中恢复。OpenAI TypeScript 文档也专门提醒：长期保存状态时，应为 Agent 代码和 SDK 版本实施版本分支。

最终选择

第一版直接用 Python 全栈完成：FastAPI + PostgreSQL + Temporal/DBOS + OpenAI Agents SDK。

等产品稳定以后，再根据实际瓶颈拆分：

TypeScript：Web console、外部 SDK、API gateway
Python：Agent harness、OpenAI Agents SDK worker
Go/Rust：高密度 sandbox daemon、网络代理或基础设施组件

不要一开始用 Go 或 Rust 编写核心 harness，否则仍然需要通过 RPC 调用 Python/TypeScript Agents SDK，相当于在产品尚未成型时先引入一次不必要的语言边界。

> 项目名：`open-managed-agents`  
> 目标语言：Python 3.12  
> 外部协议：兼容 Claude Managed Agents（下文简称 CMA）的公开 REST / JSON / SSE 接口  
> 内部执行引擎：OpenAI Agents SDK  
> 持久化：PostgreSQL；可以使用 Supabase Postgres、Storage、Queues  
> 当前兼容基线：`managed-agents-2026-04-01`

---

## 1. Codex 的任务

构建一个独立 Web Service：

```text
CMA-compatible client
        |
        | REST / JSON / SSE
        v
open-managed-agents compatibility layer
        |
        | internal domain events
        v
OpenAI Agents SDK runtime + sandbox + workers
        |
        v
Postgres / Supabase + object storage
```

客户端应当能够把官方 Anthropic Python SDK 的 `base_url` 指向本服务，然后调用 `client.beta.agents`、`client.beta.sessions` 等 API。除服务地址、API Key 和模型配置外，P0 示例代码应尽量不需要修改。

本项目实现的是 **公开接口兼容层**，不是 Anthropic 服务，也不得宣称由 Anthropic 提供或认证。

---

## 2. 兼容目标分层

按以下优先级实现，不要把“兼容”理解成模型输出完全一致。

### L1：Wire compatibility

必须尽量一致：

- HTTP method、path、query 参数；
- 请求头及认证方式；
- JSON 字段、可选性、`null` 与 omitted 的区别；
- union 的 `type` discriminator；
- ID 前缀和 RFC 3339 时间；
- pagination envelope；
- error envelope 与 HTTP status；
- SSE framing、事件顺序和断线重连。

### L2：Lifecycle compatibility

必须尽量一致：

- Agent 版本不可变；
- Session 状态机；
- event append/list/stream；
- archive 与 delete 的区别；
- tool approval、custom tool continuation；
- retry、rescheduling、termination；
- thread、resource、deployment 生命周期。

### L3：Capability compatibility

逐步实现：

- sandbox、filesystem、shell；
- MCP；
- files、GitHub repository resources；
- memory stores；
- multi-agent threads；
- vaults；
- scheduled deployments；
- self-hosted workers。

### 非目标：Behavioral parity

OpenAI 模型不需要产生与 Claude 相同的文本、工具选择或推理轨迹。不要写依赖特定自然语言输出的兼容测试。

---

## 3. 第一阶段必须先研究，禁止直接写业务实现

Codex 首先建立一个机器可读的 CMA compatibility contract。上游唯一事实来源应当是：

1. Anthropic 官方 Managed Agents 文档；
2. Anthropic 官方 Python SDK 的生成代码；
3. Anthropic 官方 Python SDK 的 `api.md`；
4. OpenAI Agents SDK 官方文档和公开类型；
5. Supabase 官方文档。

优先研究 Anthropic SDK 中这些目录：

```text
anthropic-sdk-python/
  api.md
  src/anthropic/resources/beta/
  src/anthropic/types/beta/
```

重点搜索：

```text
path_template(
self._get(
self._post(
self._delete(
managed-agents-2026-04-01
BetaManagedAgents
```

### Phase 0 必须产出的文件

```text
compat/upstream-manifest.yaml
compat/cma-api-inventory.yaml
compat/cma-event-catalog.yaml
compat/cma-errors.yaml
compat/cma-pagination.yaml
compat/cma-state-machines.yaml
docs/compatibility-matrix.md
tests/contract/
```

`upstream-manifest.yaml` 至少锁定：

```yaml
cma_beta: managed-agents-2026-04-01
anthropic_python_sdk_version: "..."
anthropic_python_sdk_commit: "..."
openai_agents_sdk_version: "..."
research_date: "YYYY-MM-DD"
```

每一个 API operation 必须记录：

```yaml
operation_id: sessions.events.send
method: POST
path: /v1/sessions/{session_id}/events
query:
  beta: true
headers: []
request_model: ...
response_model: ...
pagination: null
side_effects: []
emitted_events: []
archive_semantics: null
errors: []
research_status: verified | inferred | unknown
source_files: []
```

凡是没有从官方文档或官方 SDK 验证的内容，都标成 `unknown`，不得猜测后伪装成事实。

---

## 4. 需要 Codex 研究的 CMA API 清单

下面是研究范围和实施优先级。方法名来自官方 SDK 的公开资源结构；准确 HTTP verb、path、query、字段和响应模型仍需由 Codex 从锁定版本源码中提取。

## P0：必须先实现的核心接口

### 4.1 Agents

研究：

```text
client.beta.agents.create
client.beta.agents.retrieve
client.beta.agents.update
client.beta.agents.list
client.beta.agents.archive
client.beta.agents.versions.list
```

主要 route root：

```text
/v1/agents
/v1/agents/{agent_id}
/v1/agents/{agent_id}/archive
/v1/agents/{agent_id}/versions
```

重点行为：

- 创建时生成 version 1；
- update 是否为 full replacement、partial update，及 omitted/null 语义；
- update 的 optimistic concurrency/version precondition；
- 新版本不可修改；
- Session 必须解析并固定具体 Agent version；
- archive 后旧 Session 是否继续运行、新 Session 是否允许创建；
- `model`、`system`、`tools`、`mcp_servers`、`skills`、`multiagent`、`metadata` 的完整 union schema。

### 4.2 Environments

研究：

```text
client.beta.environments.create
client.beta.environments.retrieve
client.beta.environments.update
client.beta.environments.list
client.beta.environments.delete
client.beta.environments.archive
```

主要 route root：

```text
/v1/environments
/v1/environments/{environment_id}
/v1/environments/{environment_id}/archive
```

P0 只需要可靠实现一种 `cloud`-like environment backend，可以映射到 Docker 或 hosted sandbox。仍需接受并验证 CMA-compatible config shape。

重点字段：

- `type: cloud | self_hosted`；
- packages；
- unrestricted/limited networking；
- allowed hosts；
- package-manager 和 MCP egress 设置；
- scope、metadata；
- archive/delete 对已有 Session 的影响。

不支持的配置必须返回明确的兼容错误，不能静默降级为不安全配置。

### 4.3 Sessions

研究：

```text
client.beta.sessions.create
client.beta.sessions.retrieve
client.beta.sessions.update
client.beta.sessions.list
client.beta.sessions.delete
client.beta.sessions.archive
```

主要 route root：

```text
/v1/sessions
/v1/sessions/{session_id}
/v1/sessions/{session_id}/archive
```

重点行为：

- 创建 Session 时解析 Agent 的具体版本；
- Session 创建后是否先处于 idle/pending；
- `agent` 接受字符串还是带 version 的对象；
- environment、resources、vault IDs、title、metadata；
- Session update 能修改哪些字段；
- status、stop reason、usage、stats；
- archive、delete、terminated 的区别；
- 同一 Session 是否允许并发发送用户事件；
- session-level system override 与 Agent version 的关系。

### 4.4 Session events：项目最重要的接口

研究：

```text
client.beta.sessions.events.list
client.beta.sessions.events.send
client.beta.sessions.events.stream
```

主要 route root：

```text
/v1/sessions/{session_id}/events
/v1/sessions/{session_id}/events/stream
```

必须逐个提取完整 event union，至少包括：

```text
user.message
user.interrupt
user.tool_confirmation
user.tool_result
user.custom_tool_result
user.define_outcome
system.message

agent.message
agent.thinking
agent.tool_use
agent.tool_result
agent.mcp_tool_use
agent.mcp_tool_result
agent.custom_tool_use
agent.thread_message_sent
agent.thread_message_received
agent.thread_context_compacted

session.status_running
session.status_idle
session.status_rescheduled
session.status_terminated
session.error
session.updated
session.deleted
session.thread_created

span.model_request_start
span.model_request_end
span.outcome_evaluation_start
span.outcome_evaluation_ongoing
span.outcome_evaluation_end
```

Codex 必须研究并测试：

- Event ID、created timestamp、session/thread ID；
- per-session total ordering；
- list 的排序方向和 cursor；
- `send` 是否支持 batch，以及 batch 的原子性；
- SSE 的 `event:`、`id:`、`data:` 形态；
- heartbeat/keepalive；
- reconnect 从哪里继续；
- slow consumer 和 backpressure；
- stream 建立前已存在事件是否 replay；
- terminal event 后连接如何关闭；
- tool confirmation/custom result 如何解除阻塞；
- interrupt 是立即取消还是在安全点生效。

不要把 OpenAI SDK stream event 原样暴露。必须经过稳定的 CMA event adapter。

### 4.5 Session resources

研究：

```text
client.beta.sessions.resources.retrieve
client.beta.sessions.resources.update
client.beta.sessions.resources.list
client.beta.sessions.resources.delete
client.beta.sessions.resources.add
```

主要 route root：

```text
/v1/sessions/{session_id}/resources
/v1/sessions/{session_id}/resources/{resource_id}
```

Resource union 至少研究：

- file；
- GitHub repository；
- memory store；
- outcome evaluation resource；
- branch/commit checkout；
- read-only/read-write 和 mount semantics。

P0 可以只完整实现 file resource，其余返回明确的 `not_supported`；但 schema 验证必须先研究清楚。

### 4.6 Files

研究：

```text
client.beta.files.upload
client.beta.files.list
client.beta.files.retrieve_metadata
client.beta.files.download
client.beta.files.delete
```

P0 推荐：

- metadata 存 Postgres；
- binary 存 Supabase Storage 或兼容 S3 的 object store；
- 以流方式上传和下载；
- 使用 workspace-scoped object key；
- 校验 size、content type、checksum；
- 删除操作和 Session mount 生命周期解耦。

---

## P1：核心体验补齐

### 4.7 Permission policies、custom tools 和 MCP

这不是独立 CRUD resource，但必须研究 Agent schema 和 event flow：

- `always_allow`；
- `always_ask`；
- toolset-level default；
- per-tool override；
- built-in agent toolset；
- MCP toolset；
- custom tools；
- `agent.tool_use` / `user.tool_confirmation`；
- `agent.custom_tool_use` / `user.custom_tool_result`。

### 4.8 Threads / multi-agent

研究：

```text
client.beta.sessions.threads.retrieve
client.beta.sessions.threads.list
client.beta.sessions.threads.archive
client.beta.sessions.threads.events.list
client.beta.sessions.threads.events.stream
```

主要 route root：

```text
/v1/sessions/{session_id}/threads
/v1/sessions/{session_id}/threads/{thread_id}
/v1/sessions/{session_id}/threads/{thread_id}/events
/v1/sessions/{session_id}/threads/{thread_id}/events/stream
```

实现时可使用 OpenAI Agents SDK 的 handoffs、`Agent.as_tool()` 或 nested agent runs，但必须额外建立 CMA thread/event abstraction。不要把一个 Python task 直接等同于一个 CMA thread。

### 4.9 Vaults 与 credentials

研究：

```text
client.beta.vaults.create
client.beta.vaults.retrieve
client.beta.vaults.update
client.beta.vaults.list
client.beta.vaults.delete
client.beta.vaults.archive

client.beta.vaults.credentials.create
client.beta.vaults.credentials.retrieve
client.beta.vaults.credentials.update
client.beta.vaults.credentials.list
client.beta.vaults.credentials.delete
client.beta.vaults.credentials.archive
client.beta.vaults.credentials.mcp_oauth_validate
```

Credential types 至少研究：

- environment variable；
- static bearer；
- MCP OAuth；
- token refresh；
- networking policy；
- credential validation status。

数据库不得存明文 secret。使用 KMS/Vault 或 application-level envelope encryption。API、event、trace 和 exception 中不得返回 secret。

### 4.10 Memory stores

研究：

```text
client.beta.memory_stores.create
client.beta.memory_stores.retrieve
client.beta.memory_stores.update
client.beta.memory_stores.list
client.beta.memory_stores.delete
client.beta.memory_stores.archive

client.beta.memory_stores.memories.create
client.beta.memory_stores.memories.retrieve
client.beta.memory_stores.memories.update
client.beta.memory_stores.memories.list
client.beta.memory_stores.memories.delete

client.beta.memory_stores.memory_versions.retrieve
client.beta.memory_stores.memory_versions.list
client.beta.memory_stores.memory_versions.redact
```

重点行为：

- memory path namespace；
- immutable versions；
- optimistic preconditions/checksum；
- conflict error；
- delete tombstone；
- redact 与 delete 的区别；
- read-only/read-write mount；
- 跨 Session 同步；
- Session actor attribution。

不要把 OpenAI Agents SDK 的 conversational Session 误当成 CMA memory store。它们是不同概念。

### 4.11 Skills

研究：

```text
client.beta.skills.create
client.beta.skills.retrieve
client.beta.skills.list
client.beta.skills.delete

client.beta.skills.versions.create
client.beta.skills.versions.retrieve
client.beta.skills.versions.list
client.beta.skills.versions.delete
client.beta.skills.versions.download
```

内部可以把 Skill version 解包为只读 workspace content，并通过 sandbox manifest/materialization 注入。

### 4.12 Webhooks

研究官方文档中的：

- webhook event type；
- payload envelope；
- signature、timestamp 和 replay protection；
- retry/backoff；
- ordering 和 duplicate delivery；
- Session、Thread、Vault、Credential 相关事件。

若官方 SDK 只暴露 payload helper、没有公开管理 CRUD，就不要虚构同名 CRUD API。可以额外提供 `open-managed-agents` 自有 webhook 管理 API，但必须放在单独 namespace，例如 `/oma/v1/...`。

---

## P2：高级运行能力

### 4.13 Self-hosted environment work protocol

研究：

```text
client.beta.environments.work.retrieve
client.beta.environments.work.update
client.beta.environments.work.list
client.beta.environments.work.ack
client.beta.environments.work.heartbeat
client.beta.environments.work.poll
client.beta.environments.work.stats
client.beta.environments.work.stop
```

这是 self-hosted worker control plane，不要与普通 Session job queue 混在同一个未经版本化的协议中。

### 4.14 Deployments 与 scheduled runs

研究：

```text
client.beta.deployments.create
client.beta.deployments.retrieve
client.beta.deployments.update
client.beta.deployments.list
client.beta.deployments.archive
client.beta.deployments.pause
client.beta.deployments.run
client.beta.deployments.unpause

client.beta.deployment_runs.retrieve
client.beta.deployment_runs.list
```

Deployment 是 Agent、Environment、resources、vaults、initial events 和 schedule 的绑定。Scheduler 只负责生成 run/job；实际 agent loop 必须仍由 durable worker 执行。

### 4.15 User profiles

研究：

```text
client.beta.user_profiles.create
client.beta.user_profiles.retrieve
client.beta.user_profiles.update
client.beta.user_profiles.list
client.beta.user_profiles.create_enrollment_url
```

除非产品明确需要 end-user OAuth enrollment，否则放到最后。

### 4.16 Outcomes / evaluation

通过 `user.define_outcome` 和 span events 研究：

- text rubric；
- file rubric；
- evaluation lifecycle；
- ongoing/end event；
- evaluation resource；
- usage 和 error semantics。

OpenAI Agents SDK 没有一对一的 CMA outcome runtime，可实现为独立 evaluator worker。

---

## 5. 外部协议要求

### 5.1 Headers

为了让官方 Anthropic SDK 可以连接本服务，Codex 必须研究并兼容：

```text
x-api-key
Authorization: Bearer ...
anthropic-version
anthropic-beta: managed-agents-2026-04-01
content-type
request-id / idempotency-related headers
```

至少接受 CMA beta header。可以额外返回：

```text
open-managed-agents-version: ...
```

但不得要求兼容客户端必须发送自有 header。

### 5.2 Beta query

官方生成 SDK 的 Managed Agents route 当前会附带 `?beta=true`。本服务需要支持准确形式，同时最好宽容接受省略该 query 的请求；宽容行为必须写进自有文档，不能改变规范化响应。

### 5.3 Authentication and tenancy

- 每一条业务记录都带 `workspace_id`；
- API Key 映射到 workspace；
- 永远不要相信客户端传入的 workspace ID；
- 所有查询包含 workspace predicate；
- Supabase 开启 RLS 作为 defense in depth；
- worker 使用独立受限 DB role；
- service-role key 不进入客户端或 sandbox。

### 5.4 Errors

建立统一错误 adapter：

```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "message": "..."
  },
  "request_id": "req_..."
}
```

具体 error type、HTTP status、字段路径格式必须由 Phase 0 研究确定。不要直接返回 FastAPI 默认 422 body。

### 5.5 Pagination

不要自创 offset pagination。精确研究并复制：

- query 参数名；
- cursor 方向；
- response envelope；
- `has_more`；
- stable ordering；
- archived filtering；
- maximum/default limit。

### 5.6 SSE

SSE 必须以数据库 append-only event log 为 source of truth。`LISTEN/NOTIFY`、Supabase Realtime 或 Redis 只能作为唤醒提示，不能作为唯一事件存储。

推荐算法：

1. 客户端给出 cursor/last event position；
2. 从 Postgres 查询并 replay；
3. 订阅通知；
4. 每次收到通知后再次按 sequence 查询数据库；
5. 定期 keepalive；
6. reconnect 后重复上述过程。

---

## 6. OpenAI Agents SDK 映射

建立 adapter，不要让外部 API model 直接依赖 SDK 内部 class。

| CMA 概念 | OpenAI Agents SDK / 自建组件 |
|---|---|
| Agent | `Agent` 或 `SandboxAgent` 的持久化 definition |
| Agent version | 自建 immutable `agent_versions` |
| Session | 自建 runtime aggregate；不是 SDK Session 的同义词 |
| Conversation history | SDK Session / SQLAlchemySession 或自建 adapter |
| Agent run | `Runner.run_streamed()` |
| Pause/resume | `RunState` serialization |
| Approval | SDK HITL interruptions + persisted pending action |
| Sandbox | `SandboxAgent`、`Manifest`、`SandboxRunConfig`、SandboxClient |
| MCP | OpenAI Agents SDK MCP adapter |
| Custom tool | function tool + external continuation protocol |
| Multi-agent | handoff / `Agent.as_tool()` + 自建 thread/event layer |
| Span events | tracing processor/hooks -> CMA span adapter |
| Files/resources | object storage + sandbox materializer |
| Memory store | 自建 versioned file store + sandbox mount |
| Deployments | scheduler + durable jobs |

### 重要限制

`agent.thinking` 不得通过伪造或泄露隐藏 chain-of-thought 实现。只允许：

- 转发模型 API 明确返回、允许展示的 reasoning summary；或
- 不发送该事件；或
- 发送明确标注为运行状态而非推理内容的自有事件，但不能冒充 CMA `agent.thinking` 内容。

---

## 7. 推荐系统架构

```text
┌──────────────────────────────────────────────┐
│ FastAPI compatibility API                    │
│ auth / validation / errors / pagination / SSE│
└──────────────────────┬───────────────────────┘
                       │ transaction
┌──────────────────────▼───────────────────────┐
│ PostgreSQL / Supabase                        │
│ definitions / versions / sessions / events  │
│ checkpoints / pending actions / jobs / leases│
└──────────────────────┬───────────────────────┘
                       │ claim with fencing token
┌──────────────────────▼───────────────────────┐
│ Durable worker                               │
│ restore -> Runner.run_streamed -> translate  │
└───────────────┬───────────────────┬──────────┘
                │                   │
     ┌──────────▼─────────┐  ┌──────▼──────────┐
     │ Sandbox provider   │  │ MCP / tools     │
     │ Docker / hosted    │  │ credential proxy│
     └──────────┬─────────┘  └─────────────────┘
                │
     ┌──────────▼─────────┐
     │ Object storage     │
     │ files / snapshots  │
     └────────────────────┘
```

### 进程拆分

```text
oma-api        FastAPI、CRUD、event send/list/stream
oma-worker     OpenAI Agent execution、tooling、checkpoint
oma-scheduler  deployment schedules、retry timers
oma-migrate    Alembic migrations
```

不要使用 FastAPI `BackgroundTasks` 承担 durable agent run。

---

## 8. Postgres / Supabase 数据模型

最小表集合：

```text
workspaces
api_keys

agents
agent_versions

environments

sessions
session_runs
session_events
session_checkpoints
session_pending_actions
session_resources
session_threads

files

vaults
credentials

memory_stores
memories
memory_versions

skills
skill_versions

deployments
deployment_runs

jobs
job_attempts
session_leases
idempotency_keys

webhook_subscriptions        # 自有管理面时才需要
webhook_deliveries
```

### `session_events` 建议字段

```text
id                  text primary key
workspace_id        uuid not null
session_id          text not null
thread_id           text null
sequence            bigint not null
run_id              text null
type                 text not null
direction            text not null
payload               jsonb not null
created_at            timestamptz not null
trace_id              text null
```

约束：

```text
unique(session_id, sequence)
index(workspace_id, session_id, sequence)
index(workspace_id, created_at)
```

Event 必须 append-only。需要更正时追加新的 correction/status event，不原地修改历史事件。

### Checkpoint

至少保存：

```text
run_state_json
sandbox_session_state_json
sandbox_snapshot_ref
agent_id
agent_version
openai_agents_sdk_version
runtime_image_digest
event_sequence_at_checkpoint
fencing_token
```

禁止使用 Python pickle 作为长期格式。状态必须是版本化 JSON；敏感部分使用 envelope encryption。

### Job queue

优先选择之一：

1. Supabase Queues / `pgmq`；
2. 自建 `jobs` 表 + `FOR UPDATE SKIP LOCKED`；
3. 后期接 Temporal/DBOS/Restate，但 domain contract 不应依赖其私有类型。

无论选择什么，保证：

- job 执行至少一次；
- event append 对客户端表现为幂等；
- Session 同一时刻只有一个有效 executor；
- lease 带 fencing token，过期 worker 不能继续写事件。

---

## 9. Session 执行流程

### 9.1 发送用户事件

```text
POST session events
  -> validate union schema
  -> check idempotency key
  -> lock session row
  -> append user event(s)
  -> enqueue/wake session job in same transaction
  -> commit
  -> return accepted event envelope
```

### 9.2 Worker

```text
claim job
  -> acquire session lease + fencing token
  -> load pinned agent version
  -> load environment
  -> restore RunState/checkpoint
  -> restore/create sandbox
  -> translate pending user events to runner input/actions
  -> append session.status_running
  -> Runner.run_streamed(...)
  -> translate SDK events to CMA events
  -> checkpoint at every durable boundary
```

Durable boundary 至少包括：

- 模型 response 完成；
- tool call 创建；
- tool result 完成；
- approval interruption；
- custom tool interruption；
- handoff/nested agent start/end；
- context compaction；
- end turn；
- retry/reschedule；
- cancellation。

### 9.3 结束状态

```text
normal end turn        -> session.status_idle
requires approval      -> session.status_idle(stop_reason=requires_action)
custom tool required   -> session.status_idle(stop_reason=requires_action)
transient failure      -> session.status_rescheduled + delayed job
unrecoverable failure  -> session.error + session.status_terminated
archive/delete         -> 按上游语义停止或清理
```

具体 stop reason schema 必须由 Phase 0 提取。

---

## 10. Event adapter 设计

建立内部 canonical event，再映射到外部 CMA event：

```python
class RuntimeEvent(BaseModel):
    kind: str
    run_id: str
    thread_id: str | None
    payload: dict
    occurred_at: datetime
```

转换层：

```text
OpenAI raw stream event
        -> OpenAI semantic runtime event
        -> domain RuntimeEvent
        -> CMA-compatible SessionEvent
        -> append Postgres
        -> SSE/list API
```

禁止：

- 把 SDK Python object pickle 后放进 event；
- 把 SDK event class 名当成公开 event type；
- 在 SSE handler 内直接运行 Agent；
- 只向在线客户端发送、却不落库；
- 因 worker retry 而重复暴露相同 tool result。

---

## 11. Model compatibility

外部 `model.id` 应视为 opaque identifier，通过数据库映射：

```text
external model id -> provider -> internal model id -> model settings
```

示例：

```yaml
model_aliases:
  openai/gpt-5.4:
    provider: openai
    model: gpt-5.4
```

可以允许 OpenAI model ID 直接出现于 CMA-compatible `model` 字段。若提供 Claude 名称到 OpenAI 模型的 alias，必须在文档中明确它只是配置别名，不表示行为等价。

不要在 Pydantic schema 中把当前模型列表写死为永久 enum，除非上游协议确实如此。

---

## 12. Sandbox 抽象

定义自有 provider protocol：

```python
class SandboxProvider(Protocol):
    async def create(self, spec: EnvironmentSpec) -> SandboxHandle: ...
    async def resume(self, state: dict) -> SandboxHandle: ...
    async def snapshot(self, handle: SandboxHandle) -> SnapshotRef: ...
    async def stop(self, handle: SandboxHandle) -> None: ...
    async def delete(self, handle: SandboxHandle) -> None: ...
```

P0：

- 本地开发：Docker；
- CI：Docker 或 fake sandbox；
- 生产：hosted sandbox 或严格隔离的容器平台。

有限网络策略如果不能可靠执行，就拒绝创建对应 environment，不能仅在 prompt 中告诉 Agent “不要联网”。

Secret 不应作为普通环境变量永久写入 workspace。优先通过短期 credential proxy、tool gateway 或只在进程内注入。

---

## 13. 推荐代码结构

```text
src/open_managed_agents/
  main.py
  config.py

  api/
    dependencies.py
    errors.py
    pagination.py
    sse.py
    routes/
      agents.py
      environments.py
      sessions.py
      session_events.py
      session_resources.py
      files.py
      threads.py
      vaults.py
      memory_stores.py
      skills.py
      deployments.py

  compat/cma/
    headers.py
    ids.py
    models/
    event_adapter.py
    error_adapter.py
    contract.py

  domain/
    agents.py
    sessions.py
    events.py
    environments.py
    state_machines.py

  runtime/openai/
    agent_builder.py
    runner.py
    stream_adapter.py
    run_state_codec.py
    tracing_processor.py
    tool_adapter.py
    mcp_adapter.py

  sandboxes/
    base.py
    docker.py
    hosted.py

  persistence/
    models.py
    repositories/
    unit_of_work.py
    migrations/

  workers/
    session_worker.py
    scheduler.py
    retry_policy.py

  security/
    auth.py
    tenancy.py
    encryption.py
    credential_proxy.py
```

不要在 API、domain、database 三层各复制一套容易漂移的 CMA schema。兼容 schema 要有单一事实来源。

---

## 14. Codex 的实施阶段

### PR 0：Research only

只提交：

- upstream manifest；
- API inventory；
- event/error/pagination/state-machine catalog；
- compatibility matrix；
- contract test skeleton。

不要实现 Runner。

### PR 1：Service skeleton

- FastAPI；
- config；
- auth/workspace；
- error envelope；
- request ID；
- Postgres/Alembic；
- health/readiness；
- OpenAPI；
- CI。

### PR 2：Agents、versions、environments、files

- 完成 P0 CRUD；
- immutable versions；
- object storage；
- official Anthropic SDK contract tests。

### PR 3：Sessions、events、SSE，先使用 fake runtime

- Session state machine；
- append-only event log；
- send/list/stream；
- cursor replay；
- leases/jobs；
- fake deterministic runner。

先证明协议和 durability 正确，再接真实模型。

### PR 4：OpenAI Agents SDK runtime

- Agent builder；
- Runner streaming；
- event adapter；
- SQLAlchemy conversation session；
- RunState checkpoint；
- retry/cancellation；
- tracing。

### PR 5：Sandbox、tools、approval、custom tool

- Docker/hosted adapter；
- filesystem/shell；
- HITL；
- external custom tool continuation；
- restart recovery。

### PR 6：MCP、vaults、resources、memory、skills

逐个 capability 增加，保持 compatibility matrix 更新。

### PR 7：Multi-agent、deployments、self-hosted work

最后实现高级 control plane。

---

## 15. P0 验收条件

P0 完成时必须证明：

1. 官方 Anthropic Python SDK 可通过自定义 `base_url` 调用本服务的 P0 methods；
2. request/response 可被官方 SDK 类型正常反序列化；
3. Agent update 创建新版本，旧版本不可变；
4. 已创建 Session 固定具体 Agent version；
5. `events.send` 后可通过 list 和 SSE 按同一顺序看到事件；
6. SSE 断线重连不丢事件、不重复展示已确认 cursor 之前的事件；
7. worker 在模型调用后、tool call 后、approval 时被杀掉，重启可恢复；
8. duplicate HTTP request 不产生重复用户事件或重复工具副作用；
9. approval/custom tool pending action 可跨进程重启；
10. 两个 worker 竞争同一 Session 时只有持有最新 fencing token 的 worker 能写；
11. workspace A 无法读取 workspace B 的任何资源；
12. secret 不出现在日志、trace、event、database plaintext；
13. unsupported capability 返回稳定、文档化的错误，而不是静默忽略；
14. 所有 compatibility claims 都在 `docs/compatibility-matrix.md` 中标成 complete/partial/not-supported。

---

## 16. Codex 不应做的事情

- 不要从 UI 截图猜 API；
- 不要只读教程而忽略官方 SDK 生成代码；
- 不要一开始把全部功能塞进一个 FastAPI 进程；
- 不要用内存 queue 作为生产 job queue；
- 不要把 SSE socket 当作 Session 状态；
- 不要把 Supabase Realtime 当作 durable event log；
- 不要让多个 worker 无 lease 地执行同一 Session；
- 不要把 Agent definition 更新成 mutable row；
- 不要将 `RunState` 仅保存在 worker 内存；
- 不要暴露 OpenAI SDK 内部类型；
- 不要伪造模型 thinking/chain-of-thought；
- 不要在 sandbox 中放 Supabase service key、OpenAI admin key 或数据库凭据；
- 不要为了“兼容”而复制 Anthropic 商标、品牌或声称官方关系。

---

## 17. 可以直接发给 Codex 的第一条指令

```text
Read open-managed-agents-codex-high-level-guide.md in full.

Work only on Phase 0 / PR 0. Do not implement the web service or OpenAI runner yet.

1. Pin the current official anthropic Python SDK and openai-agents Python SDK versions and commits.
2. From anthropic-sdk-python/api.md, src/anthropic/resources/beta, and src/anthropic/types/beta, extract every CMA-related public operation listed in this guide.
3. Record exact method, path, query, required headers, request model, response model, pagination, errors, archive/delete behavior, and emitted events.
4. Build compat/cma-api-inventory.yaml, compat/cma-event-catalog.yaml, compat/cma-errors.yaml, compat/cma-pagination.yaml, compat/cma-state-machines.yaml, and docs/compatibility-matrix.md.
5. Create contract-test scaffolding that instantiates the official Anthropic Python client with a configurable local base_url.
6. Mark every unverified detail as unknown; do not infer silently.
7. End with a concise report listing ambiguities and the minimum P0 operation set.

Do not copy Anthropic implementation code. Public method signatures, schemas, paths, and observable protocol behavior may be documented for compatibility.
```

---

## 18. 官方研究入口

Anthropic：

```text
https://platform.claude.com/docs/en/managed-agents/overview
https://platform.claude.com/docs/en/managed-agents/agent-setup
https://platform.claude.com/docs/en/managed-agents/environments
https://platform.claude.com/docs/en/managed-agents/sessions
https://platform.claude.com/docs/en/managed-agents/session-operations
https://platform.claude.com/docs/en/managed-agents/events-and-streaming
https://platform.claude.com/docs/en/managed-agents/tools
https://platform.claude.com/docs/en/managed-agents/permission-policies
https://platform.claude.com/docs/en/managed-agents/mcp-connector
https://platform.claude.com/docs/en/managed-agents/memory
https://platform.claude.com/docs/en/managed-agents/multi-agent
https://platform.claude.com/docs/en/managed-agents/scheduled-deployments
https://platform.claude.com/docs/en/managed-agents/reference
https://github.com/anthropics/anthropic-sdk-python
```

OpenAI Agents SDK：

```text
https://openai.github.io/openai-agents-python/
https://openai.github.io/openai-agents-python/running_agents/
https://openai.github.io/openai-agents-python/streaming/
https://openai.github.io/openai-agents-python/human_in_the_loop/
https://openai.github.io/openai-agents-python/ref/run_state/
https://openai.github.io/openai-agents-python/sessions/
https://openai.github.io/openai-agents-python/sessions/sqlalchemy_session/
https://openai.github.io/openai-agents-python/mcp/
https://openai.github.io/openai-agents-python/sandbox/guide/
https://openai.github.io/openai-agents-python/sandbox/clients/
```

Supabase：

```text
https://supabase.com/docs/guides/database/overview
https://supabase.com/docs/guides/database/postgres/row-level-security
https://supabase.com/docs/guides/queues
```
