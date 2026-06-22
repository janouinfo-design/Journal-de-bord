"""Phase 5 — OCR / structured extraction for fine documents.

Accepts a PDF or image of a fine notice and asks Gemini Vision
(`gemini-3.1-pro-preview` via the Emergent LLM key) to extract the structured
fields needed to pre-fill the create-fine form.

Why PyMuPDF and not pdf2image: PyMuPDF is pure-Python, ships its own MuPDF
binaries — no poppler / ImageMagick dependency required.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image

from emergentintegrations.llm.chat import (
    LlmChat, UserMessage, ImageContent, TextDelta, StreamDone,
)

log = logging.getLogger(__name__)

# Model picked from the integration playbook (recommended Gemini vision).
OCR_PROVIDER = "gemini"
OCR_MODEL = "gemini-3.1-pro-preview"
MAX_IMAGE_DIMENSION = 2000   # px — keeps payload < ~3 MB
JPEG_QUALITY = 85

SYSTEM_PROMPT = (
    "Tu es un assistant expert en analyse de documents administratifs suisses, "
    "spécialement les amendes routières (police cantonale, communales, péages). "
    "Ta seule mission est d'extraire des informations structurées sous forme de "
    "JSON valide. Ne donne aucune explication, aucune phrase d'introduction, "
    "uniquement le JSON. Si une information n'est pas lisible, mets `null` pour "
    "ce champ. Les dates doivent être au format ISO 8601 (YYYY-MM-DD pour les "
    "dates, YYYY-MM-DDTHH:MM pour date+heure). Les montants en chiffres "
    "uniquement, sans devise. La devise par défaut est CHF."
)

USER_PROMPT = (
    "Voici le document d'une amende. Extrais les informations suivantes au "
    "format JSON strict (aucun commentaire) :\n"
    "{\n"
    '  "ref_fine": "numéro de référence / dossier de l\'amende, ou null",\n'
    '  "authority": "autorité émettrice (ex: Police cantonale vaudoise), ou null",\n'
    '  "country": "code pays ISO 2 lettres, défaut CH",\n'
    '  "canton": "code canton suisse (VD, GE, VS, ...) ou null",\n'
    '  "city": "commune de l\'infraction ou null",\n'
    '  "location": "lieu précis (rue, route, autoroute) ou null",\n'
    '  "received_at": "date de réception YYYY-MM-DD ou null",\n'
    '  "infraction_at": "date+heure de l\'infraction YYYY-MM-DDTHH:MM ou null",\n'
    '  "vehicle_plate": "plaque (ex: VD 123456) ou null",\n'
    '  "amount": montant principal en nombre (sans devise) ou null,\n'
    '  "admin_fees": frais administratifs en nombre ou null,\n'
    '  "currency": "code devise (CHF par défaut)",\n'
    '  "due_date": "date limite paiement YYYY-MM-DD ou null",\n'
    '  "infraction_type": "speeding|parking|red_light|toll|forbidden_zone|phone|seatbelt|other"\n'
    "}\n"
    "Réponds uniquement avec ce JSON, rien d'autre."
)


def _pdf_first_page_to_jpeg(pdf_bytes: bytes) -> bytes:
    """Render the first page of a PDF to a JPEG image (96 DPI)."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        if doc.page_count == 0:
            raise ValueError("PDF vide")
        page = doc.load_page(0)
        # 144 DPI ≈ 2x the default for crisper OCR while staying compact
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return _normalize_image(img)


def _normalize_image(img: Image.Image) -> bytes:
    """Resize if too large, convert to JPEG, return bytes."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_IMAGE_DIMENSION:
        scale = MAX_IMAGE_DIMENSION / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buf.getvalue()


def prepare_image_payload(data: bytes, mime_type: str) -> str:
    """Normalize the incoming bytes (image or PDF) to a base64 JPEG."""
    if not data:
        raise ValueError("Document vide")
    mime = (mime_type or "").lower()
    if mime == "application/pdf" or data[:4] == b"%PDF":
        normalized = _pdf_first_page_to_jpeg(data)
    else:
        try:
            img = Image.open(io.BytesIO(data))
            normalized = _normalize_image(img)
        except Exception as e:
            raise ValueError(f"Image illisible : {e}") from e
    return base64.b64encode(normalized).decode("ascii")


def _extract_json(raw: str) -> dict:
    """Strip Markdown fences / preamble and parse the JSON response."""
    if not raw:
        return {}
    # Pull the first {...} block if the model returned extra text
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {}
    text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try once more after stripping trailing commas (a common LLM mistake)
        text = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            log.warning("OCR: invalid JSON returned: %s", e)
            return {}


async def extract_fine_from_document(
    data: bytes,
    mime_type: str,
    session_id: str,
) -> dict:
    """Run Gemini Vision on the document and return a structured dict."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise RuntimeError("EMERGENT_LLM_KEY non configurée.")

    b64 = prepare_image_payload(data, mime_type)

    chat = LlmChat(
        api_key=api_key,
        session_id=session_id,
        system_message=SYSTEM_PROMPT,
    ).with_model(OCR_PROVIDER, OCR_MODEL)

    message = UserMessage(
        text=USER_PROMPT,
        file_contents=[ImageContent(image_base64=b64)],
    )

    chunks = []
    async for ev in chat.stream_message(message):
        if isinstance(ev, TextDelta):
            chunks.append(ev.content)
        elif isinstance(ev, StreamDone):
            break
    raw = "".join(chunks).strip()
    parsed = _extract_json(raw)
    return parsed
