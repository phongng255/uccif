# Checklist thực hiện

Bạn đã duyệt đề xuất ngày 06/11/2026. Đã có code setup/workflow theo repo; đang chờ kiểm chứng trong ứng dụng đích.
Điểm chưa rõ hoặc cần hỗ trợ phải hỏi trước khi làm phần phụ thuộc, không tự giả định.

## 0. Duyệt và kiểm chứng môi trường chạy

- [x] 0.1 Bạn duyệt phạm vi, cách chia phần cơ bản/plugin và việc để báo cáo token sang giai đoạn sau (06/11/2026).
- [ ] 0.2 Chốt ứng dụng Codex, phiên bản, nền tảng và cách cài được hỗ trợ.
- [ ] 0.3 Thu mẫu sự kiện thực tế đã loại dữ liệu nhạy cảm: mở phiên, prompt, patch/shell thành công
  và thất bại, lệnh bất đồng bộ hoàn tất, Stop, resume/compact và ngắt lượt nếu có.
- [ ] 0.4 Xác minh đầu ra, trust, đường dẫn plugin, cách đóng gói core và cách tìm MCP;
  ghi rõ đã hỗ trợ/chưa hỗ trợ/chưa thử trong dữ liệu kiểm tra tương thích.
- [ ] 0.5 Đối chiếu kết quả mốc B; chỉ làm tự động hóa khi đã kiểm chứng giao diện môi trường.

### Ghi nhận khảo sát cho bước 0.2 (chưa hoàn tất)

- Đã xác minh tài liệu: app, CLI và IDE extension dùng chung cấu hình agent/MCP.
- Đích thiết kế: một bộ tích hợp Codex dùng chung, kiểm thử từng giao diện.
- Đã có phiên bản CLI/app-server thực tế: 0.167.0/Linux; chưa có dữ liệu sự kiện từ lượt gọi model.
- Đã làm rõ: Antigravity chỉ là ví dụ trải nghiệm plugin; đích là Codex app và VS Code.
- CLI Codex đã cài trong môi trường thử riêng; chưa chạy hooks thực tế.
- Đã chạy model turn thật bằng bundled CLI của Codex Desktop `0.166.0-alpha.6` trên macOS 15.7.7;
  native status/init/resume và repository resume đều chọn đúng skill. Chưa kiểm tra GUI/VS Code.

## 1. Host và setup cơ bản

- [x] 1.1 Thêm host codex, khả năng hỗ trợ và đường dẫn `.agents/skills`; giữ hành vi các host cũ.
- [x] 1.2 Sinh nội dung quy trình Codex và test khả năng dùng chung skills dự án.
- [x] 1.3 Làm setup/dry-run/remove, mã băm quyền quản lý và khối có ranh giới trong AGENTS.md.
- [x] 1.4 Ghép cấu hình MCP trong repo, phát hiện xung đột và tránh trùng với server từ plugin.
- [x] 1.5 Điều chỉnh doctor/CodeGraph theo host; phân biệt chưa rõ/đã cấu hình/đã kiểm chứng.
- [x] 1.6 Test cài/gỡ lặp lại, file đã sửa/không thuộc UCCIF, chú thích TOML, đường dẫn có khoảng trắng,
  cấu hình chỉ đọc, thiếu CodeGraph/git, file dùng chung giữa host và tương thích Python.

## 2. Tự động hóa bằng hooks (phụ thuộc mốc B)

- [ ] 2.1 Chuyển đổi sự kiện, tên công cụ và đầu ra dựa trên mẫu đã kiểm chứng.
- [ ] 2.2 Theo dõi patch thêm/sửa/xóa/di chuyển nhiều file; patch thất bại không sinh bản ghi giả.
- [ ] 2.3 Kiểm tra tiêu đề từ prompt, đối chiếu thay đổi shell, lệnh bất đồng bộ, ngắt lượt,
  file có thay đổi từ trước, resume/compact và tiếp tục công việc qua host khác.
- [ ] 2.4 Test dữ liệu sai, sự kiện chưa hỗ trợ và thiếu phụ thuộc đều không chặn host;
  xác nhận không thay đổi cơ chế cấp quyền hoặc Stop.
- [x] 2.5 Thêm trình sinh package Codex với `--check`; đóng core trong package và test đường dẫn.
- [ ] 2.6 Kiểm tra setup repo và plugin cùng tồn tại, hooks khi chưa/đã trust và MCP không bị trùng.

## 3. Kiểm chứng và tài liệu

- [x] 3.1 Chạy toàn bộ pytest; so với mốc ban đầu 322 test đạt, 1 test bỏ qua.
- [x] 3.2 Chạy kiểm tra sinh file Gemini/Antigravity và thêm kiểm tra Codex vào CI.
- [ ] 3.3 Kiểm tra manifest và thử tích hợp trên từng môi trường Codex công bố hỗ trợ;
  ghi phiên bản, kết quả quan sát và test bỏ qua. CI mặc định không gọi model thật.
- [ ] 3.4 Thử phiên thật: sửa 2 file bằng apply_patch, sửa file khác qua shell, xem task,
  tiếp tục ở phiên mới, checkpoint/close, chuyển host và gỡ cài đặt mà giữ dữ liệu.
- [ ] 3.5 Cập nhật README, hướng dẫn Việt/Anh, bảng khả năng, changelog và các trường phiên bản đồng bộ.
- [ ] 3.6 Gửi diff, kết quả test và giới hạn để bạn duyệt phát hành; chưa publish/merge và không
  công bố hỗ trợ cloud khi chưa thử.

## Điều kiện hoàn thành

Phần cơ bản hoàn thành khi đã chứng minh setup lặp lại được, Codex đọc hướng dẫn/skills,
cấu hình MCP đúng, quy trình quản lý task bằng lệnh hoạt động và gỡ an toàn.
Phần tự động hóa chỉ hoàn thành khi sự kiện thực tế tạo lịch sử công việc đúng với hooks được trust.
Các host cũ phải tiếp tục vượt qua kiểm tra. Token, LSP và chế độ chặn vẫn để sau.

## Tiến độ triển khai bản thử nghiệm — 06/11/2026

- Đã có `setup codex`, `--dry-run`, `--remove`, `--with-codegraph` và chẩn đoán theo host.
- Có router `uccif` và workflow init/resume/codegraph; không sửa giao diện editor.
- Đã test cài/gỡ lặp lại, nội dung người dùng, TOML, MCP ở các lớp cấu hình đã đọc,
  symlink, đường dẫn có khoảng trắng, lỗi ghi, hai lần setup đồng thời và dữ liệu task dùng chung.
- Đã kiểm tra skills bản đồ dự án Codex nằm trong `.agents/skills/` và vẫn còn sau khi gỡ workflow.
- Mục 1.6 đã đạt trên matrix Python 3.9/3.12 của Ubuntu, macOS và Windows; Windows CI cũng kiểm tra
  bảo toàn CRLF, ownership và generator trên checkout có line-ending khác.
- Đã viết hướng dẫn Việt/Anh và changelog Unreleased; chưa tăng version phát hành.
- Đã có package native workflow và marketplace local; chưa có bộ chuyển đổi hooks hoặc số liệu token Codex.
- Đã kiểm chứng discovery không credential trên cloud và model turn thật trên máy người dùng.
  Model workflow đạt không được diễn giải thành hooks đã hoạt động.

### Kết quả kiểm tra kỹ thuật gần nhất

- Toàn bộ pytest local gần nhất: **333 đạt** trên macOS/Python 3.9.6.
- Kiểm tra sinh file Codex, Gemini và Antigravity: đạt.
- `git diff --check`: đạt.
- GitHub Actions: đạt trên Ubuntu/macOS/Windows với Python 3.9/3.12; chưa chạy OpenSpec CLI vì
  chưa cài và chưa chạy UI đồ họa Codex/VS Code hoặc hooks thật.

### Tiến độ kiểm chứng runtime thật

- Marketplace add, plugin add/remove: đạt trên Codex CLI 0.167.0/Linux.
- Skills/list: đạt với repo setup và package được cài; tên native đã được xác nhận thực tế.
- Core version/doctor và task CLI trong package: đạt.
- Coexistence và gỡ từng chế độ: đạt; dữ liệu task được giữ.
- Hook thử riêng được runtime đánh dấu `untrusted`; không trust hoặc thực thi.
- Script không cần credential và job CI pin 0.167.0 đã đạt trên GitHub Actions.
- Mốc B/2.1–2.4 về sự kiện trong lượt model và hooks vẫn chưa đủ bằng chứng; không bật tự động hóa.
- Chi tiết và cách tái hiện: `docs/CODEX-RUNTIME-VI.md`.

### Kiểm chứng bổ sung trên máy người dùng

- Pytest trên macOS/Python 3.9.6: **333 đạt**; ba generator `--check` và `git diff --check`: đạt.
- Sửa test harness để tắt Python bytecode cache trong subprocess; nếu không, macOS ghi `.pyc`
  vào HOME fixture và làm kiểm tra dry-run báo sai dù UCCIF không tạo metadata.
- Model turn native plugin: status, init và resume đạt; model turn repo setup resume đạt.
- Gỡ setup/plugin giữ nguyên summary và task checkpoint. Plugin/marketplace thử nghiệm đã được gỡ
  khỏi cấu hình người dùng sau khi kiểm tra.
- Hai vòng CI Windows đã phát hiện và giúp sửa newline translation cùng ownership hash; regression
  mới kiểm tra LF/CRLF và lần matrix cuối đạt toàn bộ.
- Chưa thu payload hook hoặc kiểm tra success/failure/interrupt/compact; các mục 0.3 và 2.1–2.4
  vẫn chưa hoàn tất.

### Kết quả cuối của giai đoạn workflow

- Pytest local: **333 đạt** trên Python 3.9/macOS; matrix Python 3.9/3.12 trên ba hệ điều hành đạt.
- Cả ba trình sinh Codex/Gemini/Antigravity: `--check` đạt.
- Bài kiểm chứng runtime Codex 0.167.0 không credential: đạt các hạng mục ghi trong
  `tests/fixtures/codex/runtime-0.167.0.json`.
- Native package đã cài/gỡ, được app-server nhận và chạy đúng các model turn workflow đã nêu;
  chưa thực thi hooks.
- Source, package, marketplace, hướng dẫn và CI sẵn sàng để duyệt; chưa merge/publish.
