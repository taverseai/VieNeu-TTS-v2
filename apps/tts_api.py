"""Voice-Pro HTTP adapter, mounted alongside the OpenAI speech routes."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
import weakref
import logging
import math

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError

from apps.speech_service import RenderedAudio, SpeechService
from apps.tts_contract import RenderContext, SynthesisRequest, TtsError


def is_voice_pro_request(request: Request) -> bool:
    return bool(getattr(request.state, "tts_request_id", None))


def error_response(request: Request, exc: TtsError) -> JSONResponse:
    rid = getattr(request.state, "tts_request_id", None) or "tts_" + uuid.uuid4().hex
    kind = ("authentication_error" if exc.status == 401 else "rate_limit_error" if exc.status == 429
            else "server_error" if exc.status >= 500 else "invalid_request_error")
    headers = {"X-Request-Id": rid}
    if exc.status in (429, 503):
        headers["Retry-After"] = "2" if exc.status == 429 else "5"
    return JSONResponse({"error": {"code": exc.code, "type": kind, "message": str(exc),
                                   "param": exc.param, "request_id": rid}},
                        status_code=exc.status, headers=headers)


class VoiceProMiddleware:
    """Bound the body before JSON parsing and correlate errors as well as audio."""
    def __init__(self, app, get_engine):
        self.app, self.get_engine = app, get_engine

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        enabled = os.environ.get("VIENEU_VOICE_PRO_ENABLED", "0") == "1"
        if scope["type"] != "http" or not enabled or not (path.startswith("/v1/tts") or path == "/v1/voices"):
            return await self.app(scope, receive, send)
        scope.setdefault("state", {})["tts_request_id"] = "tts_" + uuid.uuid4().hex
        response_started = False

        async def correlated(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                message["headers"] = [*headers, (b"x-request-id", scope["state"]["tts_request_id"].encode())]
            await send(message)

        async def invoke(inner_receive):
            try:
                await self.app(scope, inner_receive, correlated)
            except Exception:
                if response_started:
                    raise
                logging.getLogger("vieneu.api").exception("Unexpected Voice-Pro request failure")
                response = error_response(Request(scope), TtsError(500, "internal_error", "Internal speech server error."))
                await response(scope, receive, correlated)

        if path == "/v1/tts" and scope["method"] == "POST":
            settings = self.get_engine().tts_settings
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > settings.max_request_bytes:
                    response = error_response(Request(scope), TtsError(413, "request_too_large", "JSON body is too large."))
                    return await response(scope, receive, correlated)
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            scope["state"]["tts_started"] = time.monotonic()
            delivered = False

            async def buffered_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            return await invoke(buffered_receive)
        return await invoke(receive)


class AudioFileResponse(FileResponse):
    def __init__(self, audio: RenderedAudio, rid: str):
        self.audio = audio
        self._cleanup = weakref.finalize(self, audio.close)
        super().__init__(audio.path, media_type=audio.media_type,
                         filename=f"speech-{rid}.{audio.path.suffix[1:]}",
                         headers={"Cache-Control": "no-store", "X-Request-Id": rid,
                                  "X-Sample-Rate": str(audio.sample_rate), "X-Audio-Duration": str(audio.duration)})

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._cleanup()


async def render_response(request: Request, service: SpeechService, **options) -> AudioFileResponse:
    context = RenderContext(service.settings.timeout)
    context.deadline = getattr(request.state, "tts_started", time.monotonic()) + service.settings.timeout
    engine = service.engine
    acquired = service.complete_slots.acquire(blocking=False)
    if not acquired:
        engine.enter_queue()
        try:
            end = min(context.deadline, time.monotonic() + engine.queue_timeout)
            while not acquired:
                context.check()
                if time.monotonic() >= end:
                    raise TtsError(429, "server_busy", "Timed out waiting for complete-audio capacity.")
                if await request.is_disconnected():
                    raise TtsError(504, "synthesis_timeout", "Client disconnected.")
                await asyncio.sleep(0.02)
                acquired = service.complete_slots.acquire(blocking=False)
        finally:
            engine.leave_queue()
    task = asyncio.create_task(asyncio.to_thread(service.render, context, **options))
    try:
        while not task.done():
            context.check()
            if await request.is_disconnected():
                raise TtsError(504, "synthesis_timeout", "Client disconnected.")
            await asyncio.wait({task}, timeout=min(0.05, context.remaining()))
        audio = task.result()
        context.check()
        return AudioFileResponse(audio, getattr(request.state, "tts_request_id", "tts_" + uuid.uuid4().hex))
    except BaseException:
        context.cancelled.set()

        def cleanup(future):
            try:
                future.result().close()
            except BaseException:
                pass

        task.add_done_callback(cleanup)
        raise


async def snapshot_voice(request: Request, service: SpeechService, voice: str) -> dict:
    """Read the published registry view without a lock, I/O, or executor queue."""
    started = getattr(request.state, "tts_started", time.monotonic())
    request.state.tts_started = started
    remaining = service.settings.timeout - (time.monotonic() - started)
    if remaining <= 0:
        raise TtsError(504, "synthesis_timeout", "Timed out resolving the requested voice.")
    return service.engine.registry.snapshot(voice)


def create_router(get_engine, auth) -> APIRouter:
    router = APIRouter(dependencies=[Depends(auth)])

    @router.get("/v1/tts/capabilities")
    def capabilities():
        engine = get_engine()
        if engine.tts_settings is None:
            raise HTTPException(404, "Voice-Pro profile is disabled")
        return engine.tts_settings.capabilities(engine)

    @router.post("/v1/tts")
    async def synthesize(request: Request):
        engine = get_engine()
        service = engine.speech_service
        if service is None:
            raise HTTPException(404, "Voice-Pro profile is disabled")
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise TtsError(415, "unsupported_media_type", "Use application/json with UTF-8 text.")
        try:
            body = json.loads((await request.body()).decode("utf-8"))
            if isinstance(body, dict) and isinstance(body.get("text"), str) and len(body["text"]) > service.settings.max_text_chars:
                raise TtsError(413, "text_too_long", "Text exceeds the configured character limit.", "text")
            values = SynthesisRequest.model_validate(body)
        except (ValueError, UnicodeError, ValidationError) as exc:
            raise TtsError(400, "invalid_request", "Request contains invalid fields or values.") from exc
        if not values.text.strip():
            raise TtsError(400, "invalid_request", "Text must contain a non-whitespace character.", "text")
        voice = await snapshot_voice(request, service, values.voice)
        if engine.stream_error() is not None:
            raise TtsError(503, "engine_unavailable", "Speech engine is unavailable.")
        from apps.audio_encoding import FORMATS
        mime = FORMATS[values.format][1]
        accept = request.headers.get("accept", "*/*")
        matches = []
        for item in accept.split(","):
            parts = [p.strip() for p in item.split(";")]
            media = parts[0].lower()
            if media in (mime, "audio/*", "*/*"):
                try:
                    quality = next((float(p[2:]) for p in parts[1:] if p.startswith("q=")), 1)
                except ValueError:
                    quality = 0
                if not math.isfinite(quality) or not 0 <= quality <= 1:
                    quality = 0
                matches.append((2 if media == mime else 1 if media == "audio/*" else 0, quality))
        if not matches or max(matches)[1] <= 0:
            raise TtsError(406, "not_acceptable", "Accept does not allow the requested audio format.")
        options = values.model_dump()
        options["voice"] = voice
        options["fmt"] = options.pop("format")
        return await render_response(request, service, **options)

    return router
