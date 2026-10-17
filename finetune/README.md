# 🦜 Fine-tune VieNeu-TTS v3 Turbo bằng LoRA — một giọng

Thư mục này dạy **VieNeu-TTS v3 Turbo** đọc bằng **một giọng** của bạn với **LoRA**: chỉ vài triệu tham số được học, model gốc giữ nguyên, train được trên một GPU phổ thông (~6 GB VRAM với cấu hình mặc định).

Toàn bộ quy trình dựa trên chính SDK `vieneu`: dữ liệu được chuẩn hoá, phiên âm và mã hoá **giống hệt lúc suy luận**, nên model sau khi merge dùng được ngay với `Vieneu(mode="v3turbo")`.

**Cách nó hoạt động, ngắn gọn:** mỗi clip được mã hoá thành codec codes (nhãn) và một speaker embedding 192 chiều; model học sinh ra codes từ phiên âm + embedding đó, **không dùng clip tham chiếu trong ngữ cảnh**. Giọng sau fine-tune = LoRA + embedding của giọng đó, nên khi dùng chỉ cần đóng gói một embedding (bước 4), không cần audio mẫu.

> **Bao nhiêu dữ liệu?** v3 Turbo đã clone giọng tức thì từ một clip **vài giây**, nên chỉ fine-tune khi cần bám giọng chặt hơn clone, một phong cách đọc đặc thù (đọc truyện, tin tức, thuyết minh…), hoặc sửa cách đọc trên một miền văn bản riêng. Với một giọng, **10–30 phút** audio sạch (100–300 câu khác nhau) là đủ; câu đa dạng quan trọng hơn tổng thời lượng. Data ít thì rủi ro là overfit chứ không phải thiếu: giữ eval bật và dừng khi eval loss ngừng giảm.
>
> Muốn nhiều giọng? Train mỗi giọng một LoRA riêng — đơn giản và ổn định hơn nhồi nhiều giọng vào một adapter.

## Chạy trên Google Colab hoặc Kaggle

Dùng notebook [VieNeu_TTS_Finetune_Colab_Kaggle.ipynb](VieNeu_TTS_Finetune_Colab_Kaggle.ipynb). Tải file rồi mở bằng **Upload notebook** trên Colab hoặc **Import notebook** trên Kaggle, bật GPU và chạy các ô theo thứ tự. Trên Kaggle cần bật Internet và thêm dataset vào Input.

Notebook có hướng dẫn nén `metadata.csv` + `raw_audio/` thành ZIP từ Windows, upload trực tiếp hoặc đọc từ Drive/Kaggle, cài môi trường, chuẩn bị parquet, train LoRA, chọn checkpoint để merge, đóng gói giọng, nghe thử và tải kết quả. Trên Kaggle, notebook tự tìm dataset theo cấu trúc trong Input, không cần nhập đường dẫn; đường dẫn cũ không tồn tại sẽ được bỏ qua để tìm lại. Nếu có nhiều dataset phù hợp, chọn bằng số thứ tự `DATASET_CHOICE`. Cấu hình mặc định dành cho dataset một giọng khoảng 329 clip; tự chọn BF16 khi GPU hỗ trợ, dùng FP32 khi không hỗ trợ.

Để giữ kết quả trên Colab, bật `SAVE_TO_DRIVE=True` trong notebook. Trên Kaggle, lưu notebook kèm outputs hoặc tải ZIP từ `/kaggle/working/vieneu_exports`. Script hiện chưa hỗ trợ resume optimizer; checkpoint đã lưu có thể dùng để merge model.

## ⚙️ Cài đặt

```bash
git clone https://github.com/pnnbao97/VieNeu-TTS.git
cd VieNeu-TTS
uv sync --extra finetune        # torch, transformers, peft, accelerate (cần GPU CUDA để train)
```

## 1. Chuẩn bị dữ liệu

```
finetune/dataset/
  metadata.csv        mỗi dòng: file_name|text
  raw_audio/          các file audio được nhắc trong metadata.csv
```

- **Tất cả clip phải là cùng một người nói.** Đây là ràng buộc duy nhất của pipeline — một LoRA là một giọng.
- Mỗi clip **1–20 giây**, nội dung đúng với `text` (kể cả dấu câu). Clip dài hơn hãy cắt nhỏ trước.
- Audio sạch, ít vang, không nhạc nền. Tần số lấy mẫu bất kỳ, mono hay stereo đều được.

```bash
uv run python finetune/prepare_dataset.py --dataset-dir finetune/dataset
```

Script chạy trên CPU, không cần torch: phiên âm bằng sea-g2p, mã hoá audio bằng codec MOSS (ONNX) và trích speaker embedding 192 chiều của từng clip. Kết quả là `finetune/dataset/train.parquet` (cột `phones, codes, speaker_embedding, duration, text, file_name`).

## 2. Train LoRA

```bash
uv run python finetune/train_lora.py --data finetune/dataset/train.parquet --run my_voice --merge
```

Mặc định: LoRA rank 16 trên toàn bộ attention và MLP của backbone, learning rate 2e-4, 3 epoch, batch hiệu dụng 16, bf16. Vài tuỳ chọn hay dùng:

| Tuỳ chọn | Ý nghĩa |
|---|---|
| `--epochs 3` / `--max-steps N` | thời lượng train |
| `--r 16 --alpha 32` | dung lượng LoRA; giọng khó hoặc data nhiều thì tăng `--r 32` |
| `--target all` | thêm LoRA cho acoustic decoder (chất giọng bám sát hơn, cần data nhiều hơn) |
| `--grad-checkpoint` | tiết kiệm VRAM khi tăng `--batch-size` hoặc `--max-length` |
| `--merge` | ghi thêm model đầy đủ đã merge ở cuối |

Theo dõi log: `audio` là cross-entropy trung bình của 16 codebook, `acc_cb0` là độ chính xác top-1 của codebook đầu. Trên pipeline đúng, `acc_cb0` phải ở mức 0.2–0.4 ngay từ bước đầu và tăng dần; nếu gần 0 thì dữ liệu có vấn đề (phiên âm hoặc codes không khớp audio).

Kết quả nằm trong `finetune/output/my_voice/`:

```
adapter/        LoRA adapter (vài MB) — dùng với merge_lora.py
checkpoint-*/   adapter trung gian
merged/         model đầy đủ, đúng bố cục repo chính thức (khi có --merge)
```

## 3. Merge model

```bash
uv run python finetune/merge_lora.py --adapter finetune/output/my_voice/adapter --out finetune/output/my_voice/merged
# đẩy lên Hugging Face: thêm --push-to-hub your-name/VieNeu-TTS-v3-Turbo-my-voice [--private]
```

Model merge chạy trên **GPU (PyTorch)**. Đường CPU/ONNX của SDK dùng đồ thị đã export sẵn của model gốc, nên chưa nhận model fine-tune.

## 4. Đóng gói giọng và dùng

Lấy một clip 3–8 giây của **đúng người nói đó** (một clip trong dataset cũng được) để tạo speaker embedding và ghi thành giọng dựng sẵn đi kèm model:

```bash
uv run python finetune/make_voice.py --audio ref.wav --name "Giọng của tôi" \
    --description "Nữ · Bắc · Phong cách tự nhiên" --gender female \
    --out finetune/output/my_voice/merged
```

Lệnh này ghi `voices_v3_turbo.json` vào thư mục model — chỉ speaker embedding, **không có mã tham chiếu**, đúng như lúc train. SDK tự nạp file đó từ thư mục local hoặc repo Hub, cộng thêm vào các giọng có sẵn, và giọng bạn đặt thành mặc định:

```python
from vieneu import Vieneu
tts = Vieneu(mode="v3turbo", backbone_repo="finetune/output/my_voice/merged")   # hoặc "your-name/…"
audio = tts.infer("Xin chào, đây là giọng đã fine-tune.", voice="Giọng của tôi")
tts.save(audio, "out.wav")
```

Lưu ý: model merge được dạy cho **một giọng**; muốn nó clone giọng khác thì dùng model gốc. (`make_voice.py --with-ref-codes` chỉ dành cho đóng gói giọng cho model gốc.)

## 5. Dùng model fine-tune trong VieNeu-TTS web

Giải nén file `*_merged.zip` vào thư mục giọng, ví dụ `finetune/voices/dat_phi_01/`. Thư mục kết quả phải có `merged/update/model.safetensors` và `merged/voices_v3_turbo.json`.

Khai báo model trong `backbone_configs` của `config.yaml` (tên lựa chọn nên chứa `v3-Turbo` để giao diện bật các chức năng v3):

```yaml
"VieNeu-TTS-v3-Turbo — Đạt Phi 01 (GPU)":
  mode: v3turbo
  repo: finetune/voices/dat_phi_01/merged
  local: true
  backend: pytorch
  requires_cuda: true
  model_subfolder: update
  supports_streaming: false
  description: "Giọng đã fine-tune, dùng GPU NVIDIA/CUDA."
```

Đường dẫn local được tính từ thư mục chứa `config.yaml`. Cấu hình Đạt Phi 01 đã được thêm sẵn trong repo này.

Nếu chưa có môi trường GPU, cài bằng `uv sync --extra cuda`. Khởi động hoặc khởi động lại web bằng:

```bash
uv run --extra cuda vieneu-web
```

Mở `http://127.0.0.1:7860`, chọn **VieNeu-TTS-v3-Turbo — Đạt Phi 01 (GPU)** trong danh sách model, chọn Device **Auto** hoặc **CUDA**, rồi bấm tải model. Trong giọng có sẵn, chọn **Đạt Phi**, nhập văn bản và tạo audio. Bản local Đạt Phi đã đổi tên preset từ `Giong cua toi` thành `Đạt Phi` và giữ tên cũ làm alias; model này được chọn sẵn trong giao diện bằng `default: true` ở config. Giọng chỉ xuất hiện sau khi tải model tương ứng. SDK tự đọc embedding từ `voices_v3_turbo.json`, không cần upload audio mẫu. Model này hiện cần GPU NVIDIA; chưa có bản ONNX fine-tune cho CPU. Lần đầu cần Internet để tải codec MOSS nếu chưa có trong cache.

### Windows: lưu cache và file tạm ngay trong repo

Dừng phiên web cũ, sau đó chạy `run_web_local.bat` ở thư mục gốc repo (có thể nhấp đúp). Hoặc chạy PowerShell:

```powershell
.\run_web_local.bat
```

Launcher đặt cache Hugging Face/model/codec, cache uv/pip, Python do uv quản lý, cache Torch/CUDA, giọng người dùng và file audio tạm vào `.runtime/` trong repo; môi trường thư viện ở `.venv/`. Biến môi trường được đặt trước cả bước `uv run`, không thay đổi cấu hình toàn hệ thống. Các lần sau dùng launcher này thay cho lệnh `uv run` trực tiếp. Kiểm tra đường dẫn mà không cài thư viện hay khởi động web bằng `run_web_local.bat -Check`.

Cache và giọng đã lưu từ trước ở hồ sơ người dùng ổ C không tự chuyển sang đây; lần đầu dùng cache mới có thể tải lại model/codec và chưa thấy giọng đã lưu bằng tab Voice Cloning. Giọng fine-tune đóng gói trong `merged/` vẫn được nạp bình thường. File do Windows, driver, trình duyệt hoặc Python đã cài sẵn quản lý có thể vẫn nằm ngoài repo; launcher điều hướng các đường dẫn lưu trữ của ứng dụng và thư viện được liệt kê, không di chuyển các thành phần hệ thống.

### Tương thích tokenizer giữa cloud và máy local

Transformers 5 có thể lưu generic fast tokenizer dưới tên `TokenizersBackend`, trong khi Transformers 4 không nhận tên này. Exporter và bước tạo ZIP trong notebook chuẩn hóa tên đó thành `PreTrainedTokenizerFast`, giữ nguyên `tokenizer.json` và token IDs. Bản model Đạt Phi local đã được sửa tương ứng. SDK cũng truyền rõ `rope_theta` cho Qwen3 để giữ đúng cấu hình khi chạy bằng Transformers 4. Sau khi cập nhật code SDK, cần khởi động lại web.

## Cấu trúc code

```
finetune/
  prepare_dataset.py   audio + text (một người nói)  →  train.parquet
  train_lora.py        train LoRA (peft)
  merge_lora.py        adapter + base  →  model đầy đủ, tuỳ chọn push Hub
  make_voice.py        clip  →  voices_v3_turbo.json (speaker embedding, không mã tham chiếu)
  vieneu_lora/
    data.py            dựng chuỗi token 2 chiều và nhãn từ một hàng dữ liệu (không ref)
    model.py           forward teacher-forcing + loss trên model của SDK
    lora.py            gắn, lưu, nạp, merge, export LoRA
```
