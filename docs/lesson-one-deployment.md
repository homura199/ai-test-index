# 彩田学校新版前端与 SCF 部署设置

本包实现在线问卷和课前隐藏 AI 判级，不修改现有扣子智能体。新页面目录为 `caitian-ai/`，标准访问地址 `https://test.homura.cn/caitian-ai/index.html`。原网页及 `caitian.html` 保留。

## 当前已部署设置（2026-11-11）

| 项目 | 当前值 |
| --- | --- |
| SCF | 广州 / default / `caitian-lesson-one-profiles` |
| 执行环境 | Python 3.10，`index.main_handler`，512MB，120秒 |
| 私有桶 | `caitian-profiles-1308037263`，`ap-guangzhou`，私有读写，版本控制从未开启 |
| 运行角色 | `CaitianLessonOneProfilesRole` |
| 角色策略 | `CaitianLessonOnePrivateCOS`，仅课程目录读写和桶版本状态查询 |
| HTTPS 函数 URL | `https://1308037263-7d4qlm2zrr.ap-guangzhou.tencentscf.com` |
| 函数 URL 参数 | 默认流量、公网开启、参数兼容开启；网关层 CORS 关闭，由应用返回精确来源限制 |
| 环境变量 | 下表七项必需/选用配置已保存，`COZE_ASSESSMENT_TOKEN` 未配置，复用现有鉴权 |

身份签名密钥与管理密钥已在本机 `.private/caitian-scf-env.production.json` 备份，该文件被 Git 忽略，不随交付压缩包发布。不要重新生成 `IDENTITY_SECRET`，否则已有学生数据键名会改变。

健康检查、跨域预检、管理接口未授权拒绝、非法来源和非法学号检查均通过。真实写入回环测试待确认空闲测试学号，前端提交入口暂保持关闭。

## 1. 上传 SCF 包

在腾讯云广州地域新建独立函数 `caitian-lesson-one-profiles`，保留现有鉴权云函数。

| 设置项 | 配置 |
| --- | --- |
| 函数类型 | 事件函数 |
| 运行环境 | Python 3.10，x86_64 |
| 部署方式 | 上传交付的 `caitian-lesson-one-scf.zip` |
| 执行方法 | `index.main_handler` |
| 内存 | 建议512MB，后续按监控调整 |
| 执行超时 | 120秒 |
| 公网访问 | 开启，需要访问现有鉴权、api.coze.cn、COS |
| 运行角色 | 下一节创建的私有桶权限角色 |

压缩包根目录必须直接有 `index.py`、`profiles/` 和 `qcloud_cos/`。交付包使用 Linux Python3.10 依赖，不能用 Windows 原生二进制替换。

## 2. 私有 COS 与角色

新建独立私有桶，例如 `caitian-profiles-你的APPID`，地域 `ap-guangzhou`。不要使用网站桶；不公开读写，不绑定网站/CDN。**保持从未启用版本控制**，不能是 Enabled 或 Suspended：学生重复提交通过 COS 禁止覆盖写入保障，版本控制会使该机制失效，服务会拒绝提交。

运行角色仅授权：

- 该桶的 `GetBucketVersioning`。
- `lesson-one/profiles/*`、`lesson-one/submissions/*`、`lesson-one/tickets/*` 的 `GetObject` 和 `PutObject`。

使用 `deploy/cos-role-policy.example.json` 替换地域、APPID、桶名后创建自定义策略。对象按桶默认私有权限保存并使用 AES256 服务端加密。tickets 可设置一天后生命周期清理；问卷与画像保留期限按学校要求配置。不要给新函数网站桶或其他桶的权限。

SCF运行角色会提供 `TENCENTCLOUD_SECRETID`、`TENCENTCLOUD_SECRETKEY`、`TENCENTCLOUD_SESSIONTOKEN` 临时凭据，代码每次操作读取它们，不在包里存长期密钥。依据[腾讯云运行角色说明](https://cloud.tencent.com/document/product/583/47933)。禁止覆盖写入的限制见[腾讯云 PUT Object](https://cloud.tencent.com/document/product/436/7749)。

## 3. 环境变量

| 名称 | 要填的值 |
| --- | --- |
| `PROFILE_BUCKET` | 上一步完整私有桶名，带APPID |
| `PROFILE_REGION` | `ap-guangzhou` |
| `LEGACY_AUTH_URL` | `https://1308037263-lxn5m4tut3.ap-guangzhou.tencentscf.com` |
| `ALLOWED_ORIGIN` | `https://test.homura.cn`，不加子路径或末尾斜杠 |
| `IDENTITY_SECRET` | 随机至少32字符，用于学生存储键名；保存好，不随意更换 |
| `ADMIN_KEY` | 另一把不同的随机至少32字符密钥，仅教师后台工具使用 |
| `COZE_PROFILE_MODE` | `variables` |
| `COZE_ASSESSMENT_TOKEN` | 可选；留空/不配置时复用原 OAuth 鉴权发放的令牌 |

在本机生成两把不同的密钥后分别填入云函数环境变量，不提交仓库或网页：

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32)); print(secrets.token_urlsafe(32))"
```

`deploy/scf-env.example.json` 只含占位值。此次不用 `COZE_PLUGIN_KEY`，也不用导入插件或改扣子连线；未配置此密钥时旧 `/internal/profile` 接口关闭。

## 4. HTTPS 入口

本次使用 SCF 控制台的“函数 URL”，绑定默认流量，开启公网访问与参数兼容，授权类型选择开放；应用自行保护管理接口和限制网页来源。参数兼容保留 `httpMethod`、`path`、`headers`、字符串 `body`，函数返回 `statusCode/headers/body`。网关层不再重复设置 CORS，应用只允许 `https://test.homura.cn`。参见[腾讯云函数 URL 文档](https://cloud.tencent.com/document/product/583/96099)。

同步判级需保证入口和函数超时覆盖整次请求，函数已设120秒。当前使用腾讯云分配的测试 URL；正式长期使用时可在 SCF 自定义域名页面绑定自己的域名，并更新前端 `/auth` 地址。

| 路径 | 用途与鉴权 |
| --- | --- |
| `GET /health` | 存活检查，不代表所有依赖已连通 |
| `POST /questionnaire/status` | 学生传 user_id，只返回 missing/processing/ready/needs_review |
| `POST /questionnaire/submit` | 学生传 user_id、answers；原始问卷先私有落盘，再调用 AI |
| `POST /auth` | 准备好后写已有用户变量，返回令牌、匿名ID、临时会话标识和bot_id |
| `POST /admin/profile` | `X-Admin-Key`，读取一名学生的记录 |
| `POST /admin/regrade` | `X-Admin-Key` 与当前 source_digest，重新由AI判级 |
| `POST /admin/questionnaires` | `X-Admin-Key`，教师Excel导入 |
| `POST /admin/review` | `X-Admin-Key`，教师可选人工复核 |

CORS仅允许 `https://test.homura.cn`，不要再添加通配符或缓存鉴权/问卷响应。日志不记录请求正文、Authorization 或管理员密钥。

同步首次提交通常包含三次并行 AI 调用，各自使用随机服务身份、无历史保存。第11题与第6题是唯一送给判级智能体的问卷字段。重复提交返回已存状态，不重复调用，不覆盖旧问卷。执行中断超过120秒时标记需处理，老师可重试AI；不会自动降级或默认判P1。教师更新按单人串行操作，不支持多管理员同时改同一学生。

## 5. 扣子只需现有权限与变量，无需改连线

- 主智能体：`7706348792413011968`，已发布 Chat SDK 渠道，启用现有用户变量 `Pn`，可选 `P0`。
- 判级智能体：`7706346907417362432`，当前OAuth应用可通过 API 调用。
- 主智能体登录令牌须有 `readVariable`、`updateVariable` 和既有聊天权限。
- 后台使用主聊天同一 OAuth 身份、匿名学生ID、渠道 `999` 写入 `Pn`，存在 `P0` 时同时写入，再读取验证；不会写 Ln/Kn。

变量接口只读写已创建并启用的变量，不能把提示词里的变量名当作变量声明。参见[读取变量](https://docs.coze.cn/developer_guides_read_variable)、[设置变量](https://docs.coze.cn/developer_guides_update_variable)。若权限不足，先调整现有 OAuth 应用/鉴权发放范围；不需要改提示词或绘制连线。若根本没有启用Pn，当前方案不能仅靠网页完成，应先完成变量设置。

判级仍输出原六字段。后台分别给现有判级智能体三个临时任务：判断拟人化、检索、规律生成；有该维度证据则Pn为1/2/3，无证据则Pn=0，P0=0且L0/Ln/K0/Kn保持1。每个调用独立，不继承上次等级。“学习很多再找一张”应只认可检索；否定某观点不能算认可；多个解释同时成立则混合。以上是每次API请求的任务上下文，不是更改智能体。

后台不检查回答关键词，不替 AI 做语义判断。它校验三份返回并按文档确定性计分：选择题30分，第11题生成70/检索40/拟人化20/混合30/空白或不知道或答非所问不打分；第9题A/B/C/D对应4/6/2/0。第6题只参考，第12题只留存。总分0—19/P0，20—44/P1，45—74/P2，75—100/P3。既有六字段没有置信度或证据字段，记录中不伪造这些信息，保留三个AI结果和原始回答供审计。

这依赖既有模型遵守请求中的分项核查协议，必须用真实接口验收；若不遵守，服务保存问卷并阻止带错误结果进入课堂，老师可重试AI或复核。本地替身测试不能证明语义判定准确。P等级也不等于SOLO等级；主智能体原有教学提示词（包括三轮规则）保持原样，第二课时与每轮动态监控未接入。

## 6. 新前端发布

将前端包解压到网站根目录，会得到 `caitian-ai/` 五个文件。CI只发布这五个文件，不上传问卷/后台，不覆盖原 `index.html` 或 `caitian.html`。

部署并验收新函数后编辑 `caitian-ai/caitian-config.js`：

```javascript
profileAuthUrl: 'https://你的新函数或网关地址/auth',
```

保留 `questionnaireEnabled: true`、`profileTransport: 'variables'` 以及现有bot ID。网页里不填管理员密钥、Coze令牌、问卷评分规则或等级。配置为空时页面可预览问卷，禁止提交并显示尚未开放。标准链接用 `https://test.homura.cn/caitian-ai/index.html`，若网站目录首页可用，也可用 `https://test.homura.cn/caitian-ai/`。

## 7. 回环与课堂前验收

1. `/health` 返回200；打开新链接，班级1—8、学号1—55、课次只有1。
2. 使用约定测试学号填写问卷；查看后台私有记录，公开响应没有答案、分数、P等级。
3. 至少测试：学习规律生成、学习后找图、拟人化、混合观点、否定检索转向生成、不知道；与教师人工标注核对，第6题不能替代第11题。
4. 检查写变量的GET/PUT/GET成功，SDK以同一匿名ID进入，小画君按Pn引导。没有自动输入或发送“开始”。
5. 麦克风拒绝时不能进入对话；重复点击不重复创建SDK；超时后不丢问卷、状态可查；令牌刷新不重置Pn。
6. 教师重试AI：`python tools/admin_profile.py --base-url https://新服务 --class-no 8 --student-no 55 --regrade`。密钥隐藏输入，结果保存 `.private/profile-result.json`，仅打印状态。
7. 在学校网络按实际人数逐步测试（例如5、15、40人），记录问卷判级耗时、聊天首字耗时、失败率、Coze限流和SCF并发指标。三次判级会增加调用量，40份问卷最多120次模型请求。没有实测数据前不能承诺几十人并发。

可选Excel导入：安装 `tools/requirements.txt`，用 `tools/import_questionnaires.py --template .private/template.xlsx` 生成模板，再执行 `python tools/import_questionnaires.py .private/students.xlsx --base-url https://新服务`。密钥隐藏输入，不通过网址或命令行传递。

## 8. 回退

旧链接始终保留。新后台未就绪时保持新前端 profileAuthUrl 为空即可暂停提交；已保存数据仍在独立私有桶。不要通过删除问卷或清空浏览器全站存储来回退。
