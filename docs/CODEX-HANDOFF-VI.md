# Handoff: bổ sung UCCIF cho Codex

Ngày bàn giao: 06/11/2026. Repo: `phongng255/uccif`. Baseline: commit `23f479a`.
Nhánh làm việc local: `codex/development-environment`. Chưa commit, push, merge hoặc publish.

## 1. Mục tiêu đã thống nhất

Bổ sung UCCIF cho Codex theo hai cách dùng:

1. Plugin native cài qua Codex CLI, để gọi các workflow có namespace trong Codex chat.
2. Setup theo từng repository, để Codex đọc `.agents/skills/` và khối UCCIF trong `AGENTS.md`.

Antigravity không phải đích chạy Codex. Ví dụ Antigravity trước đó chỉ mô tả trải nghiệm cài
plugin rồi gọi workflow trong chat. Không được ghi rằng Codex hỗ trợ Antigravity nếu chưa có bằng chứng.

Phạm vi hiện tại là workflow và task memory. Không tích hợp GPT API riêng, không token footer,
không LSP và chưa bật automatic task tracking bằng hooks.

## 2. Trạng thái hiện tại

### Đã hoàn thành

- `uccif setup codex`, `--dry-run`, `--remove`, `--with-codegraph` theo phạm vi repository.
- Setup an toàn: marker có ranh giới, ownership hash, không ghi global config, không đổi trust,
  giữ file người dùng đã sửa, kiểm tra path traversal/symlink, rollback khi ghi lỗi.
- Bốn repo skills: `uccif`, `uccif-codex-init`, `uccif-codex-resume`,
  `uccif-codex-codegraph`.
- Package native tự chứa core tại `plugins/uccif-codex/`.
- Marketplace local tại `.agents/plugins/marketplace.json`.
- Bốn native skills đã được Codex runtime nhận:
  `$uccif:init`, `$uccif:resume`, `$uccif:codegraph`, `$uccif:uccif`.
- Plugin native và repo setup tồn tại cùng lúc mà không trùng tên.
- Gỡ plugin/setup không xóa task history trong `.claude/uccif/`.
- CodeGraph MCP là tùy chọn; không tự cài dependency hoặc tự khởi động MCP.
- Runtime check không dùng credential tại `tests/codex_runtime_check.py`.
- CI job `codex-runtime` đã được thêm nhưng chưa chạy trên GitHub vì chưa push.
- Tài liệu runtime: `docs/CODEX-RUNTIME-VI.md`.
- OpenSpec: `openspec/changes/add-codex-support/`.

### Bằng chứng đã có

- Codex CLI/app-server thật: `codex-cli 0.167.0`, Linux x86_64.
- Marketplace add, plugin add/remove: đạt.
- `skills/list`: đạt cho cả native plugin và repo setup.
- Core đóng gói chạy độc lập: version, doctor, task start/checkpoint/show/close đều đạt.
- Hook vô hại trong dự án tạm được phát hiện là `untrusted`; hook không được trust hoặc thực thi.
- Toàn bộ pytest gần nhất: **367 đạt, 1 bỏ qua** trên Python 3.12/Linux.
- Ba generator Codex/Gemini/Antigravity: `--check` đạt.
- Fixture kết quả: `tests/fixtures/codex/runtime-0.167.0.json`.

## 3. Những gì chưa được chứng minh

Không được biến các mục dưới đây thành tuyên bố “đã hỗ trợ” nếu chưa thu được bằng chứng thật:

1. Model trong Codex app/CLI/VS Code thực sự chọn và làm đúng toàn bộ chỉ dẫn của workflow.
2. Codex Desktop UI và Codex extension trong VS Code hiển thị/call skills đúng.
3. Hooks UCCIF được trust và thực thi qua một model turn thật.
4. Payload thực tế cho prompt, apply_patch thành công/thất bại, shell thành công/thất bại,
   lệnh bất đồng bộ, compact/resume, interrupt và kết thúc lượt.
5. Automatic task/file tracking, token footer và LSP.
6. GitHub Actions trên macOS/Windows/Linux. Workflow mới tồn tại trong diff nhưng chưa chạy remote.

Một lần `skills/list` thành công chỉ chứng minh runtime khám phá được skill; không chứng minh model
đã gọi workflow. Chạy core bằng subprocess cũng không được tính là model turn.

## 4. Vì sao môi trường cloud hiện tại chưa test hết được

Môi trường đã dùng là container cloud Linux, hostname quan sát gần nhất `b96e146f6d6c`, không phải
máy Mac của người dùng. Môi trường kiểm chứng cố ý không đọc credential, không có phiên đăng nhập
Codex của người dùng và không tạo model turn. Một lần thử mở thread/prompt đã timeout; chưa xác định
nguyên nhân nên không được quy timeout cho authentication nếu chưa có log xác nhận.

Do đó có ba cấp kiểm tra:

| Cấp | Chạy ở đâu | Kiểm tra được | Không kiểm tra được |
|---|---|---|---|
| A | Cloud không credential | package, app-server discovery, core CLI, cài/gỡ | model behavior, UI, hook execution |
| B | GitHub Actions | Python/OS matrix, generator, Codex CLI runtime | Desktop/VS Code UI, tài khoản người dùng |
| C | Máy có Codex đăng nhập | model turn, UI, trust prompt, hook events thật | Chỉ có giá trị cho phiên bản/môi trường đã ghi nhận |

## 5. Cách tái hiện phần đã kiểm chứng

Không sửa trực tiếp `plugins/uccif-codex/`; sửa nguồn rồi sinh lại package.

```bash
python3 plugins/uccif/scripts/build_codex.py
python3 plugins/uccif/scripts/build_codex.py --check
python3 plugins/uccif/scripts/build_gemini.py --check
python3 plugins/uccif/scripts/build_antigravity.py --check
python3 -m pytest -q
git diff --check
```

Kiểm tra runtime thật, không model/credential:

```bash
npm install --prefix /tmp/uccif-codex-runtime --no-audit --no-fund @openai/codex@0.167.0
python3 tests/codex_runtime_check.py \
  --codex-bin /tmp/uccif-codex-runtime/node_modules/.bin/codex
```

Script pin chính xác `codex-cli 0.167.0`. Nếu muốn nâng version, không chỉ đổi constant: phải đọc
release notes/schema, chạy lại toàn bộ contract check và lưu fixture mới có tên version tương ứng.

## 6. Cách test trên máy có Codex đăng nhập

Chỉ dùng dự án Git tạm không chứa secret. Ghi lại hệ điều hành, Codex/extension/editor version và
cách cài trước khi thử.

### Plugin native

```bash
codex plugin marketplace add /duong/dan/uccif
codex plugin add uccif@uccif-codex-local
```

Mở dự án thử trong Codex, kiểm tra bốn native skills. Chạy lần lượt `status`, `init`, tạo một task
thật, checkpoint, mở phiên mới rồi `resume`. So sánh file/task trước và sau; không chỉ nhìn câu trả lời.

Gỡ sau khi thử:

```bash
codex plugin remove uccif@uccif-codex-local
```

Task history phải còn. Hướng dẫn chi tiết hơn nằm trong `docs/CODEX-TEST-VI.md`.

### Setup theo repository

```bash
/duong/dan/uccif/plugins/uccif/bin/uccif setup codex --dry-run
/duong/dan/uccif/plugins/uccif/bin/uccif setup codex
/duong/dan/uccif/plugins/uccif/bin/uccif doctor --host codex
```

Sau khi UI/model test xong:

```bash
/duong/dan/uccif/plugins/uccif/bin/uccif setup codex --remove --dry-run
/duong/dan/uccif/plugins/uccif/bin/uccif setup codex --remove
```

## 7. Công việc tiếp theo theo thứ tự

1. Chạy CI trên branch riêng, đặc biệt matrix macOS/Windows và job `codex-runtime`.
2. Kiểm tra model turn thật với native plugin và repo setup; lưu kết quả đã loại secret.
3. Trên một dự án tạm, review/trust hook theo UI chính thức rồi thu payload sự kiện thật.
4. Chỉ sau bước 3 mới thiết kế adapter Codex trong `uccif_lib/hooks.py`.
5. Thêm fixtures cho success/failure/interrupt/resume; kiểm tra không tạo task/file record giả.
6. Chạy regression toàn bộ host Claude/Gemini/Antigravity.
7. Gửi diff, test evidence và giới hạn cho người dùng duyệt trước khi commit/push/merge/release.

Nếu không có credential/model session hoặc không thể review trust, dừng ở workflow preview hiện tại.
Không được giả lập payload rồi gọi đó là “runtime verified”.

## 8. Ràng buộc kỹ thuật và an toàn

- Không tự thay đổi trust hoặc dùng flag bypass permission.
- Không đọc/copy token, API key, cookie hoặc config tài khoản vào fixture/log.
- Không ghi user/global Codex config trong setup mặc định.
- Không cài dependency nếu chưa hỏi; CodeGraph phải là tùy chọn.
- Không suy luận Codex hỗ trợ Antigravity.
- Không bật hook production từ tài liệu hoặc mock; cần event thật đã sanitize.
- Không xóa/sửa file người dùng để vượt ownership conflict.
- Không push, merge, publish hoặc bump version nếu người dùng chưa duyệt rõ.
- Giữ Python 3.8+ cho core; tránh syntax chỉ có ở Python mới.

## 9. Các file chính

| File | Vai trò |
|---|---|
| `plugins/uccif/uccif_lib/codex_setup.py` | setup/remove/dry-run và ownership |
| `plugins/uccif/uccif_lib/codex_workflows.py` | nguồn workflow Codex |
| `plugins/uccif/scripts/build_codex.py` | sinh package native |
| `plugins/uccif-codex/` | output generated, không sửa tay |
| `.agents/plugins/marketplace.json` | marketplace local Codex |
| `tests/test_codex.py` | unit/integration setup safety |
| `tests/test_codex_plugin.py` | package/generator/portable core |
| `tests/codex_runtime_check.py` | runtime contract không credential |
| `.github/workflows/ci.yml` | matrix hiện có và job Codex runtime |
| `docs/CODEX-RUNTIME-VI.md` | kết quả đã quan sát |
| `docs/CODEX-TEST-VI.md` | checklist test trong app/editor |
| `openspec/changes/add-codex-support/` | proposal, design, spec, tasks |

## 10. Tiêu chí chốt

Workflow preview có thể duyệt khi CI đa nền tảng đạt và model trong ít nhất một môi trường Codex
thật gọi đúng skill, giữ task data khi gỡ và không sửa ngoài phạm vi. Automatic tracking chỉ được
chốt sau khi hooks thật tạo đúng task/file history cho cả thành công, thất bại và gián đoạn.

Khi báo cáo, tách ba trạng thái: **đã kiểm chứng**, **chưa kiểm chứng**, **không hỗ trợ trong bản này**.
