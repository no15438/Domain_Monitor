# 分支盘点与管理建议

审计时间：2026-11-16 UTC。完整只读证据：`artifacts/branch-audit.json`。该快照在事件记忆第一阶段的本地提交前生成。

已执行的发布只有前端修复：`2529f3f023a0a411c3b749d462eb9e29f610a826` 普通快进推送到 `origin/feat/render-blueprint-deploy`。推送前远端为 `47b0949`，两者严格相差一个提交，修改文件严格为 `EventFeed.tsx` 与 `useStore.ts`。推送后通过 `ls-remote --heads` 读回目标 SHA。没有强推；没有推送事件重构分支。

原仓库仍位于 `/Users/no15438/Desktop/Domain_Monitor`，当前分支保持 `feat/render-blueprint-deploy`，其 README 未提交改动与未跟踪 data/ 都保留，哈希已核实未变。没有删除、重置或合并任何分支。

## 全部分支

“独有”表示相对指定基线的提交差集，并不自动代表工作可丢弃。

| 本地分支 | 上游 | 最近提交时间 | 相对 main | 相对修复基线 2529f3f | 建议 |
|---|---|---|---|---|---|
| `main` | `origin/main` | 2026-04-03 +11:00 | 同步，d7ac7ad | 落后 7，无独有提交 | 保留为集成基线 |
| `feat/render-blueprint-deploy` | `origin/feat/render-blueprint-deploy` | 2026-11-17 +11:00 | 领先 7、落后 0 | 同步 | 保留；包含尚未进 main 的有效工作 |
| `deploy` | 无 | 2026-04-04 +11:00 | 领先 6、落后 0 | 落后 1，无独有提交 | 重复本地指针，清理候选，暂不删除 |
| `feat/knowledge-lineage-refactor` | 无 | 2026-04-02 +11:00 | 落后 2，无独有提交，已被 main 包含 | 落后 9，无独有提交 | 已合并旧功能，清理候选，暂不删除 |
| `feat/topic-mobile-research-news-20260404` | 无 | 2026-04-04 +11:00 | 领先 3、落后 0 | 落后 4，无独有提交 | 已被部署分支包含，但尚未全部进 main；确认集成后再清理 |
| `feat/event-memory-v1` | 无 | 本次新建 | 从领先 main 7 的修复提交起步 | 基线 2529f3f，后续本地事件记忆工作 | 保留在独立 worktree，不发布 |

GitHub 实际远端 heads 只有两个：`main`（d7ac7ad）与 `feat/render-blueprint-deploy`（2529f3f）。`origin/HEAD` 是符号引用，不是第三个远端工作分支。未配置其他远端。

## 有价值的未集成内容

部署分支比 main 多出的 7 个提交（含本次修复）：

| 提交 | 内容 |
|---|---|
| 2529f3f | 切话题清理文章、选中内容与无话题时停止抓取 |
| 47b0949 | 聊天状态持久化与 Markdown 表格渲染修复 |
| b35561f | OpenAI 兼容模型路由修复 |
| 6cdbd3d | 移动话题工作区集成合并提交 |
| 9088d31 | 移动话题工作区体验 |
| f89e5d3 | Render 前端启动命令 |
| fb22929 | Render blueprint 部署配置 |

它们已经在远端部署分支，不应在没有审阅的情况下丢弃或自动整体合入 main。尤其部署配置与功能变更混在同一谱系，后续应先确认发布需求与集成测试，再决定合并或拆分。没有根据较旧日期直接判定分支无用。

## 建议规则与待决定项

1. main 作为后续集成基线；先审阅部署分支中的有效差异，再单独决定如何集成。这次不执行合并。
2. 当前事件记忆保存在 `feat/event-memory-v1` 的独立 worktree，避免 README 未提交内容跟着切分支。之后新增功能用短期 `feat/...` 分支，修复用 `fix/...`。
3. `deploy` 与已合并 lineage 分支是优先清理候选；移动话题分支等 main 集成策略确定后再决定。这次不删除本地或远端引用。
4. 是否保留永久部署分支、是否将历史部署差异合入 main、是否删除上述三个候选，需要后续决定，不在本次操作范围。
5. 保留原目录未提交 README 与运行数据，另行决定 README 的格式修复；不把它们混入本次修复或事件重构。

项目区登记仍未完成：Codex 的 create/attach_worktree 接口返回 `Cloud worktrees are unavailable.`；列出项目也未发现新 worktree。原生 Codex UI 被 Computer Use 安全策略禁止访问。实际 Git worktree 与分支已建立，用户可在 Codex 新增项目入口选择本目录，未擅自编辑 Codex 私有注册文件。
