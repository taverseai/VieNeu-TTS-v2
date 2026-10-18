# Yêu cầu API TTS để tích hợp với Voice-Pro

Tài liệu này mô tả hợp đồng API tổng hợp giọng nói mà một dịch vụ TTS cần cung cấp để có thể kết nối với Voice-Pro. Đây là đặc tả tích hợp đề xuất dựa trên luồng TTS hiện có của dự án; tên endpoint và trường JSON có thể khác nếu có lớp chuyển đổi tương ứng trong Voice-Pro.

## 1. Cách Voice-Pro sử dụng TTS

Voice-Pro gửi văn bản cần đọc cùng giọng và các thông số giọng nói tới bộ TTS. Với văn bản dài, ứng dụng tự chia văn bản thành câu và tổng hợp từng câu riêng, sau đó ghép các đoạn âm thanh. Với phụ đề, ứng dụng phân tích từng dòng và tự căn thời gian/đệm im lặng trước khi ghép. Vì vậy API không cần xử lý trực tiếp tệp phụ đề hoặc timestamp.

Âm thanh TTS được lưu thành tệp cục bộ và có thể được dùng tiếp trong các chức năng lồng tiếng, xử lý hàng loạt, trộn âm thanh hoặc RVC. Kết quả cần là audio hoàn chỉnh, có thể giải mã được bằng FFmpeg/Pydub.

## 2. Chức năng bắt buộc

API cần:

- Nhận văn bản UTF-8 và một mã giọng đọc.
- Tổng hợp mỗi yêu cầu độc lập, kể cả khi ứng dụng gọi API nhiều lần liên tiếp cho các câu trong cùng một văn bản.
- Trả dữ liệu âm thanh hoặc cung cấp URL tải âm thanh có thể truy cập từ máy chạy Voice-Pro.
- Trả lỗi có cấu trúc khi yêu cầu sai, giọng không tồn tại, xác thực thất bại, vượt giới hạn hoặc tổng hợp không thành công.
- Hỗ trợ xác thực bằng API key hoặc cơ chế tương đương.
- Công bố giới hạn ký tự, giới hạn tốc độ gọi, thời gian lưu URL kết quả (nếu dùng URL), và các định dạng âm thanh hỗ trợ.

## 3. Giọng đọc

Mỗi giọng cần có mã định danh ổn định để Voice-Pro gửi trong yêu cầu. Nên cung cấp endpoint liệt kê giọng, hoặc tài liệu/JSON tĩnh để cấu hình danh sách giọng trong dự án.

Thông tin tối thiểu cho mỗi giọng:

| Trường | Ý nghĩa | Ví dụ |
|---|---|---|
| `id` | Mã gửi trong yêu cầu tổng hợp | `vi-VN-HoaiMyNeural` |
| `name` | Tên hiển thị | `Hoài My` |
| `locale` | Ngôn ngữ/địa phương theo BCP-47 | `vi-VN` |
| `gender` | Giới tính, nếu có | `Female` |

Voice-Pro hiện có danh sách giọng dựng sẵn và hiển thị ngôn ngữ/giọng theo dữ liệu nội bộ. Nếu ID từ API khác danh sách hiện có, phần tích hợp cần thêm ánh xạ giữa lựa chọn trên giao diện và `id` API, hoặc thay nguồn danh sách giọng để đọc từ API.

## 4. Endpoint tổng hợp đề xuất

Ví dụ hợp đồng đơn giản, trả audio trực tiếp:

```http
POST /v1/tts
Authorization: Bearer <API_KEY>
Content-Type: application/json
Accept: audio/mpeg
```

```json
{
  "text": "Xin chào, đây là câu cần đọc.",
  "voice": "vi-VN-HoaiMyNeural",
  "rate": 0,
  "volume": 0,
  "pitch": 0,
  "format": "mp3"
}
```

Ý nghĩa các trường:

| Trường | Bắt buộc | Kiểu | Ý nghĩa |
|---|---:|---|---|
| `text` | Có | string | Đoạn văn bản cần tổng hợp; phải chấp nhận Unicode/tiếng Việt. |
| `voice` | Có | string | ID giọng đọc. |
| `rate` | Nên có | number | Tốc độ đọc. Voice-Pro hiện dùng giá trị phần trăm, mặc định `0`. |
| `volume` | Nên có | number | Âm lượng tương đối theo phần trăm, mặc định `0`. |
| `pitch` | Nên có | number | Cao độ; giao diện hiện ghi đơn vị Hz, mặc định `0`. |
| `format` | Nên có | string | Định dạng đầu ra, tối thiểu `mp3`; giao diện Voice-Pro còn có `wav` và `flac`. |

API cần định nghĩa rõ quy ước dấu và phạm vi cho `rate`, `volume`, `pitch`. Các giới hạn giao diện hiện tại là tốc độ `-100` đến `+200`, âm lượng `-100` đến `+100`, cao độ `-400` đến `+400`. Dịch vụ có thể hỗ trợ phạm vi hẹp hơn nếu bộ tích hợp giới hạn hoặc ánh xạ giá trị trước khi gửi.

Khi thành công, trả:

```http
HTTP/1.1 200 OK
Content-Type: audio/mpeg
Content-Disposition: attachment; filename="speech.mp3"
```

Body là bytes của tệp âm thanh. Đây là dạng phản hồi thuận tiện nhất cho lớp tích hợp vì có thể ghi trực tiếp vào tệp đầu ra mà Voice-Pro yêu cầu.

### Phương án trả URL

Nếu dịch vụ xử lý bất đồng bộ, có thể trả JSON chứa URL kết quả:

```json
{
  "audio_url": "https://tts.example.com/results/abc123.mp3",
  "format": "mp3",
  "expires_at": "2026-10-18T12:00:00Z"
}
```

URL cần tải được từ máy Voice-Pro, không yêu cầu cookie của trình duyệt, và còn hiệu lực đủ lâu để ứng dụng tải tệp. Nếu API trả `202 Accepted`, cần có endpoint trạng thái tác vụ và quy tắc polling rõ ràng. Phương án này cần nhiều xử lý tích hợp hơn trả audio trực tiếp.

## 5. Định dạng và đặc tính âm thanh

- Định dạng tối thiểu nên hỗ trợ: MP3.
- Định dạng giao diện hiện cung cấp: MP3, WAV, FLAC. Có thể để API chỉ xuất MP3 và chuyển đổi trong Voice-Pro.
- Nên trả âm thanh mono hoặc stereo tiêu chuẩn, sample rate phổ biến như 24 kHz hoặc 48 kHz, và khai báo chính xác qua metadata/container.
- Audio phải có kích thước lớn hơn 0, hoàn tất trước khi trả thành công và không chứa JSON/lỗi trong body audio.
- Nếu xuất MP3, cấu hình tương thích hiện tại là mono 48 kHz, 192 kbit/s (đây là cấu hình Azure đang dùng; không bắt buộc nếu bộ tích hợp chuyển đổi được).

## 6. Endpoint liệt kê giọng đề xuất

```http
GET /v1/voices
Authorization: Bearer <API_KEY>
Accept: application/json
```

Ví dụ phản hồi:

```json
{
  "voices": [
    {
      "id": "vi-VN-HoaiMyNeural",
      "name": "Hoài My",
      "locale": "vi-VN",
      "gender": "Female",
      "formats": ["mp3", "wav"]
    }
  ]
}
```

Endpoint này không bắt buộc nếu danh sách giọng được cấu hình tĩnh trong Voice-Pro. ID trả về phải giống giá trị API chấp nhận trong trường `voice`.

## 7. Xác thực và cấu hình kết nối

Thông tin kết nối nên được đặt trong biến môi trường hoặc `.env`, không ghi cứng vào mã nguồn. Tối thiểu cần:

```dotenv
CUSTOM_TTS_BASE_URL=https://tts.example.com
CUSTOM_TTS_API_KEY=replace_with_your_key
```

Nếu dịch vụ cần vùng, project ID hoặc header riêng, thêm các biến cấu hình tương ứng. Cấu hình cần cho biết rõ header xác thực, ví dụ `Authorization: Bearer ...` hoặc `X-API-Key: ...`.

## 8. Lỗi và mã trạng thái

Nên trả JSON lỗi nhất quán, kể cả khi endpoint thành công thường trả audio:

```json
{
  "error": {
    "code": "voice_not_found",
    "message": "Voice vi-VN-Unknown không tồn tại."
  }
}
```

Mã HTTP đề xuất:

| Mã | Trường hợp |
|---:|---|
| `400` | Thiếu/sai trường hoặc thông số ngoài phạm vi. |
| `401` / `403` | API key sai hoặc không đủ quyền. |
| `404` | Endpoint hoặc giọng không tồn tại. |
| `413` | Văn bản vượt giới hạn kích thước. |
| `429` | Vượt giới hạn tốc độ gọi. |
| `5xx` | Lỗi phía dịch vụ TTS. |

Lỗi nên có `code` ổn định để ứng dụng phân biệt nguyên nhân, và `message` ngắn gọn để ghi log/hiển thị. Không trả mã `200` nếu synthesis thất bại.

## 9. Hành vi vận hành nên có

- Timeout tổng hợp và timeout tải kết quả được công bố rõ.
- API hỗ trợ nhiều request độc lập, vì Voice-Pro có thể tạo một request cho mỗi câu.
- Có thể retry an toàn khi lỗi mạng hoặc `429`/`5xx`; nên công bố `Retry-After` khi giới hạn tốc độ.
- Không cắt cụt văn bản âm thầm. Khi vượt giới hạn, trả lỗi có cấu trúc.
- Có tùy chọn hoặc quy tắc rõ về xử lý markup/SSML. Voice-Pro hiện gửi văn bản thường cho luồng Edge, còn luồng Azure xây SSML nội bộ; bộ tích hợp API riêng nên escape văn bản an toàn nếu chuyển nó thành SSML.

## 10. Checklist để xác nhận API sẵn sàng

- [ ] Có base URL, endpoint synthesis và phương thức xác thực.
- [ ] Có thể gửi Unicode tiếng Việt và chọn giọng bằng ID ổn định.
- [ ] Biết danh sách giọng và cách ánh xạ lên giao diện Voice-Pro.
- [ ] Biết đơn vị, phạm vi và cách xử lý `rate`, `volume`, `pitch`.
- [ ] Trả MP3/WAV/FLAC trực tiếp hoặc URL tải file có hạn dùng phù hợp.
- [ ] Công bố giới hạn ký tự, timeout, rate limit và hành vi retry.
- [ ] Trả lỗi có mã và thông báo rõ ràng.
- [ ] Có URL/API key có thể cấu hình bên ngoài mã nguồn.

## 11. Thông tin cần lấy từ nhà cung cấp API

Trước khi viết lớp kết nối, cần có tài liệu hoặc ví dụ thực tế cho các mục sau:

1. Base URL và endpoint tổng hợp.
2. Cách xác thực, ví dụ header hoặc query parameter.
3. Một request thành công và response tương ứng.
4. Endpoint/dữ liệu danh sách giọng, gồm ID, tên và locale.
5. Định dạng phản hồi: bytes audio hay URL; loại MIME và codec.
6. Hỗ trợ và đơn vị cho tốc độ, âm lượng, cao độ.
7. Giới hạn ký tự, timeout, rate limit, thời hạn URL kết quả và mã lỗi.

## 12. Tham chiếu trong mã nguồn Voice-Pro

- `app/abus_tts_azure.py`: ví dụ bộ TTS Azure hiện tại, gồm tổng hợp, định dạng âm thanh, xử lý từng câu và ghép audio.
- `app/abus_tts_edge.py`: luồng Edge TTS cùng giao diện tham số tương tự.
- `app/gradio_tts_edge.py`: điểm gọi `infer(...)` từ giao diện.
- `app/abus_voice_ms.py`: danh sách giọng dựng sẵn và ánh xạ tên hiển thị sang mã giọng.
- `app/abus_config.py`: cách đọc cấu hình Azure từ biến môi trường.
