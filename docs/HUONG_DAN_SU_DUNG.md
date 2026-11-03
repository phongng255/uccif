# Hướng dẫn sử dụng UCCIF

UCCIF là một plugin cho **Claude Code** và **Antigravity CLI** (`agy`, bản kế nhiệm của Gemini CLI).
Cài một lần, sau đó mở bất kỳ repo nào cũng có:

- **CodeGraph**: chỉ mục mã nguồn (tree-sitter, SQLite trong `.codegraph/`). AI tra code qua tool
  MCP `codegraph_explore` thay vì grep/find, nên tốn ít token hơn.
- **Skill của project** sinh tự động từ CodeGraph: `<project>-map` (bản đồ code), `<project>-bugfix`
  (quy trình sửa lỗi) và `<project>-mod-*` (mỗi module lớn một skill).
- **Bộ nhớ task**: việc đang làm vẫn còn sau `/clear`, sau compact và khi mở phiên mới.
- **CORE RULES**: các quy tắc làm việc được nạp vào đầu mỗi phiên. Hook **không bao giờ chặn** lệnh nào.

---

## 1. Yêu cầu

| Cần có | Kiểm tra | Ghi chú |
|---|---|---|
| Python 3.8+ | `python3 --version` | dùng `python3`, `python` hoặc `py -3` |
| git | `git --version` | |
| Node.js 18+ (khuyến nghị) | `node -v` | để cài CodeGraph bằng npm |
| Claude Code **hoặc** Antigravity CLI | `claude --version` / `agy --version` | dùng cái nào cài cái đó, hoặc cả hai |

---

## 2. Thêm plugin vào Claude Code

### 2.1. Cài từ GitHub (khuyến nghị)

Gõ trong Claude Code:

```
/plugin marketplace add phongng255/uccif
/plugin install uccif@uccif
```

Hoặc chạy từ terminal:

```bash
claude plugin marketplace add phongng255/uccif
```

```bash
claude plugin install uccif@uccif
```

Sau đó **khởi động lại Claude Code**.

### 2.2. Cài từ một nhánh khác (ví dụ nhánh có hỗ trợ Antigravity)

Thêm `#<tên nhánh>` vào cuối URL git:

```bash
claude plugin marketplace add "https://github.com/phongng255/uccif.git#feature/gemini-antigravity-support"
```

```bash
claude plugin install uccif@uccif
```

Nếu trước đó đã add marketplace `uccif` từ nhánh chính, hãy gỡ đi trước
(`claude plugin marketplace remove uccif`).

### 2.3. Chạy thử từ mã nguồn (không cần cài)

```bash
git clone https://github.com/phongng255/uccif
```

```bash
claude --plugin-dir ./uccif/plugins/uccif
```

### 2.4. Tuỳ chọn (gõ `/config` trong Claude Code)

| Tuỳ chọn | Mặc định | Ý nghĩa |
|---|---|---|
| `reply_language` | `vi` | ngôn ngữ AI trả lời bạn |
| `token_report` | bật | hiện một dòng số token thật sau mỗi câu trả lời |
| `auto_setup` | bật | nếu đã có CodeGraph CLI: tự index project và sinh skill |

### 2.5. Cập nhật, gỡ bỏ

```bash
claude plugin marketplace update uccif
```

```bash
claude plugin update uccif@uccif
```

```bash
claude plugin uninstall uccif@uccif
```

Cập nhật xong cần khởi động lại Claude Code.

---

## 3. Thêm plugin vào Antigravity CLI (Gemini)

Gemini CLI đã được thay bằng **Antigravity CLI** (`agy`) từ tháng 6/2026. Thư mục `plugins/uccif/`
vừa là plugin Claude Code, vừa là plugin Antigravity (`.antigravity-plugin/plugin.json`). Plugin
nằm trong thư mục con của repo, nên hãy clone về rồi cài từ đường dẫn local:

```bash
git clone -b feature/gemini-antigravity-support https://github.com/phongng255/uccif
```

```bash
agy plugin install ./uccif/plugins/uccif
```

Sau đó **khởi động lại `agy`**.

Plugin mang vào `agy` những thứ sau:

| Thành phần | File trong plugin | Tác dụng |
|---|---|---|
| Server MCP CodeGraph | `mcp_config.json` | tool `codegraph_explore` |
| Skills | `skills/*/SKILL.md` | dùng chung với Claude |
| Hooks | `hooks.json` | mở phiên: nạp CORE RULES, task, trạng thái CodeGraph; sửa file: ghi vào task; kết thúc: bảo trì nền |
| Skill của project | `<project>/.agents/skills/` | `<project>-map`, `-bugfix`, `-mod-*` |

Khác biệt so với Claude Code:

- Lệnh `uccif` **không có trên PATH** trong `agy`. Lúc mở phiên, AI được cho biết đường dẫn đầy đủ
  (`sh <plugin>/bin/uccif ...`) và tự dùng đường dẫn đó.
- Không có dòng báo token, không có nhắc nhở mỗi prompt, không có cấu hình LSP và 3 agent chỉ-đọc
  (các phần này chỉ có trên Claude Code).
- Cập nhật plugin: `git pull` trong thư mục đã clone, rồi chạy lại `agy plugin install ./uccif/plugins/uccif`.

> Phần Antigravity mới được kiểm tra bằng test giả lập, chưa chạy trong `agy` thật. Nếu hook hoặc
> MCP không chạy, xem mục 7.

---

## 4. Cài CodeGraph (làm một lần trên mỗi máy)

Dễ nhất là nói với AI "cài CodeGraph cho project này". AI sẽ chạy skill `uccif:codegraph`
(trên Claude Code) và tự làm hết các bước. Nếu muốn tự làm thì chạy:

```bash
npm install -g @colbymchenry/codegraph
```

```bash
codegraph init --yes
```

```bash
codegraph status
```

- **Không dùng `npx codegraph`**: gói `codegraph` không có scope là một dự án khác, không liên quan.
- Thêm `.codegraph/` vào `.gitignore`, vì index là dữ liệu riêng của từng máy.
- **Đừng** chạy `codegraph install --target=claude`, vì plugin đã khai báo server MCP rồi.
- Cài xong, khởi động lại Claude Code hoặc `agy` để tool `codegraph_explore` được nạp.

Từ đó về sau (khi `auto_setup` bật), mỗi lần mở project, UCCIF tự index trong nền và tự sinh
skill của project.

---

## 5. Sử dụng hằng ngày

Bạn **không cần nhớ lệnh**: cứ nói bằng tiếng Việt bình thường, AI sẽ tự chọn skill hoặc lệnh phù hợp.

| Bạn nói | AI làm |
|---|---|
| "khảo sát project này" (lần đầu) | skill `init`: viết `.claude/uccif/summary.md`, `architecture.md` và khối UCCIF trong `CLAUDE.md` |
| "sửa lỗi đăng nhập bị 500" | skill `task-context` + `<project>-bugfix`: mở task, tra CodeGraph, sửa, chạy test liên quan |
| "hàm X được gọi ở đâu?" | skill `smart-code-search`: dùng `codegraph_explore` trước, Grep sau |
| "đổi tên interface Y có ảnh hưởng gì?" | skill `code-impact-analysis`: liệt kê chỗ phụ thuộc, rủi ro, test cần chạy |
| "review thay đổi này" | skill `code-review` |
| "tiếp tục", "nãy đang làm gì?" | skill `resume`: đọc task đang mở |
| "cài lại / index lại CodeGraph" | skill `codegraph` (`reindex`) |

Thêm `#quick` vào prompt để bỏ qua bước mở/đóng task khi chỉ sửa nhỏ.

### Lệnh `uccif` (để tự kiểm tra; AI cũng tự chạy được)

Trong Claude Code, gọi `uccif` trực tiếp. Trong terminal thường hoặc `agy`, gọi qua đường dẫn
`sh <thư mục plugin>/bin/uccif`.

| Lệnh | Tác dụng |
|---|---|
| `uccif doctor` | kiểm tra cài đặt: Python, CodeGraph, LSP, rules |
| `uccif codegraph` | trạng thái CodeGraph (JSON: `cli`, `indexed`, `mcp`) |
| `uccif skills generate [--target auto\|claude\|agents\|all]` | sinh hoặc làm mới skill của project |
| `uccif skills list` | các skill đã sinh |
| `uccif task show` | task đang mở |
| `uccif task start "<tiêu đề>" --type bug` | mở task |
| `uccif task checkpoint --decision "..." --next "..."` | lưu tiến độ |
| `uccif task close` | đóng task |
| `uccif drift show` / `uccif drift ack` | xem hoặc xác nhận tài liệu đã cũ so với cấu trúc code |
| `uccif log hooks --today` | các hook đã chạy hôm nay |
| `uccif log sessions` | các phiên làm việc |
| `uccif where` | đường dẫn project và thư mục dữ liệu |

### Đích ghi skill của project (`--target`)

| Giá trị | Ghi vào |
|---|---|
| `auto` (mặc định) | `.claude/skills/`; thêm `.agents/skills/` khi phiên chạy từ `agy` hoặc project đã có `.agents/` / `.agent/` |
| `claude` | chỉ `.claude/skills/` |
| `agents` | chỉ `.agents/skills/` (hoặc `.agent/skills/` nếu project chỉ có thư mục cũ đó) |
| `all` | cả hai |

Ghi chú riêng viết trong khối `<!-- uccif:notes -->` của skill được giữ lại sau mỗi lần sinh lại.
File không có marker UCCIF thì không bao giờ bị ghi đè. Nên commit các skill này để chia sẻ với team.

---

## 6. Tuỳ biến theo project

| Muốn | Đặt ở |
|---|---|
| Quy tắc riêng cho project (commit được) | `<project>/.claude/uccif/rules.md` |
| Quy tắc cho mọi project | `~/.claude/uccif/rules.md` |
| Skill riêng | `<project>/.claude/skills/<tên>/SKILL.md` hoặc `<project>/.agents/skills/<tên>/SKILL.md` |

File rules là Markdown, mỗi dòng một quy tắc, tối đa 15 dòng mỗi file.

---

## 7. Xử lý sự cố

| Triệu chứng | Cách xử lý |
|---|---|
| AI không thấy tool `codegraph_explore` | `uccif codegraph`: nếu `cli` là `null` thì cài CodeGraph (mục 4); xong khởi động lại Claude Code / `agy` |
| `indexed: false` | `codegraph init --yes` ở thư mục gốc project |
| Kết quả tra code cũ | `codegraph index --force`, hoặc nói "index lại CodeGraph" |
| Hook không chạy | `uccif log hooks --today`; trên Claude Code thử `/reload-plugins` hoặc khởi động lại |
| "no Python 3.8+ found" | cài Python 3 và đảm bảo `python3` có trên PATH |
| Cập nhật plugin mà không có tác dụng | gỡ plugin, cài lại, rồi khởi động lại |
| (`agy`) skill không hiện trong `.agents/skills/` | `sh <plugin>/bin/uccif skills generate --target agents` |

Gỡ CodeGraph: `codegraph uninit` (chỉ project hiện tại), `codegraph uninstall` (toàn bộ).

---

## 8. Phát triển / chạy test

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
```

```bash
.venv/bin/python -m pytest -q
```

```bash
claude plugin validate plugins/uccif --strict
```
