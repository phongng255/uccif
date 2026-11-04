# Hướng Dẫn Sử Dụng UCCIF (Dành Cho Người Mới Bắt Đầu)

Tài liệu này được viết dành cho tất cả mọi người, kể cả khi bạn **chưa từng dùng dòng lệnh (terminal)** bao giờ. Mọi thao tác đều có lệnh mẫu để bạn sao chép (copy) và dán (paste), kèm theo hình ảnh văn bản kết quả thực tế.

---

## 1. UCCIF Là Gì Và Giúp Gì Cho Bạn?

Bình thường khi bạn dùng AI hỗ trợ lập trình (như Claude Code, Gemini CLI hay Antigravity), mỗi lần bạn hỏi một câu mới hoặc chuyển sang việc khác, AI thường "quên" những gì vừa làm, tìm kiếm file rất chậm và tiêu tốn rất nhiều token (chi phí API).

**UCCIF** giống như một trợ lý quản lý dự án thông minh chạy ngầm cùng AI của bạn:
1. **Ghi nhớ công việc tự động:** Ngay khi AI sửa file đầu tiên, UCCIF tự động tạo ghi chú việc đang làm. Dù bạn tắt máy hay xoá ngữ cảnh chat (`/clear`), AI vẫn nhớ mình đang làm dở điều gì.
2. **Bản đồ mã nguồn thông minh:** Tích hợp bộ tạo bản đồ code (CodeGraph) giúp AI hiểu cấu trúc dự án ngay lập tức mà không phải đọc dò từng file, giúp AI trả lời nhanh hơn và tiết kiệm đến 70% chi phí token.
3. **Quy tắc làm việc an toàn:** Nhắc nhở AI luôn tự kiểm tra lại code sau khi sửa và trả lời bạn bằng tiếng Việt rõ ràng, dễ hiểu.

---

## 2. Chuẩn Bị Môi Trường

Trước khi dùng, máy tính của bạn cần có **Git**, **Python** và **Node.js**. Hãy mở cửa sổ dòng lệnh (Terminal trên macOS/Linux hoặc PowerShell trên Windows) và làm theo hướng dẫn dưới đây.

### Bước 2.1: Mở cửa sổ dòng lệnh (Terminal)
- **macOS:** Nhấn tổ hợp phím `Command + Space`, gõ `Terminal` rồi nhấn `Enter`.
- **Windows:** Nhấn phím `Windows`, gõ `PowerShell`, chuột phải vào **Windows PowerShell** và chọn **Run as Administrator**.
- **Linux:** Nhấn tổ hợp phím `Ctrl + Alt + T`.

---

### Bước 2.2: Kiểm tra hoặc cài đặt Git

**Lệnh kiểm tra:**
```bash
git --version
```
*Kết quả mong đợi:*
```text
git version 2.39.0 (hoặc số phiên bản tương tự)
```

**Nếu chưa có Git:**
- **macOS:** Gõ `xcode-select --install` rồi nhấn nút **Install** trên hộp thoại xuất hiện.
- **Windows:** Tải và cài đặt từ trang chủ [git-scm.com/download/win](https://git-scm.com/download/win) (chọn thiết lập mặc định).
- **Ubuntu/Linux:** Chạy lệnh:
  ```bash
  sudo apt update && sudo apt install -y git
  ```

---

### Bước 2.3: Kiểm tra hoặc cài đặt Python (phiên bản 3.8 trở lên)

**Lệnh kiểm tra:**
```bash
python3 --version || python --version
```
*Kết quả mong đợi:*
```text
Python 3.10.12 (hoặc bất kỳ bản nào từ 3.8 trở lên)
```

**Nếu chưa có Python:**
- **macOS:** Tải bản cài đặt từ [python.org/downloads](https://www.python.org/downloads/) hoặc nếu dùng Homebrew: `brew install python`.
- **Windows:** Tải từ [python.org/downloads](https://www.python.org/downloads/). *(Lưu ý quan trọng: Nhớ tích chọn vào ô "Add Python to PATH" ở bước đầu tiên khi cài đặt)*.
- **Ubuntu/Linux:** Chạy lệnh:
  ```bash
  sudo apt update && sudo apt install -y python3 python3-pip
  ```

---

### Bước 2.4: Kiểm tra hoặc cài đặt Node.js (phiên bản 18 trở lên)

Node.js cần thiết để chạy công cụ phân tích mã nguồn CodeGraph.

**Lệnh kiểm tra:**
```bash
node --version && npm --version
```
*Kết quả mong đợi:*
```text
v20.18.0
10.8.2
```

**Nếu chưa có Node.js:**
- **macOS / Windows:** Tải bản LTS từ [nodejs.org](https://nodejs.org/) và chạy bộ cài đặt.
- **Ubuntu/Linux:** Chạy lệnh:
  ```bash
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt install -y nodejs
  ```

---

## 3. Cài Đặt UCCIF Cho Từng Công Cụ

Chọn phần hướng dẫn ứng với công cụ AI mà bạn đang sử dụng:

```
+-------------------------------------------------------------------+
|  Bạn đang dùng công cụ nào?                                       |
|  - Claude Code: Xem Mục 3.1                                       |
|  - Antigravity CLI (lệnh agy): Xem Mục 3.2                        |
|  - Antigravity IDE: Xem Mục 3.3                                   |
|  - Gemini CLI (dành cho tài khoản doanh nghiệp): Xem Mục 3.4      |
+-------------------------------------------------------------------+
```

---

### 3.1. Dành cho Claude Code

#### 1. Lệnh cài đặt
Khởi động Claude Code trong terminal của bạn:
```bash
claude
```
Bên trong giao diện chat của Claude Code, gõ lần lượt 2 dòng sau:
```text
/plugin marketplace add phongng255/uccif
/plugin install uccif@uccif
```

#### 2. Kiểm tra cài đặt thành công
Gõ lệnh:
```text
/plugin list
```
*Kết quả bạn sẽ thấy:* Danh sách có plugin `uccif` kèm trạng thái `enabled`.

#### 3. Lần đầu mở dự án
- Mở thư mục dự án của bạn bằng lệnh `claude`.
- Bạn có thể đặt bất kỳ câu hỏi nào về dự án, ví dụ: `"Dự án này làm gì?"`.
- Claude sẽ phát hiện chưa có CodeGraph và hỏi bạn một câu duy nhất:
  > *"CodeGraph is NOT installed. Install it now? (yes/no)"*
- Bạn chỉ cần trả lời: **`yes`**. Claude Code sẽ tự động cài đặt CodeGraph, quét dự án và tạo bản đồ mã nguồn ngay lập tức. Sau đó, bạn khởi động lại Claude Code một lần để hoàn tất.

---

### 3.2. Dành cho Antigravity CLI (`agy`)

> [!NOTE]
> Google đã ngừng cung cấp Gemini CLI miễn phí từ ngày 18/06/2026 và thay thế bằng **Antigravity CLI** (`agy`). Đây là công cụ chuẩn dành cho người dùng cá nhân và tài khoản Google miễn phí.

#### 1. Lệnh cài đặt
Mở Terminal và chạy lệnh sau (lưu ý đường dẫn trỏ đúng thư mục plugin):
```bash
agy plugin install https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity
```
*Hoặc nếu bạn đã tải mã nguồn dự án về máy:*
```bash
agy plugin install /đường/dẫn/tới/uccif/plugins/uccif-antigravity
```

#### 2. Kiểm tra cài đặt thành công
Chạy lệnh trong terminal:
```bash
agy plugin list
```
*Kết quả bạn sẽ thấy:*
```text
Installed plugins:
- uccif (enabled, 1.1.0)
    Source:     antigravity
    Components: 3 skills, 1 MCP server, 1 hook
```

#### 3. Trải nghiệm lần đầu
Mở một thư mục code bất kỳ và gõ:
```bash
agy
```
UCCIF sẽ kích hoạt ngay lập tức: các quy tắc cốt lõi được nạp, cấu trúc dự án được phân tích và sẵn sàng hỗ trợ bạn.

---

### 3.3. Dành cho Antigravity IDE

Antigravity IDE hỗ trợ đọc cấu hình theo từng thư mục dự án (workspace) qua thư mục `.agents/`.

#### 1. Cài đặt cho một dự án
Mở Terminal, di chuyển vào thư mục dự án bạn muốn lập trình và chạy:
```bash
cd /duong/dan/du-an-cua-ban
python3 /duong/dan/uccif/plugins/uccif/bin/uccif setup antigravity
```
*(Nếu bạn dùng Windows, thay `python3` bằng `python`)*.

*Kết quả:*
```text
uccif: configured .agents/ for Antigravity IDE (rules, skills, mcp_config.json)
```

#### 2. Kiểm tra cài đặt thành công
Kiểm tra thư mục `.agents/` vừa được tạo:
- Tệp `.agents/rules/uccif.md`: Chứa các quy tắc dự án.
- Tệp `.agents/mcp_config.json`: Chứa cấu hình CodeGraph.

Mở dự án trong Antigravity IDE, công cụ sẽ tự động nhận diện toàn bộ kỹ năng và quy tắc của UCCIF.

---

### 3.4. Dành cho Gemini CLI (Tài khoản Google Code Assist doanh nghiệp)

> [!IMPORTANT]
> Chỉ áp dụng nếu tổ chức của bạn đã mua gói bản quyền **Gemini Code Assist Enterprise**. Tài khoản Google cá nhân không thể đăng nhập được Gemini CLI.

#### 1. Lệnh cài đặt
Trong Terminal, chạy lệnh:
```bash
gemini extensions install https://github.com/phongng255/uccif.git
```

#### 2. Kiểm tra cài đặt thành công
```bash
gemini extensions list
```
Bạn sẽ thấy `uccif` xuất hiện trong danh sách các tiện ích đã cài.

---

## 4. Sử Dụng Hằng Ngày

Khi đã cài đặt UCCIF, **bạn hoàn toàn không cần học thuộc bất kỳ lệnh kỹ thuật nào**. Bạn chỉ cần trò chuyện tự nhiên với AI.

### Một số câu lệnh mẫu bằng tiếng Việt:
- *"Giải thích giúp mình luồng đăng nhập của người dùng hoạt động thế nào?"*
- *"Tìm giúp mình hàm tính tổng tiền đơn hàng nằm ở đâu?"*
- *"Mình muốn thêm tính năng gửi email xác thực, cần sửa những file nào?"*
- *"Kiểm tra xem thay đổi này có làm hỏng các bài test hiện tại không."*

### Dòng báo cáo Token (🔢) có ý nghĩa gì?
Sau mỗi câu trả lời của AI, bạn sẽ thấy một dòng nhỏ ở cuối dạng:
```text
🔢 2.4k tok (+120 cache 90%) · turn 3 · 💡 /clear recommended (task saved)
```
- **Ý nghĩa:** Cho bạn biết chính xác lượt chat vừa rồi tốn bao nhiêu token, bao nhiêu phần trăm được lưu trong bộ nhớ tạm (cache) để tiết kiệm tiền.
- **Lời khuyên `/clear`:** Khi dự án lớn và cuộc trò chuyện dài, UCCIF sẽ nhắc bạn gõ `/clear`. Bạn cứ yên tâm gõ `/clear` vì UCCIF đã lưu lại công việc dang dở vào bộ nhớ đệm, AI sẽ không bao giờ bị quên!

### Tệp nào nên đưa lên Git (Commit) và tệp nào không?

| Tệp / Thư mục | Có commit không? | Ý nghĩa |
| :--- | :---: | :--- |
| `AGENTS.md` | **CÓ** | Hướng dẫn chung cho mọi AI khi đọc dự án. |
| `.claude/skills/` hoặc `.agents/skills/` | **CÓ** | Bản đồ mã nguồn dự án giúp đồng đội dùng AI nhanh hơn. |
| `.claude/uccif/summary.md` | **CÓ** | Tóm tắt mục đích và quy ước của dự án. |
| `.claude/uccif/.local/` | **KHÔNG** | Bộ nhớ tạm cá nhân (đã được tự động bỏ qua qua `.gitignore`). |
| `.codegraph/` | **KHÔNG** | Cơ sở dữ liệu chỉ mục code (được tự động loại khỏi git). |

---

## 5. Cập Nhật Lên Phiên Bản Mới

Khi UCCIF ra mắt tính năng mới, bạn có thể cập nhật rất nhanh:

### Cho Claude Code:
Vào Claude Code và gõ:
```text
/plugin marketplace update uccif
/plugin update uccif@uccif
```
*Sau khi cập nhật, hãy khởi động lại Claude Code một lần.*

### Cho Antigravity CLI:
Chạy lại lệnh cài đặt từ URL:
```bash
agy plugin install https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity
```

### Cho Antigravity IDE:
Di chuyển vào thư mục dự án và chạy lại lệnh setup:
```bash
python3 /duong/dan/uccif/plugins/uccif/bin/uccif setup antigravity
```

---

## 6. Gỡ Cài Đặt Hoàn Toàn

Nếu bạn không muốn sử dụng UCCIF nữa, dưới đây là cách gỡ sạch sẽ mà không ảnh hưởng tới mã nguồn dự án:

### Bước 6.1: Gỡ plugin khỏi công cụ
- **Claude Code:** Gõ `/plugin uninstall uccif@uccif` trong chat.
- **Antigravity CLI:** Chạy lệnh terminal:
  ```bash
  agy plugin uninstall uccif
  ```
- **Antigravity IDE:** Chạy lệnh trong thư mục dự án:
  ```bash
  python3 /duong/dan/uccif/plugins/uccif/bin/uccif setup antigravity --remove
  ```
- **Gemini CLI:** Chạy lệnh:
  ```bash
  gemini extensions uninstall uccif
  ```

### Bước 6.2: Gỡ công cụ CodeGraph (nếu muốn)
```bash
npm uninstall -g @colbymchenry/codegraph
```

### Bước 6.3: Xoá dữ liệu UCCIF đã tạo trong dự án
UCCIF chỉ tạo các thư mục độc lập sau, bạn có thể xoá chúng đi bằng tay hoặc lệnh:
- Thư mục `.claude/uccif/`
- Thư mục `.codegraph/`
- Thư mục `.agents/skills/` (chứa các kỹ năng `<project>-map`, `-mod-*`, `-bugfix`)
- Nếu muốn giữ lại tài liệu tóm tắt dự án, bạn chỉ cần giữ lại file `.claude/uccif/summary.md`.

---

## 7. Các Lỗi Thường Gặp Và Cách Xử Lý

| Triệu chứng | Nguyên nhân | Cách khắc phục |
| :--- | :--- | :--- |
| `python3: command not found` hoặc `python not found` | Máy tính chưa cài Python hoặc chưa đưa Python vào biến môi trường PATH. | Tải và cài đặt Python từ python.org. Nếu dùng Windows, nhớ tích chọn ô **"Add Python to PATH"**. |
| `Error: install target must be a directory` khi chạy `agy plugin install` | Bạn truyền sai đường dẫn thư mục hoặc đường dẫn chưa được tải về. | Dùng đúng URL chi tiết: `https://github.com/phongng255/uccif/tree/main/plugins/uccif-antigravity` hoặc chỉ định thư mục đầy đủ trên máy. |
| AI không hiển thị dòng tính token sau mỗi câu trả lời | Đang dùng Antigravity hoặc chế độ token report bị tắt. | Antigravity không hỗ trợ chèn tin nhắn hệ thống sau lượt trả lời. Với Claude Code, gõ `/config` và bật lại `token_report`. |
| Gemini CLI báo lỗi không đăng nhập được | Tài khoản Google của bạn là tài khoản cá nhân miễn phí. | Google đã ngừng cung cấp Gemini CLI miễn phí từ 18/06/2026. Hãy chuyển sang sử dụng **Antigravity CLI** (`agy`). |
| `ModuleNotFoundError: No module named 'pytest'` khi chạy kiểm thử | Môi trường Python thiếu thư viện `pytest`. | Chạy lệnh `python3 -m pip install pytest` hoặc dùng môi trường ảo `.venv`. |

---

## 8. Các Câu Hỏi Thường Gặp (FAQ)

**Hỏi: Dùng UCCIF có làm lộ mã nguồn dự án của tôi ra ngoài không?**  
*Trả lời:* **Tuyệt đối không.** Toàn bộ việc ghi nhớ và lập chỉ mục CodeGraph đều chạy 100% cục bộ (offline) trên máy tính của bạn. UCCIF không có máy chủ lưu trữ bên ngoài và không gửi code của bạn đi bất cứ đâu.

**Hỏi: UCCIF có tự ý xóa hay sửa code dự án của tôi không?**  
*Trả lời:* **Không.** Mọi thay đổi code đều do chính mô hình AI mà bạn ra lệnh thực hiện và bạn luôn có quyền kiểm soát phê duyệt. Bản thân UCCIF chỉ quản lý file hướng dẫn, bản đồ code và ghi nhớ ngữ cảnh.

**Hỏi: Dự án của tôi có nhiều người cùng làm, họ không cài UCCIF thì có bị lỗi không?**  
*Trả lời:* **Hoàn toàn không ảnh hưởng.** File `AGENTS.md` và các skill trong `.agents/skills/` là các tệp Markdown tiêu chuẩn. Đồng nghiệp của bạn dù dùng bất kỳ công cụ nào cũng vẫn đọc hiểu được bình thường.
