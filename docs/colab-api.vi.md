# Chạy API trên Colab với checkpoint Google Drive

Notebook: [VieNeu_TTS_API_Colab.ipynb](../notebooks/VieNeu_TTS_API_Colab.ipynb).
Tải file về rồi chọn **File → Upload notebook** trong Google Colab.

## Chuẩn bị

- Chọn **Runtime → Change runtime type → GPU**, ví dụ T4.
- Upload checkpoint v3 Turbo đã merge lên Drive, gồm `voices_v3_turbo.json`
  trong `merged/` và weights/tokenizer/config trong `merged/update/`.
  Xem [cấu trúc checkpoint](backbones.vi.md). Adapter LoRA chưa merge không dùng được.
- Source tải về phải có API local checkpoint từ commit `e8960c4` hoặc thay đổi
  tương đương. Điền `REPO_URL` và `REPO_REF` của repo/branch đã chứa code này.
  Nếu code chưa được push, upload các thư mục `apps/`, `src/` và các file
  `pyproject.toml`, `uv.lock` lên cùng một thư mục Drive rồi nhập `SOURCE_DIR`.
  Không cần upload `.venv`, `.git` hoặc toàn bộ thư mục fine-tune.

## Chạy bằng một cell

Trong form **Chạy API + Cloudflare Tunnel**, nhập:

| Trường | Ví dụ / cách dùng |
|---|---|
| `BACKBONE_PATH` | `/content/drive/MyDrive/VieNeu/dat_phi_01/merged` |
| `SOURCE_DIR` | `/content/drive/MyDrive/VieNeu/api-source`; để trống để clone GitHub |
| `REPO_URL`, `REPO_REF` | Repo và branch chứa API; chỉ dùng khi `SOURCE_DIR` trống |
| `API_KEY_SECRET` | Tên Colab Secret, mặc định `VIENEU_API_KEY` |
| `STARTUP_TIMEOUT_SECONDS` | Thời gian chờ load model, mặc định 1200 giây |

Nhập đường dẫn `merged/update` cũng được. File giọng nằm ở `merged` sẽ được
tự tìm. Notebook tạo profile YAML riêng ở `/content/vieneu-colab-api`, không
sửa config gốc hoặc checkpoint trên Drive.

Bấm ▶, cấp quyền mount Drive. Nếu không có Secret, notebook hỏi API key bằng
ô nhập ẩn. Key không được in ra output. Có thể dùng Colab Secrets với quyền
truy cập notebook để tránh nhập lại key.

Cell tự cài FFmpeg, tạo môi trường Python 3.12/CUDA riêng theo `uv.lock`, load
checkpoint, chờ API sẵn sàng rồi mở tunnel. Lần đầu cần tải thêm codec và
speaker encoder từ Hugging Face. Khi thấy **SẴN SÀNG**, output có:

- **API URL**: dùng làm server URL trong Voice-Pro.
- **OpenAI Base URL**: URL có hậu tố `/v1`.
- **TTS endpoint**: URL kết thúc bằng `/v1/tts`.
- Model ID và danh sách giọng API đang cung cấp (preset SDK cộng giọng checkpoint).

Gửi `Authorization: Bearer <API key>` cho các request API. Với `/v1/tts`, body:

```json
{"text":"Xin chào!","voice":"Đạt Phi","format":"wav"}
```

Lấy ID thực tế qua `GET /v1/voices`. Với `/v1/audio/speech`, dùng `input`,
`response_format` và `stream:false`. Các profile local của notebook tắt
streaming và clone giọng. Các preset SDK vẫn dùng được như Web; giọng mặc định
lấy từ checkpoint. Các giọng người dùng đã lưu riêng trên máy chạy Web không tự
được đồng bộ lên Colab.

Cell **Lấy danh sách voices từ API** gọi `GET /v1/voices` qua tunnel bằng API
key hiện tại, in ID và tên từng giọng; biến `VOICE_IDS` lưu các ID để dùng lại.

Cell **Tạo audio mẫu** là tùy chọn để nghe thử ngay trong notebook. Nhập ID vào
`VOICE`, đặt `TEMPERATURE` từ `0` đến `2` (mặc định `0.8`). Bỏ trống `VOICE` sẽ
dùng giọng mặc định của checkpoint. Audio file API tự cân peak về tối đa `0.98`
trước encode theo chức năng cân biên độ Web; source server phải chứa thay đổi
này để áp dụng. Cell
**Dừng API và Cloudflare Tunnel** kết thúc hai process. Chạy lại cell khởi động
cũng dừng process cũ trước khi load checkpoint mới.

## Log và thời gian phiên chạy

Log nằm trong `/content/vieneu-colab-api/logs/server.log` và `tunnel.log`.
Lỗi startup/tunnel sẽ in phần cuối log và dừng các process đã tạo.

Notebook đặt timeout synthesis và giới hạn audio là 90 giây. Nên gửi từng
đoạn ngắn: proxy có thể timeout trước khi một request dài hoàn tất. Có thể đổi
hai biến `VIENEU_TTS_TIMEOUT`, `VIENEU_MAX_AUDIO_SECONDS` trong code cell;
điều này không thay đổi giới hạn của Cloudflare.

[Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
không cần tài khoản/domain, có hostname ngẫu nhiên, không bảo đảm uptime và
không hỗ trợ SSE. URL hết hiệu lực khi process tunnel dừng.

Đây là notebook cho phiên tương tác. Theo [Colab FAQ](https://research.google.com/colaboratory/faq.html),
runtime có giới hạn tài nguyên và có thể bị ngắt; gói miễn phí có hạn chế khi
tương tác chủ yếu qua giao diện bên ngoài notebook. Notebook không giữ phiên
bằng cơ chế chống idle. Cần server luôn hoạt động thì triển khai trên máy GPU
riêng thay vì phụ thuộc phiên Colab.
