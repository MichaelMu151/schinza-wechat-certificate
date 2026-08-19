<p align="center">
  <img src="assets/logo.png" alt="Schinza" width="128" height="128" />
</p>

<h1 align="center">Schinza · run from source</h1>

<p align="center">
  <a href="./README.md"><b>English</b></a> · <a href="./README.zh-CN.md">中文</a>
</p>

<p align="center">
  Start the desktop UI with <b>Python</b> (<code>main.py</code>). Capture ~30‑minute
  Official Account credentials from WeChat Desktop, page the history list, then
  archive article bodies slowly. This fork is meant to be run from source — not
  from the upstream DMG / exe.
</p>

> Based on upstream Schinza 1.8.9. Feature branch:
> [`scalable-archive`](https://github.com/MichaelMu151/schinza-wechat-certificate/tree/scalable-archive)
> (version **1.9.7**). Upstream `main` and GitHub Releases **do not** include
> full-history resume or list-first archiving.

The step-by-step Chinese guide is the canonical walkthrough:
[README.zh-CN.md](./README.zh-CN.md). This page is the English counterpart.

---

## What this tool does

| Step | Needs 30‑min `uin`/`key`? | Speed | Where |
|------|---------------------------|-------|--------|
| Capture credentials | — | once | this repo, source GUI |
| Page history **list** | **yes** | ~1 s/page | History tab |
| Download article **bodies** | **no** | 8–15 s/article | History tab |
| Merge into legacy SQLite | no | offline | sibling `wechat_crawler` |

Use the half-hour window **only for paging**. If the list is incomplete, renew
and continue. Bodies can wait until credentials expire.

Suggested layout:

```text
wechat-work/
├── name_list.xlsx
├── wechat_crawler/
└── schinza-wechat-certificate-main/   ← this repo
```

---

## Requirements

- macOS 12+ or Windows 10/11
- WeChat **Desktop** signed in
- Python **3.11+ with Tk** (`_tkinter`)
- Git
- Only accounts you are allowed to archive

**Intel Mac:** Homebrew Python 3.13 often has no `_tkinter`. Use python.org
**Python 3.14** and the `.venv-intel` environment:

```bash
cd "$HOME/Desktop/wechat-work/schinza-wechat-certificate-main"
.venv-intel/bin/python main.py
```

Do not launch `.venv-313` or a brew `python3`.

---

## Clone this branch

```bash
mkdir -p "$HOME/Desktop/wechat-work"
cd "$HOME/Desktop/wechat-work"
git clone --branch scalable-archive \
  https://github.com/MichaelMu151/schinza-wechat-certificate.git \
  schinza-wechat-certificate-main
```

Updates: `git pull` on `scalable-archive`. Check version:

```bash
.venv-intel/bin/python -c "from app import __version__; print(__version__)"
# 1.9.7
```

---

## Install and start

Entry point is always `main.py`.

**Intel macOS**

```bash
cd "$HOME/Desktop/wechat-work/schinza-wechat-certificate-main"
/usr/local/bin/python3.14 -m venv .venv-intel
.venv-intel/bin/python -m pip install --upgrade pip
.venv-intel/bin/pip install -r requirements.txt
.venv-intel/bin/python main.py
```

**Apple Silicon macOS**

```bash
python3 -m venv .venv-mac
.venv-mac/bin/pip install -r requirements.txt
.venv-mac/bin/python main.py
```

**Windows**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

On the History tab the primary button is **拉取列表并归档** while credentials
are valid, and **继续归档正文** after they expire. There are no article cards
or checkboxes.

---

## First capture

1. **Credential Manager** → **Install CA**. On macOS, `security` may ask for
   your login password.
2. **Fully quit WeChat Desktop** (menu-bar icon too) and reopen it so the
   `127.0.0.1:8088` proxy and CA apply.
3. Fill in the Official Account name (must match `name_list.xlsx` later) plus
   any public article URL → **Add & Capture**.
4. In WeChat, **re-open** an article from that account (do not only refresh an
   old tab). If `key` is still missing, scroll the account history page to
   trigger `getmsg`.
5. The card should become active with a ~30‑minute countdown. Secrets land in
   `data/accounts.json` — never commit or share that file.

If `data/capture_debug.log` is empty, WeChat is not using the proxy: quit
WeChat again. If the log says credentials are incomplete, scroll history.
After you quit Schinza, turn off a leftover manual proxy at `127.0.0.1:8088`
if the browser has no network.

---

## List first, bodies later

On **History Articles**, pick the account (default: all history) and click
**拉取列表并归档**.

- Listing uses the 30‑minute window and writes `data/history_cache.sqlite`.
  Paging stops ~90 seconds before expiry.
- Bodies start **only after the list is complete**. Public HTML is fetched
  **without** expired cookies, one request at a time, 8–15 s apart.
- If the window ends with an incomplete list, bodies are **not** started, so
  you can renew immediately and keep paging.
- After expiry, **继续归档正文** downloads cached URLs. Already-written files
  in `data/archives/<account>/` are skipped.

HTTP 429, `unknownerror`, or “too frequent” pages **stop the job**. Wait hours
to a day. Do not raise concurrency.

Renew: Credential Manager → **Renew** → restart WeChat if needed → re-open the
article or scroll history → same account on the History tab → click again.
Paging resumes from the cached offset.

On macOS, **无人值守归档** (v1.9.7) finishes one account before the next:
list until complete (recapture the same account if the 30-minute window
ends), then archive bodies slowly, then move on. This avoids paging many
accounts back-to-back, which triggers WeChat rate limits. Safari still
opens a **new tab**, clicks `#js_name`, then 「前往」 at fullscreen
coordinates (958, 640). Cards are not deleted. Rate-limit errors stop the
whole queue. The canonical walkthrough is the **操作指南** in
[README.zh-CN.md](./README.zh-CN.md).

Archive layout (no short-lived secrets):

```text
data/archives/<account>/
├── manifest.json / manifest.jsonl
├── articles/
├── archive_index.sqlite
├── job_state.jsonl
├── failures.jsonl
└── summary.json
```

---

## Merge into SQLite

```bash
cd "$HOME/Desktop/wechat-work/wechat_crawler"
source .venv/bin/activate
python run.py import-list
python run.py import-schinza-export \
  --manifest "../schinza-wechat-certificate-main/data/archives/<account>/manifest.json" \
  --articles-dir "../schinza-wechat-certificate-main/data/archives/<account>/articles"
python run.py status
```

See the [crawler README](https://github.com/MichaelMu151/wechat_crawler/blob/cursor/wechat-archive-enhancements/README.md).

---

## Troubleshooting

| Symptom | What to do |
|---------|------------|
| `No module named '_tkinter'` | Use `.venv-intel` / python.org 3.14 on Intel Mac |
| UI looks like the old app | You launched `Schinza.app`, not `python main.py` on `scalable-archive` |
| `unknownerror` | Server-side rate limit; wait; do not hammer “all history” |
| Renew does nothing | Restart WeChat; re-open article or scroll history; read `capture_debug.log` |
| Credentials expired | Bodies can continue; listing needs a renew |

---

## Security

Use only on accounts you may archive. Do not publish CA private keys or live
`uin` / `key` / `pass_ticket`. History fetches set `trust_env=False` so the
capture proxy does not intercept body downloads. The Sync Server tab has **no**
built-in URL.

```bash
.venv-intel/bin/python -m pytest tests -q
```

Do not commit `data/`, `.venv*`, `dist/`, or CA private keys.

---

## Optional packaging

Daily use is source. Scripts: `build.ps1`, `build_mac.sh`, `build_mac_x64.sh`
(Intel, Rosetta 2). Capture-capable builds need a private CA — never commit it.
Upstream Releases are **not** this fork.

---

## License and disclaimer

[MIT License](LICENSE). Provided for learning, research, and legitimate
self-hosted use. You accept the consequences. Authors are not liable for bans,
leaks, or third-party misuse. Not affiliated with Tencent or WeChat.
