# Chạy API cho Voice-Pro

API dùng v3 Turbo và cùng engine với API OpenAI streaming. Hợp đồng chi tiết ở
[OpenAPI](openapi.voice-pro.yaml) và [thiết kế](tts-api-design.vi.md).

## Khởi chạy

Cài FFmpeg có encoder `libmp3lame`, `pcm_s16le`, `flac` và filter `rubberband`,
`volume`. Server kiểm tra chúng khi khởi động.

Sao chép `.env.voice-pro.example` thành `.env`, thay `VIENEU_API_KEY`, rồi chạy:

```sh
uv run --env-file .env python -m apps.openai_speech
```

Cấu hình model trong `.env`:

```dotenv
VIENEU_BACKBONE=v3turbo
VIENEU_BACKEND=auto
VIENEU_DEVICE=auto
```

`VIENEU_BACKBONE` chọn model giọng nói. API V1 hiện chỉ hỗ trợ `v3turbo`;
giá trị khác bị từ chối khi startup. `VIENEU_BACKEND` chọn runtime suy luận
(`auto`, `onnx`, `pytorch`), còn `VIENEU_DEVICE` chọn thiết bị (`auto`, `cpu`, `cuda`).
Model không đổi theo request. Sau khi sửa `.env`, khởi động lại server hoặc
tạo lại container để áp dụng; `GET /v1/models` và `GET /v1/tts/capabilities`
công bố trường `backbone` đang chạy.

Để chọn checkpoint local từ `config.yaml`, thêm tên profile vào `.env`:

```dotenv
VIENEU_MODEL_PROFILE="VieNeu-TTS-v3-Turbo — Đạt Phi 01 (GPU)"
VIENEU_BACKEND=auto
VIENEU_DEVICE=auto
```

API đọc `repo`, `model_subfolder`, `requires_cuda` và `supports_streaming` từ
profile. Đường dẫn `repo` tương đối tính theo thư mục chứa `config.yaml`.
`VIENEU_CONFIG_PATH` cho phép dùng file YAML khác. `default: true` trong YAML
thuộc Web UI; API chọn profile bằng biến môi trường này. Để trống profile sẽ
dùng model gốc. Xem [danh sách backbone và checkpoint](backbones.vi.md).

Bốn profile fine-tune hiện có yêu cầu CUDA và không streaming: gọi `/v1/tts`
hoặc `/v1/audio/speech` với `stream=false`. Mỗi profile chỉ công bố giọng đóng
gói cùng checkpoint và không nhận upload để clone giọng. Inference hoàn chỉnh
được xử lý tuần tự để bảo vệ trạng thái model dùng chung; capability công bố
`max_streams=1` dù cấu hình streaming chung có giá trị cao hơn. Dữ liệu registry
nằm dưới `VIENEU_HOME/checkpoints/<checkpoint-id>`, tách khỏi model gốc và các
checkpoint khác. `GET /v1/models` và capability trả `model_profile`,
`backbone_repo`, `model_subfolder`, `supports_streaming`, `voice_cloning_supported`.

Mặc định server nghe `127.0.0.1:8000`. Đặt `HOST=0.0.0.0` khi Voice-Pro chạy trên
máy khác. Dùng HTTPS qua reverse proxy nếu kết nối qua mạng không tin cậy.

Hoặc dùng Docker đã kèm FFmpeg:

```sh
docker compose -f docker/docker-compose.yml --profile api-cpu up --build
# NVIDIA GPU: thay api-cpu bằng api-gpu.
```

Với checkpoint local CUDA, dùng profile `api-gpu`. Compose mount `config.yaml`
và `finetune/voices` của máy host vào container ở chế độ chỉ đọc. Có thể đặt
`VIENEU_CHECKPOINTS_DIR` thành đường dẫn host khác chứa các thư mục `alan`,
`dat_phi_01`, `dat_phi_02`, `dat_phi_03`; đường dẫn tương đối của bind mount
được tính theo thư mục `docker`. Nếu chọn YAML riêng, cần mount YAML đó và model
đúng đường dẫn tương ứng trong container. Không đóng gói weights vào image.

Compose đọc `.env` và lưu giọng vào volume `api_data`. Chạy một process API cho
mỗi `VIENEU_HOME`; server khóa thư mục này để hai process không xóa file của nhau.
Các instance chạy song song cần thư mục/volume riêng. Bản local mặc định lưu vào
`~/.vieneu`; dùng `VIENEU_HOME` để đổi.

## Kết nối từ Voice-Pro

```dotenv
CUSTOM_TTS_BASE_URL=http://vieneu-host:8000
CUSTOM_TTS_API_KEY=<same key as VIENEU_API_KEY>
```

Base URL không chứa `/v1`. Gọi các endpoint với `Authorization: Bearer <key>`:

- `GET /v1/tts/capabilities`: giới hạn hiệu lực, đơn vị controls và timeout.
- `GET /v1/voices`: lấy ID giọng từ trường `data`, không dùng ID giọng Microsoft.
- `POST /v1/tts`: tạo file MP3 mặc định hoặc WAV/FLAC hoàn chỉnh.

Ví dụ JSON gửi tới `/v1/tts`:

```json
{
  "text": "Xin chào, đây là câu cần đọc.",
  "voice": "Trúc Ly",
  "format": "mp3",
  "rate": 0,
  "volume": 0,
  "pitch": 0,
  "temperature": 0.8
}
```

Dùng đúng ID thực tế từ danh sách giọng của instance. Ghi bytes thành file chỉ
khi status là `200`; kiểm tra Content-Type, đủ Content-Length và giải mã được
trước khi đưa file vào luồng ghép/lồng tiếng. Lỗi là JSON với `error.code` và
`error.request_id`, không phải audio.

`rate` là phần trăm thay đổi tempo (`-90..200`); `volume` là phần trăm thay đổi
biên độ (`-100..100`, `-100` tắt tiếng); `pitch` dùng **cent**, phạm vi `-400..400`.
`temperature` là tham số tùy chọn từ `0` đến `2`, mặc định `0.8`, được chuyển
trực tiếp tới model khi tổng hợp.

Audio file từ `/v1/tts` và `/v1/audio/speech` với `stream:false` tự cân biên độ
theo cùng quy tắc của Web: sau hiệu ứng và resample, nếu peak vượt `0.98` thì
giảm đều toàn bản ghi về mức đó trước encode. Audio nhỏ giữ nguyên, không cân
riêng từng chunk. MP3 có thể có peak khác sau decode do nén mất dữ liệu.
Streaming trực tiếp giữ pipeline hiện có, không đo peak toàn bản ghi.

Adapter Voice-Pro cần đổi nhãn pitch từ Hz sang cent và reset về 0 khi đổi
provider. Nếu chưa sửa UI, khóa pitch ở 0. Không áp lại các hiệu ứng này tại client.

Đăng ký giọng qua `POST /v1/voices` multipart với `name`, `file` và tùy chọn
`denoise`, `description`, `locale`, `gender`. ID `usr_...` trả về giữ nguyên qua
restart; tên vẫn được nhận làm alias. Các client dùng chung danh sách giọng.

`POST /v1/audio/speech` vẫn streaming mặc định. Khi profile Voice-Pro được bật,
thêm `stream: false` để nhận WAV/PCM hoàn chỉnh; `stream_format` phải là `audio`.
Endpoint này tiếp tục giữ schema và cách xử lý `speed`/`instructions` cũ.

## Giới hạn và retry

Mặc định: 20.000 Unicode code point, JSON 256 KiB, deadline xử lý 300 giây,
audio thô/kết quả tối đa 600 giây và file tối đa 64 MiB. Queue chờ tối đa 10 giây.
Đọc capability để lấy giá trị thực tế. Voice-Pro vẫn nên gửi từng câu và tự căn
thời gian phụ đề. Server nhận plain text, không parse SSML.

Không có quota request/phút. Số luồng và queue hữu hạn; khi đầy trả `429` cùng
`Retry-After`. Timeout trả `504`; tác vụ native đang dừng vẫn giữ permit tài nguyên.
Retry tối đa hai lần với backoff khi lỗi mạng, `429` hoặc `5xx`; retry có thể sinh
audio khác vì sampling và không có bảo đảm exactly-once.

Client đặt connect timeout 5 giây, read timeout 330 giây và ngân sách tải file
60 giây sau khi nhận header. Proxy cần upstream read timeout ít nhất 330 giây.
`GET /health` dùng cho readiness; API key thiếu hoặc FFmpeg thiếu khả năng bắt buộc
sẽ làm profile Voice-Pro không khởi động.
