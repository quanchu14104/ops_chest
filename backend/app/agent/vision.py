"""Doc HSD tu anh tem. Model chi tra ve chu in tren bao bi; viec hieu ngay do code tat dinh lam.

Khong ghi gi vao DB va khong luu anh: ket qua chi dien san o HSD, nguoi nhan hang van phai bam xac nhan.
"""
from __future__ import annotations

import calendar
import json
import re
from datetime import date, timedelta

from app.clock import today
from app.config import settings

MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_BASE64_CHARS = 8_000_000
LOW_CONFIDENCE = 0.6

PROMPT = """You read dates printed on Vietnamese food packaging. Reply with ONLY a JSON object:
{"hsd_text": string or null, "nsx_text": string or null, "confidence": number from 0 to 1}
hsd_text: the expiry date exactly as printed, next to HSD, Hạn sử dụng, EXP, Use by or Best before.
nsx_text: the manufacturing date exactly as printed, next to NSX, Ngày sản xuất or MFG.
If the expiry date is unclear or absent, set hsd_text to null. Never guess and never use the manufacturing date as the expiry date."""


class VisionError(Exception):
    pass


def parse_expiry(text: object) -> date | None:
    """Ngay kieu Viet Nam (ngay truoc thang). Chi co thang/nam thi lay ngay cuoi thang."""
    if not text or not isinstance(text, str):  # model co the tra so hoac mang thay vi chuoi
        return None
    s = text.strip()
    m = re.search(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", s)
    try:
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.search(r"(?<!\d)(\d{1,2})[-/.\s](\d{1,2})[-/.\s](\d{4}|\d{2})(?!\d)", s)
        if m:
            y = int(m[3])
            return date(y + 2000 if y < 100 else y, int(m[2]), int(m[1]))
        m = re.search(r"(?<!\d)(\d{1,2})[-/.\s](\d{4})(?!\d)", s)
        if m:
            y, mo = int(m[2]), int(m[1])
            return date(y, mo, calendar.monthrange(y, mo)[1])
    except ValueError:
        return None
    return None


def _provider() -> tuple[str, str, str]:
    s = settings
    if s.llm_vision_model:
        return s.llm_vision_base_url or s.llm_base_url, s.llm_vision_api_key or s.llm_api_key, s.llm_vision_model
    if s.llm_model_fallback and s.llm_base_url_fallback:
        return s.llm_base_url_fallback, s.llm_api_key_fallback, s.llm_model_fallback
    return s.llm_base_url, s.llm_api_key, s.llm_model


def _call_model(image_base64: str, mime: str) -> str:
    from openai import OpenAI

    base_url, api_key, model = _provider()
    client = OpenAI(base_url=base_url, api_key=api_key or "not-needed", timeout=45, max_retries=1)
    r = client.chat.completions.create(model=model, temperature=0, messages=[{"role": "user", "content": [
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_base64}"}},
    ]}])
    return r.choices[0].message.content or ""


def _parse_reply(reply: str) -> dict:
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        raise VisionError("Model không trả về kết quả đọc được, hãy nhập HSD bằng tay.")
    try:
        return json.loads(m[0])
    except json.JSONDecodeError as e:
        raise VisionError("Model không trả về kết quả đọc được, hãy nhập HSD bằng tay.") from e


def read_expiry(image_base64: str, mime: str, shelf_life_days: int | None = None) -> dict:
    if mime not in MIMES:
        raise VisionError("Chỉ nhận ảnh JPEG, PNG hoặc WebP.")
    if len(image_base64) > MAX_BASE64_CHARS:
        raise VisionError("Ảnh quá lớn, hãy chụp lại với độ phân giải thấp hơn.")
    try:
        reply = _call_model(image_base64, mime)
    except Exception as e:  # noqa: BLE001 - loi mang/han muc/model khong ho tro anh deu quy ve nhap tay
        raise VisionError(f"Chưa đọc được ảnh ({type(e).__name__}), hãy nhập HSD bằng tay.") from e
    data = _parse_reply(reply)
    raw, nsx = data.get("hsd_text"), data.get("nsx_text")
    conf = data.get("confidence") if isinstance(data.get("confidence"), (int, float)) else None
    exp = parse_expiry(raw)
    warnings = []
    if exp is None:
        warnings.append("Không đọc được HSD trên ảnh, hãy nhập bằng tay.")
    else:
        if nsx and parse_expiry(nsx) == exp:
            warnings.append("Ngày đọc được trùng ngày sản xuất, hãy kiểm tra lại.")
        if exp < today():
            warnings.append("Ngày đọc được đã qua: hàng hết hạn hoặc đọc sai.")
        elif shelf_life_days and exp > today() + timedelta(days=int(shelf_life_days * 1.5) + 1):
            warnings.append("Ngày đọc được xa hơn nhiều so với hạn chuẩn của mặt hàng.")
        if conf is not None and conf < LOW_CONFIDENCE:
            warnings.append("Ảnh không rõ, hãy đối chiếu với bao bì.")
    return {"expiry_date": exp.isoformat() if exp else None, "raw_text": raw, "nsx_text": nsx, "confidence": conf,
            "warnings": warnings}
