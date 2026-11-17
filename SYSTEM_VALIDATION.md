# 完整系统修复与验证 · 2026-11-17

工作分支 `feat/event-memory-v1`，在第二阶段本地提交 `0850815` 上继续。未推送或部署。

## 已修复

- 首页失败的根因是只启动了独立事件 API。新增根入口 `app:app` 和 `scripts/run-local.py`，同一后端提供话题、文章、聊天和事件记忆，前端代理统一指向它。
- 启动器检查端口和就绪状态；退出时回收自身进程。依赖移到项目目录外的持久缓存，减少 iCloud 卸载依赖造成的失败。存储路径统一按仓库根解析，支持显式指定数据目录与配置文件。
- 本地启动默认关闭外部调用与调度。未启用／模型未配置时直接返回可读错误，不创建等待任务；页面显示本地模式。
- 前端只自动重试 GET／HEAD，避免生成、采集和聊天任务被重复提交。耗尽读取重试后抛出包含服务端原因的错误，保留首页失败与重试界面；写入错误直接进入提示解析。
- 聊天开始期间阻止重复发送；失败后解除加载；快速完成不再留下加载状态；迟到响应不覆盖另一话题的上下文。
- 向量候选重新从 SQLite 读取正文、话题和状态；当前补检不接受被替代、失效、缺失或跨话题记录。
- 稳定 fact／structural 不因报道年龄自动失效，终止状态不会因为有限扫描缺少替代项而复活。
- 新快照捕获关联插入时的事件和断言正文，后续源记录修改或删除不会改变快照。旧快照没有捕获内容的部分标为不可还原，未用当前记录伪造历史。
- Compose／Render 源码构建入口包含新事件模块，Compose 配置文件可缺省，不要求复制凭据。

## 验证结果

| 验证 | 结果与范围 |
| --- | --- |
| 完整 Python 测试 | **213 passed**；包括原有 179 项及事件记忆、旧风险回归与完整应用检查。3 个既有 pytest fixture 弃用警告。 |
| 完整应用联动 | **39 项通过**；真实 ASGI 生命周期、SQLite、Chroma 写入／查询／删除／重新打开；话题／关键词／RSS／资料、聊天 SSE 与任务持久化、重启恢复、话题隔离、未配置服务边界。该组包含在上面 213 项中的一个集成测试内。 |
| 前端专项行为 | **18 项通过**：8 项话题／聊天状态、5 项事件页面迟到请求／日期／历史只读、5 项 API 错误与重试行为。网络使用合成响应。 |
| 前端接口与状态契约 | topics、archive、claims、evidence、snapshots、deltas、lifecycle、两种 synthesis 等 9 个接口契约通过；按钮状态契约与文案检查通过。经前端真实代理请求完整后端。 |
| 正式构建 | `npm run build -- --webpack` 通过，包含全仓 TypeScript 检查及五个页面路由。 |
| 启动与退出 | 独立端口实际启动两端，读取运行状态后发送 SIGTERM，两个端口均释放，未留下孤立服务。 |
| 浏览器实际操作 | 首页创建合成话题并进入工作区；聊天请求得到具体本地模式提示，输入保留；事件当前／历史状态、证据、归档隐藏、召回与恢复通过。最终返回首页，无 Topics unavailable。 |
| 配置与依赖 | `docker compose config --quiet`、`pip check`、`git diff --check` 通过。 |

原仓库 `/Users/no15438/Desktop/Domain_Monitor` 的 README 与 Chroma SQLite 已按此前 SHA-256 清单核实，内容未变。没有导入原仓库数据、复制凭据或上传资料。浏览器创建的“系统验证（合成数据）”话题与 `synthetic` 事件用于本地验收，保留方便复查；传闻事件已恢复至原摘要层级。

## 边界

完整应用联动测试替换外部响应生成器，并阻断出站连接；Chroma 使用确定性的测试嵌入，不下载模型。因此没有验证真实模型提供商的在线可用性、付费新闻采集或实际嵌入模型质量，也没有产生模型调用。现有生成流水线测试同样使用模拟模型。当前 Docker 引擎未运行，仅校验了容器配置，未构建镜像、推送或部署。

旧聊天与采集仍使用原知识库；新事件库的双时间字段投影尚未接管整个旧流水线。旧快照已经缺失的过去内容无法补造。以上不影响当前本地功能的已验证范围。

## 复跑

在仓库根目录：

```bash
python3 scripts/run-local.py --install
# 另一个终端：
python3 scripts/run-local.py --check
PYTHONPATH="$PWD/backend:$PWD" ~/.cache/domain-monitor/venv/bin/python -m pytest backend/tests tests -q
~/.cache/domain-monitor/venv/bin/python scripts/validate-system.py
node scripts/validate-topic-isolation.cjs "$PWD"
node scripts/validate-api-errors.cjs
```

事件页面专项测试还需在指定依赖目录额外安装 `react-test-renderer@19.2.4`，详见 `EVENT_MEMORY.md`。构建前停止本工作目录的开发服务器：

```bash
cd frontend
INTERNAL_API_BASE=http://127.0.0.1:8000 npm run build -- --webpack
```

合成检查详情：`artifacts/system-verification.json`；截图：`artifacts/system-memory-current.jpg`、`artifacts/system-memory-history.jpg`、`artifacts/system-chat-local-mode.jpg`。
