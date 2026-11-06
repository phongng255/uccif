# Đề xuất: Thêm Codex vào các host của UCCIF

Trạng thái: ĐÃ DUYỆT ngày 06/11/2026. Đã triển khai bản thử nghiệm setup/workflow theo repo;
đã kiểm chứng cài/gỡ plugin local và nhận skills bằng Codex CLI/app-server 0.167.0 trên Linux.
Đã kiểm chứng native status/init/resume và repository resume bằng model turn thật qua bundled CLI
0.166.0-alpha.6 trên macOS. Chưa kiểm chứng UI đồ họa app/VS Code; chưa phát hành hoặc bật hooks.

Yêu cầu khi thực hiện: điểm chưa rõ hoặc cần người dùng hỗ trợ phải được hỏi trước khi làm phần phụ thuộc; không tự đoán.

## Lý do

UCCIF hiện khai báo `claude`, `gemini` và `antigravity` trong `hosts.py`. Core Python đã
xử lý bộ nhớ công việc, quy tắc, nhật ký, skills của dự án và CodeGraph. Để hỗ trợ Codex,
cần bổ sung cách cài đặt, cấu hình và chuyển đổi sự kiện riêng, đồng thời dùng lại core.

Phạm vi là Codex chạy các mô hình GPT. Không xây tích hợp gọi GPT API trực tiếp hoặc
công cụ cho cuộc trò chuyện ChatGPT thông thường; không phụ thuộc một tên model cụ thể.

## Hướng tích hợp sau khảo sát app/IDE

Dùng một bộ tích hợp Codex chung cho app, CLI và extension VS Code dựa trên cấu hình
agent/MCP được chia sẻ; kiểm chứng riêng từng môi trường. Không viết lại giao diện chat.
Ví dụ Claude trong Antigravity chỉ mô tả trải nghiệm gọi workflow trong chat; không có yêu cầu
chạy Codex trong Antigravity. Repo setup dùng điểm vào `$uccif`; plugin native có namespace thực tế `$uccif:init`, `$uccif:resume`,
`$uccif:codegraph` và menu `$uccif:uccif`. Chi tiết và nguồn chính thức nằm trong `design.md`.

## Những thay đổi dự kiến

- Thêm host `codex`, kèm bảng khả năng theo từng ứng dụng và phiên bản đã kiểm chứng.
- Thêm `uccif setup codex [--dry-run|--remove]` để thiết lập trong phạm vi repo:
  một khối do UCCIF quản lý trong `AGENTS.md`, skills tương thích trong `.agents/skills/`,
  và cấu hình CodeGraph MCP trong `.codex/config.toml` khi người dùng chọn dùng và chưa có server tương đương.
- Giữ nguyên hướng dẫn, cấu hình, skills có sẵn và quyết định tin cậy hooks của người dùng.
- Sinh package plugin cho Codex desktop, gồm skills, MCP và hooks theo vòng đời phiên.
  Chỉ phát hành phần hooks sau khi đã kiểm chứng trên môi trường chạy thực tế.
- Đưa các lần sửa thành công, patch nhiều file và thay đổi qua shell vào bộ nhớ công việc hiện có.
- `doctor` và hướng dẫn phải nói rõ tính năng chưa hỗ trợ. Tách báo cáo token thành công việc sau,
  trừ khi tìm được nguồn số liệu ổn định, đã kiểm chứng và kênh hiển thị phù hợp.
- Giữ dữ liệu tại `.claude/uccif/` để các host tiếp tục cùng công việc của dự án.

## Các mốc bàn giao và duyệt

| Mốc | Sản phẩm | Điều kiện hoàn thành |
|---|---|---|
| A — duyệt đề xuất | Đề xuất, thiết kế, checklist, đặc tả bổ sung | Bạn duyệt trước khi sửa source |
| B — kiểm chứng môi trường | Phiên bản ứng dụng cụ thể và mẫu sự kiện đã loại dữ liệu nhạy cảm | Xác minh hooks, dữ liệu vào, cơ chế trust và đầu ra; môi trường chưa hỗ trợ chỉ có phần cơ bản |
| C — phần cơ bản | Setup, hướng dẫn, skills, MCP, doctor | Cài/gỡ lặp lại và dùng chung với host khác đều đạt |
| D — tự động hóa | Bộ chuyển đổi host và package desktop được sinh tự động | Thử sửa file, chạy shell và tiếp tục phiên thành công trên từng môi trường công bố hỗ trợ |
| E — duyệt phát hành | Diff, kết quả test, bảng tương thích, ghi chú chuyển đổi | Bạn xem kết quả trước khi phát hành hoặc merge |

Mốc B là điều kiện bắt buộc trước D. Nếu B không đạt, báo rõ vướng mắc và bàn giao phần cơ bản
đã kiểm chứng để duyệt. Không dùng lời nhắc thay cho hooks rồi gọi đó là theo dõi tự động.

## Phạm vi ảnh hưởng

- Đặc tả mới: `codex-support`.
- File hiện có có thể cần sửa: `hosts.py`, `cli.py`, `hostfiles.py`, `hooks.py`,
  `codegraph.py`, `detect.py`, `skillgen.py` và các test liên quan trong `tests/`.
- File triển khai mới dự kiến: `uccif_lib/codex_setup.py`, `scripts/build_codex.py`,
  package được sinh trong `plugins/uccif-codex/`, test và dữ liệu mẫu của Codex.
- Tài liệu: README, hướng dẫn Việt/Anh, changelog và kiểm tra file sinh tự động trong CI.
- Không di chuyển dữ liệu; phần setup cơ bản không ghi cấu hình toàn máy.

## Chưa làm trong thay đổi này

- Gọi OpenAI API trực tiếp, thêm backend model hoặc prompt riêng cho từng model.
- Cam kết desktop, CLI, IDE, web/cloud và ChatGPT có khả năng giống nhau.
- Tự cài CodeGraph, language server hoặc Codex.
- Ước lượng token, sao chép bộ đọc transcript Claude hoặc cam kết dòng token sau mỗi trả lời.
- LSP riêng cho Codex, chế độ chặn nghiêm ngặt hoặc đầy đủ custom agents như Claude.
- Đăng plugin công khai, deploy, push hoặc merge trong giai đoạn lập kế hoạch.

## Căn cứ

Bản repo đối chiếu: commit `23f479a`, UCCIF `1.3.0`; kiểm tra ngày 06/11/2026.
Trước khi thêm tài liệu này, bộ test đạt 322 test, bỏ qua 1 test.
Nguồn OpenAI chính thức và những điểm cần xác minh thêm nằm trong `design.md`.

## Kết quả triển khai giai đoạn workflow

Đã sinh package native workflow và marketplace riêng cho Codex, cài/gỡ bằng CLI thật,
kiểm tra skills từ cache và chạy core/task CLI của bản cài. Xem `docs/CODEX-RUNTIME-VI.md`.
Đây chưa phải giai đoạn hooks: package workflow không có hooks hoặc MCP tự khởi động;
CodeGraph dùng CLI hoặc cấu hình dự án tùy chọn. Các phần tự động hóa vẫn phụ thuộc mốc B.
