# Domain Monitor 事件本体与分层记忆

工作分支：`feat/event-memory-v1`。基线：前端修复提交 `2529f3f`。

这是可运行的离线纵向切片：事件身份 → 证据版本 → 字段断言 → 双时间查询 → 历史回溯 → 可恢复记忆策略 → Markdown 索引。核心与原始离线界面使用 Python 3.10+ 标准库和 SQLite，零依赖、无模型调用。默认使用独立 `data/eventkb.sqlite3`，不加载 `.env`，不读取旧数据库，不启动采集器或调度器。第二阶段的 FastAPI 适配器需要可选依赖，见下文。

旧 FastAPI / Next.js 系统仍保留在 `backend/` 和 `frontend/`。第二阶段已加入 Next.js `/event-memory` 页面、主页入口和可选的旧 FastAPI 路由挂载。新查询入口只返回数据库投影；旧 `/api/chat` 尚未迁移，旧聊天检索中的风险仍然存在。尚未做生产迁移、真实新闻抽取和身份自动合并。

## 第二阶段：原前端中的事件记忆

以下命令均在本 worktree 操作。初次安装适配器依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-event-memory.txt
```

终端一，在仓库根目录启动合成数据 API：

```bash
.venv/bin/python -m eventkb --db data/phase2-preview.sqlite3 demo
.venv/bin/python -m eventkb --db data/phase2-preview.sqlite3 api --port 8770
```

终端二，在 `frontend/` 安装前端依赖后启动页面：

```bash
npm ci
EVENT_MEMORY_API_BASE=http://127.0.0.1:8770 npm run dev -- --webpack --hostname 127.0.0.1 --port 3870
```

打开 `http://127.0.0.1:3870/event-memory`。原主页右上角也有“事件记忆”入口。独立 API 不提供旧话题主页、旧聊天或采集功能；离线预览直接访问事件记忆页面。重播 demo 不会新增事实，但会追加演示策略记录；不应对真实数据运行 demo。

页面支持话题隔离、字段值搜索、生效／获知时间、冲突双方与引用、演化原文、重要性、置顶、归档及恢复。历史视图的记忆策略表单只读；策略调整始终发生在现在。原始日期框在当前浏览器中需要同时处理 input/change，已通过实际日期查询验证。切换条件时立即隐藏旧结果，并取消旧请求，防止迟到响应覆盖新视图。策略保存期间切换话题后，旧保存仍可完成，但完成回调不会恢复旧视图。输入的日期使用浏览器本机时区；结果明确显示悉尼时间。

`GET /api/event-memory/query?topic=synthetic` 是供页面或后续回答组件使用的结构化查询边界。话题必填；可带 `q`、`event_id`、`valid_at`、`known_at`、`include_archived`、`limit`（1–100）。结果只含对应时间的字段、明确标记的冲突候选、有效断言的来源元数据与版本，不包含旧摘要、历史断言、证据正文、聊天历史或向量正文。来源正文只在独立 history 请求中用于追溯。字段一致不等于外部事实核验；当前没有模型生成回答，搜索是投影字段的文本匹配。

其余适配器路由均在 `/api/event-memory` 下：`GET /health`、`GET /topics`、`POST /events`、`POST /evidence`、`GET /events/{id}/state`、`GET /events/{id}/history`、`POST /events/{id}/assertions` 和 `POST /events/{id}/memory`。事件详情、历史和写入均校验话题；请求不能回填获知时间。响应禁止缓存。新 API 继续仅面向本机开发，没有生产身份认证。

若需要在旧 FastAPI 服务中挂载相同路由，在根目录设置 `PYTHONPATH="$PWD:$PWD/backend"`，并设置 `EVENT_MEMORY_ENABLED=true`；`EVENT_MEMORY_DATABASE_PATH` 默认为相对仓库根的 `data/eventkb.sqlite3`，也接受绝对路径。默认关闭，不更改旧接口。旧服务原有启动流程仍会开启调度器，**离线验证使用独立 api 命令**。现有 backend 容器构建上下文不含根目录 eventkb 包，此可选挂载目前仅支持本机；本次未更改或验证部署。

验证命令：

```bash
.venv/bin/python -m unittest discover -s tests -v
node frontend/node_modules/typescript/bin/tsc --project frontend/tsconfig.json --noEmit --incremental false
cd frontend
EVENT_MEMORY_API_BASE=http://127.0.0.1:8770 npm run build -- --webpack
```

测试使用真实 FastAPI TestClient 和合成 SQLite。旧 main 的挂载条件使用真实源码块隔离验证，未启动旧依赖、调度器或完整旧服务。原始离线测试依然可只用标准库运行，可选 API 测试在依赖缺失时标为跳过。当前本机前端依赖链接到 `/tmp/domain-monitor-event-memory-node/node_modules` 的独立安装；旧仓库依赖读取曾挂起，不再复用它，临时目录清理后需重新安装。

另有 `scripts/validate-event-memory-ui.cjs` 定向 React 检查，模拟不理会取消信号的迟到查询，以及跨话题的迟到保存完成；也验证日期输入、历史只读和不安全来源链接。该脚本运行真实页面组件，只模拟网络和框架外壳；不替代浏览器。需要在传入依赖目录中额外安装与 React 匹配的 `react-test-renderer@19.2.4`（可选测试工具，未加入产品依赖；上游会打印弃用提示）。运行 `node scripts/validate-event-memory-ui.cjs /tmp/domain-monitor-event-memory-node/node_modules`。浏览器实际操作和五项定向检查均已通过。

## 启动

在本 worktree 根目录运行：

```bash
python3 -m eventkb demo
python3 -m eventkb memory
python3 -m eventkb serve --port 8769
```

浏览 `http://127.0.0.1:8769`。界面支持按有效时间与获知截止时间查询、查看完整来源和演化、调整重要性、归档和恢复。演示仅有 `example.invalid` 的合成收购案和相反传闻。页面不请求这些来源网址。

```bash
python3 -m eventkb show acquisition-demo
python3 -m eventkb show acquisition-demo --valid-at 2026-01-15T00:00:00Z
python3 -m unittest discover -s tests -v
```

首次运行 demo 的获知时间是真实本机时间，因此 `known_at` 早于 demo 写入时刻会返回“当时尚未知晓”。演示的有效时间在 2026 年 1–2 月。测试使用受控时钟，验证“当时所知”与“事后重建”的差别。所有时间须有时区，规范化为 UTC；区间使用 `[valid_from, valid_to)`，空 `valid_to` 表示未声明终止时间。

前端两项修复的定向行为检查（可以只读复用原仓库已安装的 TypeScript，不复制 node_modules）：

```bash
node scripts/validate-topic-isolation.cjs "$PWD" /Users/no15438/Desktop/Domain_Monitor/frontend/node_modules/typescript
```

这使用隔离的 hooks/store harness 验证真实源码的行为。第一阶段全仓 TypeScript 检查曾因旧依赖读取挂起而停止；第二阶段改用锁文件安装的独立依赖后，全仓检查已通过。第二阶段新页面另做了浏览器实际操作验证，见 `artifacts/phase2-verification.json`。

## 数据契约

- `events`：稳定 ID、topic 内唯一 identity_key、不可变显示标签与事件种类。显示标签用于识别；可变化的标题应作为 `headline` 字段断言。不按标题相似度自动合并事件。
- `assertions`：事件 ID、字段、JSON 值、有效起止时间、数据库获知时间、证据 ID、置信度、消息幂等键、关系、目标断言和审阅理由。参与方用带角色和 entity_id 的 JSON 字段；金额、地点、状态等也各自版本化。
- `evidence`：来源键、版本、发布方、URL、发布时间、原文、原文 SHA-256、获知时间。同一来源同一版本不可变；原公告发生修改时必须追加新 revision。来源版本本身不会自动改写事实，必须追加有指向的字段更正。
- `memory_policy`：重要性、置顶、active/summary/archived 层级、理由、获知时间。追加式审计，与事实真假分离。

所有权威表通过 SQL trigger 禁止 UPDATE/DELETE，写入使用事务和外键。获知时间由服务端生成，HTTP 调用者不能回填它。发生本机时钟倒退时写入拒绝，不偷偷重写历史。`Store(clock=...)` 仅用于离线重放测试。

## 状态演化规则

1. **observation**：独立断言，必须有来源和有效时间。重复消息键、相同内容返回原 ID；同键不同内容拒绝。抓取重播不刷新获知时间。
2. **transition**：世界状态发生变化。必须显式目标指向同事件同字段的旧断言，时间向前推进，并提供 `reviewed: true` 与理由。旧断言在转换时刻起被关闭；新状态的有限有效区间结束后，旧状态不会自动复活，届时字段为未知。
3. **correction**：认识修正。保留旧断言，并追加新断言指向它。第一阶段要求起止区间完全一致，避免隐式裁切其他历史区间。金额更正不会覆盖参与方或状态。复杂区间重述须先在上游拆分，当前 API 会拒绝不等区间。
4. 未经明确替代的相反值同时有效时，返回 `status: conflict`、`value: null`、双方断言与证据。不按新旧、来源数量或置信度强行选胜者。`confirmed` 仅表示本投影中的活动断言值一致，不代表事实经外部核验。置信度保留来源判断，未做概率校准。
5. 迟到旧报道若有已结束的有效区间，可补充历史而不改变当前。若只知道旧发布时间、无法判断报道描述的有效区间，不猜测其已经失效：保留未解决冲突，等待审阅。发布时间与获知时间都不能代替有效时间。
6. 更正已关闭的历史状态只改变历史认识，不复活当前已替代状态；更正一个转换的值仍保留该转换对前序状态的关闭作用。

`GET state` 根据指定的 known_at 先筛选“截至当时已知的断言”，再按 valid_at 进行投影。`GET history` 返回追加式完整记录与不可变证据版本。没有通过修改现存行来冒充双时间历史。

## 检索与选择性遗忘

新检索只对数据库重建的字段值匹配，不搜索历史正文或信任旧向量缓存。事件有冲突时不把任一候选当作已确定值送入当前检索；调用者仍可按事件标签定位并查看冲突。查询指定有效时间即得到对应的历史投影，不复用“当前摘要”。

稳定事实不会因新闻变旧而变假。只对注意力做 90 天半衰期降权：`importance * 2^(-policy_age_days/90)`；summary 再乘 0.5，置顶权重为 1。年龄从策略时间计算，解释写入每个搜索结果。此分数是可解释原型策略，尚未验证其业务最优性。归档事件默认不在列表中；按 ID 仍可直接查询，`include_archived=true` 可召回并恢复 active。事实、原始证据和重要转折都不被删掉。

`python3 -m eventkb memory` 生成：

```text
memory/MEMORY.md        # 最多 20 个工作记忆入口，字段值简述
memory/archive.md       # 归档与溢出入口
memory/events/<id>.md   # 当前投影、全部演化、证据版本和策略变更
```

Markdown 是可丢弃、可再生的工作索引，修改它不会修改 SQLite。策略或事实写入后须重新运行 memory 命令；本阶段没有后台自动刷新。根索引简洁，完整档案目前无长度预算，大数据量时应改为分页与分段档案。本设计参考本机可读 Markdown 的“范围—索引—证据—经验”分层方式，不复制个人记忆到项目，不声称复刻 ChatGPT 私有记忆实现。

## HTTP API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 离线模式、schema_version |
| POST | `/api/events` | 创建稳定事件身份 |
| POST | `/api/evidence` | 写入不可变来源版本 |
| POST | `/api/events/{id}/assertions` | 写入 observation / transition / correction |
| GET | `/api/events/{id}/state?valid_at=...&known_at=...` | 双时间投影 |
| GET | `/api/events/{id}/history?known_at=...` | 完整历史与证据 |
| GET | `/api/events?q=...&topic=...&include_archived=true` | 数据库投影检索，也接受双时间参数 |
| POST | `/api/events/{id}/memory` | 重要性、降权、归档、恢复及理由 |

这是本机开发用 HTTP 适配器，只绑定 127.0.0.1，拒绝跨来源写入和非本机 Host。没有对外认证或多用户权限，不能直接部署。写入 API 没有永久删除入口。

## 旧版审计与下一阶段

`tests/test_legacy_risks.py` 用 AST 隔离真实函数与最小合成 SQL，复现三个问题，不导入模型或向量客户端：

- `backend/chatbot.py::_run_vector_supplement` 非 archive 模式只排除 inactive/archived，会让 superseded/stale 条目进入补检。提示中的状态标签不能提供硬隔离；向量元数据也不是权威状态。
- `backend/claim_lifecycle.py::evaluate_claim_lifecycle` 对稳定 fact 与短期趋势使用相同老化逻辑，仅因支持报道变旧就设置 inactive；未在当前 500 条内找到替代项也可能错误改变先前状态。
- `backend/database.py::get_snapshot_claims` 通过 snapshot_claims JOIN 当前 claims 行；`upsert_claim` 可原位修改该行，历史快照因而漂移。events_v2 的 upsert 也会原位更新摘要和属性，不能独立还原完整过去。

下一阶段应在旧采集器之后加入“候选事件身份匹配 → 有效时间抽取 → 关系审阅”边界，迁移工具只读旧库、写新库并生成审计报告。未来迁移旧聊天时，回答应只使用新投影；向量索引仅返回候选 ID，再向 SQLite 复核有效状态与时间，禁止直接把向量正文送入当前上下文。还需要断言人工审阅 UI、字段级权限、实体别名合并、部分区间更正、撤回和大规模索引；这些均未完成。当前新页面的策略调整不等于断言审阅。

## 本地目录与项目登记

实际 worktree：`/Users/no15438/Documents/Codex/2026-11-17/task/Domain_Monitor_EventMemory`。

早期独立源码快照保留在同级 `Domain_Monitor_EventKB`，已停止开发，适用核心源码迁入本分支，见 `artifacts/migration.json`。没有把快照 legacy 副本叠加回仓库；README 使用修复基线提交的版本。

首阶段在远端聊天中的项目登记失败；2026-11-17 续做时，本机 `attach_worktree` 已成功，并从当前聊天附件列表读回核实实际目录。现在可通过当前聊天的 worktree 附件访问代码。侧边栏同名本地项目的根目录仍是 `/Users/no15438/Documents/ChatGPT/Domain Monitor`；本次没有移动代码、修改该项目根目录或复制另一套源码。没有修改 Codex 私有状态文件。
