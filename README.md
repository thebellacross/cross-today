# CROSS daily recordings

听后反馈改造：可重放计划、立体声链路、私有 A/B、成对偏好模型与生成器连接见 [使用说明](docs/listening-feedback.md)。当前学习证据与上线验证见 [反馈改造验证](docs/feedback-verification.md)。

在当前项目内工作的个人生成音乐系统。显示名称由用户指定为 **CROSS**。已有作品、头像和专辑链接来自已核对的
[Bandcamp 页面](https://bellacrossmusic.bandcamp.com/)。

## 当前状态

网站、管理页、素材同步和真实云端生成已上线，真实定时检查已观察到成功运行。当前采用免绑卡方案，没有开通 R2。
已用真实素材完成连续三天的受控生成、跨日发布、失败恢复与旧专辑清理后的 Selected 播放检查。
执行记录、跨日验收和浏览器验证范围见 [验证记录](docs/verification.md)。

- 网站：[CROSS](https://thebellacross.github.io/cross-today/)
- 管理：[受保护管理页](https://cross-today.thebellacross.workers.dev/admin)
- 代码：[thebellacross/cross-today](https://github.com/thebellacross/cross-today)
- 集中配置：[config.json](config.json)

## 日常使用

1. 在这台 Mac 双击 `Open Admin.command` 自动登录，再批量选择声音文件。
   文件先上传到私有存储，由后台任务解码；Mac 关闭后仍可供云端生成使用。
   本地文件夹同步可直接双击 `Sync Sounds.command`，只增量同步 `C_SoundSource`。
2. “立即生成 / 重试今天”使用固定的当日素材快照。重复点击不会重复发行。
3. 试听后加入 Selected。等到“已永久保存”再把它加入精选发行顺序。
4. 调整顺序、标题和备注并保存；“导出发行包”包含 WAV、MP3、封面、曲名、
   credits 和来源记录。Selected 本身不会训练模型，也不会自动发布 Bandcamp。听后反馈与模型训练在独立管理区明确进行，见 [听后反馈使用说明](docs/listening-feedback.md)。
5. 参数、时区、生成/发布时间、保留张数和随机结束规则集中在 `config.json`。
   改动渲染代码、依赖或头像时使用新的固定引擎标签，已有任务保留创建时的版本。

Selected 中当前两首曲目与 Delivery validation 发行包用于交付验证；它们不代表替用户作出的审美精选。可在管理页编辑备注与正式发行顺序。

默认上海时区，21:00 准备次日专辑，00:00 左右发布。Worker 每15分钟检查，
Actions 每小时两次补查。平台延迟可能造成晚发布；失败保留上一张成功专辑。
随机结束默认开启，000 的概率为1/366，001为1/365，以后逐渐增加。
终止后最后一张保留，可在管理页继续系列；关闭随机结束可持续每日生成。

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
读取本机已保存的项目凭据，不需要复制口令。网页和本地同步使用相同原始素材 ID。
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

在这台 Mac 双击 `Open Admin.command`，会从钥匙串读取凭据，通过两分钟有效的一次性链接打开管理页；不需要把密码复制到聊天。

参考许可、复现边界和依赖说明见 `THIRD_PARTY.md`。测试执行
`python -m pytest tests`、`node --test tests/worker.test.mjs`；
当前免费后端集成测试运行 `node tests/cloud.integration.mjs --free`；保留的 R2 适配使用不带 `--free` 的同一测试。两者都在本地 workerd 中运行，GitHub 为隔离替身。
