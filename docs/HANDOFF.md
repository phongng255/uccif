# UCCIF — Handoff & Context

> **Đọc file này trước tiên** nếu bạn là AI (hoặc người) mới tiếp nhận UCCIF.
> Nó gom toàn bộ ngữ cảnh, quyết định, sự cố đã gặp và cách làm việc với framework,
> để không phải hỏi lại người dùng những gì đã thống nhất.
>
> Cập nhật: 2026-11-03 · Phiên bản code: **3.0.0-dev.4** (commit `286613b` trên `main`)
> Repo: https://github.com/phongng255/uccif
>
> Ký hiệu: ✅ đã chốt / đã kiểm chứng · 🟡 đề xuất, chưa chốt · ❓ câu hỏi mở · ⚠️ cạm bẫy đã gặp

---

## 0. Cách dùng tài liệu này (cho AI)

1. Đọc mục 1–3 để hiểu mục tiêu và trạng thái hiện tại.
2. Trước khi đề xuất thay đổi, đọc mục 6 (quyết định) và mục 7 (sự cố). Phần lớn "ý tưởng hay"
   đã được cân nhắc ở đó; đừng đề xuất lại thứ đã bị loại mà không có lý do mới.
3. Đừng coi 🟡 là quyết định của người dùng.
4. Kiểm tra docs Claude Code hiện hành trước khi sửa `plugin.json`, `hooks.json`, `.lsp.json`,
   frontmatter skill/agent: dữ kiện ở mục 5 được kiểm tra ngày 2026-11-03 (Claude Code 2.1.317).
5. Trả lời người dùng bằng **tiếng Việt**; code, comment, commit, file framework viết **tiếng Anh**.

---

## 1. UCCIF là gì

**UCCIF — Universal Claude Code Intelligence Framework**: bộ "trí nhớ + quy trình" cho
Claude Code mà người dùng (phongng255) tự xây, dùng chung cho mọi project của mình.

Mục tiêu (không đổi từ v1):
- Claude tự biết đọc gì, tìm code ở đâu **mà không quét lại cả repo**.
- Phân tích ảnh hưởng, chạy đúng test.
- Giữ tiến độ qua `/clear`, compact và phiên mới.
- **Tốn ít token nhất mà không giảm độ chính xác.**
- Người dùng **chỉ giao việc bằng lời**; không phải gõ lệnh `uccif`, không phải gọi tên skill.

Mong muốn cụ thể của người dùng (✅, nói rõ trong hội thoại):
- "Cài plugin vào là chạy, lo hết": index, LSP, khảo sát project, cập nhật khi code đổi.
- Prompt "làm chức năng A" thì Claude tự chạy workflow tối ưu token.
- Code đổi thì index/tài liệu tự cập nhật, không chạy tay.

---

## 2. Lịch sử ngắn

| Giai đoạn | Hình thức | Ghi chú |
|---|---|---|
| v2 → v2.1 | **Prompt ~800 dòng** (`UCCIF-Project-Setup.md`) dán vào Claude Code; Claude sinh CLAUDE.md, skills, agents, hooks và `uccif.py` (index SQLite, drift, log…) **ngay trong từng project** | v2 chặn quá nhiều → Claude rụt rè, đẩy việc cho người dùng → v2.1 mặc định `enforce: off` |
| Review v2.1 (2026-11-03) | — | Vấn đề lớn nhất: sinh lại cả framework ở mỗi project (mỗi project một bản khác nhau, dễ dở dang, tốn token). Nhiều mâu thuẫn nội bộ (mục 7.1) |
| 3.0.0-dev.1 | **Claude Code plugin** + marketplace trên GitHub | Code cố định có version + test; phần cần AI thu gọn thành skill `/uccif:init` |
| 3.0.0-dev.2 | Sửa sau review | Windows, fallback thư mục dữ liệu, chi phí hook, race task |
| 3.0.0-dev.3 | Index `.db` tự cập nhật, drift, LSP đóng gói | Đáp ứng "cài vào là lo hết" |
| 3.0.0-dev.4 | Chạy được trong Bash sandbox | Sửa lỗi "readonly database" gặp trên máy thật |

---

## 3. Trạng thái hiện tại ✅

**Đã kiểm chứng trên máy người dùng** (macOS arm64, Python 3.9.6, project web-app chuyến đi
Thái Lan: Vue 3 + Vite + TS + Pinia + Firebase, 82 file source):
- `uccif doctor`: không WARN/FAIL; hook session-start / user-prompt-submit / stop đều chạy,
  không lỗi, không chậm.
- Index: 88 file, 486 symbol, 304 import (205 nối được tới file trong repo).
- LSP TypeScript/JavaScript hoạt động (`typescript-language-server` đã cài).
- `/uccif:init` chạy lại không phải viết gì vì docs (commit `5a2552c` của project) còn khớp;
  `drift check` → No drift; `drift ack` đã lưu baseline.

**Kiểm chứng trong CI/máy dev:** 104 test pass (kể cả chạy bằng user thường để giả lập sandbox
chỉ-đọc); `claude plugin validate --strict` pass cho plugin và marketplace; Claude Code nhận
6 skill, 3 agent, 12 hook, 2 LSP server; chi phí context cố định ≈ 780 token/phiên.

**Hiệu năng đo thật** (repo Vue core, 541 file): build index 1,2 s; query ≈ 0,12 s;
hook mở phiên 0,1 s (build chạy nền); hook sau Edit 0,14 s.

**Chưa kiểm chứng:** Windows trên máy thật (CI Windows đang ở chế độ thử nghiệm,
`continue-on-error`); smoke test headless (cần secret `ANTHROPIC_API_KEY`, workflow chạy tay).

---

## 4. Kiến trúc

### 4.1 Cấu trúc repo
```text
uccif/                                   ← repo GitHub = marketplace "uccif"
├── .claude-plugin/marketplace.json
├── plugins/uccif/                       ← plugin lõi "uccif"
│   ├── .claude-plugin/plugin.json       ← version + userConfig (reply_language, token_report)
│   ├── .lsp.json                        ← LSP: typescript-language-server, pyright-langserver
│   ├── bin/uccif                        ← launcher sh: python3 → python → py -3; vào PATH của Bash
│   ├── scripts/uccif_main.py            ← entry Python, tự thêm sys.path (không dùng PYTHONPATH)
│   ├── hooks/hooks.json                 ← 12 hook, dạng shell có quote
│   ├── skills/  init · task-context · smart-code-search · code-impact-analysis · code-review · resume
│   ├── agents/  project-analyst · code-impact-analyzer · change-reviewer   (chỉ đọc)
│   └── uccif_lib/
│       ├── paths.py    root project, data dir, khoá file, local dir
│       ├── rules.py    CORE RULES (nguồn duy nhất)
│       ├── hooks.py    xử lý từng hook event, spawn nền, đề nghị cài LSP
│       ├── index.py    index SQLite: files, symbols, imports, tests; query
│       ├── drift.py    phát hiện thay đổi cấu trúc → nhắc cập nhật docs
│       ├── task.py     task memory (start/checkpoint/close), khoá liên tiến trình
│       ├── usage.py    đọc token thật từ transcript
│       ├── log.py      hooks.jsonl, sessions.jsonl, usage.jsonl; che secret
│       ├── detect.py   khảo sát cơ học (`uccif detect`), `uccif doctor`
│       └── cli.py      lệnh `uccif …`
├── tests/          pytest (104 test) + smoke.sh (headless Claude Code)
├── .github/workflows/  ci.yml (Ubuntu, macOS, Windows thử nghiệm + validate) · smoke.yml (chạy tay)
├── CHANGELOG.md · README.md
└── docs/HANDOFF.md ← file này
```

### 4.2 Dữ liệu nằm ở đâu ✅
| Dữ liệu | Vị trí | Ai ghi |
|---|---|---|
| Code framework | `${CLAUDE_PLUGIN_ROOT}` (cache plugin, đổi theo version) | — |
| Index `.db`, log, metrics | `~/.claude/plugins/data/uccif-uccif/projects/<hash-đường-dẫn>/` | **chỉ hook** (chạy ngoài sandbox) |
| Task memory, history, drift baseline | `<project>/.claude/uccif/.local/` (git-ignore qua `.claude/uccif/.gitignore`) | hook và CLI (Bash sandbox ghi được ở đây) |
| Tài liệu project: `summary.md`, `architecture.md`, `decisions.md`, `known-issues.md` | `<project>/.claude/uccif/` → **commit** | Claude (init, drift), script (decision/issue khi đóng task) |
| Khối project-specific trong `CLAUDE.md` | giữa `<!-- UCCIF:BEGIN -->` / `<!-- UCCIF:END -->` | Claude, **hỏi người dùng trước** |
| Tuỳ chọn chung | `userConfig` của plugin (`/config`) | người dùng |

Khoá project = hash đường dẫn thật; lưu kèm root commit để nhận ra repo **đổi tên/di chuyển**
(chuyển dữ liệu sang), trong khi **hai bản clone/worktree đang tồn tại** vẫn tách biệt.

### 4.3 "Hiểu source code" = 3 tầng ✅
| Tầng | Nội dung | Công cụ | Tự động |
|---|---|---|---|
| 1. Cấu trúc chính xác | định nghĩa, tham chiếu, kiểu | LSP (TS/JS, Python) | tiến trình nền, cập nhật thời gian thực |
| 2. Bản đồ repo | file, symbol, import, ai import ai, test liên quan | index SQLite | build nền khi mở phiên, cập nhật sau Edit, cuối lượt, trước mỗi query |
| 3. Nghiệp vụ | dự án làm gì, kiến trúc, quy ước | docs do AI viết | `/uccif:init` một lần; drift nhắc sửa đúng mục khi cấu trúc đổi |

- Index **phủ toàn bộ source** và không tốn token (script). `/uccif:init` chỉ đọc ~25 file
  đại diện để **viết docs** (đọc hết sẽ tốn hàng trăm nghìn token); repo > 300 file thì
  agent `project-analyst` làm theo từng module; docs được bổ sung dần khi task chạm module mới.
- Symbol lấy từ universal-ctags nếu có, không thì regex theo ngôn ngữ (đánh dấu `~approx`);
  tham chiếu đếm trực tiếp bằng `git grep -w` lúc query nên luôn mới.
- Vue: chưa có LSP (plugin không cấu hình) → index phủ file `.vue`.

### 4.4 Hooks ✅ (không hook nào chặn)
| Event | Việc làm |
|---|---|
| SessionStart | Chuyển task cũ sang `.local/` (một lần); ghi phiên; cache userConfig + export `UCCIF_DATA_DIR` qua `CLAUDE_ENV_FILE`; in **CORE RULES** (startup/clear/compact); spawn nền `uccif maintain` (cập nhật index + drift); báo index sẵn sàng / đang build; đề nghị cài LSP thiếu (1 lần/binary/máy); nhắc init nếu chưa có docs; tóm tắt task dở |
| UserPromptSubmit | ≤ 3 dòng: task dở + bước kế tiếp; drift đang chờ; "Reply in vi… `uccif index query` first; code changes follow the uccif task flow" (`#quick` bỏ phần task) |
| PreToolUse (Bash) | Chỉ với agent của UCCIF: lệnh Bash ngoài danh sách → ghi `would_block` (không chặn). Lệnh của Claude chính không ghi log |
| PostToolUse (Edit/Write…) | Ghi file vào task; index lại đúng file đó |
| PostToolUseFailure (Bash/Grep/Glob) | Lệnh tìm kiếm lỗi → nhắc "sửa lệnh, đừng coi là không có kết quả" |
| SubagentStart/Stop | Log agent, token của agent, `partial` |
| Stop | Spawn nền `maintain` (bắt thay đổi ngoài Claude); ghi usage; in **dòng token thật** cho người dùng + gợi ý `/clear` theo ngưỡng token |
| PreCompact / SessionEnd | Snapshot task vào history; log; SessionEnd prune log > 30 ngày |
| PostCompact | Log |
| InstructionsLoaded | Kiểm tra khối UCCIF trong CLAUDE.md |

### 4.5 CORE RULES (≤ 8, nguồn duy nhất `rules.py`, hook inject — không chép vào CLAUDE.md)
1 Tự làm, không bảo người dùng chạy lệnh · 2 Ops làm luôn; sửa code: skill → `task start` →
`uccif index query` → LSP → Grep giới hạn → đọc đúng đoạn → Edit → test → checkpoint/close
(flow không phải cổng chặn) · 3 Bằng chứng (`file:line`, output) · 4 Hỏi trước khi cài gói,
deploy, `git push`, gọi dịch vụ ngoài, xoá dữ liệu · 5 Sửa hụt 2 lần → thu thập bằng chứng ·
6 Trả lời bằng `reply_language` · 7 Người dùng không gõ `uccif`; Claude tự map lời nói → lệnh;
không tự nêu số token · 8 `#quick` cho sửa nhỏ.

### 4.6 Lệnh CLI (Claude tự chạy; chỉ có trong PATH của Bash bên trong Claude Code)
```text
uccif version | where | detect | doctor
uccif task start "<title>" --type <bug|feature|refactor|review|test|explore|ui> [--goal] [--rewrite]
uccif task show | checkpoint [--decision|--issue|--test|--file|--next|--goal|--modules|--set] | close (--decision|--issue|--no-findings)
uccif index query --symbol X | --file P | --tests-for P      (≤ 30 dòng; tự refresh nếu ghi được)
uccif index status | build | update [--quiet]
uccif drift check | show | ack
uccif maintain                                               (hook gọi nền)
uccif log hooks [--last N|--today|--event E|--only-blocks|--only-errors] | sessions [--days N] | prune
uccif usage turn|session --transcript <path>
uccif hook <event>                                           (hook gọi)
```

### 4.7 Một vòng làm việc
1. **Mở phiên** → hook in rules, build/refresh index nền, kiểm drift, nhắc task dở / init / LSP.
2. **Người dùng gửi prompt** → hook nhắc task, drift, "tra index trước".
3. **Claude:** ops thì làm luôn. Sửa code: `task-context` → `task start` → `index query` → LSP →
   Grep giới hạn → đọc đúng đoạn → Edit (hook index lại file) → test → `checkpoint` →
   (≥ 3 file hoặc có ràng buộc → agent `change-reviewer`) → `task close` (ghi decisions/issues).
   Lần đầu ở project: `/uccif:init`.
4. **Hết lượt** → dòng token thật; quét thay đổi ngoài Claude; drift.
5. **`/clear`/compact** → task đã lưu; phiên mới nhận lại rules; "tiếp tục" → skill `resume`.

Mức độ tự động: **hook chạy chắc chắn 100%**; **skill do Claude tự chọn** theo mô tả + lời nhắc
mỗi lượt → thường đúng nhưng không bảo đảm. Nếu thực tế Claude hay bỏ bước → làm `uccif-strict`.

---

## 5. Dữ kiện Claude Code đã kiểm tra (2026-11-03, CLI 2.1.317)

- Plugin gói: skills, agents, hooks, MCP, LSP, monitors, output styles, themes; chỉ
  `plugin.json` nằm trong `.claude-plugin/`.
- `${CLAUDE_PLUGIN_ROOT}` (đổi theo version, không ghi state), `${CLAUDE_PLUGIN_DATA}`
  (`~/.claude/plugins/data/<id>/`, sống qua update, xoá khi gỡ), `${CLAUDE_PROJECT_DIR}`.
- Hook nhận `CLAUDE_PLUGIN_DATA`; **lệnh Bash của Claude thì không** → SessionStart export
  `UCCIF_DATA_DIR` qua `CLAUDE_ENV_FILE`.
- `bin/` của plugin vào PATH của Bash khi plugin bật.
- `CLAUDE.md` ở gốc plugin **không được nạp**.
- Agent của plugin không hỗ trợ `hooks`, `mcpServers`, `permissionMode`.
- `userConfig` → `CLAUDE_PLUGIN_OPTION_<KEY>` cho hook; chỉ đọc từ user settings.
- `version` trong `plugin.json` **ghim** bản cài: máy người dùng chỉ nhận update khi bump.
- LSP qua `.lsp.json`: cần cài binary riêng; server trùng extension → server đăng ký trước thắng.
- **Bash sandbox** chỉ cho ghi working dir, temp dir, `--add-dir`; **gần như toàn bộ `~/.claude`
  là protected path**, `allowWrite` không mở được. Hook, LSP, MCP chạy ngoài sandbox.
- Công cụ: `claude plugin validate <dir> --strict`, `claude --plugin-dir <dir>`,
  `claude plugin details <name>` (inventory + token), `/reload-plugins`.

---

## 6. Quyết định thiết kế (decision log)

| # | Quyết định | Lý do / phương án đã loại |
|---|---|---|
| D1 ✅ | Plugin + marketplace, không phải prompt sinh code | Bản code duy nhất, có test, update 1 lệnh. Loại: sinh lại mỗi project |
| D2 ✅ | Lõi **không bao giờ chặn**; cổng chặn để dành cho `uccif-strict` (`defaultEnabled: false`) | Bài học v2. Bỏ cờ `enforce` |
| D3 ✅ | CORE RULES chỉ ở hook (`rules.py`); CLAUDE.md chỉ chứa thông tin riêng project | Tránh trùng/lệch |
| D4 ✅ | Python 3.8+ stdlib; adapter tuỳ chọn (ctags) có fallback regex | Chạy mọi máy |
| D5 ✅ | Khoá project = đường dẫn + root commit để phát hiện đổi tên | Root commit đơn thuần làm 2 clone dùng chung dữ liệu |
| D6 ✅ | Launcher thử `python3 → python → py -3`; entry `scripts/uccif_main.py`; hook dạng shell có quote | Windows (mục 7.2) |
| D7 ✅ | Index SQLite của UCCIF + LSP, không phụ thuộc MCP bên ngoài | Người dùng muốn "cài vào là xong"; không tự cài MCP. Serena/indxr để dành `uccif-codeintel` |
| D8 ✅ | Index ngoài repo, chỉ hook ghi; CLI đọc read-only | Sandbox (mục 7.6) |
| D9 ✅ | Task memory + drift ở `<project>/.claude/uccif/.local/` (git-ignore) | Sandbox cho ghi working dir; tự tách theo checkout |
| D10 ✅ | Drift dựa trên dấu vân tay cấu trúc (thư mục độ sâu 2, manifest, dependency); sửa bên trong hàm không tính | Tránh báo động giả |
| D11 ✅ | Không vector/semantic search | Tránh embedding/dịch vụ ngoài |
| D12 ✅ | Không tự cài language server; hỏi **một lần** mỗi binary mỗi máy | Rule "hỏi trước khi cài gói" |
| D13 ✅ | LSP đóng gói chỉ TS/JS + Python | Go/Rust dùng plugin chính thức; tránh lỗi "Executable not found" khi máy không dùng |
| D14 ✅ | Init đọc tối đa ~25 file; index phủ toàn bộ | Token |
| D15 ✅ | Scope cài mặc định `user`; marketplace `uccif`; repo `phongng255/uccif` | — |

---

## 7. Sự cố đã gặp và cách xử lý ⚠️

### 7.1 Mâu thuẫn trong spec v2.1 (đã loại khi port)
deny `node_modules` vs test kỳ vọng deny; "mặc định không deny" vs bước 9 hợp nhất deny;
"cần 4 lớp ép buộc" vs mặc định tắt 3/4; số dòng nhắc 2/3 không thống nhất; rule "not a gate"
vs bảng toàn cổng chặn; bảng hook vỡ; đánh số lộn xộn.

### 7.2 Windows
- `PYTHONPATH` với dấu `:` và đường dẫn `/c/...` từ Git Bash → Python bản Windows đọc sai.
  → Bỏ `PYTHONPATH`, gọi `scripts/uccif_main.py` (Git Bash tự đổi đường dẫn trong tham số).
- Hook dạng exec (`args`) có báo lỗi trên Windows (args bị bỏ, đường dẫn mất `\`).
  → Dùng dạng shell: `"${CLAUDE_PLUGIN_ROOT}/bin/uccif" hook <event>`.
- Chưa test trên máy Windows thật.

### 7.3 Fallback thư mục dữ liệu chọn nhầm
Glob `uccif-*` sẽ khớp cả `uccif-strict-*`/`uccif-codeintel-*` sau này.
→ Ưu tiên đúng tên `uccif-uccif`, rồi thư mục có file đánh dấu `options.json` (chỉ lõi ghi).

### 7.4 Chi phí hook
- `git rev-list --max-parents=0 HEAD` duyệt cả lịch sử, chạy ở mọi hook → cache trong `meta.json`.
- PreToolUse(Bash) chạy mọi lệnh Bash chỉ để `skip` → không ghi log các lần skip.

### 7.5 Hai phiên cùng một project
Ghi đè `current.json`, trùng mã task → khoá file `O_EXCL` (stdlib), timeout 3 s, khoá cũ > 30 s
coi là của tiến trình chết và tiếp quản. Hook không bao giờ chờ lâu (bỏ qua nếu bận).

### 7.6 "readonly database" trong sandbox (gặp trên máy người dùng)
Bash sandbox của Claude Code chặn ghi `~/.claude` (protected, không mở được bằng `allowWrite`)
→ `uccif index status` lỗi, Claude phải xin chạy ngoài sandbox.
→ dev.4: query/status mở DB **read-only** (`mode=ro`, journal DELETE thay WAL vì WAL cần ghi
`-shm`); bỏ refresh khi không ghi được; task/drift chuyển sang `.claude/uccif/.local/`; doctor
coi data dir chỉ-đọc là INFO. Test bằng user thường (root bỏ qua quyền file → test bị skip).

### 7.7 Kỳ vọng "cài vào là có index" nhưng 3.0 ban đầu không có
Lộ trình gốc dời index sang 3.2; người dùng thấy "plugin chả có gì".
→ Đưa index vào dev.3, tự build/tự cập nhật. Bài học: ưu tiên thứ người dùng thấy được.

### 7.8 Cảnh báo LSP cho Vue gây hiểu lầm
Doctor báo thiếu `vue-language-server` dù plugin không cấu hình Vue → cài cũng vô ích.
→ Chỉ cảnh báo ngôn ngữ có trong `.lsp.json`; ngôn ngữ khác là INFO "index phủ".
(Bản detect vẫn liệt kê thông tin Vue; Claude có thể nhắc lại — trả lời: không cần cài.)

### 7.9 Index: lỗi nhỏ đã sửa
`git ls-files` vẫn liệt kê file tracked đã bị xoá → lọc theo file tồn tại. Danh sách skip dùng
chung với `detect` (node_modules, dist, .claude…); bỏ `.min.js`, file > 1 MB, file nhị phân.

### 7.10 Quy trình git / push
- Phiên Claude đầu tiên không có quyền ghi GitHub (403) → giao patch (`git am`), sau đó người
  dùng cấp quyền GitHub App.
- Người dùng tự áp patch dev.2 → trùng nội dung commit → Claude `rebase` lên `origin/main`
  (git tự bỏ commit trùng) rồi push.
- Stop hook của môi trường nhắc "unpushed commits" liên tục khi chưa có quyền → không thử lại
  vòng lặp; giải thích và chờ người dùng.

### 7.11 Ghi chú vận hành
- Lệnh `uccif` chỉ có trong Bash **bên trong** Claude Code, không có ở terminal thường →
  muốn kiểm tra thì nhờ Claude chạy (`uccif version`, `index status`, `doctor`).
- File `.db` không nằm trong project (xem 4.2); `/uccif:init` không tạo index (hook tạo).
- Sau `claude plugin update`, phiên đang mở cần `/reload-plugins` hoặc mở phiên mới.
- Project sẽ có thêm `.claude/uccif/.gitignore` → nên commit.

---

## 8. Giới hạn hiện tại & câu hỏi mở

- Symbol bằng regex là gần đúng khi không có universal-ctags (cài `ctags` để chính xác hơn).
- Vue chưa có LSP (cần cấu hình hybrid với TS plugin) 🟡.
- Skill không được bảo đảm 100% → `uccif-strict` nếu cần ❓.
- Windows chưa kiểm chứng thực tế ❓.
- Doc-claims check (`[src:]` trỏ tới file vừa sửa → nhắc kiểm lại dòng doc) chưa làm (3.1) 🟡.
- Agent chỉ bị *ghi log* khi chạy Bash ngoài danh sách, không bị chặn (hook có thấy tool call
  của subagent qua `agent_id`) 🟡.
- `compact-summary.md` xuất hiện untracked trong project của người dùng: không do UCCIF tạo ❓.

## 9. Lộ trình
| Bản | Nội dung |
|---|---|
| 3.0 (đang dev) | task/resume, token line, logs, `/uccif:init`, CORE RULES qua hook, 3 agent, index, LSP, drift, test + CI |
| 3.1 | doc-claims check `[src:]` |
| 3.2 | `uccif-codeintel` tuỳ chọn (Serena, indexer tree-sitter), `defaultEnabled: false` |
| 3.3 | `uccif-strict` (cổng chặn), chỉ khi cần |

---

## 10. Phát triển & phát hành

```bash
python3 -m pytest -q                                  # 104 test
claude plugin validate plugins/uccif --strict && claude plugin validate . --strict
claude --plugin-dir plugins/uccif                     # chạy thử bản đang sửa
tests/smoke.sh                                        # headless, tốn API (hoặc Actions → smoke)
```
Phát hành: bump version ở **cả** `plugins/uccif/.claude-plugin/plugin.json` và
`uccif_lib/__init__.py` (có test kiểm tra) → ghi `CHANGELOG.md` → push.
Cập nhật máy người dùng:
```bash
claude plugin marketplace update uccif && claude plugin update uccif@uccif   # rồi /reload-plugins
```
Cài lần đầu: `claude plugin marketplace add phongng255/uccif && claude plugin install uccif@uccif`.

Lưu ý khi test: chạy bằng root sẽ skip test sandbox → chạy thêm bằng user thường.

---

## 11. Bối cảnh người dùng (chỉ những gì liên quan)
- Trả lời bằng tiếng Việt; framework bằng tiếng Anh.
- Máy: macOS (Apple Silicon), Python 3.9.6, có `typescript-language-server`.
- Project chính đang dùng UCCIF: web-app chuyến đi Thái Lan (Vue 3, Vite, TS, Pinia, Firebase,
  deploy preview lên surge.sh); lệnh `npm run dev|build|typecheck`, `npm test`, `deploy:*`.
- Muốn tự động tối đa, ít thao tác tay; không thích tool chặn hay đẩy việc ngược lại.

---

## 12. Prompt mẫu để bàn giao cho AI khác

```text
Mình đang phát triển UCCIF — một Claude Code plugin (repo phongng255/uccif).
Đính kèm docs/HANDOFF.md: đọc hết trước khi làm gì. Ký hiệu ✅ đã chốt, 🟡 đề xuất,
❓ câu hỏi mở. Đừng đề xuất lại phương án đã bị loại ở mục 6–7 nếu không có lý do mới.

Việc của bạn:
1. Tóm tắt trong ≤ 8 dòng: plugin làm gì, đang ở bản nào, việc dở dang.
2. Rồi làm: <mô tả việc cần làm>.

Lưu ý: kiểm tra docs Claude Code hiện hành trước khi sửa plugin.json/hooks.json/.lsp.json;
chạy pytest + `claude plugin validate --strict` trước khi commit; bump version khi phát hành;
trả lời mình bằng tiếng Việt, code/commit bằng tiếng Anh.
```
