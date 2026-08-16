# Scholens

[English](./README.md)

Scholens 是一个尚未正式发布的研究工作空间，用于围绕学术论文建立可持续、可追溯的阅读与分析流程。当前产品前端位于 `web/`，由 `server/` 中的 FastAPI 服务和 `jobs/` 中的异步任务提供支持。

## 当前已实现

- 在主页、项目和单篇论文中共享同一个、由上下文驱动的对话体验。
- 支持 PDF、DOI、arXiv、直接 URL 和 Zotero 导入的个人论文库。
- 用项目组织论文、对话、生成内容以及协作者可见的研究上下文。
- 提供 PDF 导航、基于来源的对话、锚定式批注线程、选区翻译和保留证据关系的阅读重排。
- 允许用户连接可选的搜索、解析和研究服务，并由用户自己管理凭据。

稳定的产品原则记录在 [PRODUCT.md](./PRODUCT.md)。具体实现应以当前代码、生成的 API 契约和测试为准。

## 仓库结构

| 路径          | 职责                               |
| ------------- | ---------------------------------- |
| `web/`        | 当前正式开发的产品前端             |
| `server/`     | FastAPI 应用及同步产品 API         |
| `jobs/`       | 异步导入与生成任务                 |
| `packages/`   | 共享 Python 契约和基础包           |
| `client/`     | 仅用于对照的旧前端，不进入生产发布 |
| `deploy/ecs/` | ECS/Fargate 生产发布基础设施       |

## 开发入口

请从 [docs/README.md](./docs/README.md) 的文档索引开始：

- [DEVELOPMENT.md](./DEVELOPMENT.md)：依赖、环境变量、固定端口、初始化和启动命令；
- [CONTRIBUTING.md](./CONTRIBUTING.md)：分支、评审、文档和验证流程；
- [AGENTS.md](./AGENTS.md)：仓库边界及开发代理必须遵守的规则。

根验证命令为：

```bash
./scripts/run-gates.sh <server|jobs|shared-packages|web|client|deployment|docs|all>
```

该命令只验证已经准备好的工作区，不会安装依赖、启动常驻服务或执行数据库迁移。

## 许可证与来源

Scholens 采用 [GNU Affero General Public License version 3](./LICENSE)。必要的来源和修改声明见 [NOTICE.md](./NOTICE.md)；使用其他许可证的评测夹具在其所在目录单独说明。
