---
status: accepted
---

# Add a complete-audio interface for Voice-Pro alongside OpenAI streaming

Voice-Pro needs a complete, decodable audio file and explicit rate, volume, and pitch controls, whereas the existing OpenAI route begins its response before synthesis completes. Add `/v1/tts` as a second HTTP adapter over the same v3 Turbo engine and voice registry, completing synthesis, post-processing, encoding, and validation before returning MP3/WAV/FLAC; this extends ADR 0001 while preserving the existing streaming contract and server-level resource configuration. Pitch uses cents with an explicit Voice-Pro UI adaptation because the existing Hz label has no fixed conversion without a reference frequency, and the Voice-Pro deployment profile requires Bearer authentication and the declared codec/filter dependencies.
