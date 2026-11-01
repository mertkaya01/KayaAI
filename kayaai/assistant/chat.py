"""Asistan çalışma alanı (Adım 8, MASTER_PROMPT v2 §9A): kalıcı sohbetler, ekler, ajana yönlendirme, Claude'a devretme.

- Konuşmalar ve mesajlar SQLite'ta (yeniden başlatınca geri gelir). Her asistan mesajı bir iş kaydına (şef işi ya da
  tek ajan görevi) bağlıdır; mesajın durumu iş kaydından türetilir. Böylece başka süreçte biten iş — ör. Claude'un
  Claude Code'dan `kayaai_claude_complete` ile tamamladığı devredilmiş iş — sohbete kendiliğinden düşer.
- Bağlam: son mesajlar + bu mesajın ekleri, sınırlı boyutta; modele `<input_data>` içinde güvenilmez VERİ olarak gider.
- Claude'a devretme yalnızca sahibin açık isteğiyle (arayüzde onay penceresi) ve mevcut Claude kutusu üzerinden olur
  (sahip kararı, 2026-10-31): kayaAI Claude'u kendisi çağırmaz.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from ..core.task import TaskStatus, utcnow

if TYPE_CHECKING:
    from ..runtime import Runtime

HISTORY_MESSAGES = 8
HISTORY_CHARS = 2000
ATTACHMENT_BUDGET = 12_000
MAX_TEXT = 20_000
TITLE_CHARS = 60
AUTO = "auto"

MessageStatus = Literal["done", "pending", "running", "waiting_claude", "failed", "cancelled"]
BusinessMode = Literal["analyze", "summarize", "invoice"]
MAX_BINARY_MB = 10.0
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_SAFE_NAME = re.compile(r"[^\w.\- ()]+", re.UNICODE)


class ChatError(ValueError):
    pass


class Conversation(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    title: str = "Yeni sohbet"
    agent: str = AUTO


class AttachmentRef(BaseModel):
    id: str
    name: str
    chars: int
    kind: Literal["text", "pdf", "table", "image"] = "text"  # Adım 10: PDF/tablo · Adım 12a: görüntü (ekran görüntüsü)


class Attachment(AttachmentRef):
    created_at: datetime = Field(default_factory=utcnow)
    size: int
    source: Literal["upload", "path"]
    path: str | None = None  # izinli klasörden seçildiyse


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    conv_id: str
    created_at: datetime = Field(default_factory=utcnow)
    role: Literal["user", "assistant"]
    content: str = ""
    status: MessageStatus = "done"
    agent: str = AUTO                       # kullanıcı: istenen ajan; asistan: cevaplayan(lar)
    job_id: str | None = None
    job_kind: Literal["conductor", "task"] | None = None
    reply_to: str | None = None
    handoff: bool = False                   # Claude'a devredildi
    attachments: list[AttachmentRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    context_warnings: list[str] = Field(default_factory=list)  # bağlam kesme uyarıları (iş uyarılarından ayrı)
    meta: dict[str, Any] = Field(default_factory=dict)
    # Adım 9: bu cevap için hafızadan/belgelerden getirilenler (arayüzde "Kaynaklar" / "Kullanılan hafıza")
    recall: dict[str, Any] = Field(default_factory=dict)


class ConversationView(BaseModel):
    conversation: Conversation
    messages: list[ChatMessage]


def safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name.strip() or "ek.txt"
    return _SAFE_NAME.sub("_", base)[:120]


class ChatBook:
    def __init__(self, rt: "Runtime"):
        self.rt = rt
        self.store = rt.store
        self.attach_dir = rt.settings.data_dir / "attachments"

    # ------------------------------------------------------------------ konuşmalar

    def _save_conv(self, c: Conversation) -> None:
        self.store.save_conversation(c.id, c.created_at.isoformat(), c.updated_at.isoformat(), c.model_dump(mode="json"))

    def create(self, title: str | None = None, agent: str = AUTO) -> Conversation:
        c = Conversation(title=(title or "Yeni sohbet").strip()[:TITLE_CHARS] or "Yeni sohbet", agent=agent)
        self._save_conv(c)
        return c

    def get(self, conv_id: str) -> Conversation:
        raw = self.store.get_conversation(conv_id)
        if raw is None:
            raise ChatError(f"Sohbet bulunamadı: {conv_id}")
        return Conversation.model_validate(raw)

    def list(self) -> list[Conversation]:
        return [Conversation.model_validate(r) for r in self.store.list_conversations()]

    def rename(self, conv_id: str, title: str) -> Conversation:
        c = self.get(conv_id)
        title = title.strip()[:TITLE_CHARS]
        if not title:
            raise ChatError("Başlık boş olamaz")
        c.title, c.updated_at = title, utcnow()
        self._save_conv(c)
        return c

    def delete(self, conv_id: str) -> None:
        self.get(conv_id)
        self.store.delete_conversation(conv_id)
        self.store.emit("chat.deleted", {"conv_id": conv_id})

    def view(self, conv_id: str) -> ConversationView:
        c = self.get(conv_id)
        msgs = [self.refresh(ChatMessage.model_validate(m)) for m in self.store.list_messages(conv_id)]
        return ConversationView(conversation=c, messages=msgs)

    # ------------------------------------------------------------------ ekler

    def _save_attachment(self, name: str, text: str, source: Literal["upload", "path"], path: str | None) -> Attachment:
        if "\x00" in text:
            raise ChatError("Bu bir metin dosyası değil (ikili içerik). PDF/Excel desteği Adım 10'da gelecek.")
        limit = int(self.rt.settings.files.max_read_mb * 1024 * 1024)
        size = len(text.encode("utf-8"))
        if size > limit:
            raise ChatError(f"Ek çok büyük ({size / 1e6:.1f} MB > {self.rt.settings.files.max_read_mb} MB)")
        kind: Literal["text", "table"] = "table" if Path(safe_name(name)).suffix.lower() in (".csv", ".tsv") else "text"
        a = Attachment(id=uuid.uuid4().hex[:12], name=safe_name(name), chars=len(text), size=size, source=source,
                       path=path, kind=kind)
        self.attach_dir.mkdir(parents=True, exist_ok=True)
        (self.attach_dir / f"{a.id}.txt").write_text(text, encoding="utf-8")
        self.store.save_attachment(a.id, a.created_at.isoformat(), a.model_dump(mode="json"))
        return a

    def _save_binary(self, name: str, data: bytes, source: Literal["upload", "path"], path: str | None) -> Attachment:
        """PDF/Excel eki: özgün dosya saklanır (iş modülleri için), çıkarılan metin bağlam için."""
        from ..business.readers import ReadError, extract_text

        if len(data) > MAX_BINARY_MB * 1024 * 1024:
            raise ChatError(f"Ek çok büyük ({len(data) / 1e6:.1f} MB > {MAX_BINARY_MB:.0f} MB)")
        try:
            text, kind = extract_text(data, safe_name(name))
        except ReadError as exc:
            raise ChatError(str(exc)) from exc
        a = Attachment(id=uuid.uuid4().hex[:12], name=safe_name(name), chars=len(text), size=len(data), source=source,
                       path=path, kind=kind)
        self.attach_dir.mkdir(parents=True, exist_ok=True)
        (self.attach_dir / f"{a.id}.bin").write_bytes(data)
        (self.attach_dir / f"{a.id}.txt").write_text(text, encoding="utf-8")
        self.store.save_attachment(a.id, a.created_at.isoformat(), a.model_dump(mode="json"))
        return a

    def _save_image(self, name: str, data: bytes, source: Literal["upload", "path"], path: str | None) -> Attachment:
        """Görüntü eki (ekran görüntüsü/fotoğraf): özgün dosya saklanır; metni OCR ile okunur (Windows; yoksa boş)."""
        from ..perception.ocr import OcrUnavailable, normalize_image, ocr_image

        if len(data) > MAX_BINARY_MB * 1024 * 1024:
            raise ChatError(f"Görüntü çok büyük ({len(data) / 1e6:.1f} MB > {MAX_BINARY_MB:.0f} MB)")
        try:
            normalize_image(data)  # doğrula (bozuk / dev görüntü)
        except ValueError as exc:
            raise ChatError(str(exc)) from exc
        try:
            text = ocr_image(data).text
        except (OcrUnavailable, ValueError):
            text = ""
        a = Attachment(id=uuid.uuid4().hex[:12], name=safe_name(name), chars=len(text), size=len(data), source=source,
                       path=path, kind="image")
        self.attach_dir.mkdir(parents=True, exist_ok=True)
        (self.attach_dir / f"{a.id}.bin").write_bytes(data)
        (self.attach_dir / f"{a.id}.txt").write_text(text, encoding="utf-8")
        self.store.save_attachment(a.id, a.created_at.isoformat(), a.model_dump(mode="json"))
        return a

    def upload_binary(self, name: str, data_b64: str) -> Attachment:
        import base64
        import binascii

        from ..business.readers import BINARY_SUFFIXES

        suffix = Path(safe_name(name)).suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            try:
                return self._save_image(name, base64.b64decode(data_b64, validate=True), "upload", None)
            except (binascii.Error, ValueError) as exc:
                if isinstance(exc, ChatError):
                    raise
                raise ChatError("Görüntü içeriği bozuk (base64)") from exc
        if suffix not in BINARY_SUFFIXES:
            raise ChatError(f"Bu dosya türü ikili ek olarak kabul edilmiyor ({suffix or 'uzantısız'}); PDF, Excel (.xlsx) ve görüntü (PNG/JPEG) olur")
        try:
            data = base64.b64decode(data_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ChatError("Dosya içeriği bozuk (base64)") from exc
        return self._save_binary(name, data, "upload", None)

    def file_bytes(self, att_id: str) -> tuple[Attachment, bytes]:
        """İş modülleri için ekin özgün baytları (metin eklerinde metnin kendisi, ör. CSV)."""
        a, text = self.attachment(att_id)
        raw = self.attach_dir / f"{a.id}.bin"
        return a, (raw.read_bytes() if raw.is_file() else text.encode("utf-8"))

    def upload(self, name: str, text: str) -> Attachment:
        from ..tools.files import TEXT_SUFFIXES

        suffix = Path(safe_name(name)).suffix.lower()
        if suffix not in TEXT_SUFFIXES:
            raise ChatError(f"Bu dosya türü henüz eklenemiyor ({suffix or 'uzantısız'}); metin dosyaları: "
                            + " ".join(sorted(TEXT_SUFFIXES)))
        return self._save_attachment(name, text, "upload", None)

    def attach_path(self, path: str) -> Attachment:
        """İzinli klasörden dosya (FileTools: kök kontrolü, tür ve boyut sınırı; R0)."""
        assert self.rt.files is not None
        from ..business.readers import BINARY_SUFFIXES

        if Path(path).suffix.lower() in BINARY_SUFFIXES | IMAGE_SUFFIXES:
            resolved, _ = self.rt.files.resolve(path)  # kök kontrolü (izinli klasör dışı → PathNotAllowed)
            if not resolved.is_file():
                raise ChatError(f"Dosya yok: {resolved}")
            if resolved.suffix.lower() in IMAGE_SUFFIXES:
                return self._save_image(resolved.name, resolved.read_bytes(), "path", str(resolved))
            return self._save_binary(resolved.name, resolved.read_bytes(), "path", str(resolved))
        res = self.rt.files.read(path, requested_by="assistant")
        if res.status != "done" or not res.result:
            raise ChatError(res.error or res.message or "Dosya okunamadı")
        return self._save_attachment(Path(res.result["path"]).name, res.result["content"], "path", res.result["path"])

    def attachment(self, att_id: str) -> tuple[Attachment, str]:
        raw = self.store.get_attachment(att_id)
        if raw is None:
            raise ChatError(f"Ek bulunamadı: {att_id}")
        a = Attachment.model_validate(raw)
        return a, (self.attach_dir / f"{a.id}.txt").read_text(encoding="utf-8")

    # ------------------------------------------------------------------ bağlam

    def build_context(self, conv_id: str, before: ChatMessage, attachments: list[AttachmentRef]) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        history = [ChatMessage.model_validate(m) for m in self.store.list_messages(conv_id)]
        history = [m for m in history if m.id != before.id and m.status == "done" and m.content.strip()]
        convo = []
        for m in history[-HISTORY_MESSAGES:]:
            text = m.content if len(m.content) <= HISTORY_CHARS else m.content[:HISTORY_CHARS] + " …(kısaltıldı)"
            names = f" [ekler: {', '.join(a.name for a in m.attachments)}]" if m.attachments else ""
            convo.append({"role": m.role, "content": text + names})
        files = []
        budget = ATTACHMENT_BUDGET
        for ref in attachments:
            _, text = self.attachment(ref.id)
            if budget <= 0:
                warnings.append(f"'{ref.name}' bağlam sınırı nedeniyle modele verilmedi.")
                continue
            if len(text) > budget:
                warnings.append(f"'{ref.name}' çok uzun; ilk {budget} karakteri kullanıldı.")
                text = text[:budget]
            budget -= len(text)
            files.append({"name": ref.name, "content": text})
        ctx: dict[str, Any] = {}
        if convo:
            ctx["conversation"] = convo
        if files:
            ctx["attachments"] = files
        return ctx, warnings

    # ------------------------------------------------------------------ gönderme

    def _save_msg(self, m: ChatMessage) -> None:
        self.store.save_message(m.id, m.conv_id, m.created_at.isoformat(), m.status, m.model_dump(mode="json"))

    def _touch(self, conv: Conversation, first_text: str | None = None) -> None:
        if first_text and conv.title == "Yeni sohbet":
            line = first_text.strip().splitlines()[0] if first_text.strip() else ""
            conv.title = (line[:TITLE_CHARS - 1] + "…") if len(line) > TITLE_CHARS else (line or conv.title)
        conv.updated_at = utcnow()
        self._save_conv(conv)

    def send(self, conv_id: str, text: str, agent: str = AUTO, attachment_ids: list[str] | None = None,
             mode: BusinessMode | None = None) -> tuple[ChatMessage, ChatMessage, Callable[[], None]]:
        """Kullanıcı mesajını kaydeder, bekleyen asistan mesajını ve işi oluşturur. Üçüncü değer: işi çalıştıran
        çağrılabilir (API onu arka plan kuyruğuna verir, CLI/test doğrudan çağırır)."""
        conv = self.get(conv_id)
        text = (text or "").strip()
        if not text:
            raise ChatError("Mesaj boş olamaz")
        if len(text) > MAX_TEXT:
            raise ChatError(f"Mesaj en fazla {MAX_TEXT} karakter olabilir")
        if agent != AUTO and agent not in self.rt.workers.names():
            raise ChatError(f"Bilinmeyen ajan: {agent}")
        if agent in ("planner", "reviewer"):
            raise ChatError(f"'{agent}' yalnızca şefin iç ajanıdır; 'otomatik' ya da bir uzman seç")
        refs = []
        for att_id in attachment_ids or []:
            a, _ = self.attachment(att_id)
            refs.append(AttachmentRef(id=a.id, name=a.name, chars=a.chars, kind=a.kind))
        user = ChatMessage(conv_id=conv_id, role="user", content=text, agent=agent, attachments=refs)
        self._save_msg(user)
        from ..memory import REMEMBER_RE

        if (m := REMEMBER_RE.match(text)) and not refs:
            reply, runner = self._remember(conv_id, user, m.group(1))
            self._touch(conv, text)
            self.store.emit("chat.message", {"conv_id": conv_id, "message_id": user.id, "role": "user"})
            return user, reply, runner
        # Adım 12a: görüntü eki → görsel ajan (ekran görüntüsü); devam sorusu da önceki görüntü(ler)le cevaplanır
        images = [r for r in refs if r.kind == "image"]
        if mode is None and not images and not refs and agent in (AUTO, "vision"):
            images = self._last_vision_images(conv_id, user.id)
        if mode is None and images and agent in (AUTO, "vision"):
            reply, runner = self._vision(conv_id, user, images)
            self._touch(conv, text)
            self.store.emit("chat.message", {"conv_id": conv_id, "message_id": user.id, "role": "user"})
            return user, reply, runner
        # Adım 10: tablo eki + otomatik/data → analiz; açık mod (Analiz et / Özetle / Fatura olarak oku) her zaman
        if mode is None and agent in (AUTO, "data") and any(r.kind == "table" for r in refs) \
                and not any(r.kind == "pdf" for r in refs):
            mode = "analyze"
        if mode is not None:
            reply, runner = self._business(conv_id, user, refs, mode)
            self._touch(conv, text)
            self.store.emit("chat.message", {"conv_id": conv_id, "message_id": user.id, "role": "user"})
            return user, reply, runner
        reply = ChatMessage(conv_id=conv_id, role="assistant", status="pending", agent=agent, reply_to=user.id)
        ctx, warnings = self.build_context(conv_id, user, refs)
        reply.warnings = reply.context_warnings = warnings
        runner = self._start(reply, text, agent, ctx, force=None)
        self._touch(conv, text)
        self.store.emit("chat.message", {"conv_id": conv_id, "message_id": user.id, "role": "user"})
        return user, reply, runner

    def handoff(self, conv_id: str, message_id: str) -> tuple[ChatMessage, Callable[[], None]]:
        """Bir kullanıcı mesajını (ya da ona verilen cevabı) Claude kutusuna devreder. Claude modu açık olmalı."""
        if not (self.rt.claude and self.rt.claude.is_enabled()):
            raise ChatError("Claude modu kapalı: devretmek için önce Claude'u aç (yerel ekip zaten cevaplıyor).")
        conv = self.get(conv_id)
        raw = self.store.get_message(message_id)
        if raw is None or raw.get("conv_id") != conv_id:
            raise ChatError(f"Mesaj bulunamadı: {message_id}")
        msg = ChatMessage.model_validate(raw)
        if msg.role == "assistant":
            if not msg.reply_to:
                raise ChatError("Bu cevabın bağlı olduğu soru bulunamadı")
            msg = ChatMessage.model_validate(self.store.get_message(msg.reply_to))
        reply = ChatMessage(conv_id=conv_id, role="assistant", status="pending", agent="claude", reply_to=msg.id,
                            handoff=True)
        # Ekran görüntüleri (ve OCR metinleri) özeldir: Claude'a gönderilmez (Adım 12a güvenlik kuralı)
        refs = [r for r in msg.attachments if r.kind != "image"]
        ctx, warnings = self.build_context(conv_id, msg, refs)
        if len(refs) < len(msg.attachments):
            warnings.append("Ekran görüntüleri Claude'a gönderilmez (yerelde kalır); yalnızca metin devredildi.")
        reply.warnings = reply.context_warnings = warnings
        runner = self._start(reply, msg.content, AUTO, ctx, force="claude")
        self._touch(conv)
        return reply, runner

    def _last_vision_images(self, conv_id: str, before_id: str) -> list[AttachmentRef]:
        """Son asistan cevabı görsel ajandansa, sorduğu görüntüler (devam sorusu: "peki sağ üstte ne yazıyor?")."""
        msgs = [ChatMessage.model_validate(m) for m in self.store.list_messages(conv_id)]
        msgs = [m for m in msgs if m.id != before_id]
        last = next((m for m in reversed(msgs) if m.role == "assistant"), None)
        if last is None or last.agent != "vision" or last.status != "done" or not last.reply_to:
            return []
        q = next((m for m in msgs if m.id == last.reply_to), None)
        if q is None:
            return []
        if q.attachments:
            return [r for r in q.attachments if r.kind == "image"]
        return [AttachmentRef.model_validate(r) for r in last.meta.get("vision_images", [])]

    def _vision(self, conv_id: str, user: ChatMessage, images: list[AttachmentRef]) -> tuple[ChatMessage, Callable[[], None]]:
        """Görüntü eki: OCR (ek yüklenirken okundu) + yerel görsel model; sayılar OCR metnine karşı kodla denetlenir."""
        from ..perception.vision import MAX_IMAGES

        images = images[:MAX_IMAGES]
        reply = ChatMessage(conv_id=conv_id, role="assistant", status="pending", agent="vision", reply_to=user.id)
        self._save_msg(reply)
        history = [ChatMessage.model_validate(m) for m in self.store.list_messages(conv_id)]
        convo = [{"role": m.role, "content": m.content[:HISTORY_CHARS]} for m in history
                 if m.id not in (user.id, reply.id) and m.status == "done" and m.content.strip()][-4:]

        def run_vision() -> None:
            from ..perception.vision import VisionError, see

            msg = ChatMessage.model_validate(self.store.get_message(reply.id))
            msg.status = "running"
            self._save_msg(msg)
            self.store.emit("chat.message", {"conv_id": conv_id, "message_id": msg.id, "role": "assistant",
                                             "status": "running"})
            try:
                datas, ocr = [], []
                for ref in images:
                    a, data = self.file_bytes(ref.id)
                    datas.append(data)
                    ocr.append((self.attach_dir / f"{a.id}.txt").read_text(encoding="utf-8"))
                result = see(self.rt, datas, user.content, ocr_texts=ocr if any(ocr) else None, conversation=convo)
                msg.content = result.markdown()
                msg.warnings = list(result.warnings)
                msg.job_id, msg.job_kind = result.task_id, "task"
                msg.meta = {"vision": result.model_dump(mode="json", exclude={"answer"}), "agents": ["vision"],
                            "vision_images": [r.model_dump() for r in images]}
                msg.status = "done"
            except (VisionError, ChatError) as exc:
                msg.content, msg.status = str(exc), "failed"
            except Exception as exc:  # noqa: BLE001 - mesaj her durumda kapanmalı
                msg.content, msg.status = f"Beklenmeyen hata: {exc}", "failed"
            self._save_msg(msg)
            self.store.emit("chat.message", {"conv_id": conv_id, "message_id": msg.id, "role": "assistant",
                                             "status": msg.status})
        return reply, run_vision

    def _business(self, conv_id: str, user: ChatMessage, refs: list[AttachmentRef],
                  mode: BusinessMode) -> tuple[ChatMessage, Callable[[], None]]:
        """İş modülü: dosya üzerinde analiz / özet / fatura (sayıları kod hesaplar, tutarlar kodla denetlenir)."""
        want = "table" if mode == "analyze" else "pdf"
        target = next((r for r in refs if r.kind == want), None)
        if target is None:
            need = "bir Excel/CSV dosyası" if want == "table" else "bir PDF"
            raise ChatError(f"Bu işlem için {need} ekle.")
        agent = "data" if mode == "analyze" else "document"
        reply = ChatMessage(conv_id=conv_id, role="assistant", status="pending", agent=agent, reply_to=user.id)
        self._save_msg(reply)

        def run_business() -> None:
            from ..business import run_mode
            from ..business.readers import ReadError

            msg = ChatMessage.model_validate(self.store.get_message(reply.id))
            msg.status = "running"
            self._save_msg(msg)
            self.store.emit("chat.message", {"conv_id": conv_id, "message_id": msg.id, "role": "assistant",
                                             "status": "running"})
            try:
                _, data = self.file_bytes(target.id)
                result = run_mode(self.rt, mode, data, target.name, user.content)
                msg.content = result.markdown()
                msg.warnings = list(result.warnings)
                msg.meta = {"business": _trim_result(result.model_dump(mode="json")), "agents": [agent]}
                msg.status = "done"
            except (ReadError, ValueError) as exc:
                msg.content, msg.status = f"Dosya işlenemedi: {exc}", "failed"
            except Exception as exc:  # noqa: BLE001 - mesaj her durumda kapanmalı
                msg.content, msg.status = f"Beklenmeyen hata: {exc}", "failed"
            self._save_msg(msg)
            self.store.emit("chat.message", {"conv_id": conv_id, "message_id": msg.id, "role": "assistant",
                                             "status": msg.status})
        return reply, run_business

    def report(self, conv_id: str, message_id: str, fmt: str):  # -> SubmitResult
        """Bir asistan cevabından iş raporu (md/xlsx/docx/pdf) → ~/kayaAI-files/raporlar (R1; aynı ad R2)."""
        from ..business import FORMATS, from_markdown, from_result, save
        from ..business.report import ReportError

        if fmt not in FORMATS:
            raise ChatError(f"Biçim {', '.join(FORMATS)} olmalı")
        raw = self.store.get_message(message_id)
        if raw is None or raw.get("conv_id") != conv_id:
            raise ChatError(f"Mesaj bulunamadı: {message_id}")
        msg = ChatMessage.model_validate(raw)
        if msg.role != "assistant" or msg.status != "done" or not msg.content.strip():
            raise ChatError("Rapor yalnızca tamamlanmış bir cevaptan üretilebilir")
        conv = self.get(conv_id)
        try:
            business = msg.meta.get("business")
            rep = from_result(business) if business else from_markdown(
                msg.content, title=conv.title, sources=[s.get("name", "") for s in msg.recall.get("sources", [])])
            if not business and msg.warnings:
                rep.notes = list(msg.warnings)
            res = save(self.rt, rep, fmt, requested_by="assistant")  # type: ignore[arg-type]
        except ReportError as exc:
            raise ChatError(str(exc)) from exc
        self.store.emit("chat.report", {"conv_id": conv_id, "message_id": message_id, "format": fmt,
                                        "status": res.status})
        return res

    def _remember(self, conv_id: str, user: ChatMessage, body: str) -> tuple[ChatMessage, Callable[[], None]]:
        """"hatırla: …" — sahibin açık isteği: not hafızaya kaydedilir (gizli bilgi reddedilir)."""
        reply = ChatMessage(conv_id=conv_id, role="assistant", status="pending", agent="memory", reply_to=user.id)
        self._save_msg(reply)

        def run_remember() -> None:
            from ..memory import remember

            msg = ChatMessage.model_validate(self.store.get_message(reply.id))
            try:
                item, text, warnings = remember(self.rt, body, source="chat", conv_id=conv_id)
                msg.content, msg.warnings = text, warnings
                msg.meta = {"memory_saved": item.id} if item else {"memory_refused": True}
                msg.status = "done"
            except Exception as exc:  # noqa: BLE001 - mesaj her durumda kapanmalı
                msg.content, msg.status = f"Hafızaya kaydedilemedi: {exc}", "failed"
            self._save_msg(msg)
            self.store.emit("chat.message", {"conv_id": conv_id, "message_id": msg.id, "role": "assistant",
                                             "status": msg.status})
        return reply, run_remember

    def _recall(self, reply: ChatMessage, text: str, for_claude: bool) -> dict[str, Any]:
        """İlgili hafıza öğeleri ve belge parçaları (Adım 9). Hata sohbeti durdurmaz."""
        mem = self.rt.memory
        if mem is None or not self.rt.settings.memory.recall_in_chat:
            return {}
        try:
            rec = mem.recall(text, for_claude=for_claude)
        except Exception as exc:  # noqa: BLE001
            rec = None
            warn = [f"Hafıza kullanılamadı: {exc}"]
        else:
            warn = rec.warnings
        msg = ChatMessage.model_validate(self.store.get_message(reply.id))
        if rec is not None:
            msg.recall = {
                "memories": [{"id": m["id"], "text": m["text"], "category": m["category"],
                              "sensitivity": m["sensitivity"]} for m in rec.memories],
                "sources": [{"path": d["path"], "name": d["name"], "line": d["line"], "loc": d.get("loc", "")}
                            for d in rec.documents],
            }
        msg.context_warnings = _merge(msg.context_warnings, warn)
        msg.warnings = _merge(msg.warnings, warn)
        self._save_msg(msg)
        return rec.context() if rec is not None else {}

    def _start(self, reply: ChatMessage, text: str, agent: str, ctx: dict[str, Any],
               force: Literal["claude"] | None) -> Callable[[], None]:
        from ..conductor import Conductor

        if agent == AUTO:
            conductor = Conductor(self.rt)
            job = conductor.create_job(text, force=force, origin="user", context=ctx or None)
            reply.job_id, reply.job_kind = job.id, "conductor"
            self._save_msg(reply)

            def run_conductor() -> None:
                try:
                    extra = self._recall(reply, text, for_claude=force == "claude")
                    if extra:
                        job.input["context"] = {**(job.input.get("context") or {}), **extra}
                        self.rt.store.save(job)
                    conductor.run_job(job)
                finally:
                    self.refresh(reply, emit=True)
            return run_conductor
        task = self.rt.orchestrator.submit(text, worker=agent, input=ctx or None)
        reply.job_id, reply.job_kind = task.id, "task"
        self._save_msg(reply)

        def run_task() -> None:
            try:
                extra = self._recall(reply, text, for_claude=False)
                if extra:
                    t = self.store.get(task.id)
                    if t is not None:
                        t.input = {**t.input, **extra}
                        self.store.save(t)
                self.rt.orchestrator.run(task.id)
            finally:
                self.refresh(reply, emit=True)
        return run_task

    # ------------------------------------------------------------------ iş kaydından mesaj durumu

    def refresh(self, msg: ChatMessage, emit: bool = False) -> ChatMessage:
        """Bekleyen asistan mesajını bağlı iş kaydına göre günceller (iş başka süreçte bitmiş olabilir)."""
        if msg.role != "assistant" or msg.status not in ("pending", "running", "waiting_claude") or not msg.job_id:
            return msg
        raw = self.store.get_message(msg.id)
        if raw is not None:
            msg = ChatMessage.model_validate(raw)  # güncel kopya
            if msg.status not in ("pending", "running", "waiting_claude"):
                return msg
        job = self.store.get(msg.job_id or "")
        if job is None:
            return msg
        before = msg.status
        if job.status == TaskStatus.RUNNING:
            msg.status = "running"
        elif job.status == TaskStatus.WAITING_CLAUDE:
            msg.status = "waiting_claude"
            res = job.result or {}
            msg.meta = _conductor_meta(res)
            msg.warnings = _merge(msg.context_warnings, res.get("warnings", []))
        elif job.status == TaskStatus.SUCCEEDED:
            res = job.result or {}
            if msg.job_kind == "conductor":
                msg.content = str(res.get("answer", ""))
                msg.meta = _conductor_meta(res)
                # İşin GÜNCEL uyarıları (kutudan tamamlanınca "kutuya bırakıldı" uyarısı silinir)
                msg.warnings = _merge(msg.context_warnings, res.get("warnings", []))
                if res.get("completed_by"):
                    msg.agent = "claude"
                    msg.meta["agents"] = []  # planın önerdiği yerel ajanlar cevabı yazmadı
            else:
                msg.content = str(res.get("answer", ""))
                msg.meta = {"agents": [job.worker], "model": job.model}
                msg.agent = job.worker
            msg.status = "done"
        elif job.status.is_terminal:
            msg.status = "cancelled" if job.status == TaskStatus.CANCELLED else "failed"
            msg.content = msg.content or f"Cevap üretilemedi: {job.error or job.status.value}"
        if msg.status != before:
            self._save_msg(msg)
            if emit or msg.status in ("done", "failed", "cancelled"):
                self.store.emit("chat.message", {"conv_id": msg.conv_id, "message_id": msg.id, "role": "assistant",
                                                 "status": msg.status})
        return msg


def _trim_result(d: dict[str, Any], max_rows: int = 200) -> dict[str, Any]:
    """Mesajda saklanan iş sonucu: rapor için yeterli, veritabanını şişirmeyecek kadar."""
    for r in d.get("results", []):
        r["rows"] = r.get("rows", [])[:max_rows]
    if "profile" in d:
        d["profile"] = {**d["profile"], "sample_rows": d["profile"].get("sample_rows", [])[:3]}
    return d


def _merge(a: list[str], b: list[str]) -> list[str]:
    return list(dict.fromkeys([*a, *b]))


def _conductor_meta(res: dict[str, Any]) -> dict[str, Any]:
    steps = res.get("steps", [])
    reviews = [s.get("review") for s in steps if s.get("review")]
    return {
        "agents": [s.get("agent") for s in steps],
        "mode": res.get("mode"),
        "routing": (res.get("routing") or {}).get("decision"),
        "duration_s": res.get("duration_s"),
        "reviewed": sum(1 for r in reviews if not r.get("skipped")),
        "revised": sum(1 for r in reviews if r.get("revised")),
        "disputes": sum(len(r.get("disputes", [])) for r in reviews),
        "dropped": sum(int(r.get("dropped_issues", 0)) for r in reviews),
    }
