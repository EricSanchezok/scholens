# Scholens MCP 工具测试报告

| 元数据 | 值 |
| --- | --- |
| 报告状态 | 当前有效的基线审计报告 |
| 测试日期 | 2026-08-24（Asia/Shanghai） |
| 仓库分析基线 | `3d6442fd1f36db3a9a1f22f14b5d6632625a9ee8` |
| 被测接口 | 已配置的 Scholens Remote MCP profile（Streamable HTTP） |
| 协议基线 | Model Context Protocol `2025-11-25` |
| 测试方式 | 真实 MCP 调用、契约静态检查、服务端及连接器自动化门禁 |
| 数据处理 | 不记录访问密钥、确认令牌、上传/下载签名 URL、邀请邮箱或既有用户内容 |

## 1. 执行结论

本次测试发现并调用了当前 Remote MCP profile 的全部 **57 个工具**。工具发现、
认证、绝大多数查询、项目/文库基础写入、论文导入、检索、引用、标注和 Unicode
字段往返整体可用，但当前版本不能判定为“所有 MCP 能力均正常”。

核心结果如下：

| 结论 | 数量 | 说明 |
| --- | ---: | --- |
| 已完成实际成功路径 | 37 | 查询、非破坏性写入或工作流返回了有效结果 |
| 已完成确认预览路径 | 9 | 第一阶段影响预览正常；依照工具协议未擅自执行第二阶段破坏性动作 |
| 已验证预期业务错误 | 7 | 当前没有可安全使用的成功态夹具，但错误类型、错误码和边界行为可复现 |
| 阻断性失败 | 4 | 工具在合法参数下仍无法生成确认预览，不能使用 |
| 合计 | **57** | 当前会话可发现工具 100% 至少调用一次 |

同时，`resources/list` 和 `resources/templates/list` 可用，但对五类实际资源 URI
执行 `resources/read` 均失败。因此 MCP 的工具面大体可用，资源面目前整体不可用。

综合评级：**有条件不可发布（Conditional No-Go）**。若发布标准仅要求主要工具调用，
大部分核心流程可工作；若发布标准包含完整 MCP Tools + Resources 契约、所有公开工具
可调用、受控输出体积和无明显内部信息暴露，则当前版本不满足要求。

本次未发现 P0 级数据破坏或认证绕过问题，但确认了 4 个 P1 问题：

1. 所有实际 `resources/read` 请求失败，并产生最高约 10 MB 的内部校验诊断。
2. 四个公开写入/管理工具无法通过第一阶段确认预览。
3. 作业结果未经公共投影，单次列表响应约 7.95 MB，并暴露内部对象存储键及完整解析内容。
4. 研究产物的公开枚举、输入校验、默认列表结果和单项读取语义彼此冲突。

## 2. 测试目标与范围

### 2.1 目标

本次审计回答以下问题：

- 当前配置的 Scholens MCP 工具是否都能被发现和调用；
- 正常路径、错误路径、幂等语义、二次确认和权限提示是否符合公开契约；
- 中文、多语种和 Emoji 是否发生乱码或丢失；
- Tool、Resource、Schema、错误结果和 Streamable HTTP 行为是否符合 MCP 规范；
- 输出是否有过大、重复、泄露内部实现细节或消耗 Agent 上下文的风险；
- 现有自动化门禁能否捕获实时调用发现的问题。

### 2.2 实际覆盖边界

- 实时端到端覆盖的是本会话直接暴露的 Remote MCP profile：56 个共享工具加
  `prepare_paper_upload`，共 57 个。
- 已配置 endpoint 没有向本次客户端返回可独立核验的部署 SHA；因此报告把实时行为与上述
  仓库基线进行对照和根因定位，但不把仓库 SHA 误写成远端发布证明。
- 本地连接器 profile 会用 `upload_local_paper` 替换
  `prepare_paper_upload`。当前会话没有暴露该本地文件工具，因此只运行了
  `mcp-connector` 全量自动化门禁，未把它计入 57 个实时调用结果。
- 内部 conversation profile 的 `wait_for_jobs` 不是当前 Remote MCP profile 的公开工具，
  不计入本次 57 个工具。
- 需要 `confirmation_token` 的动作只执行第一阶段影响预览。没有用户针对具体影响的
  明确批准时，不执行公开分享、永久删除、移交所有权、退出项目等第二阶段动作。
- 邀请接受、重试失败任务、取消运行中任务和读取非标注类研究产物没有合适的隔离成功态
  夹具；这些工具验证了可安全构造的预期错误路径，并在矩阵中明确标注。

### 2.3 测试数据隔离

实时测试创建了两个带 `【MCP审计】` 前缀的隔离项目，并使用公开论文标识符导入三篇
论文。测试只修改了审计创建的项目、文库成员关系、标签、元数据覆盖和标注。未修改
既有项目的成员、邀请、论文、标签或分享状态。

由于 `remove_library_papers` 和 `remove_paper_from_project` 本身存在阻断性缺陷，且永久
删除/公开分享需要第二阶段人工确认，审计数据尚未全部清理。详见第 10 节。

## 3. 依据与判定标准

测试以仓库提交的 `server/contracts/mcp-v1.json` 为 Scholens 公开契约，并对照 MCP
`2025-11-25` 规范：

- [Tools 规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
  要求工具输入和输出使用 JSON Schema；声明 `outputSchema` 时，成功结果的
  `structuredContent` 必须符合该 Schema。执行失败应通过工具结果的 `isError: true`
  返回，并建议同时提供文本形式的 JSON 以兼容客户端。
- [Resources 规范](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)
  定义资源发现、模板发现和资源读取；资源读取应返回与 URI 对应的 `contents`，并建议
  使用标准 JSON-RPC 错误码表达资源不存在和内部错误。
- [Transports 规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
  定义 Streamable HTTP 的 GET/POST、`Accept`、Origin 校验、会话和安全要求。
- [Authorization 规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
  定义 HTTP transport 的标准 OAuth 发现与授权模型。Scholens 当前使用 Bearer Access
  Key；本报告把它视为产品自定义认证 profile，并检查最小权限和错误隔离，而不把自定义
  Access Key 本身直接判为协议违规。

严重度定义：

| 等级 | 定义 |
| --- | --- |
| P0 | 可造成未授权访问、不可逆数据损坏或系统完全不可用，必须立即停止使用 |
| P1 | 公开能力不可用、契约严重冲突、显著数据暴露或上下文/性能风险，发布前应修复 |
| P2 | 质量、可诊断性、输入契约或局部体验缺陷，应进入最近修复周期 |
| P3 | 低风险一致性、文档或优化问题，可排期处理 |

状态定义：

- **PASS**：实际成功结果符合该场景的主要契约；
- **PREVIEW PASS**：需要确认的工具正确返回影响预览，但未执行第二阶段；
- **EXPECTED ERROR**：安全构造的无效状态返回稳定、可理解的业务错误；
- **FAIL**：合法参数或可用资源仍触发非预期内部/不可用错误；
- **PASS WITH ISSUE**：功能返回成功，但结果同时触发本报告的问题项。

## 4. 环境与契约清单

静态契约和实时发现均为 57 个工具，未发现重复名称或工具遗漏。契约分类如下：

| 维度 | 分布 |
| --- | --- |
| 所需权限 | `read` 21、`write` 18、`manage` 11、`delete` 7 |
| 执行类型 | `query` 22、`command` 28、`workflow` 7 |
| 行为提示 | `read_only=true` 22、`destructive=true` 11、`idempotent=true` 31 |
| 二次确认 | `required` 17、`none` 40 |

实时客户端返回的成功结果普遍同时包含文本 JSON 和 `structuredContent`，结构化 envelope
包含 `result`、`sources`、`artifacts`、`action` 和 `resource_links`。业务错误通过
`isError: true` 返回，且没有把错误对象错误地塞入成功输出 Schema；这部分设计与 MCP
工具规范相符。

## 5. 逐工具实时测试矩阵

### 5.1 项目、成员与邀请

| 工具 | 实时场景与观察 | 状态 | 关联问题 |
| --- | --- | --- | --- |
| `create_project` | 创建隔离项目成功；相同幂等键和相同参数重放返回同一项目；同键不同参数返回 `tool_invocation_conflict` | PASS | — |
| `update_project` | 中文、繁体、拉丁扩展、希腊文和 Emoji 标题/描述精确往返 | PASS | — |
| `get_project` | 通过不可变 UUID 读取成功，成员、论文和绑定信息结构完整 | PASS | — |
| `list_projects` | 默认列表和标题过滤均成功，审计项目可检索 | PASS | — |
| `delete_project` | 对两个隔离项目均返回清晰的永久删除影响预览 | PREVIEW PASS | — |
| `list_project_members` | 返回审计项目唯一 owner，分页结构正常 | PASS | — |
| `update_project_member` | 对 owner 权限变更返回影响预览；尚未执行 | PREVIEW PASS | MCP-007 |
| `remove_project_member` | 对 owner 移除返回影响预览；尚未执行 | PREVIEW PASS | MCP-007 |
| `leave_project` | owner 退出项目返回影响预览；尚未执行 | PREVIEW PASS | MCP-007 |
| `transfer_project_ownership` | 使用合法项目和可解析目标成员仍返回 `tool_execution_failed` / `unavailable` | **FAIL** | MCP-002 |
| `create_project_invitation` | 合法项目和邀请输入无法生成确认预览，稳定返回 `tool_execution_failed` | **FAIL** | MCP-002 |
| `list_project_invitations` | 空邀请列表读取成功 | PASS | — |
| `accept_project_invitation` | 隔离的无效 token 返回 `project_invitation_invalid`，未泄露邀请信息 | EXPECTED ERROR | — |
| `resend_project_invitation` | 不存在的邀请 UUID 返回 `project_invitation_not_found` | EXPECTED ERROR | — |
| `revoke_project_invitation` | 不存在的邀请 UUID 返回 `project_invitation_not_found` | EXPECTED ERROR | — |

### 5.2 项目论文与文库

| 工具 | 实时场景与观察 | 状态 | 关联问题 |
| --- | --- | --- | --- |
| `list_project_papers` | 三篇审计论文均可按项目列出 | PASS | — |
| `list_paper_projects` | 论文到项目的反向关系读取成功 | PASS | — |
| `add_papers_to_project` | 文库论文加入辅助项目成功；项目可见但非文库论文被正确拒绝为 `library_document_not_found` | PASS | — |
| `remove_paper_from_project` | 合法项目/论文关系无法生成确认预览，返回 `tool_execution_failed` | **FAIL** | MCP-002 |
| `collect_project_paper_to_library` | 项目论文收录个人文库成功 | PASS | — |
| `get_library_summary` | 汇总读取成功，收录后论文计数增加 | PASS | — |
| `list_library_papers` | 默认列表、过滤和审计论文检索成功 | PASS | — |
| `get_library_paper` | 审计论文文库状态、覆盖元数据和标签读取成功 | PASS | — |
| `update_library_paper` | 中文标题、`Łukasz`、机构、摘要、测试 DOI 和阅读状态精确往返 | PASS | — |
| `remove_library_papers` | 合法文库论文无法生成确认预览，返回 `tool_execution_failed` | **FAIL** | MCP-002 |
| `create_library_tag` | 创建审计标签成功 | PASS | — |
| `update_library_tag` | `MCP审计·标签（已更新）🔬` 精确往返 | PASS | — |
| `list_library_tags` | 默认列表和名称过滤成功 | PASS | — |
| `replace_library_paper_tags` | 审计论文完整替换为审计标签成功 | PASS | — |
| `delete_library_tag` | 返回受影响标签及永久删除影响预览 | PREVIEW PASS | — |
| `share_library_paper` | 返回创建公开访问链接的影响预览；未公开执行 | PREVIEW PASS | — |
| `unshare_library_paper` | 对当前未公开论文仍返回“现有公开链接将失效”的预览 | PREVIEW PASS | MCP-007 |
| `collect_shared_paper` | 不存在的公开 token 返回 `public_paper_not_found` | EXPECTED ERROR | — |

### 5.3 论文导入、内容、引用和作业

| 工具 | 实时场景与观察 | 状态 | 关联问题 |
| --- | --- | --- | --- |
| `prepare_paper_upload` | 合法 PDF 文件名返回 HTTPS 签名上传会话；URL 无 userinfo/fragment，签名 query/headers 未落盘；路径型文件名被 Schema 拒绝 | PASS | — |
| `ingest_paper` | arXiv 单篇导入成功并复用既有文档；未上传完成的会话稳定返回 `paper_upload_not_completed` | PASS | — |
| `ingest_papers` | 两篇 arXiv 批量导入并等待完成，汇总正确；响应约 454 KB，包含完整作业原始结果和内部键 | PASS WITH ISSUE | MCP-003 |
| `retry_paper_ingestion` | 对已完成任务返回 `paper_ingestion_retry_not_allowed` | EXPECTED ERROR | — |
| `cancel_paper_ingestion` | 对已完成任务返回 `paper_ingestion_cancel_not_allowed` | EXPECTED ERROR | — |
| `list_jobs` | 可按项目过滤并返回正确任务；未过滤 100 条时响应约 7.95 MB | PASS WITH ISSUE | MCP-003 |
| `get_job` | 完成任务读取成功，但单条响应约 67 KB，公开结果含完整解析正文和内部存储键 | PASS WITH ISSUE | MCP-003 |
| `get_paper` | 论文 manifest 读取成功 | PASS | — |
| `get_paper_content` | 行范围读取成功；两篇 PDF 的解析文本出现 U+FFFD，最大实测响应约 410 KB | PASS WITH ISSUE | MCP-005、MCP-008 |
| `search_paper_content` | 在指定论文内检索到相关段落和定位信息 | PASS | — |
| `get_paper_download_url` | 返回 HTTPS 临时下载链接；未在报告中持久化签名参数 | PASS | — |
| `get_paper_citation` | 引用字段完整并可生成引用 | PASS | — |
| `resolve_paper_citation` | DOI/引用解析成功，命中缓存路径正常 | PASS | — |
| `search_scholens_knowledge` | 对文库/项目知识检索返回来源、摘录和定位信息 | PASS | — |

### 5.4 标注与研究产物

| 工具 | 实时场景与观察 | 状态 | 关联问题 |
| --- | --- | --- | --- |
| `create_annotation_thread` | 用精确引文位置创建项目标注和首条中文评论成功 | PASS | — |
| `get_annotation_thread` | 线程、评论、受众和位置读取成功 | PASS | — |
| `list_annotation_threads` | 项目/论文范围列表成功 | PASS | — |
| `update_annotation_thread` | 单独更新颜色和状态均成功；同时提供两者时运行时拒绝，但 JSON Schema 未表达 exactly-one 约束 | PASS WITH ISSUE | MCP-006 |
| `delete_annotation_thread` | 返回线程及评论永久删除影响预览 | PREVIEW PASS | — |
| `create_annotation_comment` | 第二条多语种评论创建成功 | PASS | — |
| `update_annotation_comment` | 中文、拉丁扩展和 Emoji 评论精确往返 | PASS | — |
| `delete_annotation_comment` | 返回单条评论永久删除影响预览 | PREVIEW PASS | — |
| `list_research_outputs` | 默认文库列表成功，但返回标注线程；显式传 `annotation_thread` 又被输入校验拒绝 | PASS WITH ISSUE | MCP-004 |
| `get_research_output` | 标注 ID 被正确说明为“不是 research output”；当前账户无 citation/audio/data-table 成功夹具 | EXPECTED ERROR | MCP-004 |

## 6. MCP Resources 测试矩阵

资源发现本身正常：`resources/list` 返回 library、projects 及具体资源，
`resources/templates/list` 返回 paper、project、annotation-thread 和 research-output 模板。
但下列五类实际读取全部失败：

| URI 类型 | 实际结果 | 诊断规模 | 状态 |
| --- | --- | ---: | --- |
| `scholens://library` | 嵌套模型无法验证为 `JsonValue` | 12,412 条校验错误，错误文本约 10.25 MB | **FAIL** |
| `scholens://projects` | 同类嵌套序列化失败 | 461 条错误，约 279 KB | **FAIL** |
| `scholens://project/{id}` | 同类嵌套序列化失败 | 405 条错误，约 306 KB | **FAIL** |
| `scholens://paper/{id}` | 同类嵌套序列化失败 | 118 条错误，约 56 KB | **FAIL** |
| `scholens://annotation-thread/{id}` | 同类嵌套序列化失败 | 215 条错误，约 127 KB | **FAIL** |

客户端最终只得到 `Mcp error: 0` 和完整的 Pydantic 校验诊断，没有标准化、可行动的
资源错误 envelope。失败文本包含内部类型、字段路径和模型表示；在授权用户数据较多时，
还会把大量已授权业务内容复制进错误上下文。这既是功能缺陷，也是诊断放大和上下文污染风险。

## 7. 问题清单与根因证据

### MCP-001 — P1 — 所有资源读取因嵌套模型序列化失败

**现象**

- 资源和模板能够发现，但五类资源读取 5/5 失败。
- 客户端显示非标准、不可诊断的 `Mcp error: 0`。
- 单次 library 读取可生成约 10.25 MB 错误文本。

**代码证据**

`server/app/transport/mcp/server.py::_resource_json` 只在传入值本身具有
`model_dump` 时做 JSON 模式转换。资源加载器实际返回的是“字典中包含 Pydantic 模型”的
嵌套结构，顶层字典不会触发转换；随后 `TypeAdapter(JsonValue).validate_python` 对 UUID、
datetime 和 BaseModel 递归校验失败。

使用当前虚拟环境进行最小复现：顶层 BaseModel 可以通过，包含同一模型的字典稳定失败，
与全部实时资源读取的错误一致。

**影响**

- MCP Resource 能力整体不可用；
- 大型诊断可能耗尽客户端上下文、增加延迟和成本；
- 内部模型结构和授权数据被不必要地复制到错误文本。

**验收方向**

五类 URI 均应返回合法 `contents`；嵌套 UUID/datetime/BaseModel 必须转换为 JSON 值；
失败响应应有有界、稳定、可分类的 JSON-RPC 错误，不能包含整份模型诊断。

### MCP-002 — P1 — 四个确认型工具无法生成影响预览

受影响工具：

- `create_project_invitation`
- `transfer_project_ownership`
- `remove_paper_from_project`
- `remove_library_papers`

**现象**

四个工具在合法参数和可访问资源上均返回：

- `isError: true`
- `code: tool_execution_failed`
- `kind: unavailable`
- `retryable: true`

相同幂等键重试得到相同失败，证明不是暂时性网络问题。

**代码证据**

`server/app/modules/action_confirmations/application.py::confirmation_digest` 与资源序列化
存在同型缺陷：只转换顶层 BaseModel，然后直接验证 `JsonValue`。四个 handler 传入的
确认状态分别包含嵌套的 project、target member、annotation thread 或 library paper 模型，
因此在影响预览生成前失败。使用顶层模型的其它确认工具可以正常生成预览。

**影响**

- 四个公开工具无法使用；
- 邀请创建失败还阻断了 resend、revoke、accept 的完整成功链路夹具；
- 用户只能看到泛化的 unavailable 错误，无法知道真实原因。

**验收方向**

为所有 17 个确认工具分别覆盖“预览、参数不变后确认、状态变更后 stale、token 重放”四类
行为，并加入嵌套 BaseModel、UUID 和 datetime 状态的回归测试。

### MCP-003 — P1 — 作业结果无界且暴露内部存储实现

**实测数据**

| 场景 | 响应规模 | 关键观察 |
| --- | ---: | --- |
| `list_jobs`，默认返回 100 条 | 约 7,947,897 字符 | 调用批次耗时约 70 秒 |
| `list_jobs`，仅审计项目 3 条 | 约 223,911 字符 | 仍包含完整结果 |
| `get_job`，单个 U-Net 任务 | 约 67,421 字符 | 单个 `result` 约 32,506 字符 |
| `ingest_papers`，两篇 | 约 454,352 字符 | 文本 JSON 与结构化结果均包含大对象 |

公开结果包含完整 `raw_content`、`s3_object_key`、预览对象键、解析器归档键和 Markdown
对象键。签名凭证没有出现在这些字段中，但这些是内部存储拓扑和作业实现细节，不应作为
面向 Agent 的默认结果。

**代码证据**

`list_jobs`、`get_job` 和 JobWaiter 直接把完整 `JobResponse.result` 投射为工具 payload；
批量导入又把完整 job 嵌入每个条目。文本 JSON 和 `structuredContent` 的兼容性重复使实际
传输进一步放大。

**影响**

- 严重消耗 Agent 上下文和请求延迟；
- 增加内部对象键及解析器细节暴露面；
- 小量任务也可能产生不可预测的大响应；
- 可能掩盖真正需要的 `status`、`job_id`、`document_id` 和下一步动作。

**验收方向**

为公开 Job 建立有版本、可分页/可继续读取的安全投影；默认结果不得包含原始全文、对象存储
键或提供方原始响应；对 Tool 文本、structured content、Resource 和错误文本分别设置并
测试明确的字符/条目上限。

### MCP-004 — P1 — 研究产物类型契约自相矛盾

**现象**

- `ListResearchOutputsInput.kinds` 的公开 JSON Schema 枚举包含
  `annotation_thread`；
- 运行时 validator 明确拒绝显式传入 `annotation_thread`，提示应使用标注工具；
- 不传 `kinds` 时，默认文库列表却返回标注线程，实测总数从审计前 512 增至 513；
- `get_research_output` 对同一标注 ID 又返回“annotation thread, not research output”；
- 工具描述宣称该工具用于 citation、audio overview 和 data table，不用于标注。

**代码证据**

输入使用包含四种值的通用 `ResearchItemKind`，同时设置 `maxItems=3` 并用运行时 validator
排除 annotation。handler 在默认空过滤时调用 library 输出列表，但没有把默认结果限制为
`_OUTPUT_KINDS`，因此把 annotation 混入。

**影响**

Agent 无法从 Schema 推导合法输入，也无法把列表结果稳定交给单项读取工具；公开工具描述、
Schema 和运行时语义三方不一致。

**验收方向**

公开 Schema 应只暴露实际允许的三类产物；所有 scope 的默认与显式过滤必须相同；列表返回
的每个 `item_id` 必须能由 `get_research_output` 读取。

### MCP-005 — P2 — PDF 解析乱码未触发质量降级

**实测结果**

- U-Net：224 行中出现 4 个 U+FFFD replacement character；
- ResNet：读取前 500/646 行时出现 18 个 U+FFFD；
- 乱码集中在数学符号、根号和图示字符附近，例如字符被替换为 `�`；
- 对应任务仍报告 `parser_quality: full` 且 `parser_warning_code: null`。

用户输入的简体、繁体、法语重音、波兰字符、希腊文和 Emoji 均精确往返，因此这不是
MCP JSON/UTF-8 传输层乱码，而是 PDF 解析或解析后质量检测缺陷。

**影响**

研究检索、引文定位和后续模型理解可能基于已损坏的数学文本；`full` 质量标记会使客户端
无法提示用户降级。

### MCP-006 — P2 — 标注更新的 JSON Schema 未表达 exactly-one 约束

`update_annotation_thread` 运行时要求 `color` 和 `status` 恰好提供一个。单独更新二者均
成功，同时提供两者返回 `tool_arguments_invalid`，错误本身清晰；但公开 JSON Schema
只把两个字段声明为可选，没有 `oneOf` 或等价约束。严格依赖 Schema 生成参数的客户端会
构造出看似合法、运行时却必然失败的请求。

### MCP-007 — P2 — 部分确认预览在业务可执行性校验之前生成

实测中：

- 对项目唯一 owner 执行降权、移除或退出，可以先得到影响预览；
- 对当前未公开论文执行 `unshare_library_paper`，仍得到“现有公开链接将停止工作”的预览。

这些预览没有被执行，因此未验证最终 command 是否会正确拒绝。问题在于第一阶段预览会让
用户误以为动作可执行或确实会产生所述影响。确认预览应基于当前状态描述真实后果；明显
不可能的动作或 no-op 应在签发 token 前返回稳定业务结果。

### MCP-008 — P2 — 正文范围上限仍可产生超大结果

`get_paper_content` 虽限制最多 500 行，但实测 500 行响应约 410 KB。行数不是可靠的输出
体积边界；包含长表格、公式或无换行文本的 PDF 仍可能远超 Agent 适用范围。应以字符/字节
预算为最终边界，并返回 continuation 信息。

## 8. 乱码、编码与国际化结论

对测试产生的 51 份响应、约 910 万字符进行替换字符扫描后，U+FFFD 只出现在论文解析
正文和相应作业原始结果中。以下字段没有发现乱码：

- 项目标题和描述；
- 文库论文标题、作者、机构、摘要和 DOI 覆盖；
- 标签名称；
- 标注评论；
- JSON 文本结果及 `structuredContent`；
- 错误 envelope 的中文/英文文本。

结论是：MCP transport、JSON 编码和数据库常规 Unicode 字段没有显示编码损坏；乱码问题
局限于 PDF 内容提取链路，但该链路缺少正确的质量告警。

## 9. 自动化测试结果与覆盖缺口

### 9.1 已执行门禁

```text
./scripts/run-gates.sh server
1226 passed, 13 skipped in 24.54s

./scripts/run-gates.sh mcp-connector
22 passed in 1.33s
Ruff format、Ruff lint、mypy 均通过
```

另执行了定向 MCP/工具测试：

```text
68 passed in 29.63s
```

定向集合包括 MCP transport、输出 Schema、一致权限、导入、知识检索、确认顺序、Access
Key 架构和 operation context 架构测试。

### 9.2 为什么自动化全绿但实时调用失败

现有测试已经验证工具列表、资源列表、资源模板列表、Tool 输出 Schema、错误 envelope 和
大量 handler 行为，但存在以下关键缺口：

1. 资源测试只覆盖 `resources/list` 和 `resources/templates/list`，未对每种 URI 执行
   真实 `resources/read`。
2. 确认 digest 测试没有使用“容器内嵌 Pydantic BaseModel + UUID + datetime”的真实状态。
3. 公开 Job 契约没有限制 `result` 的字段、层级、字符数，也没有禁止对象存储键和原始正文。
4. Schema conformance 测试验证“成功结果符合已生成 Schema”，但没有验证 Schema 能表达
   运行时跨字段约束。
5. 研究产物测试没有建立“不带 kinds 的默认列表”和单项读取之间的闭包不变量。
6. PDF 质量测试没有把 U+FFFD 与 `parser_quality` / `parser_warning_code` 联动。

因此，本次结果不是“自动化错误报警”，而是现有测试集合没有覆盖真实数据形态和端到端
公共契约边界。

## 10. 安全、确认和测试数据状态

### 10.1 已验证的安全行为

- Access Key 权限元数据和工具权限分层存在，自动化权限门禁通过；
- 路径型上传文件名被参数校验拒绝，错误没有回显签名 URL；
- 上传和下载链接使用 HTTPS，报告没有保存 query、headers 或 token；
- 无效邀请、公开分享 token 和资源 UUID 返回稳定的 not-found/invalid 错误，没有枚举出
  其它用户资源；
- 相同幂等键、不同业务参数会返回冲突，不会静默执行另一动作；
- 错误 ToolResult 使用 `isError: true`，不伪装成成功结构化结果。

### 10.2 尚未执行的高影响动作

以下第二阶段动作没有在未经具体批准时执行：项目永久删除、标签永久删除、标注评论/线程
永久删除、公开分享及取消分享、成员降权/移除、owner 退出项目。确认预览 token 具有短时效，
本报告不保存 token；若继续完整执行测试，必须重新获取预览并逐项确认影响未变化。

### 10.3 当前审计数据残留

- 两个 `【MCP审计】` 前缀项目；
- 一条由项目论文收录产生的审计文库成员关系及其元数据覆盖；
- 一个 `MCP审计` 前缀标签及标签关联；
- 一条审计标注线程和两条评论；
- 一个未完成上传的临时 upload session，按服务端会话生命周期过期。

这些对象不包含秘密或真实协作成员，但会影响当前用户的项目、文库、标签和标注计数。
`remove_library_papers` / `remove_paper_from_project` 修复前无法通过 MCP 完成对应清理；其它
永久删除需要用户对新影响预览做明确确认。

## 11. 修复后的最低验收门槛

本报告只定义验收结果，不在本阶段展开具体设计方案。后续修复至少应达到：

1. Remote profile 的 57 个工具全部有成功路径或可控、可重复的状态夹具；17 个确认工具
   全部覆盖 preview/confirm/stale/replay。
2. 五类资源 URI 100% 可读；资源错误有界且使用可分类的 JSON-RPC 错误。
3. 默认 `list_jobs`、单个 `get_job` 和批量导入结果满足明确的公共投影及大小预算，禁止
   `raw_content`、对象存储键和提供方原始响应进入默认 MCP 结果。
4. `list_research_outputs` Schema、默认过滤、显式过滤和 `get_research_output` 形成一致闭包。
5. 所有运行时跨字段约束由公开 JSON Schema 表达，至少覆盖标注更新 exactly-one。
6. 解析文本出现 U+FFFD 或其它质量阈值异常时，质量字段必须降级并给出可行动 warning。
7. 对所有工具、资源、错误和兼容性文本建立字符/条目预算及自动化回归。
8. 修复后重新运行本报告的 57 工具矩阵、本地连接器实际 PDF 上传端到端、server 和
   mcp-connector 全量门禁。

## 12. 总体评价

Scholens MCP 的主体架构具备良好基础：工具目录完整，权限和行为元数据清晰，成功结果有
结构化 envelope，幂等冲突可控，错误路径多数稳定，Unicode 业务字段表现良好，论文导入、
检索、引用、项目、文库和标注的主要流程已经能够真实工作。

当前最需要解决的不是工具数量，而是公共边界的一致性和有界性：嵌套模型在 Resource 与
Confirmation 两处采用了同一种不完整 JSON 规范化方式；Job 结果把内部处理对象直接暴露给
Agent；研究产物则复用了过宽的内部枚举。这三类问题共同说明，内部领域模型到公开 MCP
模型之间还缺少足够严格、独立且经过真实数据验证的投影层。

在 MCP-001 至 MCP-004 修复并完成回归前，不建议把当前版本宣称为“全部 MCP 工具与资源
均可正常使用”。
