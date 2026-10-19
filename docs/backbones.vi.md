# Backbone và cấu hình checkpoint

Danh sách này dựa trên `src/vieneu/factory.py`, các constructor SDK và
`config.yaml` trong repo. Nó phân biệt họ model, mode SDK và profile checkpoint
để tránh nhầm tên cấu hình của Web UI với giá trị API chấp nhận.

## Chọn checkpoint cho API Voice-Pro

`VIENEU_BACKBONE=v3turbo` chọn họ model mà API hỗ trợ. `VIENEU_MODEL_PROFILE`
chọn checkpoint cụ thể từ `backbone_configs` trong `config.yaml`; để trống sẽ
dùng repo `pnnbao-ump/VieNeu-TTS-v3-Turbo` mặc định.

| Profile local trong `config.yaml` | Thư mục `repo` | Giọng đi kèm |
|---|---|---|
| `VieNeu-TTS-v3-Turbo — Alan (GPU)` | `finetune/voices/alan/merged` | `Alan` |
| `VieNeu-TTS-v3-Turbo — Đạt Phi 01 (GPU)` | `finetune/voices/dat_phi_01/merged` | `Đạt Phi` |
| `VieNeu-TTS-v3-Turbo — Đạt Phi 02 (GPU)` | `finetune/voices/dat_phi_02/merged` | `Đạt Phi 02` |
| `VieNeu-TTS-v3-Turbo — Đạt Phi 03 (GPU)` | `finetune/voices/dat_phi_03/merged` | `Đạt Phi 03` |

Cả bốn profile có `mode: v3turbo`, `backend: pytorch`, `requires_cuda: true`,
`model_subfolder: update`, `supports_streaming: false`. Các thư mục trong workspace
đã có weights, config, tokenizer và file giọng. Cần giữ các tệp này khi chuyển
server sang máy khác; tên profile trong YAML không tự tải checkpoint local.

Ví dụ `.env` để chạy Đạt Phi 01:

```dotenv
VIENEU_VOICE_PRO_ENABLED=1
VIENEU_API_KEY=replace_with_your_key
VIENEU_BACKBONE=v3turbo
VIENEU_MODEL_PROFILE="VieNeu-TTS-v3-Turbo — Đạt Phi 01 (GPU)"
VIENEU_BACKEND=auto
VIENEU_DEVICE=auto
```

```sh
uv sync --extra cuda
uv run --env-file .env python -m apps.openai_speech
```

`auto` nhận backend/thiết bị yêu cầu bởi profile: với bốn model trên là PyTorch
và CUDA. Chỉ định `VIENEU_BACKEND=onnx`, `VIENEU_DEVICE=cpu`, thiếu CUDA hoặc
thiếu checkpoint sẽ làm startup báo lỗi; API không âm thầm quay về model gốc.

Sau startup, gọi `GET /v1/voices` để lấy ID giọng và gửi:

```json
{
  "text": "Xin chào, đây là giọng Đạt Phi.",
  "voice": "Đạt Phi",
  "format": "wav"
}
```

Đây là body của `POST /v1/tts`, có header Bearer như
[hướng dẫn Voice-Pro](voice-pro-api.vi.md). Với endpoint OpenAI, dùng `input`
thay `text` và thêm `stream: false`. Không bật streaming cho profile khai báo
`supports_streaming: false`. Danh sách giọng giống Web: giữ các preset có sẵn
của SDK và thêm giọng checkpoint; trùng tên thì giọng checkpoint được ưu tiên.
Giọng mặc định vẫn lấy từ checkpoint. Upload để
clone giọng chỉ được bật trên model gốc.

Kiểm tra checkpoint thực tế qua `GET /v1/models` hoặc `GET /v1/tts/capabilities`:
`model_profile`, `backbone_repo`, `model_subfolder` và `supports_streaming`.
Model ID local có hậu tố riêng theo checkpoint. Đổi profile cần restart server
hoặc tạo lại container; không gửi đường dẫn model trong request synthesis.

## Thêm profile local

Ví dụ cấu trúc, cùng định dạng với các entry hiện có:

```yaml
backbone_configs:
  "Giọng của tôi (GPU)":
    mode: v3turbo
    repo: finetune/voices/my_voice/merged
    local: true
    backend: pytorch
    requires_cuda: true
    model_subfolder: update
    supports_streaming: false
```

Thư mục checkpoint cần có:

```text
merged/
├── voices_v3_turbo.json      # presets, speaker_emb và default_voice hợp lệ
└── update/
    ├── model.safetensors
    ├── config.json
    ├── tokenizer.json
    └── tokenizer_config.json
```

Đặt `VIENEU_MODEL_PROFILE="Giọng của tôi (GPU)"`. Các đường dẫn `repo` trong
YAML luôn tính theo thư mục của YAML, kể cả khi chạy Python từ thư mục khác.
`VIENEU_CONFIG_PATH` mặc định là `config.yaml` ở thư mục dự án; có thể đặt thành
đường dẫn file khác. Registry local được tách theo đường dẫn checkpoint/subfolder
trong `VIENEU_HOME/checkpoints`, tránh trộn giọng khi chuyển model.

Docker GPU mount checkpoint bên ngoài image. Xem cấu hình bind mount trong
`docker/docker-compose.yml` và hướng dẫn [chạy API](voice-pro-api.vi.md).

## Model gốc: CPU hoặc GPU

| Cách chạy API | `VIENEU_BACKBONE` | `VIENEU_MODEL_PROFILE` | `VIENEU_BACKEND` | `VIENEU_DEVICE` | `VIENEU_PRECISION` |
|---|---|---|---|---|---|
| CPU fp32 | `v3turbo` | trống | `onnx` | `cpu` | `fp32` |
| CPU int8 | `v3turbo` | trống | `onnx` | `cpu` | `int8` |
| NVIDIA GPU | `v3turbo` | trống | `pytorch` | `cuda` | không áp dụng |
| Tự chọn | `v3turbo` | trống | `auto` | `auto` | `fp32` |

INT8 là độ chính xác của cùng backbone, không phải mode khác. Theo tài liệu
repo, chỉ nên dùng CPU int8 khi phần cứng hỗ trợ VNNI; fp32 là mặc định. Cài core
bằng `uv sync` cho ONNX/CPU hoặc `uv sync --extra cuda` cho GPU. FFmpeg cần được
cài riêng khi chạy local, hoặc dùng image Docker đã kèm theo.

## Các họ model và mode SDK còn có trong repo

Bảng dưới liệt kê SDK; API Voice-Pro hiện chỉ hỗ trợ họ v3 Turbo gốc và các
profile local v3 Turbo ở trên. Không đặt các mode SDK khác vào
`VIENEU_BACKBONE` rồi kỳ vọng API tự đổi codec, sample rate và registry.

| Họ model/checkpoint | Mode SDK | Runtime/thiết bị trong mã nguồn | Sample rate |
|---|---|---|---|
| `pnnbao-ump/VieNeu-TTS-v3-Turbo` | `v3turbo` | ONNX/CPU hoặc PyTorch/CUDA | 48 kHz |
| `pnnbao-ump/VieNeu-TTS-v3-Nano` | `v3nano` | ONNX/CPU | 24 kHz |
| `pnnbao-ump/VieNeu-TTS-v2` | `standard`, `fast` khi truyền repo tương ứng | Transformers/GGUF hoặc LMDeploy/CUDA | 24 kHz |
| `pnnbao-ump/VieNeu-TTS-v2-Turbo-GGUF` | `turbo` | llama.cpp và codec ONNX, mặc định CPU | 24 kHz |
| `pnnbao-ump/VieNeu-TTS-v2-Turbo` | `turbo_gpu` | Transformers hoặc LMDeploy, mặc định CUDA; codec ONNX | 24 kHz |
| `pnnbao-ump/VieNeu-TTS` (v1) | `standard`, `fast` khi truyền repo tương ứng | Transformers/GGUF hoặc LMDeploy | 24 kHz |

Các model v1/v2 được README đánh dấu legacy, giữ cho hệ thống cũ. V3 Nano là
preview. Các tên `standard`/`fast` là cách nạp/chạy model, không phải các họ
model độc lập. Repo của SDK mặc định có thể khác nhau theo mode:

| Mode | Mặc định / alias / lưu ý |
|---|---|
| `v3turbo` | Mặc định của `Vieneu()`, repo v3 Turbo |
| `v3nano` | Repo v3 Nano; không dùng làm backend của API Voice-Pro hiện tại |
| `standard` | Repo v2, mặc định có `gguf_filename`; đặt `gguf_filename=None` khi muốn nạp Transformers |
| `fast` | Alias `gpu`; mặc định repo v1, cần LMDeploy và CUDA |
| `turbo` | Bản v2 Turbo GGUF; khác `v3turbo` và `turbo_gpu` |
| `turbo_gpu` | Bản v2 Turbo qua PyTorch/LMDeploy |
| `remote` | Alias `api`; client gọi server legacy `/chat/completions`, không khởi chạy server và không gọi `/v1/tts` mới |
| `xpu` | Nhánh Intel GPU có trong factory; cần môi trường PyTorch XPU và codec phù hợp, chưa được xác minh trong hướng dẫn này |

Với SDK, checkpoint local có thể được nạp trực tiếp:

```python
from vieneu import Vieneu

tts = Vieneu(
    mode="v3turbo",
    backbone_repo="finetune/voices/alan/merged",
    model_subfolder="update",
    backend="pytorch",
    device="cuda",
)
audio = tts.infer("Xin chào, đây là giọng Alan.", voice="Alan")
tts.save(audio, "alan.wav")
tts.close()
```

Các mode legacy cần dependency bổ sung: nhóm `legacy` cung cấp các thư viện
PyTorch/Transformers/NeuCodec; `llama-cpp-python` và `lmdeploy` phải được cài riêng
theo môi trường tương ứng. Xem [custom model](CUSTOM_MODEL_USAGE.md),
[triển khai legacy](Deploy.vi.md) và README. Danh sách SDK này mô tả mã nguồn
hiện có, không khẳng định mọi tổ hợp phần cứng/dependency đã được kiểm thử.
