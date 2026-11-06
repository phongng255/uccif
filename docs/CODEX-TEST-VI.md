# Kiểm chứng bản thử nghiệm UCCIF trong Codex

Mục tiêu: xác minh app/extension thực tế có nhận skills và chạy workflow đúng hay không.
Bản này đã có plugin native dạng development preview và setup theo repo, nhưng chưa có hooks.
Không cần gửi API key hoặc nội dung cấu hình có thông tin đăng nhập.

## Chuẩn bị

- Ghi phiên bản Codex app hoặc extension Codex trong VS Code, phiên bản editor và hệ điều hành.
- Dùng bản checkout chứa thay đổi Codex này. Nếu dùng patch, áp dụng vào bản sạch tại commit
  `23f479a` bằng `git apply /duong/dan/uccif-codex-preview.patch`.
- Chọn dự án Git nhỏ, không chứa dữ liệu nhạy cảm để thử.

### Cách A: plugin native (ưu tiên)

Từ checkout UCCIF, đăng ký marketplace local và cài package:

```bash
codex plugin marketplace add /duong/dan/uccif
codex plugin add uccif@uccif-codex-local
```

Kết quả mong đợi: Codex nhận `$uccif:init`, `$uccif:resume`, `$uccif:codegraph` và
`$uccif:uccif`. Package chứa core riêng, không phụ thuộc đường dẫn checkout sau khi cài.

### Cách B: setup theo repo

Trong terminal tại dự án đích, chạy launcher từ checkout UCCIF:

```bash
/duong/dan/uccif/plugins/uccif/bin/uccif setup codex --dry-run
/duong/dan/uccif/plugins/uccif/bin/uccif setup codex
/duong/dan/uccif/plugins/uccif/bin/uccif doctor --host codex
```

Kết quả mong đợi: thêm khối UCCIF trong AGENTS.md, bốn skills riêng trong `.agents/skills/`,
manifest `.codex/.uccif-setup.json`. Không tự cài CodeGraph hoặc bật hooks/trust.
Nếu có file xung đột, dừng ở thông báo Skipped và gửi tên file/lý do; không xóa nội dung để vượt qua.

## Thử trong chat

1. Mở đúng dự án trong Codex app hoặc extension VS Code, tạo chat mới.
2. Với plugin native, kiểm tra bốn tên có namespace `uccif:*`. Với setup theo repo, kiểm tra
   `uccif` và ba skills `uccif-codex-*`.
3. Chọn menu tương ứng rồi yêu cầu `status`. Skill mention không phải lệnh terminal hay cú pháp
   slash của Claude.
4. Ghi nhận có gọi core đúng từ thư mục dự án hay không. Khi chưa có task, phải báo không có;
   không bịa công việc cũ. Doctor phải báo hooks chưa cài và kết nối MCP chưa kiểm chứng.
5. Thử `init`: phải đọc tài liệu có căn cứ, ghi summary qua core, không sửa source/CLAUDE.md,
   không tự cài CodeGraph. Nếu đã có summary cần thay, phải cho xem thay đổi trước.
6. Nếu đã có task thật được checkpoint, thử `resume`: đọc tiến độ và kiểm tra thay đổi trước
   khi tiếp tục. Nếu chưa có task, chỉ cần xác minh thông báo không có; không tạo lịch sử giả.

## Gỡ sau khi thử

Gỡ plugin native:

```bash
codex plugin remove uccif@uccif-codex-local
```

Hoặc gỡ setup theo repo:

```bash
/duong/dan/uccif/plugins/uccif/bin/uccif setup codex --remove --dry-run
/duong/dan/uccif/plugins/uccif/bin/uccif setup codex --remove
```

Nội dung người dùng đã sửa, skills dùng chung và lịch sử công việc phải còn nguyên.

## Kết quả cần gửi lại

Tên app/extension và phiên bản; hệ điều hành; skill có xuất hiện không; kết quả `status`;
lỗi nguyên văn nếu có (che đường dẫn cá nhân nếu cần). Ảnh danh sách skill hoặc lỗi là đủ,
không gửi token đăng nhập hay toàn bộ config.

Sau khi xác minh model gọi workflow đúng trong app/extension, mới chốt bộ kiểm chứng hooks.
Chưa dùng kết quả bước này để công bố theo dõi file tự động.
