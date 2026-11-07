# Hướng dẫn sử dụng UCCIF

Tài liệu này giúp bạn cài UCCIF, biết nó làm gì sau khi cài, và xử lý khi có trục trặc. Các lệnh đều chép và dán được. Bản tiếng Anh: [GUIDE.md](GUIDE.md).

## 1. UCCIF là gì

UCCIF là plugin cho các công cụ AI viết code. Nó không tự sửa code của bạn. Nó chỉ cung cấp cho AI những thứ sau:

| Thành phần | Tác dụng | Lưu ở đâu |
|---|---|---|
| **Quy tắc cốt lõi** | Nhắc AI tự chạy lệnh, phải có bằng chứng trước khi kết luận, hỏi trước khi cài package, deploy hay push, và trả lời bằng ngôn ngữ bạn chọn | Nạp đầu mỗi session |
| **Chỉ mục code (CodeGraph)** | AI tra hàm, luồng gọi và phạm vi ảnh hưởng từ chỉ mục, thay vì dò và đọc từng file | `.codegraph/` |
| **Skill của dự án** | Bản đồ module, cách sửa lỗi nhanh, và tối đa 5 skill cho các module lớn nhất, sinh từ chỉ mục | `.claude/skills/` hoặc `.agents/skills/` |
| **Ghi nhớ công việc** | Lần sửa file đầu tiên sẽ mở một task (sửa bằng lệnh Bash hay script cũng tính, nhờ so `git status` cuối mỗi lượt). Task được giữ qua các lượt chat và sau `/clear`, nên AI biết việc đang làm dở | `.claude/uccif/.local/` |
| **Dòng token** | Số token thật, đọc từ transcript, không ước lượng | Hiện sau mỗi câu trả lời |

UCCIF không chặn lệnh của AI: nó chỉ nhắc, không cấm. Ngoại lệ duy nhất là tuỳ chọn `strict_codegraph`, mặc định tắt (mục 5). Nếu bạn cài CodeGraph giữa session, AI được báo ngay ở tin nhắn kế tiếp, nên chuyển sang dùng chỉ mục luôn. Task mở sẽ tự đóng khi bạn chuyển sang việc mới hoặc sau 24 giờ không hoạt động.

## 2. Mỗi công cụ hỗ trợ đến đâu

| Tính năng | Claude Code | Antigravity CLI (`agy`) | Antigravity IDE | Gemini CLI |
|---|---|---|---|---|
| Quy tắc, skill, CodeGraph | Có | Có | Có | Có |
| Hook chạy tự động | Có | Có | **Không** | Có |
| Tự tạo task khi sửa file | Có, lấy tiêu đề từ prompt | Có, tiêu đề luôn là "Code change" | **Không** | Có, lấy tiêu đề từ prompt |
| Tự index và tự sinh skill | Có | Có | **Không**, chạy tay ở mục 3.3 | Có |
| Dòng token | Có | Không | Không | Có |
| `#quick` | Có | Không | Không | Có |
| Nhắc dùng CodeGraph trước khi tìm kiếm | Có | Không | Không | Có |

Phần Gemini CLI mới được kiểm tra bằng test tự động, chưa được chạy trong một session thật. Google đã ngừng phục vụ Gemini CLI cho người dùng không trả phí và Google One từ 18/06/2026. Nếu bạn dùng tài khoản cá nhân, hãy chọn Antigravity CLI.

Thư mục `.agents/` ít file hơn `.claude/` là bình thường. Hai bên dùng chung `.claude/uccif/`, còn những thứ như `.cc-writes` là file riêng của Claude Code.

## 3. Cài đặt

### Codex: plugin workflow và setup theo repo (bản thử nghiệm)

Đã kiểm chứng bằng **Codex CLI/app-server 0.167.0 trên Linux**: cài/gỡ plugin local, nhận đúng
skills, chạy core từ bản cài và lưu/đọc task. Trên macOS, model turn thật bằng bundled CLI
0.166.0-alpha.6 đã chạy đúng native status/init/resume và repository resume. Chưa thử thực thi
hooks hoặc UI đồ họa desktop/VS Code. Đây là package đang phát triển, chưa phát hành công khai.

Với checkout chứa thay đổi này, cài qua CLI:

```bash
codex plugin marketplace add /duong/dan/uccif
codex plugin add uccif@uccif-codex-local
```

Trong chat Codex, chọn skill hoặc nhắc `$uccif:init`, `$uccif:resume`, `$uccif:codegraph`.
Menu chung là `$uccif:uccif`. Tên này đã được app-server thực tế nhận từ plugin; không phải
lệnh terminal hoặc cú pháp slash của Claude. Package chứa core riêng được sinh từ nguồn chung,
chạy từ thư mục cache sau khi cài. Gỡ bằng `codex plugin remove uccif@uccif-codex-local`.

Nếu muốn setup riêng theo từng repo, tại dự án đích chạy launcher từ checkout UCCIF:

```bash
/duong/dan/uccif/plugins/uccif/bin/uccif setup codex --dry-run
/duong/dan/uccif/plugins/uccif/bin/uccif setup codex
```

Cách này thêm khối riêng trong AGENTS.md và skills `uccif`, `uccif-codex-*` vào `.agents/skills/`.
Tên repo skill khác tên có namespace của plugin. File setup chứa đường dẫn Python/core của
máy hiện tại, cần giữ cục bộ và setup lại khi di chuyển checkout. Xem trước khi gỡ bằng
`uccif setup codex --remove --dry-run`, sau đó `uccif setup codex --remove`.
Nội dung người dùng đã sửa, skills bản đồ dùng chung và lịch sử task được giữ lại.

Cả hai cách **chưa cài hooks**, chưa theo dõi task tự động, chưa có dòng token hay tích hợp LSP.
Workflow dùng checkpoint để lưu file thực tế đã sửa, kết quả test và bước tiếp theo. Dữ liệu
vẫn ở `.claude/uccif/`, dùng chung với các host hiện tại.

CodeGraph là tùy chọn và plugin workflow chưa tự khởi động MCP. Xem `uccif codegraph --host codex`;
muốn thêm cấu hình MCP trong repo, xem trước `uccif setup codex --with-codegraph --dry-run` rồi
chạy lại bỏ `--dry-run` nếu phù hợp. Setup giữ server có sẵn và báo cấu hình plugin chưa rõ,
không tự thêm trùng. Không có `tomllib` hoặc `tomli` tùy chọn thì giữ nguyên TOML có sẵn.
Setup không cài package hoặc đổi trust/cấu hình toàn máy. `uccif doctor --host codex` phân biệt
đã cấu hình với đã chạy kiểm chứng. Dự án chưa trust có thể không tải cấu hình/hook cục bộ,
trong khi skills vẫn được runtime 0.167.0 nhận trong bài kiểm tra.

Xem [báo cáo kiểm chứng trên cloud](CODEX-RUNTIME-VI.md). Bài kiểm chứng runtime có thể
chạy hoàn toàn trên cloud bằng script trong repo và job CI riêng.

Các công cụ cần có:

| Công cụ | Bắt buộc? | Kiểm tra bằng | Dùng để |
|---|---|---|---|
| Python 3.8 trở lên | Có | `python3 --version` | Chạy UCCIF |
| Git | Có | `git --version` | Nhận diện dự án |
| Node.js và npm | Chỉ khi dùng CodeGraph hoặc language server | `node --version` | Cài CodeGraph, pyright |

Trên Windows, Claude Code chạy hook qua Git Bash, nên hãy cài [Git for Windows](https://git-scm.com/download/win). CI có chạy trên Windows, nhưng UCCIF chưa được thử trong một session Claude Code thật trên Windows.

### 3.1. Claude Code

Trong khung chat của Claude Code, gõ:

```text
/plugin marketplace add phongng255/uccif
/plugin install uccif@uccif
```

Khởi động lại Claude Code, rồi kiểm tra trong terminal:

```bash
claude plugin list
```

Danh sách phải có `uccif`. Tiếp theo xem mục 3.5.

### 3.2. Antigravity CLI

```bash
agy plugin install https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity
```

Phải dùng đúng dạng URL này. URL repo trần, `#branch` hay `--ref` sẽ cài nhầm plugin của Claude, và Antigravity sẽ bỏ qua hook của plugin đó.

Kiểm tra:

```bash
agy plugin list
```

```text
Installed plugins:
- uccif (enabled, 1.2.0)
    Source:     antigravity
    Components: 3 skills, 1 rule, 1 MCP server, 1 hook
```

### 3.3. Antigravity IDE

IDE không có hook, nên phải chạy tay cho từng dự án. Dưới đây giả định bạn đã cài plugin ở mục 3.2. Nếu không, hãy dùng `plugins/uccif/bin/uccif` trong bản clone của repo này.

```bash
cd /duong/dan/du-an-cua-ban
```

```bash
~/.gemini/config/plugins/uccif/core/bin/uccif setup antigravity
```

Không chạy file này bằng `python3 .../bin/uccif`: đây là shell script, chạy vậy sẽ báo `SyntaxError`.

Kết quả mở đầu bằng dòng dưới đây. `N` là số file vừa ghi, lần chạy lại có thể khác:

```text
Wrote N files under .agents/ for the Antigravity IDE.
```

Lệnh này chỉ ghi `.agents/rules/uccif.md`, `.agents/mcp_config.json` và 3 skill `codegraph`, `init`, `resume`. Để có chỉ mục và skill của dự án, chạy thêm:

```bash
codegraph init --yes
```

```bash
~/.gemini/config/plugins/uccif/core/bin/uccif skills generate
```

Skill không tự cập nhật ở chế độ này. Khi cấu trúc dự án đổi nhiều, hãy chạy lại lệnh `skills generate`.

Nếu bạn dùng cả plugin `agy` lẫn `.agents/mcp_config.json`, tool của CodeGraph có thể hiện hai lần. Khi đó chỉ nên giữ một nơi khai báo.

### 3.4. Gemini CLI (chỉ tài khoản trả phí)

```bash
gemini extensions install https://github.com/phongng255/uccif.git
```

```bash
gemini extensions list
```

Để cập nhật lên bản mới nhất (thêm `--all` thay cho tên nếu muốn cập nhật mọi extension), rồi mở lại Gemini CLI:

```bash
gemini extensions update uccif
```

### 3.5. Lần đầu mở một dự án

1. Mở công cụ AI trong thư mục dự án và hỏi một câu bất kỳ.
2. Nếu máy chưa có CodeGraph, AI sẽ hỏi một lần có cài không. Câu chữ có thể khác nhau, vì AI tự viết câu hỏi.
3. Nếu trả lời **có**, AI sẽ cài CLI, index dự án và sinh skill. Sau đó khởi động lại công cụ một lần để nạp tool `codegraph_explore`.
4. Nếu trả lời **không**, AI sẽ tìm code bằng Grep và không hỏi lại trong dự án đó.

Khi CodeGraph đã có sẵn trên máy, các dự án mở sau sẽ tự được index và sinh skill ở chế độ nền.

Để kiểm tra, hãy hỏi AI: *"chạy uccif doctor giúp mình"*. Dòng `OK` là ổn, `WARN` là nên xử lý, `INFO` chỉ để tham khảo.

## 4. Dùng hằng ngày

Cứ nói chuyện bình thường, bạn không cần nhớ lệnh `uccif` nào:

| Bạn muốn | Cứ nói |
|---|---|
| Hiểu một luồng | "Luồng đăng nhập chạy thế nào?" |
| Tìm code | "Hàm tính tổng tiền ở đâu?" |
| Biết phạm vi một thay đổi | "Đổi props của component này thì ảnh hưởng những đâu?" |
| Sửa lỗi | "Bấm thanh toán bị lỗi 500, sửa giúp mình" |
| Làm tiếp việc cũ | "Tiếp tục việc hôm qua" hoặc "mình đang làm gì dở?" |
| Xem hook có chạy không | "Hôm nay hook có chạy không?" |
| Sửa rất nhỏ, không cần task | Thêm `#quick` vào prompt (Claude Code, Gemini CLI) |

### Đọc dòng token

```text
🔢 Tokens
   This turn: 2.4k input (2.1k from cache), 320 output
   Session total: 48k
   Context now: 35k (18%)
```

| Phần | Ý nghĩa |
|---|---|
| `This turn: ... input (... from cache)` | Token đầu vào của lượt này, và phần trong đó đọc từ cache |
| `output` | Token AI trả ra trong lượt này |
| `Session total` | Tổng token của cả session |
| `Context now` | Lượng context đang dùng, và tỷ lệ so với giới hạn nếu biết |

Đôi khi có thêm một dòng gợi ý ở cuối:

| Gợi ý | Khi nào | Nên làm |
|---|---|---|
| `💡 /clear recommended (task saved)` | Context từ 80k và không còn task mở | Gõ `/clear` |
| `💡 checkpoint, then /clear` | Context từ 150k và còn task mở | Bảo AI lưu tiến độ, rồi `/clear` |
| `💡 long session` | Tổng session từ 3 triệu token | Nên mở session mới |

Sau `/clear`, AI lấy lại được những gì đã lưu trong task: tiêu đề, file đã sửa, quyết định, vấn đề còn mở. Phần trao đổi trong chat thì không được giữ, nên quyết định quan trọng nên được bảo AI ghi lại.

## 5. Tùy chọn và mở rộng

Đổi tùy chọn trong `/config` của Claude Code. Với Gemini CLI, dùng phần settings của extension.

| Tùy chọn | Mặc định | Tác dụng |
|---|---|---|
| `reply_language` | `vi` | Ngôn ngữ AI trả lời bạn |
| `token_report` | bật | Hiện dòng token |
| `auto_setup` | tắt | Mặc định tắt. Khi bật, tự index và sinh skill khi đã có CodeGraph |
| `strict_codegraph` | tắt | Chỉ Claude Code. Khi đã có chỉ mục CodeGraph, lần đọc hoặc tìm trong file code đầu tiên của mỗi lượt bị từ chối một lần, cho tới khi AI tra CodeGraph. Thử lại thì được, nên vẫn tìm được chuỗi cố định hay giá trị config. Tắt: chỉ nhắc |

Muốn thêm luật riêng, hãy tạo các file sau. UCCIF chỉ đọc, không ghi vào chúng. Mỗi file được nạp tối đa 15 dòng không trống.

| Phạm vi | File |
|---|---|
| Một dự án | `<dự án>/.claude/uccif/rules.md` |
| Mọi dự án | `~/.claude/uccif/rules.md` |

Muốn ghi chú vào skill được sinh tự động, hãy viết **bên trong** khối `<!-- uccif:notes -->`. Ghi chú trong khối này được giữ qua mỗi lần sinh lại. Nếu sửa ngoài khối, UCCIF sẽ bỏ qua file đó cho đến khi chạy `--force`, và `--force` sẽ ghi đè phần bạn đã sửa ngoài khối.

## 6. Nên commit gì

| File hoặc thư mục | Làm một mình | Làm nhóm | Ghi chú |
|---|---|---|---|
| `.codegraph/` | Không | Không | Chỉ mục riêng từng máy, tự được loại khỏi git |
| `.claude/uccif/.local/` | Không | Không | Task và trạng thái riêng từng máy |
| `.agents/rules/uccif.md` | Không | Không | Chứa đường dẫn tuyệt đối của máy bạn |
| `.claude/uccif/summary.md`, `rules.md` | Tùy | Có | Mục đích và quy ước của dự án |
| Skill `<dự án>-*` | Tùy | Có | Có thể sinh lại từ chỉ mục |
| `AGENTS.md` | Tùy | Có | Nếu dự án có khối UCCIF, khối này trỏ tới `.claude/uccif/summary.md`, nên hãy commit cả hai cùng nhau |

Làm một mình thì có thể thêm `.claude/` và `.agents/` vào `.gitignore`. Nhưng nếu `.claude/` có file khác bạn muốn chia sẻ, hãy chỉ ignore đúng phần cần ignore.

## 7. Cập nhật

**Claude Code**, từ terminal:

```bash
claude plugin marketplace update uccif
```

```bash
claude plugin update uccif@uccif
```

Sau đó **khởi động lại Claude Code**, vì bản mới chỉ có hiệu lực sau khi khởi động lại. Thông báo "already up to date" nghĩa là chưa có phiên bản mới hơn. Bản cũ vẫn nằm trong thư mục cache của plugin một thời gian. Điều này bình thường, và bản đó không còn được dùng.

Skill của mỗi dự án chỉ được làm mới vào lần tiếp theo bạn mở công cụ trong dự án đó.

**Antigravity CLI:**

```bash
agy plugin uninstall uccif
```

```bash
agy plugin install https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity
```

**Antigravity IDE:** chạy lại `uccif setup antigravity` trong dự án. File bạn đã sửa sẽ được giữ nguyên, và lệnh sẽ báo những file đã bỏ qua.

## 8. Gỡ cài đặt

Gỡ khỏi công cụ:

| Công cụ | Lệnh |
|---|---|
| Claude Code | `claude plugin uninstall uccif@uccif` |
| Antigravity CLI | `agy plugin uninstall uccif` |
| Antigravity IDE | `uccif setup antigravity --remove`, chạy trong dự án và **trước khi** gỡ plugin. Chỉ xoá file nó đã ghi mà bạn chưa sửa |
| Gemini CLI | `gemini extensions uninstall uccif` |

Dọn dữ liệu trong dự án, nếu muốn. Hãy xem lại trước khi xoá:

- `.codegraph/`: có thể xoá.
- `.claude/uccif/`: có `summary.md` và `rules.md`, nên giữ lại nếu còn cần.
- `.claude/skills/<dự án>-*` và `.agents/skills/<dự án>-*`: chỉ xoá các skill được sinh tự động. Đừng xoá cả thư mục `skills/`, vì trong đó có thể có skill của bạn.
- Khối `<!-- UCCIF:BEGIN -->` đến `<!-- UCCIF:END -->` trong `AGENTS.md`, và dòng `@AGENTS.md` trong `CLAUDE.md` nếu bạn không dùng tới.

Gỡ CodeGraph, nếu không còn dự án nào cần:

```bash
npm uninstall -g @colbymchenry/codegraph
```

## 9. Xử lý sự cố

Bước đầu tiên luôn là hỏi AI: *"chạy uccif doctor giúp mình"*.

| Triệu chứng | Nguyên nhân | Cách xử lý |
|---|---|---|
| `SyntaxError` khi chạy `python3 .../bin/uccif` | `bin/uccif` là shell script | Chạy thẳng file đó, bỏ `python3` |
| `python3: command not found` | Thiếu Python hoặc Python chưa có trong PATH | Cài từ [python.org](https://www.python.org/downloads/). Trên Windows, nhớ chọn "Add Python to PATH" |
| Update xong nhưng vẫn thấy hành vi cũ | Chưa khởi động lại | Khởi động lại công cụ. Nếu vẫn vậy, gỡ rồi cài lại plugin |
| `.claude/skills` khác số lượng với `.agents/skills` | Một bên còn skill của bản cũ, hoặc chưa mở công cụ đó từ khi cập nhật | Mở công cụ đó trong dự án để skill được sinh lại |
| Không có dòng token | Đang dùng Antigravity, hoặc đã tắt `token_report` | Antigravity không hỗ trợ. Với Claude Code, bật lại trong `/config` |
| Không có tool `codegraph_explore` | Chưa khởi động lại sau khi cài, hoặc thiếu CLI | Khởi động lại, rồi hỏi AI chạy `uccif codegraph` |
| Tool CodeGraph hiện hai lần | Có hai nơi khai báo server | Chỉ giữ một nơi. Không chạy thêm `codegraph install --target=claude` |
| Antigravity không có task tự động | Đang dùng IDE, hoặc plugin cài sai URL | IDE không có hook. Với CLI, cài lại đúng URL ở mục 3.2 |
| `doctor` báo `hook errors` | Hook từng lỗi. Có thể chỉ một lần | Hỏi AI chạy `uccif log hooks --only-errors`. Chỉ cần điều tra nếu lỗi lặp lại |
| Gemini CLI không đăng nhập được | Tài khoản không trả phí | Dùng Antigravity CLI |

## 10. Câu hỏi thường gặp

**UCCIF có gửi code của tôi ra ngoài không?**
Bản thân UCCIF không có máy chủ, và CodeGraph được chạy với telemetry tắt. Việc index và ghi nhớ task đều nằm trên máy bạn. Tuy nhiên, công cụ AI bạn đang dùng vẫn gửi phần code nó đọc lên dịch vụ của nhà cung cấp, theo chính sách của họ.

**UCCIF có tự sửa code của tôi không?**
Không. UCCIF chỉ ghi file của riêng nó: chỉ mục, skill, ghi chú và trạng thái task. Code do AI sửa, theo yêu cầu và cơ chế cấp quyền của công cụ bạn dùng.

**UCCIF giúp tiết kiệm bao nhiêu token?**
Tùy dự án và cách dùng, nên tài liệu này không đưa ra con số chung. Dòng token cho biết số thật của bạn.

**Đồng đội không cài UCCIF thì sao?**
Không ảnh hưởng. `AGENTS.md` và các skill là file Markdown thường.

**Có cần tạo nhiều skill hơn không?**
Thường là không, vì mỗi skill làm tốn thêm context ở mọi session. Skill tự sinh cũng chỉ lặp lại những gì tra được từ chỉ mục. Nếu có kiến thức mà code không tự nói ra, hãy ghi vào khối notes hoặc viết một skill riêng.
