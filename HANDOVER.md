# 交接文档 · zhs-ghost

> 写给接手维护的人。读完这一份就能独立干活。
>
> **最后更新**：2026-10-10  ·  **当前版本**：v1.3.0  ·  **仓库**：https://github.com/skyslight1/zhs-ghost

---

## 0. 三十秒了解

智慧树（zhihuishu.com）自动学习工具。接口分析成果来自
[fuckZHS](https://github.com/VermiIIi0n/fuckZHS)（MIT），代码是重写的。

**这个项目和同类工具的唯一区别**：它把服务端的风控（`code: -12`，要求人机验证）
当作**必然会发生的事件**，而不是需要事后打补丁的意外。所有请求都经过 `risk/Guard`，
命中风控会自动唤起真实浏览器过验证码、回灌 Cookie、重新加密重发 ——
业务代码根本感知不到验证码存在。

交付形态：4 个 Windows exe（2 个 GUI + 2 个 CLI），GitHub Release 自动构建。

---

## 1. 当前状态

### 1.1 发布情况

| tag | 状态 | 说明 |
|---|---|---|
| v1.0.0 ~ v1.1.0 | 可用 | 命令行版 |
| **v1.2.0 ~ v1.2.2** | ⚠️ **已标 pre-release** | 所有 exe 的 GUI 一开就崩（tkinter 没打进去） |
| v1.2.3 | 可用 | 修 tkinter |
| v1.2.4 | 可用 | 修「点扫码登录窗口未响应」 |
| v1.2.5 | 可用 | 修「二维码被压扁看不见」 |
| **v1.3.0** | **最新** | 扫码登录重构（强制重新扫码/可取消/弹窗生命周期）+ 修「学习失败： 响应不是 JSON（gologin）」+ 版本号统一 |

CI（`.github/workflows/release.yml`）在推 tag 时自动构建 4 个 exe 并发布，
耗时约 7 分钟。构建前会跑 115 项单元测试 + 22 项 GUI 冒烟，
GUI 版还会真启动一次、真点一次「扫码登录」并检查窗口是否响应。

### 1.2 已知问题（按优先级）

**A / B / C：已在 v1.3.0 修复**

- **A**：GUI 的「扫码登录」每次点击都强制发起新的智慧树二维码会话
  （`App.login(force=True, qr=True)`），不再被旧 `state/state.json` 登录态静默短路；
  CLI 保持默认复用登录态的行为。
- **B**：二维码弹窗位置限制在屏幕边界内；关闭弹窗真正销毁窗口并取消后台轮询；
  取消/失败时回滚旧 Cookie 与 uuid，不会出现半更新状态。
- **C**：窗口标题带版本号（`zhs-ghost v1.3.0 · …`），
  `tests/check_gui_login_no_hang.py` 改为按前缀匹配窗口；
  `pyproject.toml` / `zhsgo/__init__.py` / `packaging/version_info.txt` 统一为 1.3.0。

**v1.3.0 顺带修复（学习链路首个真实账号端到端反馈）**

- **跨站登录按 JSON 解析**：`ZhidaoApi.cross_site_login` 请求的
  `studyservice-api.zhihuishu.com/login/gologin` 是跳转型端点，正常返回 HTML
  落地页，原实现按 JSON 解析导致「学习失败： 响应不是 JSON」——
  共享课学习的第一个必经请求必然失败。已改为 `expect_json=False`
  （对齐上游 fuckZHS：只发请求不解析响应）。
- **登录页协议**：`passport` 的登录页导航请求同样改为 HTML 处理；
  二维码响应支持 `data`/`result` envelope 与多种 Base64 变体。

**D. git 历史里有带桌面碎片的旧截图**

commit `91b4fde` / `dbbbb17` 里的那批截图，边缘混进了当时桌面上其他窗口的
内容（各约 8px 宽，只有零星汉字/字母碎片，可辨认度很低）。
后续 commit 已重建干净版本，但**历史里还留着**。

清理需要重写历史 + force push，会波及 v1.2.0~v1.2.5 的 tag 和 Release
（Release 依附 tag）。**上一任维护者问过要不要清，一直没得到答复。**
需要的话：

```bash
git filter-branch --force --index-filter \
  "git rm -r --cached --ignore-unmatch docs/images" \
  --prune-empty -- --all
git push --force origin main
git push --delete origin v1.2.0 v1.2.1 v1.2.2 v1.2.3 v1.2.4 v1.2.5
```

**E. v1.2.0 ~ v1.2.2 的 Release 已标 pre-release（v1.3.0 发布时处理）**

那三个版本的所有 exe 一开 GUI 就崩。已用 `gh release edit vX --prerelease`
标记；如需彻底删除：

```bash
gh release delete v1.2.0 --yes && git push --delete origin v1.2.0
gh release delete v1.2.1 --yes && git push --delete origin v1.2.1
gh release delete v1.2.2 --yes && git push --delete origin v1.2.2
```

### 1.3 待办

- [ ] **没有真实账号的端到端测试** —— 登录、刷课、过验证码这三条主流程
      全靠人工验证。这是目前最大的质量缺口（v1.3.0 的两个修复都来自首次
      真实账号反馈）。
- [ ] 上游 fuckZHS PR #168 的 Polymas / AI 智课（`cloudapi.polymas.com`、
      `hikeAiCourse`）尚未支持，有需要时评估移植（注意保持现有分层）。
- [ ] D：决定是否清理 git 历史（见 1.2 的 D 节，需要重写历史 + force push）
- [ ] 微信小程序端（`studyvideoh5` 之外的入口）未支持
- [ ] 命令行版没有 `--gui` 之外的交互式引导

---

## 2. 项目从哪来

原项目 `fuckZHS` 的 issue 区长期有一类反馈：**挂机几小时后开始弹人机验证，
整门课停摆**。翻它的源码能找到根因，而且是好几条叠加：

| # | 源码位置 | 问题 |
|---|---|---|
| 1 | `fucker.py:532,577` | 上报间隔恒定 30.000 秒，`elapsed_time % 30 == 0`，零抖动 |
| 2 | `fucker.py:610` | `int(time.time())*1000` —— **毫秒位恒为 000** |
| 3 | `fucker.py:87-95` | UA 是 Chrome 100、Client Hints 是 Chrome 101，版本自相矛盾；`Accept-Language: en-GB`；全网用户共用同一套头 |
| 4 | `zd_utils.py:52` | 观看点每批都从 `[0, 1]` 重来 |
| 5 | `fucker.py:544` | 进度线性单调，零卡顿零回退 |
| 6 | 整体 | 连续挂 8 小时、`-s 444` 超高倍速 |

时间序列是风控最廉价也最准的判据。这份重写把上面每一条都对着改掉了，
详细对照见 README 第 2 节。

---

## 3. 代码结构

### 3.1 分层

```
clock ──► pacer ──┐
                  ├──► HttpClient ──► Guard ──► ZhidaoApi / HikeApi / AiCourseApi
budget ───────────┘        ▲           │
                           │           └──► Relay（真浏览器过检 + Cookie 回灌）
                           └── Fingerprint（UA / Client Hints / Referer 自洽）
```

**关键约束**：API 层只负责协议（组参、AES、签名、错误码），
**永远不 import relay，也永远看不到验证码**。风控恢复全部发生在 `Guard` 里。

### 3.2 关键文件

| 文件 | 职责 | 改它的频率 |
|---|---|---|
| `zhsgo/risk/guard.py` | **风控总控**。命中 -12 → 唤中继 → 重发 | 低 |
| `zhsgo/risk/pacer.py` | **所有时间戳与节拍的唯一出口** | 调参时 |
| `zhsgo/risk/budget.py` | 会话/单日配额，超限抛异常 | 调参时 |
| `zhsgo/risk/watchpoint.py` | 观看点连续覆盖 | 极低 |
| `zhsgo/net/fingerprint.py` | UA / Client Hints / Referer | 平台更新浏览器版本时 |
| `zhsgo/net/endpoints.py` | **全部 URL 常量** | 平台改接口时 |
| `zhsgo/net/client.py` | 传输层，不管节拍也不管风控 | 低 |
| `zhsgo/api/zhidao.py` | 共享课协议 | 平台改接口时 |
| `zhsgo/api/hike.py` | 校内课协议（MD5 签名） | 平台改接口时 |
| `zhsgo/relay/browser.py` | Playwright 编排 + Cookie 回灌 | 中 |
| `zhsgo/relay/captcha.py` | 滑块/点选识别 | 中 |
| `zhsgo/runner/study.py` | **学习循环**，所有节拍在这里汇合 | 中 |
| `zhsgo/gui/` | Tkinter 界面 | 中 |
| `packaging/build.py` | 打包 + 自检 | 打包逻辑变更时 |
| `packaging/zhs-ghost.spec` | PyInstaller 配置 | 依赖变化时 |

### 3.3 一次上报的完整路径

```
StudyRunner.run_zhidao_video()            节拍由 Pacer 决定
  └─ ZhidaoApi.report_progress()          组参数、AES 加密、get_ev 编码
       └─ ZhidaoApi.call()                发请求
            └─ 若 code == -12
                 └─ Guard.recover()
                      ├─ Relay.unlock()   起浏览器、过验证码、回灌 Cookie
                      ├─ sleep 让风控状态生效
                      └─ 重新加密 payload 并重发（**不能复用密文**）
```

---

## 4. 核心设计决策

写在这里是因为它们看起来"多此一举"，但都有具体原因。改之前先读。

### 4.1 为什么风控放在请求层而不是业务层

原项目的 `CaptchaException` 从 `zhidaoQuery` 一路冒泡到 `fuckZhidaoCourse`，
然后 `return` —— 整门课结束。而且它和网络错误、答案缺失挤在同一个
`except Exception` 分支里。

本质问题：**风控是可恢复状态，不是错误**。把它放请求层，
业务代码写成直线，"恢复"这件事只在一个地方发生。

### 4.2 为什么用 Tkinter 而不是 PySide6

PySide6 会让 exe 凭空多出约 80MB（完整版已经 202MB 了）。
Tkinter 是标准库，代价是要自己写样式 —— 见 `zhsgo/gui/theme.py`。

如果以后要做深色主题、动画之类的，可以重新评估。但先想清楚
"为了好看多 80MB"值不值。

### 4.3 为什么要有 observer 层

GUI 既需要进度回调，也需要停止/暂停能力，而原来的 `StudyRunner` 只会 `print`。

`zhsgo/observer.py` 定义了 `Observer` 协议：
- CLI 用 `NullObserver`，行为逐字节不变（106 项原有测试直接通过）
- GUI 用 `ControlObserver`，带停止/暂停闸门

`StudyRunner._rest()` 把会话休息切成 0.5 秒粒度检查停止标志 ——
一次会话休息可能是 40 分钟，直接 `sleep` 会让你点了停止还要干等。

### 4.4 为什么浏览器内核优先用系统 Edge

打包成 exe 之后既没有 pip 也没有 `playwright` 命令行，
拉不了 150MB 的 chromium。而 Windows 10/11 一定自带 Edge。

```python
def channel_chain(self):
    if self.cfg.channel:
        return [self.cfg.channel]
    if self.cfg.prefer_system_browser:
        return ["msedge", "chrome", None]   # 逐个试，最后才用内置 chromium
    return [None]
```

没有这一步，"开箱即用"就是句空话。

### 4.5 为什么 exe 不做代码签名

代码签名证书一年几百到几千美元。代价是用户首次运行会看到
「Windows 已保护你的电脑」，需要点「更多信息」→「仍要运行」。
在 README 和教程里都写明了。

### 4.6 为什么 `--selfcheck` 之外还要"真实启动"自检

见 6.1。简单说：**自检走的路径必须等于用户走的路径**，
否则等于没测。

---

## 5. 开发工作流

### 5.1 环境

```bash
git clone https://github.com/skyslight1/zhs-ghost.git
cd zhs-ghost
pip install -r requirements.txt
python -m playwright install chromium     # 可选，用系统 Edge 也行
cp config.example.yaml config.yaml
```

Python 3.10+。本地开发和打包用的是 3.14，CI 用的是 3.12。

### 5.2 测试

```bash
python tests/run_tests.py                # 106 项核心逻辑，零依赖、不联网
python tests/gui_smoke.py                # 19 项界面，建窗口、切页、模拟进度
python tests/check_stream_proxy.py       # 单独验证 stderr 代理不与 loguru 递归
python tests/check_gui_login_no_hang.py dist/zhs-ghost-lite-gui.exe
                                         # 对着真 exe 点一次登录，检查窗口是否响应
```

`run_tests.py` 的关键设计：**用假时钟把 300 秒的视频循环在毫秒内跑完**，
所以能真正断言节拍逻辑（而不是靠读代码猜）：

```
[ok] 300 秒视频产生 8 次上报
[ok] 上报间隔互不相同: [34.94, 32.1, 40.16, 30.03, 29.24, 34.73]
[ok] 没有任何一次恰好落在 30.0s（对照原实现）
```

改节拍相关代码后，这个测试必须仍然通过。

### 5.3 打包

```bash
python packaging/build.py release        # 出全部四个 exe（含自检）
python packaging/build.py gui            # 只出 GUI 版
python packaging/build.py full --gui     # 只出完整版 GUI
python packaging/build.py lite --no-test # 快速迭代，跳过自检
```

产物在 `dist/`。**自检不是可选项** —— 它会：

1. 启动 GUI，观察 12 秒确认窗口进程没提前退出
2. 自动点一次「扫码登录」，用 `IsHungAppWindow` 确认窗口仍响应
3. 跑 `--selfcheck` 查依赖和系统浏览器

### 5.4 发布

```bash
git tag -a v1.2.6 -m "v1.2.6 修 xxx"
git push origin v1.2.6
```

CI 会自动：跑测试 → 构建 4 个 exe → 逐个自检 → 检查体积 →
上传到 Release。约 7 分钟。

⚠️ 发布前确认 `packaging/build.py` 的产物名和
`.github/workflows/release.yml` 里 `files:` 列表一致，
否则会出现"构建成功但 Release 缺文件"。

---

## 6. 踩过的坑（必读）

这一节是整份文档最有价值的部分。每条都是真实发生过的。

### 6.1 tkinter 被 exclude，四个 exe 的 GUI 全崩

**现象**：用户下载 v1.2.0 的 GUI 版，双击就一屏 traceback
`No module named 'tkinter'`。

**根因**：`packaging/zhs-ghost.spec` 的 `excludes` 里为了省 8MB 写了
`"tkinter"`，而那个列表**对所有变体生效**，包括 GUI 版。
CLI 版也支持 `--gui`，同样受影响。

**为什么自检没拦住**：GUI 版的自检跑的是 `--selfcheck`，而那条路径是
`gui.py` 带参数 → `from zhsgo.cli import main` → **根本不 import tkinter**。
自检全绿、CI 全绿，用户一下载就崩。

**教训**：**自检走的路径必须等于用户实际走的路径**。
现在 GUI 版的自检会真的启动它、真的点一次按钮。

### 6.2 点「扫码登录」窗口未响应 —— loguru 自递归

**现象**：点一下按钮，整个窗口卡死。

**根因**：`_StreamProxy`（给 windowed exe 补的 stdout/stderr 兜底）
把写入转发给了 loguru：

```python
def write(self, text):
    log().log(self._level, line)      # ← 问题在这
```

而 `App.__init__` 里 `setup_logging()` 会把 `sys.stderr` 注册成一个 loguru sink。
于是：

```
写日志 → 触发 stderr sink → _StreamProxy.write → 再调 loguru
      → 再触发 stderr sink → … 无限递归
```

复现出来是 `RecursionError: maximum recursion depth exceeded` +
`lost sys.stderr`。

**教训**：
- **永远不要把一个 stream 代理接回日志系统**。要写就写文件，绕开 loguru。
- `import` 检查发现不了这个 —— 必须真的跑一遍 `setup_logging()`。
  这就是 `tests/check_stream_proxy.py` 存在的原因。

### 6.3 二维码被 pack 压扁到看不见

**现象**：点「扫码登录」没有任何反应，界面上一片空白。

**根因**：二维码是主界面最后一张卡片（`pack()` 默认追加到末尾），
而主界面高度不够：

```
账号卡 142 + 任务卡 218 + 二维码 300 + 按钮行 50 + 提示 30 = 740
实际可用高度                                            = 593
```

Tk 的 pack 在空间不足时会**压缩控件** —— 实测 240×240 的图被压成
**240×94**。

**教训**：**控件"存在"不等于"可见"**。
排查时打印实际尺寸，一眼就能区分"图没生成"和"图生成了但被挤掉"：

```
to_photo -> 240x240      ← 图片本身没问题
qr_label 尺寸: 240x94    ← 被布局压扁了
```

现在二维码用独立窗口（Toplevel）显示，380×380，不跟主界面抢空间。

### 6.4 截图截进了桌面其他窗口

**现象**：README 里的界面截图，边缘能看到别的窗口的碎片。

**根因**：截图边界用的是 `GetWindowRect`，它返回的是**含 DWM 阴影**的外框。
Windows 10/11 那圈不可见边框约 8px，于是左右下三边各带进来一条。

**教训**：用 `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`
拿可见边界，四边再内缩 2px。

**另外**：截图脚本 `MainWindow()` 会读用户本地的 `config.yaml`，
而配置页会把里面的账号、**密码**、代理、推送 token 原样填进表单 ——
直接截图等于把它们发到仓库。而且 `on_close()` 会把演示数据**写回**
用户的真实配置（跑一次截图就覆盖一次）。

现在的做法：截图前整个替换成 `Config.from_dict({})`，并把 `cfg.save()` 打桩。

**建议**：以后生成截图**先切到一个干净桌面**，或者用虚拟机。
只靠裁剪总有边界情况。

### 6.5 CI 上中文输出直接崩

**现象**：GitHub Actions 的 windows-latest 上，测试挂在第一个 `print`。

```
UnicodeEncodeError: 'charmap' codec can't encode characters in position 5-6
```

**根因**：Windows runner 控制台编码是 cp1252。本地开发机是 UTF-8，
所以一直没暴露。

**教训**：脚本里显式 `stream.reconfigure(encoding="utf-8", errors="replace")`，
workflow 再补 `PYTHONIOENCODING=utf-8` 和 `PYTHONUTF8=1`。
**这种问题只有真跑 Windows CI 才能发现。**

### 6.6 PyInstaller 报 PermissionError 拒绝访问

**现象**：`PermissionError: [WinError 5] 拒绝访问: dist\zhs-ghost-gui.exe`

**根因**：上一轮自检启动的 GUI 进程没被完全回收，正在运行中的 exe 会锁住文件。

**教训**：`build_one()` 现在会先 `taskkill /F /T /IM <name>.exe`。

### 6.7 校内课死循环（原项目遗留）

`fuckZHS` 的 `fuckHikeVideo`：

```python
while played_time <= end_time:
    ...
    prev_time, played_time = ret_time, ret_time    # 服务端返回值原地不动 → 死循环
```

服务端返回的累计时间如果不变，循环条件永远成立。

**教训**：**循环条件不要依赖服务端返回值**。现在的写法是只采纳
"服务端比我们走得更远"的值，绝不回退。

### 6.8 `Config.save()` 会写出绝对路径和 tuple

`yaml.safe_dump` 序列化不了 tuple，必须转 list；
绝对路径写进配置文件后换台机器就废了，必须转回相对路径。
见 `zhsgo/config.py` 的 `to_dict()` / `_relativize()`。

### 6.9 高 DPI 下截图裁错区域

进程如果不声明 DPI aware，`GetWindowRect` 返回的是被系统虚拟化过的
逻辑坐标，而 `ImageGrab` 抓的是物理像素 —— 150% 缩放下两者差 1.5 倍，
截出来只有窗口左上角一小块。

**教训**：截图脚本开头先 `SetProcessDpiAwareness(2)`，
**必须在创建 `Tk()` 之前调用**。

### 6.10 `--selfcheck` 本身也不检查 tkinter

6.1 的连带问题。现在 `zhsgo/cli.py` 的 `selfcheck()` 里补上了
`tkinter` 和 `tkinter.ttk` 两项 —— 用户自己也能诊断出来。

---

## 7. 红线

改代码前请务必遵守：

1. **不要提交 `config.yaml` / `state/` / `logs/`**。它们含账号、密码、
   登录凭证、浏览器指纹。`.gitignore` 已排除，但 `git add -f` 之类会绕过去。
2. **不要在 GUI 主线程里做网络或重计算**。所有耗时操作走 `Worker` 线程，
   结果通过 `Bridge` 回主线程。Tkinter 不是线程安全的。
3. **不要把 stream 代理接回 loguru**。见 6.2。
4. **不要 exclude `tkinter`**。见 6.1。
5. **自检必须走用户实际走的路径**。见 6.1。
6. **不要复用加密后的 payload 重发**。`secretStr` 含随机 IV，
   复用是明显的机器人特征。
7. **不要动 `Pacer.ts_ms()` 这个统一出口**。时间戳散落各处正是原项目的病根。
8. **生成截图前先切干净桌面**。见 6.4。
9. **`relay/` 只允许被 `risk/guard.py` 调用**，API 层不许 import 它。

---

## 8. 常见维护场景

### 平台改了接口

1. 抓包确认新参数，改 `zhsgo/net/endpoints.py`
2. 改对应的 `zhsgo/api/*.py`
3. 如果签名/加密变了：
   - 校内课签名 → `zhsgo/crypto/signature.py`
   - 请求加密密钥 → `zhsgo/crypto/aes.py`
   - `ev` 编码 → `zhsgo/crypto/ev.py`
4. 跑 `python tests/run_tests.py`

接口分析的方法论在 `fuckZHS` 的 README 里有完整记录
（反混淆前端、找 salt、找密钥），那份文档很值得读。

### 平台加了新的风控

先看是不是新的错误码：

```python
# zhsgo/net/endpoints.py
CODE_CAPTCHA = -12          # 服务端风控：要求人机验证
```

如果是新的码，在 `ZhidaoApi.call()` 里加分支。
如果还是 -12 但过检后仍被拦，说明中继策略需要调整 ——
看 `GuardConfig.retry_after_unlock` 和 `relay/wait_captcha_seconds`。

### 加一个新的配置项

1. 在对应子系统的 config dataclass 里加字段（如 `PacerConfig`）
2. `config.example.yaml` 加注释说明
3. 如果 GUI 要暴露，在 `zhsgo/gui/tab_config.py` 加一行 +
   `reload()` / `_save()` 各加一条
4. `Config.to_dict()` 里如果涉及路径要记得 `_relativize()`

### 加一个新的 GUI 页面

1. 抄 `zhsgo/gui/tab_courses.py` 的结构
2. 在主窗口 `_build_tabs()` 里 add
3. `tests/gui_smoke.py` 里补几项断言

### 更新界面截图

```bash
python tests/_screenshot.py        # 主界面四张
```

`_shot_qr.py` 已经删了，需要二维码截图的话参考 git 历史里的那个版本。
**跑之前先切到干净桌面。**

---

## 9. 参考

| 资料 | 位置 |
|---|---|
| 使用教程（面向用户） | `docs/使用教程.md` |
| 打包说明 | `docs/打包说明.md` |
| 免责声明 | `DISCLAIMER.md` |
| 原项目接口分析 | https://github.com/VermiIIi0n/fuckZHS 的 README |
| 风控根因分析 | README 第 2 节 |

---

## 10. 一句话总结

这个项目的技术含量不在"能刷课"，在于**把服务端风控当成一等公民来设计**，
以及**每一次发布都真的验证过用户会走的那条路径**。

前一任维护者在这上面栽过两次（6.1、6.2），都是"自检绿灯但用户一用就崩"。
留下这份文档主要是希望别有第三次。
