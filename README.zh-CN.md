<p align="center">
  <img src="assets/logo.png" alt="Schinza" width="128" height="128" />
</p>

<h1 align="center">Schinza · 源码使用指南</h1>

<p align="center">
  <a href="./README.md">English</a> · <a href="./README.zh-CN.md"><b>中文</b></a>
</p>

<p align="center">
  在本机用 <b>Python 源码</b>启动桌面界面，从微信桌面捕获约 30 分钟有效的公众号凭证，<br />
  翻页拉取历史列表，再慢速归档正文。不依赖发行版 App / DMG / exe。
</p>

> 本 fork 基于上游 Schinza 1.8.9，保留原有凭证捕获流程。  
> 当前功能分支：[`scalable-archive`](https://github.com/MichaelMu151/schinza-wechat-certificate/tree/scalable-archive)（版本 **1.9.5**）。  
> 上游 `main` 与 GitHub Releases 里的预编译包**不包含**本指南中的全历史续拉与列表优先归档。

---

## 这份指南解决什么问题

学术存档需要「某个公众号的全部历史标题 + 正文」。微信把历史列表接口（`getmsg`）和文章网页分开了：

| 步骤 | 要不要 30 分钟凭证 | 速度 | 在哪做 |
|------|-------------------|------|--------|
| 捕获 `uin` / `key` | — | 一次抓包 | 本仓库源码 GUI |
| 翻页拉历史**列表** | **要** | 约 1 秒/页 | 本仓库「历史文章」 |
| 下载文章**正文** | **不要** | 8–15 秒/篇 | 本仓库「历史文章」 |
| 写入原来的 SQLite | 不要 | 离线 | 同级仓库 `wechat_crawler` |

因此：**半小时窗口只用来翻页**。列表没拉完就先续约；正文可以等凭证过期后再慢慢下。不要用预编译 App 代替本分支源码。

推荐工作目录：

```text
wechat-work/
├── name_list.xlsx
├── wechat_crawler/                      ← SQLite 离线合并
└── schinza-wechat-certificate-main/     ← 本仓库（源码）
```

---

## 1. 运行环境

- macOS 12+ 或 Windows 10/11
- 已登录的**微信桌面客户端**（不要只用手机）
- **Python 3.11+**，且必须带 Tk（GUI 依赖 `_tkinter`）
- Git
- 只处理你有权存档的公众号

### Intel Mac 必读

本机若是 Intel Mac，不要用 Homebrew 的 Python 3.13 跑 GUI：常见报错是 `ModuleNotFoundError: No module named '_tkinter'`。

请使用 python.org 的官方安装包（当前实测可用 **Python 3.14**，带 Tk 9），虚拟环境目录约定为 `.venv-intel`：

```bash
cd "$HOME/Desktop/wechat-work/schinza-wechat-certificate-main"
.venv-intel/bin/python main.py
```

不要用 `.venv-313` 或系统 `python3` 直接启动。

---

## 2. 克隆本分支

```bash
mkdir -p "$HOME/Desktop/wechat-work"
cd "$HOME/Desktop/wechat-work"

git clone --branch scalable-archive \
  https://github.com/MichaelMu151/schinza-wechat-certificate.git \
  schinza-wechat-certificate-main
```

之后更新（不要切到上游 `main`）：

```bash
cd "$HOME/Desktop/wechat-work/schinza-wechat-certificate-main"
git pull
```

确认版本：

```bash
# Intel Mac
.venv-intel/bin/python -c "from app import __version__; print(__version__)"
# 应显示 1.9.5
```

Apple Silicon / Windows 把上面的解释器换成第 3 节里对应的路径。

---

## 3. 安装依赖并启动（源码）

入口永远是仓库根目录的 `main.py`。首次会打开 CustomTkinter 窗口。

### 3.1 Intel macOS（推荐路径）

```bash
cd "$HOME/Desktop/wechat-work/schinza-wechat-certificate-main"

# 若还没有 .venv-intel：用官方 python.org 的 3.14
/usr/local/bin/python3.14 -m venv .venv-intel
.venv-intel/bin/python -m pip install --upgrade pip
.venv-intel/bin/pip install -r requirements.txt

.venv-intel/bin/python main.py
```

每次使用只需要最后一行。不要 `source` 进错误的 venv 后再跑。

### 3.2 Apple Silicon macOS

```bash
cd "$HOME/Desktop/wechat-work/schinza-wechat-certificate-main"

python3 -m venv .venv-mac
.venv-mac/bin/pip install --upgrade pip
.venv-mac/bin/pip install -r requirements.txt
.venv-mac/bin/python main.py
```

### 3.3 Windows

```powershell
cd $HOME\Desktop\wechat-work\schinza-wechat-certificate-main

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

启动后左侧应能看到三个页签：**凭证管理**、**历史文章**、**同步服务器**。  
「历史文章」页主按钮在凭证有效时应为 **拉取列表并归档**，过期后变为 **继续归档正文**；没有文章卡片、全选或勾选框。

---

## 操作指南（Intel Mac，版本 1.9.5）

环境已经装好、公众号已经批量导入之后，日常只做下面几步。

### A. 每次开跑前

1. Mac **不合盖、不锁屏**，接上电源更好。程序会调用 `caffeinate -dim` 防止空闲休眠，但合盖仍可能睡。
2. **微信桌面已登录**，不要只开手机微信。
3. 第一次用无人值守时，打开权限（之后不用再改）：
   - 系统设置 → 隐私与安全性 → **辅助功能**：勾选 Terminal，以及 python.org 的 Python（`/usr/local/bin/python3.14` 或 `.venv-intel` 实际用的那个解释器）。
   - Safari → 设置 → 高级 → 勾选「显示开发者功能」；菜单「开发」→ 勾选 **允许来自 Apple 事件的 JavaScript**。
4. 启动（只用这一条，不要用 Homebrew Python）：

```bash
cd "$HOME/Desktop/wechat-work/schinza-wechat-certificate-main"
git pull
.venv-intel/bin/python -c "from app import __version__; print(__version__)"   # 1.9.5
.venv-intel/bin/python main.py
```

### B. 无人值守只拉列表

1. **凭证管理**：把要处理的号都设成 **等待凭证**（可用「一键续约全部」）。已经在倒计时、列表还没拉完的号也会自动排进队列，不必再点 Safari。
2. **历史文章** → 时间范围选 **全部历史**（除非你只要近几天）→ **无人值守拉列表**。
3. 对每个「等待凭证」的号，程序会：用 Safari **新建标签**打开文章 → 等蓝字公众号名 `#js_name` 出现 → **只点这个蓝字** → 点 Safari 系统弹窗的「前往」（不是网页按钮）→ 等微信打开并入库凭证 → **只翻页拉列表** → 间隔约 6 秒换下一个。
4. **不要删号。** 卡片留着才能续拉列表、夜里下正文、再导入 SQLite。
5. **不要合盖。** 出现 `unknownerror` / 429 /「频繁」时整队停止，等数小时到一天，不要连点重试。
6. 想停就点 **停止队列**。已写入 `data/history_cache.sqlite` 的页会保留。

### C. 列表拉完之后

正文不跟列表抢那 30 分钟。夜里或凭证过期后，在历史文章里对该号点 **继续归档正文**（单请求、每篇 8–15 秒）。不要提高并发。

### D. 再写入原来的 SQLite

见第 7 节。公众号名称必须与卡片名、`name_list.xlsx` 完全一致。真实归档目录在 `data/archives/` 下，以卡片名为文件夹，例如 `data/archives/曲靖市妇幼保健院/`，不是文档里的占位符「公众号名称」。

---

## 4. 第一次抓包（必须按顺序）

凭证来自微信桌面内置浏览器访问公众号时的短期参数：`__biz`、`uin`、`key`、`pass_ticket`。本程序在本机 `127.0.0.1:8088` 开一个 MITM 代理把它们截下来。**不会把密钥上传到任何默认服务器。**

### 4.1 安装 CA 并重启微信

1. 打开 **凭证管理**。
2. 点 **安装 CA 证书**。macOS 会调用 `security`，可能要输入本机登录密码。
3. **完全退出微信桌面**（菜单栏图标也要退出），再重新打开。只刷新文章页不够，代理和证书必须在微信启动时就生效。

可选：若本机已有完整 mitmproxy CA（含私钥），可放在 `~/.mitmproxy/mitmproxy-ca.pem`。不要把私钥提交 Git 或发给别人。

### 4.2 添加一个公众号

1. 名称必须与日后 `name_list.xlsx` 的 `nickname` **逐字一致**（含空格、医院全称）。
2. 「文章链接」填该号任意一篇公开文章 URL（短链也可以）。
3. 点 **添加并抓包**。卡片状态会变成等待捕获。

批量：可用 **批量导入**（CSV/TXT，第一列公众号名、第二列文章链接，逗号或 Tab 分隔，自动识别表头）。第一次建议只加一个号，跑通再批量。

### 4.3 在微信里触发完整凭证

1. 回到**微信桌面**，打开该公众号的一篇文章（建议重新打开，不要只刷新旧标签）。
2. 若仍无完整 `key`，进入该号历史消息页并**向下滚动**，促使微信发出 `getmsg`。
3. Schinza 卡片应变为 active，并出现约 **30 分钟**倒计时。

看 `data/capture_debug.log`：

| 日志 | 含义 |
|------|------|
| 「凭证已保存」 | 已捕获，等待界面刷新 |
| 「截获…凭证不完整」 | 流量到了代理但缺 `key`，去滚动历史页 |
| 文件为空 | 微信没走代理 → 再退出并重启微信 |

凭证写入 `data/accounts.json`。其中含短期密钥，**不要提交 Git、不要上传网盘、不要发给他人**。

### 4.4 退出后网络异常

正常退出 Schinza 会恢复系统代理。若浏览器上不了网：关闭系统「手动代理」，确认不再指向 `127.0.0.1:8088`，再重启 Schinza / 微信。

---

## 5. 拉列表和下正文（效率关键）

打开 **历史文章**：

1. 选择刚抓到的公众号（下拉框会显示「列表窗口剩余 …」）。
2. 时间范围默认 **全部历史**（也可近 7 / 30 / 90 天或自定义）。
3. 点 **拉取列表并归档**。

界面只显示篇数、页数、用时和正文进度，无需勾选。

### 程序实际在做什么

1. **凭证有效时只翻页。** `getmsg` 需要 `uin`/`key`。每页约 1 秒，半小时可以缓存几千条 URL 到 `data/history_cache.sqlite`。窗口结束前约 90 秒会停止再开新页，避免用过期 key 请求。
2. **列表拉完后才自动下正文。** 正文是公开 HTML，不带过期 cookie（过期 cookie 可能把公开页打成登录页）。单请求，每篇随机等待 **8–15 秒**。
3. **列表没拉完而窗口到了：** 不开始数小时正文任务，以便你立刻续约继续翻页。状态会提示缓存了多少篇。
4. **凭证已过期、列表已在本地：** 按钮变成 **继续归档正文**，可慢慢把已缓存 URL 下完。

一个发文很多的号，列表往往要 **好几轮 30 分钟**。正文可以放到夜里跑，两者不要抢同一段凭证时间。

### 续约后再拉列表

1. 在 **凭证管理** 点该号 **续约**（不会弹出系统浏览器）。
2. **重启微信**（若代理刚重开），再重新打开该号文章或滚动历史页。
3. 倒计时恢复后，到 **历史文章** 选同一账号，再点 **拉取列表并归档**。翻页从缓存的 `next_offset` 继续，不会从头来。

### 无人值守拉列表（macOS，1.9.5）

细节与权限见上文 **操作指南**。补充行为说明：

- 队列顺序：**仍有效且列表未完成的号优先**（不再开 Safari），然后才是「等待凭证」且带文章链接的号。
- 开始前会探测辅助功能与 Safari 自动化；失败会在历史页直接提示，而不是第一个号默默失败。
- Safari 用**新标签**打开文章，等到 `#js_name` 出现才点击，避免点到别的链接。
- 「前往」通常是 Safari **系统弹窗**（不是网页里的按钮）。程序会点弹窗右侧确认键，必要时再按回车。必须打开「辅助功能」，否则只能点到蓝字、弹窗会停在那里。
- 点完「前往」后会再等几秒，给微信打开页面、MITM 入库的时间。
- 号与号之间约 6 秒，且可被「停止队列」打断。
- 100 页以上的号若 30 分钟没拉完，会留下断点并换下一个；以后续约接着翻。
- 频控（`unknownerror` / 429 / 频繁）**整队停止**。卡片不删除，正文另做。

### 正文节奏与风控

- 不会并发下载多篇。
- 短暂网络错误：最多再试 2 次（间隔加长）。
- 连续三篇最终失败：冷却 1–2 分钟再继续。
- 出现 HTTP **429**、`unknownerror`、或页面写「访问过于频繁」：**立即停**，等数小时到一天。不要提高并发、不要连点重试。
- 续跑同一账号即可：已写入 `data/archives/公众号名/` 的正文会跳过。

---

## 6. 归档目录（给 SQLite 用）

```text
data/archives/公众号名/
├── manifest.json        # 目录；wechat_crawler 的 --manifest 指向这里
├── manifest.jsonl       # 超过约 1 万篇时以这个为准
├── articles/            # 正文文件（默认 Markdown）
├── archive_index.sqlite # 已完成 / 失败索引，用于续跑
├── job_state.jsonl      # 逐篇事件
├── failures.jsonl       # 失败明细
└── summary.json         # 汇总
```

这些文件不含微信短期密钥。不要删 `history_cache.sqlite` 或该归档目录，否则续跑会丢失进度。

---

## 7. 合并进原来的 SQLite

在线工作到此结束。把结果交给同级的 `wechat_crawler`（完全离线，不再访问微信）：

```bash
cd "$HOME/Desktop/wechat-work/wechat_crawler"
source .venv/bin/activate
python run.py import-list
python run.py import-schinza-export \
  --manifest "../schinza-wechat-certificate-main/data/archives/公众号名称/manifest.json" \
  --articles-dir "../schinza-wechat-certificate-main/data/archives/公众号名称/articles" \
  --dry-run
# 确认 matched_account=true 后去掉 --dry-run
python run.py status
```

详细命令、表结构与分析示例见 [`wechat_crawler` README](https://github.com/MichaelMu151/wechat_crawler/blob/cursor/wechat-archive-enhancements/README.md)。  
公众号名称必须与 `name_list.xlsx` 以及本程序卡片上的名称完全一致。

---

## 8. 常见问题

### `ModuleNotFoundError: No module named '_tkinter'`

用了不带 Tk 的 Python（Intel Mac 上常见于 Homebrew 3.13）。改用第 3.1 节的 `.venv-intel`（python.org 3.14）。

### 点了启动但界面和发行版一样，没有「拉取列表并归档」

跑的不是本分支源码。确认：

```bash
cd "$HOME/Desktop/wechat-work/schinza-wechat-certificate-main"
git branch --show-current    # 应为 scalable-archive
.venv-intel/bin/python -c "from app import __version__; print(__version__)"  # 1.9.5
.venv-intel/bin/python main.py
```

不要从 Applications 里的 `Schinza.app` 启动。

### unknownerror / ret=-6

这是微信服务端风控，不是本地代理坏了。先确认系统手动代理已关且网页能打开；若仍出现：停数小时到一天，不要对多个号连开「全部历史」。持续出现可换一个微信账号抓包（避免主力号）。

### 续约没反应

续约依赖微信发出带 `__biz`+`uin`+`key` 的请求。只刷新旧文章页往往不够：重启微信 → 重新打开文章或滚动历史页 → 看 `data/capture_debug.log`。

### 凭证已失效

列表接口 30 分钟过期。过期后仍可 **继续归档正文**；要接着翻页必须先续约。

### 历史文章下拉框没有该号

先在凭证管理抓过包（哪怕已过期）。过期号会显示「凭证已过期，可继续归档正文」。若从未捕获到 `__biz`，需要重新添加并抓包。

---

## 9. 安全与使用规范

- 仅在你有权操作的账号与设备上使用；遵守微信 / 腾讯服务条款与相关法律。
- 勿公开 CA 私钥，勿泄露 `uin` / `key` / `pass_ticket`。
- 只存标题、作者、时间、正文等存档字段，不抓阅读量 / 点赞。
- 历史请求绕过系统 MITM 代理（`trust_env=False`），避免抓包代理干扰正文下载。
- 同步服务器页签没有内置地址；只有你自己填写 URL 时才会上传匹配到的凭证。

---

## 10. 目录结构（源码）

```text
├── main.py                 # 唯一启动入口
├── requirements.txt
├── app/
│   ├── ui.py               # 桌面界面
│   ├── mitm_capture.py     # 本机代理
│   ├── mitm_addon.py       # 截凭证
│   ├── history_client.py   # getmsg 翻页
│   ├── history_pipeline.py # 列表优先，再归档正文
│   ├── history_cache.py    # data/history_cache.sqlite
│   ├── archive_job.py      # 慢速正文
│   ├── article_reader.py   # 解析公开文章 HTML
│   ├── safari_handoff.py   # Safari → 点蓝字 / 前往
│   ├── unattended_queue.py # 无人值守队列（先有效号，再等待凭证）
│   └── store.py            # data/accounts.json
├── data/                   # 本地数据，勿提交
└── tests/
```

```bash
.venv-intel/bin/python -m pytest tests -q
```

请勿提交 `data/*.json`、`data/*.sqlite`、`.venv*`、`dist/` 或 CA 私钥。

---

## 附录：打包发行版（可选）

日常请用源码。若要自己打安装包：

```powershell
.\build.ps1          # Windows → dist\Schinza\Schinza.exe（分发整个文件夹）
```

```bash
./build_mac.sh       # Apple Silicon → dist/Schinza.app
./build_mac_x64.sh   # Intel，需 Rosetta 2 与 python.org universal2 Python
```

构建可抓包二进制需要带私钥的 CA，**切勿把私钥推进公开仓库**。上游 Releases 是原作者的包，不是本 fork 的 `scalable-archive`。

---

## 开源协议与免责声明

[MIT License](LICENSE)。本软件仅供学习、研究与合法自用。下载或运行即视为自行承担后果；作者不对封禁、泄露或第三方滥用负责。Schinza 与腾讯 / 微信无关联。不同意请勿使用。
