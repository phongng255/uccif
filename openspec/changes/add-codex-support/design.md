# Thiết kế

Trạng thái: đã được duyệt; phần setup/workflow theo repo đang được triển khai.
Package native workflow đã qua kiểm chứng cài/gỡ và nhận skills trên runtime 0.167.0/Linux.
Workflow đã qua model turn thật trên bundled CLI 0.166.0-alpha.6/macOS. Hooks và UI đồ họa
Desktop/VS Code vẫn chưa được kiểm chứng.

## Căn cứ và giới hạn

Đã đối chiếu tài liệu OpenAI chính thức ngày 06/11/2026:

1. [Đóng gói plugin](https://developers.openai.com/plugins/build/plugins): hỗ trợ `plugin.json`,
   `mcp.json`, skills và phần mở rộng OpenAI. Hooks đóng kèm plugin được mô tả cho plugin
   cài thủ công trên Codex desktop, cần người dùng tin cậy và cần script có trong môi trường chạy.
   Cài plugin trên web không tự triển khai các script đó.
2. [Hooks](https://learn.chatgpt.com/docs/hooks): dữ liệu vào gồm phiên, thư mục làm việc,
   sự kiện và đường dẫn transcript nếu có. `apply_patch` giữ tên riêng, nội dung patch nằm ở
   `tool_input.command`; unified exec khớp Bash. `PostToolUse` cũng chạy khi shell thất bại.
   Định dạng transcript không phải giao diện ổn định cho hooks. `systemMessage` là cảnh báo trên
   giao diện hoặc luồng sự kiện, không phải dòng cuối câu trả lời được bảo đảm.
3. [Skills](https://learn.chatgpt.com/docs/build-skills): skills của repo được tìm trong
   `.agents/skills/`. Các skill cùng tên không tự hợp nhất.
4. [Hướng dẫn dự án](https://learn.chatgpt.com/docs/agent-configuration/agents-md): Codex đọc
   `AGENTS.md`; không dựa vào cách Claude nhập file bằng `@AGENTS.md`.
5. [MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli): dự án được tin cậy có thể dùng
   `.codex/config.toml`. Server do plugin cấp và server trong cấu hình người dùng/dự án là
   những nguồn riêng, cần tránh đăng ký trùng.

Các nguồn này định hướng thiết kế, chưa chứng minh mọi ứng dụng đang cài đều có cùng hành vi.
Mốc B sẽ ghi phiên bản, nền tảng, cách cài, dữ liệu sự kiện thực tế và hành vi trust trước khi
công bố hỗ trợ tự động hóa.

## Kết quả khảo sát app và IDE (06/11/2026)

Tài liệu [cấu hình ứng dụng](https://learn.chatgpt.com/docs/developer-settings) xác nhận
Codex trong app dùng chung cấu hình agent và MCP với CLI/IDE extension. Tài liệu
[IDE](https://learn.chatgpt.com/docs/codex/ide) mô tả extension chính thức cho VS Code
và các editor tương thích, nêu VS Code, Cursor và Windsurf. Tài liệu
[thiết lập extension](https://learn.chatgpt.com/docs/ide/settings) tách cấu hình agent
`config.toml` khỏi thiết lập giao diện editor `chatgpt.*`.

Hướng triển khai: một tích hợp UCCIF theo Codex runtime dùng chung, không tạo ba bộ
logic riêng cho app, CLI và VS Code. Setup repo cung cấp AGENTS.md, skills và MCP;
kiểm thử xác nhận riêng trên từng giao diện/phiên bản. Các khác biệt về hooks và cách
cài plugin vẫn phải qua mốc B, không suy ra ngang bằng chỉ vì cấu hình được dùng chung.
Không cần xây lại giao diện chat hay viết một VS Code extension mới cho UCCIF.

Người dùng đã làm rõ: Claude chạy trong Antigravity và lệnh `/uccif` chỉ là ví dụ
về trải nghiệm cài plugin rồi gọi workflow trong chat. Không có yêu cầu chạy Codex trong
Antigravity. Đích triển khai là Codex trong app và extension VS Code; không viết extension
editor mới. Workflow dùng tên skill Codex, với điểm vào `$uccif` nhận yêu cầu init/resume/
codegraph. Không cam kết cú pháp slash của Claude. Phần repo setup là bản đầu có thể kiểm thử;
package native và hooks vẫn phải qua mốc kiểm chứng trên ứng dụng thực tế.

Tài liệu [cấu hình nâng cao](https://learn.chatgpt.com/docs/config-file/config-advanced)
phân biệt điều phối trên cloud với thực thi cục bộ; trong phần cloud orchestration,
command hooks và hooks từ cấu hình/plugin cục bộ không được hỗ trợ. Vì vậy không lấy
khả năng của app hoặc việc công cụ chạy local để suy ra hooks chạy trong chat cloud.

## Bảng hỗ trợ dự kiến

| Khả năng | Setup repo trên ứng dụng Codex đã kiểm chứng | Plugin desktop cài thủ công sau mốc B | Web/cloud |
|---|---|---|---|
| Quy tắc và ngữ cảnh dự án | Khối UCCIF trong AGENTS.md | Ngữ cảnh qua hooks, tránh lặp quy tắc | Cần kiểm tra file có được gắn và đọc hay không |
| Skills quy trình/dự án | .agents/skills | Quy trình đóng gói và skills dự án được sinh | Phụ thuộc cách tìm skills của môi trường |
| CodeGraph | Cấu hình MCP cục bộ khi người dùng chọn | MCP đóng kèm, không thêm cấu hình lần hai | Cần executable/server có trong môi trường |
| Lệnh quản lý và tiếp tục công việc | Qua lệnh quy trình rõ ràng | Dùng chung kho công việc | Cần core và hệ thống file hoạt động |
| Theo dõi công việc/file tự động | Chỉ công bố nếu hooks được kiểm chứng | Có sau khi thử phiên thực tế thành công | Chưa kiểm chứng, để sau |
| Dòng token / LSP / chế độ chặn | Để sau | Để sau | Để sau |

## Các quyết định thiết kế

### 1. Dùng lại core và giữ tương thích dữ liệu

Thêm `codex` vào danh sách host; skills dự án trỏ tới `.agents/skills/`.
Giữ công việc, quyết định và tài liệu tại `.claude/uccif/`. Hướng dẫn Codex trỏ rõ đến các file đó.
Không di chuyển dữ liệu hoặc tạo bản công việc riêng cho từng host.

Dùng lại định danh dự án, khóa ghi và cách ghi file nguyên tử hiện có. Cần test hai phiên chạy
đồng thời; không tuyên bố xác định chính xác phiên nào sửa file chỉ từ git diff toàn workspace.

### 2. Setup trong repo, bảo toàn nội dung và gỡ được

`uccif setup codex --dry-run` liệt kê thay đổi/xung đột dự kiến mà không ghi file.
Setup quản lý một khối có ranh giới trong AGENTS.md và các tên skill riêng như
`uccif-codex-init`, `uccif-codex-resume`, `uccif-codex-codegraph`, tránh thay thế skill của
Antigravity/Gemini. Skills bản đồ dự án được sinh vẫn giữ tên hiện tại; phải kiểm tra dùng chung
và bảo đảm các lệnh trong skill đúng với host được chọn.

Ghi quyền quản lý và mã băm nội dung trong `.codex/.uccif-setup.json`. Chỉ ghép khối AGENTS và
bảng MCP do UCCIF quản lý; giữ nguyên nội dung/chú thích xung quanh. Không ghi lại toàn bộ file
TOML chỉ để thêm một bảng. Tái sử dụng mục MCP cùng tên hoặc tương đương nếu tương thích;
nếu xung đột, đưa đoạn cấu hình gợi ý cụ thể và không thay cấu hình đang có.

Phát hiện server do plugin cung cấp khi có thể. Nếu chưa xác định được kết nối, báo chưa rõ,
không báo sẵn sàng. Bộ đọc cấu hình phải tương thích Python 3.8 hoặc dùng chiến lược chỉ xử lý
bảng được sinh trong vùng giới hạn; không bắt buộc dùng `tomllib` vốn không có ở mọi phiên bản.

Chạy setup lần hai không tạo nội dung trùng. Khi gỡ, chỉ xóa file/khối/bảng do UCCIF tạo mà
người dùng chưa sửa. Giữ nội dung đã sửa và giải thích. Không xóa lịch sử công việc hoặc skill
dự án dùng chung có sẵn. Không sửa cấu hình trong thư mục home hoặc tự đánh dấu tin cậy hooks/dự án.

### 3. Sinh package plugin dành cho Codex

Sinh `plugins/uccif-codex/` gồm `plugin.json`, `mcp.json`, skills, `hooks/hooks.json` và core có
thể chạy. Lấy phiên bản từ manifest core. Đường dẫn trong manifest nằm bên trong package,
không trỏ tới `../uccif`. Kiểm chứng trình cài đặt có giữ/sao chép core trước khi chọn symlink
hay sao chép file thật. Trình sinh hỗ trợ `--check` giống các host hiện tại.

Lệnh cài chính xác và phiên bản tối thiểu sẽ được chốt tại mốc B. Setup repo và plugin phải
cùng tồn tại mà không nhân đôi MCP, hướng dẫn hoặc workflow skill cùng tên; kiểm tra bản cài
đang có trước khi ghi.

### 4. Chuyển đổi sự kiện Codex theo dữ liệu thực tế

Dùng bảng sự kiện/đầu ra riêng cho Codex. Các sự kiện dự kiến kiểm tra: SessionStart,
UserPromptSubmit, PreToolUse, PostToolUse, Stop, PreCompact, PostCompact và SessionEnd.
Chỉ đăng ký sự kiện đã thử trên phiên bản được chọn; không tự giả định có PostToolUseFailure.
Nhận diện lỗi từ mẫu phản hồi PostToolUse đã kiểm chứng nếu host hỗ trợ.

Chuẩn hóa đầu vào Bash/unified exec và tên MCP từ dữ liệu thực tế. Với `apply_patch` thành công,
đọc các thao tác thêm/sửa/xóa/di chuyển thành danh sách đường dẫn vì một patch có thể sửa nhiều
file. Giải đường dẫn tương đối theo cwd của sự kiện, giới hạn trong repo và giữ thông tin xóa/
đổi tên. Không giả định patch chỉ có một `file_path`; patch lỗi không được tạo bản ghi sửa file giả.

Giữ cơ chế đối chiếu git đầu lượt và tại Stop cho thay đổi qua shell/script. Test lệnh chạy
bất đồng bộ, lượt bị ngắt, file đã có thay đổi từ trước và trường hợp không có git. Với công cụ/
sự kiện chưa biết hoặc dữ liệu sai, hooks bỏ qua an toàn, không chặn host và ghi thông tin chẩn đoán.

Chỉ trả các trường đầu ra được sự kiện hỗ trợ. Tích hợp này không phát lệnh cấp/từ chối quyền,
viết lại đầu vào hoặc buộc tiếp tục tại Stop. Không bỏ qua trust và không bật `strict_codegraph`
cho Codex.

### 5. Chẩn đoán đúng trạng thái; để báo cáo token sang thay đổi riêng

`uccif doctor` phân biệt đã có cấu hình với server thực sự đã chạy; báo phiên bản Codex,
core/CodeGraph có sẵn hay không, chế độ cài và trạng thái hooks đã kiểm chứng đến đâu.
Không lấy `.mcp.json` của Claude làm bằng chứng Codex đã kết nối. Hiện `codegraph.mcp_via()`
kiểm tra plugin core trước nên cần điều chỉnh theo host.

Không thêm bộ đọc token Codex trong thay đổi này. Chưa hỗ trợ thì báo không có số liệu, không
báo số 0 hoặc ước lượng. Tài liệu mô tả rõ `uccif task show/checkpoint/close` khi không có hooks.
Báo cáo token đầy đủ cần đề xuất riêng với nguồn số liệu và hành vi hiển thị đã kiểm chứng.

## Các phương án đã cân nhắc

- Sao chép nguyên plugin Claude: không chọn vì cách tìm plugin, đối số patch, sự kiện và đầu ra khác.
- Chỉ thêm AGENTS.md: đủ làm nền tảng ban đầu nhưng chưa đủ để công bố bộ nhớ công việc tự động.
- Đổi toàn bộ `.claude/uccif` thành `.uccif`: ngoài phạm vi và tăng rủi ro tương thích.
- Bọc mọi lần chạy Codex bằng script: thêm phụ thuộc khởi chạy không cần thiết; ưu tiên cấu hình gốc.

## Rủi ro và điều kiện phát hành

Giao diện host có thể đổi; ghi phiên bản đã thử và giữ mẫu sự kiện đã loại dữ liệu nhạy cảm.
Bỏ qua test phiên thực tế không được tính là đã hỗ trợ. Thư mục skill dùng chung và MCP có sẵn
cần test cùng tồn tại. Công việc được chia sẻ giữa các host nên phải giữ khóa ghi và test hai phiên.

Nếu không chạy thử được do thiếu ứng dụng, thông tin đăng nhập hoặc desktop, đánh dấu tự động hóa
chưa kiểm chứng và dừng ở bước duyệt phần cơ bản, không mở rộng tuyên bố hỗ trợ.

## Kết quả runtime và điều chỉnh package workflow

- Binary được kiểm chứng: Codex CLI/app-server 0.167.0 trên Linux.
- Package `plugins/uccif-codex/` và marketplace `.agents/plugins/marketplace.json` được sinh
  từ nguồn chung. Core được sao chép đầy đủ trong package, không dùng symlink ra ngoài.
- Plugin có tên `uccif`; runtime thêm namespace vào skills thành `uccif:init`, `uccif:resume`,
  `uccif:codegraph`, `uccif:uccif`. Repo skills vẫn giữ tên riêng đã thiết kế.
- Bản cài workflow chưa chứa hooks hoặc MCP tự khởi động. Đây là bước đóng gói workflow để
  kiểm chứng độc lập, không phải xác nhận khả năng tự động hóa của toàn bộ thiết kế.
- Script `tests/codex_runtime_check.py` kiểm tra cài/gỡ, nhận skills, core/task CLI, dùng chung
  với repo setup và ranh giới hook chưa trust, không cần gọi model hay dùng credential.
- Không suy ra UI app/VS Code hoặc hook execution từ việc skills/list thành công.
- Phiên bản package vẫn theo core 1.3.0; chưa tăng phiên bản phát hành hoặc publish.
