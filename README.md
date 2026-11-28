# CROSS daily recordings

项目维护参考。用户通过 Codex 对话提供方向和试听判断；助手负责操作，不要求用户学习后台或阅读手册。约定见 `AGENTS.md`。引擎历史见 [技术记录](docs/listening-feedback.md)。

在当前项目内工作的个人生成音乐系统。显示名称由用户指定为 **CROSS**。已有作品、头像和专辑链接来自已核对的
[Bandcamp 页面](https://bellacrossmusic.bandcamp.com/)。

## 当前状态

音乐网站、素材同步和真实云端生成已上线；管理网页已按用户要求撤下，真实定时检查已观察到成功运行。当前采用免绑卡方案，没有开通 R2。
已用真实素材完成连续三天的受控生成、跨日发布、失败恢复与旧专辑清理后的 Selected 播放检查。
执行记录、跨日验收和浏览器验证范围见 [验证记录](docs/verification.md)。

- 网站：[CROSS](https://thebellacross.github.io/cross-today/)
- 代码：[thebellacross/cross-today](https://github.com/thebellacross/cross-today)
- 集中配置：[config.json](config.json)

## 对话中的使用方式

用户描述想改善的声音或提供一批录音，助手准备可播放试听；需要判断时，一次提出一个具体听感问题。用户直接回复，助手保存与确切音频关联的真实反馈，处理训练、配置、验证及版本记录。不得让用户去管理网站完成这些操作。

管理网页和自动登录快捷入口已移除。内部认证 API、历史反馈与模型、素材、精选和每日发行继续保留。2026-11-28 Composition Review 试听按用户选择只留本地，不上传，不产生未经确认的评分。

Selected 中的交付验证曲目不代表用户审美选择。保存、导出、恢复系列及调整设置均由助手根据对话办理。

默认上海时区，21:00 准备次日专辑，00:00 左右发布。Worker 每15分钟检查，
Actions 每小时两次补查。平台延迟可能造成晚发布；失败保留上一张成功专辑。
随机结束默认开启，000 的概率为1/366，001为1/365，以后逐渐增加。
终止后最后一张保留，可由助手恢复系列；关闭随机结束可持续每日生成。

## 本地命令

使用当前项目的虚拟环境，原始 `C_SoundSource` 文件不修改、不搬移。
双击 `Start Preview.command`，再打开终端显示的本地地址，即可试听 `output/cross-current`
中的完整本地专辑；关闭终端或按 Control-C 停止预览。这不是线上网站。

```sh
.venv/bin/python scripts/doctor.py
.venv/bin/python -m music.library C_SoundSource
.venv/bin/python -m music.album --out output/manual --seed 20261118 --day 2026-11-18
.venv/bin/python scripts/sync.py C_SoundSource --keychain
.venv/bin/python scripts/refresh_bandcamp.py
```

同步命令只上传所指定文件夹里的支持格式，使用文件 SHA-256 去重；`--keychain`
读取本机已保存的项目凭据，不需要复制口令。内部服务和本地同步使用相同原始素材 ID。
更换 Mac 时需重新建立管理凭据，不要把密码或密钥放进命令参数或聊天。
长录音分段解码使用有界内存，新缓存为保留双声道的 PCM16 WAV + JSON（旧 mono 缓存保留）；成品为立体声
24-bit/48 kHz WAV 与320 kbps MP3。原立体声保留在原处与私有云端素材存储。

衍生缓存位于 `.cache`，私有索引位于 `.state`，生成结果位于 `output`。
这些目录与原素材、参考研究、登录状态都被 Git 忽略。公开构建仅允许明确列出的
网页文件和艺人图片，不能把项目根目录作为 Pages 发布目录。

## 配置与服务

- GitHub Pages：公开静态网页；每天读取 Worker 的当前专辑指针。
- GitHub Actions：Python/FFmpeg 后台解码、渲染、发布和精选导出。
- GitHub Releases：生成资产，先草稿，完整校验后公开。
- Cloudflare Worker：定时调度、媒体 MIME/CORS/Range、服务端管理认证。
- Durable Object：素材清单、任务租约、编号、当前专辑、精选顺序和备注。
- 私有 GitHub 仓库的项目 Release 资产：选入的原始声音、衍生缓存、素材快照和含私人备注的精选发行包；不把音频提交进 Git。
- 独立 `kept-*` Releases：Selected 的完整 WAV、MP3、封面、来源记录，永不匹配每日清理。
- 独立 `catalog-*` Releases：长期保留的小封面。

Worker 管理口令和会话签名秘密仅在服务端。浏览器收到 HttpOnly、Secure、
SameSite=Strict 会话；写操作同时校验来源。CI 使用独立 RUN_TOKEN。
管理记录保存在 SQLite Durable Object；私人备注只进入受保护的导出包。私有资产的签名下载地址和凭据不发送给浏览器，媒体代理支持 Range。

当前使用免绑卡方案：标准公开 Actions runner、Pages、项目 Releases、Workers Free 与 SQLite。不会开通 R2 或升级付费计划；达到服务限额时暂停相关任务并保留上一张成功专辑。项目起步保护上限为原素材 5 GiB、Selected 10 GiB（可在 config.json 调整，这是项目自设上限，不是 GitHub 官方容量承诺）。
GitHub Releases 用于这个软件项目的输入和发行结果；免费托管受平台使用条款、API 限流及可用性约束，不能承诺无限容量或永远不中断。之后确认采用 R2 时可以保持素材 ID 和公开 URL 迁移，迁移不会自动发生。

助手使用本机项目钥匙串和受保护 API 完成维护，不向用户索取或展示口令。

参考许可、复现边界和依赖说明见 `THIRD_PARTY.md`。测试执行
`python -m pytest tests`、`node --test tests/worker.test.mjs`；
当前免费后端集成测试运行 `node tests/cloud.integration.mjs --free`；保留的 R2 适配使用不带 `--free` 的同一测试。两者都在本地 workerd 中运行，GitHub 为隔离替身。
