# 彩田学校 AI 课堂：网页问卷与隐藏判级

新入口为 `https://test.homura.cn/caitian-ai/index.html`，目录入口为 `/caitian-ai/`（需网站支持目录首页）。原 `index.html` 和 `caitian.html` 保留。新页面保持原有样式、1—8班、1—55号、一个课次和麦克风授权，增加在线课前问卷，不自动替学生发送消息。

学生选身份 → 填写问卷 → SCF 调用隐藏判级智能体 → 后台按问卷规则计分并保存 → 写入小画君已有用户变量 → 学生自行开始对话。

## 无需修改扣子连线的接入方式

- 开放题语义全部交给现有判级智能体 `7706346907417362432`。每份非空第11题发起三次相互独立、并行的 AI 核查，分别判断拟人化、检索、学规律生成的观点是否成立，沿用原六字段 JSON。第6题仅供 AI 澄清含义，不传学生身份与选择题答案。
- 后台只验证响应协议、合并 AI 判断并查表计分：生成70、检索40、拟人化20、混合30、无法判定的答案不计开放题分数。没有关键词分类，也不会因学生写“不是”“可能”而自动转人工。
- 三个判断都必须有效；格式不符、模型未遵守分项任务或服务异常时保存问卷、等待老师重试 AI 或复核，不伪造等级和置信度。
- 登录前通过 Coze 变量 API 写主智能体 `7706348792413011968` 的现有 `Pn`，若 `P0` 已声明则同步写入。使用与 Chat SDK 相同的身份与渠道999，写后读取核对。刷新令牌不重复初始化。

前提是小画君已发布的 Chat SDK 渠道确实启用了 `Pn` 用户变量，现有 OAuth 令牌具有变量读写权限。提示词中提到变量名并不等于已启用变量。无需改两个智能体的提示词、节点或连线，但这两个条件仍须实测。现有主智能体的三轮等提示词规则保持原样；第二课时和对话中每轮幽灵判级仍未接入。

## 交付和配置

- `caitian-ai/`：新的全部公开前端文件，部署只上传这个目录的五个文件。
- `backend/`：Python 3.10 SCF 事件函数，入口 `index.main_handler`。
- `docs/lesson-one-deployment.md`：部署步骤、环境变量、权限与验收清单。
- `deploy/scf-env.example.json`：环境变量占位模板，不含真实密钥。
- `deploy/cos-role-policy.example.json`：私有问卷桶的运行角色权限模板。
- `tools/import_questionnaires.py`：保留教师 Excel 导入，网页填答是主要入口。
- `tools/admin_profile.py`：老师查看或重新请求 AI 判级。
- `coze/`：早期需要改智能体的可选方案，本次不用，不要照此覆盖现有智能体。

SCF 未部署时，`caitian-ai/caitian-config.js` 的 `profileAuthUrl` 保持空值。页面可查看和填写，但明确显示尚未开放提交。云端配置和联调通过后填入新服务的 HTTPS `/auth` 地址再发布；不会悄悄跳过问卷进入旧智能体。

## 验证与发布

```powershell
python -m pip install -r tools/requirements.txt
python -m unittest discover -s tests -v
node --test tests/caitian-session.test.cjs tests/caitian-login.test.cjs tests/caitian-questionnaire.test.cjs
python tools/stage_site.py build/site
```

CI 在 Linux 上安装 SCF 依赖、运行测试并打包，发布器只允许上传 `caitian-ai/` 的公开文件，不递归上传仓库。问卷、后台、文档、测试和令牌都不进入网站桶。原页面不在此次发布列表。

本地模拟测试验证流程与协议，不证明现有智能体的实际语义正确率、变量授权、腾讯云部署状态或几十人并发容量；以交付时的实测记录为准。学生依然自选班级学号，沿用原身份区分方式，不构成本人身份验证。
