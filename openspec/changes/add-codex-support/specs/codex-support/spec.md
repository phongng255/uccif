## ADDED Requirements

Bản tiếng Việt để duyệt. Giữ các từ khóa cấu trúc OpenSpec (`Requirement`, `Scenario`,
`WHEN`, `THEN`, `AND`, `SHALL`) để công cụ nhận diện được; nội dung yêu cầu ở tiếng Việt.

### Requirement: Codex là host riêng với khả năng hỗ trợ được công bố rõ

Hệ thống SHALL khai báo Codex riêng với Claude, Gemini và Antigravity, đồng thời mô tả
khả năng hỗ trợ theo từng ứng dụng và phiên bản đã kiểm chứng.

#### Scenario: Ứng dụng chưa được kiểm chứng hooks

- **WHEN** Codex đọc được hướng dẫn/skills trong repo nhưng hooks chưa có hoặc chưa được kiểm chứng
- **THEN** quy trình cơ bản vẫn dùng được và không công bố theo dõi tự động là đã bật

#### Scenario: Host khác dùng cùng repo

- **WHEN** Codex và host hiện có mở cùng dự án
- **THEN** chúng dùng kho công việc hiện tại của dự án và host cũ giữ nguyên hành vi

### Requirement: Setup giới hạn trong repo và gỡ được

Hệ thống SHALL có `uccif setup codex`, `--dry-run`, `--remove`, giữ nội dung không thuộc
UCCIF hoặc đã được người dùng sửa, và SHALL NOT thay cấu hình toàn máy hay quyết định trust.

#### Scenario: Chạy setup lần đầu

- **WHEN** setup chạy trong dự án ghi được và không có cấu hình xung đột
- **THEN** tạo khối có ranh giới trong AGENTS.md, workflow skills Codex và manifest quyền quản lý
- **AND** cấu hình cách kết nối CodeGraph MCP đã chọn mà không tạo server trùng

#### Scenario: Xem trước thay đổi

- **WHEN** setup chạy với `--dry-run`
- **THEN** báo thay đổi và xung đột dự kiến mà không sửa file

#### Scenario: Chạy setup nhiều lần

- **WHEN** setup chạy hai lần mà người dùng không sửa nội dung ở giữa
- **THEN** lần hai không tạo hướng dẫn, skills hoặc cấu hình MCP trùng

#### Scenario: Đã có hướng dẫn hoặc cấu hình TOML

- **WHEN** AGENTS.md và `.codex/config.toml` chứa nội dung khác của người dùng
- **THEN** giữ nội dung đó cùng chú thích TOML và chỉ sửa vùng UCCIF quản lý

#### Scenario: CodeGraph đã có hoặc xung đột

- **WHEN** plugin hoặc cấu hình đã cung cấp server tương đương
- **THEN** dùng lại server hoặc báo xung đột, không tạo server thứ hai
- **AND** trường hợp chưa xác định được phải báo chưa rõ, không báo đã kiểm chứng

#### Scenario: Gỡ sau khi người dùng sửa file

- **WHEN** gỡ gặp file/khối đã bị sửa hoặc skill/mục cấu hình không thuộc UCCIF
- **THEN** giữ nội dung đó và báo những phần được giữ
- **AND** tài liệu dự án, quyết định và lịch sử công việc vẫn còn

### Requirement: Skills Codex dùng chung được với các host khác

Hệ thống SHALL sinh quy trình tương thích Codex và SHALL NOT ghi đè workflow skills
Gemini/Antigravity hiện có để cài Codex.

#### Scenario: Thư mục .agents được dùng chung

- **WHEN** setup Codex chạy sau khi host khác sinh `.agents/skills/`
- **THEN** quy trình cũ còn nguyên và tên workflow skill Codex không trùng
- **AND** skills dự án dùng chung chứa lệnh hợp lệ với host được chọn

### Requirement: Hooks đã kiểm chứng cập nhật bộ nhớ công việc chung

Trên ứng dụng đã kiểm chứng và bật hooks, hệ thống SHALL chuẩn hóa các sự kiện Codex được
hỗ trợ và ghi thay đổi thực tế trong dự án theo mô hình công việc hiện có.

#### Scenario: Patch nhiều file thành công

- **WHEN** apply_patch thành công khi thêm, sửa, xóa hoặc di chuyển nhiều file dự án
- **THEN** ghi mọi đường dẫn bị ảnh hưởng theo quy ước task hiện có
- **AND** dùng prompt người dùng đã làm sạch khi tự mở task

#### Scenario: Patch thất bại hoặc đường dẫn ngoài dự án

- **WHEN** patch thất bại hoặc tham chiếu đường dẫn ngoài repo
- **THEN** không tạo bản ghi sửa file giả hoặc ngoài dự án trong bộ nhớ công việc

#### Scenario: Lệnh shell sửa file và hoàn tất trong lượt

- **WHEN** shell/script thay đổi file dự án, kể cả khi lệnh bất đồng bộ hoàn tất
- **THEN** cơ chế hoàn tất/đối chiếu lượt đã kiểm chứng ghi nhận các thay đổi đó
- **AND** không quy thêm thay đổi cho file đã có thay đổi từ đầu lượt nhưng không đổi tiếp

#### Scenario: Tiếp tục phiên và chuyển host

- **WHEN** đã checkpoint task rồi tiếp tục dự án trong Codex hoặc host được hỗ trợ khác
- **THEN** đọc được tiến độ và bước tiếp theo từ cùng kho dữ liệu dự án

### Requirement: Hooks giữ nguyên cơ chế duyệt quyền của người dùng

Hệ thống SHALL tôn trọng trust của host, bỏ qua an toàn đầu vào sai/chưa hỗ trợ, và SHALL NOT
trả quyết định cấp quyền, viết lại đầu vào hoặc buộc tiếp tục tại Stop cho Codex.

#### Scenario: Hooks chưa được tin cậy

- **WHEN** ứng dụng bỏ qua hooks UCCIF chưa được trust
- **THEN** UCCIF không vượt qua quyết định đó và setup/hướng dẫn mô tả giới hạn

#### Scenario: Sự kiện sai định dạng hoặc chưa hỗ trợ

- **WHEN** hook nhận JSON sai, công cụ/sự kiện chưa biết hoặc thiếu metadata tùy chọn
- **THEN** trả về an toàn, không chặn host và ghi chẩn đoán nếu có thể

### Requirement: Package tự chứa tài nguyên và sinh lại được

Hệ thống SHALL sinh package Codex từ nguồn chung và giữ tài nguyên thực thi cùng đường dẫn
tham chiếu trong manifest bên trong thư mục gốc package.

#### Scenario: File sinh tự động bị cũ

- **WHEN** nguồn chung thay đổi nhưng chưa sinh lại package Codex
- **THEN** `--check` của trình sinh và CI báo file chưa được cập nhật

#### Scenario: Cài và nhận skills bằng Codex runtime thật

- **WHEN** cài package workflow local bằng Codex CLI 0.167.0 rồi gọi app-server skills/list
- **THEN** runtime trả các tên `uccif:init`, `uccif:resume`, `uccif:codegraph`, `uccif:uccif`
- **AND** các đường dẫn trỏ vào cache bản cài và core chạy được từ bên trong package
- **AND** kết quả không được diễn giải thành đã kiểm chứng model turn hoặc thực thi hooks

### Requirement: Chẩn đoán không công bố quá khả năng thực tế

Hệ thống SHALL phân biệt đã cấu hình với đã chạy kiểm chứng và báo số liệu/hiển thị token
Codex là chưa hỗ trợ khi chưa có triển khai được xác minh.

#### Scenario: Có manifest MCP Claude nhưng chưa cấu hình Codex

- **WHEN** doctor kiểm tra Codex trong dự án chỉ có khai báo MCP của plugin Claude
- **THEN** không báo server CodeGraph của Codex đã sẵn sàng

#### Scenario: Không có nguồn số liệu token

- **WHEN** Codex chạy mà chưa có nguồn số liệu được kiểm chứng
- **THEN** UCCIF không ước lượng token, không bịa số 0 và không hứa dòng token cuối trả lời

#### Scenario: Cài trên cloud nhưng thiếu chương trình thực thi

- **WHEN** plugin được cài trên web nhưng môi trường thiếu Python/core/CodeGraph cần thiết
- **THEN** tài liệu và chẩn đoán không công bố hooks tự động đang hoạt động
