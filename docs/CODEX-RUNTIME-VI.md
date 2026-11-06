# Kết quả kiểm chứng UCCIF với Codex

Ngày kiểm chứng: 06/11/2026. Trạng thái: package workflow local đã qua kiểm tra runtime
không credential trên Linux và model turn thật trên macOS; chưa phát hành công khai, chưa bật
lifecycle hooks cho Codex.

## Môi trường thực tế

- Codex CLI/app-server: **0.167.0**, bản chính thức `@openai/codex@0.167.0`.
- Linux x86_64, Python 3.12, Node.js 24 trong lần chạy tại đây.
- Cài CLI vào thư mục riêng; mỗi bài thử dùng HOME/CODEX_HOME và dự án Git tạm riêng.
- Không dùng API key, không đọc credential hiện có, không tạo lượt gọi model.
- Không dùng tùy chọn bỏ qua hook trust; không đổi cấu hình tài khoản/máy của người dùng.

## Kết quả

| Hạng mục | Kết quả | Bằng chứng kiểm tra |
|---|---|---|
| Đọc skills theo repo | Đạt | `skills/list` trả đủ bốn repo skills, enabled, không có lỗi |
| Đăng ký marketplace local | Đạt | Lệnh Codex thật nhận `uccif-codex-local` |
| Cài plugin native local | Đạt | `codex plugin add` trả package UCCIF trong cache |
| Nhận skills trong plugin | Đạt | App-server trả `uccif:init`, `uccif:resume`, `uccif:codegraph`, `uccif:uccif` |
| Core độc lập sau cài | Đạt | Chạy version, doctor và lệnh task từ core trong package được cài |
| Lưu và đọc task qua CLI | Đạt | Start, checkpoint, show và close bằng core được cài |
| Plugin và repo setup cùng tồn tại | Đạt | Tên có namespace và tên repo riêng biệt; gỡ setup vẫn giữ skills plugin |
| Gỡ plugin | Đạt | Khởi động app-server mới không còn skills plugin; task history vẫn còn |
| Gỡ repo setup | Đạt | App-server mới không còn các repo skills vừa gỡ |
| Phát hiện hook chưa được trust | Đạt trong bài thử riêng | Hook vô hại hiện trạng thái `untrusted`; không được trust hoặc thực thi |
| Chạy workflow do model điều khiển | Đạt trên macOS | Bundled CLI gọi đúng native status/init/resume và repo resume trong các model turn mới |
| Thực thi hooks UCCIF | Chưa kiểm chứng | Package chưa cài hooks và chưa có fixture sự kiện từ lượt chạy thật |
| UI Codex app/VS Code | Chưa kiểm chứng | Kiểm tra app-server/CLI, không chạy giao diện desktop/editor |

Các kết quả trên là từ Codex binary thật, không phải mock của bộ đọc skills hoặc trình cài plugin.
Ở bài thử Linux không credential, việc app-server nhận skill chỉ chứng minh discovery. Bằng chứng
model thực hiện workflow đến từ bài thử macOS riêng dưới đây.

Đã thử mở thread/render prompt để kiểm tra thêm ngữ cảnh, nhưng thao tác chạm timeout;
không tính các lần thử đó là thành công và chưa kết luận nguyên nhân. Việc nhận/cài/gỡ skills
được kiểm tra riêng, hoàn tất và không phụ thuộc vào các lần timeout này.

## Model turn thật trên máy macOS

- macOS 15.7.7, Python 3.9.6; Codex Desktop bundled CLI `0.166.0-alpha.6`.
- Dùng Git repository tạm không có secret; không dùng cờ bỏ qua approval/hook trust.
- Plugin native cài từ marketplace local. Model chọn `$uccif:uccif`, chạy `task show` và
  `doctor --host codex`, rồi báo đúng trạng thái không có task và hooks chưa cài.
- `$uccif:init` đọc README/source, ghi duy nhất summary có citation qua bundled core và không sửa
  source. `verify-tests` báo unverified thay vì biến lệnh chỉ ghi trong README thành kết quả giả.
- Sau khi tạo task/checkpoint thử, model turn mới dùng `$uccif:resume` đọc đúng title, goal,
  decision, test, file và next step; không tiếp tục hoặc sửa file khi được yêu cầu chỉ đọc.
- Setup theo repository tạo bốn skills; model turn mới chọn `$uccif-codex-resume` từ
  `.agents/skills/` và đọc đúng task dùng chung.
- Gỡ repo setup và plugin đều thành công; `.claude/uccif/` cùng task history vẫn còn.
- Plugin và repo skills cùng tồn tại mà không trùng tên.
- Đây là kiểm tra qua `codex exec` của binary đi kèm Desktop, không phải xác nhận giao diện đồ họa
  Desktop hoặc extension VS Code. Hooks vẫn chưa được trust/thực thi.

Contract script vẫn cố ý pin `0.167.0`; chạy nó bằng binary `0.166.0-alpha.6` dừng ở kiểm tra
version, nên bài model-turn macOS là bằng chứng bổ sung chứ không thay thế fixture Linux đã pin.

## Chạy lại không cần thao tác trên máy người dùng

Sau khi cài Codex 0.167.0 vào môi trường thử, chạy:

```bash
python3 tests/codex_runtime_check.py --codex-bin /duong/dan/codex
```

Script dùng stdlib Python, tự tạo cấu hình/dự án tạm, cài plugin từ marketplace của checkout,
kiểm tra bằng giao thức app-server, rồi gỡ và kiểm tra lại. Không cần đăng nhập.
Job `codex-runtime` trong CI cài đúng phiên bản 0.167.0 và chạy cùng bài thử. Việc thêm job
đã đạt cùng toàn bộ matrix Python 3.9/3.12 trên Ubuntu, macOS và Windows trong GitHub Actions
run `42189541400` của nhánh `codex/codex-preview`.

Matrix Windows ban đầu phát hiện hai lỗi portability: text mode tạo `CRCRLF` khi ghi nội dung đã
có CRLF, và generator so sánh byte LF/CRLF như thay đổi nội dung. Bản sửa ghi UTF-8 bytes, chuẩn
hóa newline khi kiểm tra ownership/generated output và có regression test riêng; lần CI cuối đạt.

Package được sinh bằng `plugins/uccif/scripts/build_codex.py`; CI và pytest kiểm tra package
không lệch nguồn. Không sửa trực tiếp file trong `plugins/uccif-codex/`.

## Giới hạn phát hành

Bản này cung cấp workflow và CLI task dùng chung. Chưa có theo dõi file/task tự động, dòng token,
LSP hoặc cam kết tương thích mọi phiên bản app/VS Code. CodeGraph MCP vẫn là tùy chọn cấu hình
riêng; plugin workflow không tự khởi động server khi CLI chưa có.

Mốc xác minh hooks trong OpenSpec vẫn chưa đạt đầy đủ. Không đưa bộ chuyển đổi hooks vào
sử dụng chỉ dựa trên tài liệu hoặc unit test giả lập.

Nguồn giao thức: [Codex app-server](https://learn.chatgpt.com/docs/app-server),
[đóng gói plugin](https://developers.openai.com/plugins/build/plugins),
[hooks và cơ chế trust](https://learn.chatgpt.com/docs/hooks).
