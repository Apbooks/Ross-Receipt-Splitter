from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import pytesseract
from PIL import Image, ImageOps

MONEY_RE = re.compile(r"(?P<amount>-?\$?\d+[.,]\d{2})\s*-?$")
DIGITS_RE = re.compile(r"\d{4,}")
DISCOUNT_WORDS = ("discount", "disc", "employee", "emp disc", "associate")
TOTAL_WORDS = ("total", "amount due", "balance due")
TAX_WORDS = ("tax", "sales tax")


@dataclass
class ParsedItem:
    description: str
    identifier: str
    original_price: str
    discount: str = "0.00"
    final_price: str = "0.00"
    taxable: bool = True
    confidence: str = "review"

    def to_dict(self) -> dict:
        return asdict(self)


def preprocess_image(source: Path, output: Path) -> None:
    try:
        with Image.open(source) as opened:
            corrected = ImageOps.exif_transpose(opened).convert("RGB")
            if corrected.width > 2200:
                height = round(corrected.height * 2200 / corrected.width)
                corrected = corrected.resize((2200, height))
            corrected.save(source, format="JPEG", quality=94)
    except Exception as exc:
        raise ValueError(f"The uploaded image could not be prepared: {exc}") from exc

    image = cv2.imread(str(source))
    if image is None:
        raise ValueError("The uploaded image could not be read.")
    _, width = image.shape[:2]
    if width < 1600:
        scale = 1600 / width
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, h=10)
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    thresholded = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 13
    )
    if not cv2.imwrite(str(output), thresholded):
        raise ValueError("The processed receipt image could not be saved.")


def extract_text(image_path: Path, processed_path: Path) -> str:
    preprocess_image(image_path, processed_path)
    try:
        return pytesseract.image_to_string(processed_path, config="--oem 3 --psm 6", timeout=75)
    except RuntimeError as exc:
        raise ValueError("Receipt OCR timed out. Try a closer photo or scan the receipt in sections.") from exc
    except Exception as exc:
        raise ValueError(f"Receipt OCR failed: {exc}") from exc


def _money(line: str) -> str | None:
    match = MONEY_RE.search(line.replace("O", "0"))
    if not match:
        return None
    return match.group("amount").replace("$", "").replace(",", ".").replace("-", "")


def parse_receipt_text(raw_text: str) -> list[dict]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines() if line.strip()]
    items: list[ParsedItem] = []
    pending_description = ""
    pending_identifier = ""

    for line in lines:
        lower = line.lower()
        amount = _money(line)
        digits = DIGITS_RE.findall(line)
        identifier = max(digits, key=len) if digits else ""

        if lower.startswith("original price") and amount and items:
            items[-1].original_price = amount
            expected = round(float(items[-1].original_price) - float(items[-1].discount), 2)
            items[-1].confidence = "verified" if abs(expected - float(items[-1].final_price)) < 0.011 else "check"
            continue

        if any(word in lower for word in DISCOUNT_WORDS) and amount and items:
            items[-1].discount = amount
            continue

        if any(word in lower for word in TOTAL_WORDS + TAX_WORDS):
            continue

        if identifier and amount:
            description = MONEY_RE.sub("", line).replace(identifier, "").strip(" -") or "Receipt item"
            items.append(ParsedItem(description, identifier, amount, final_price=amount, confidence="review"))
            pending_description = ""
            pending_identifier = ""
            continue

        if identifier and not amount:
            pending_identifier = identifier
            text_without_id = line.replace(identifier, "").strip(" -")
            if text_without_id:
                pending_description = text_without_id
            continue

        if amount and pending_identifier:
            description = MONEY_RE.sub("", line).strip(" -") or pending_description or "Receipt item"
            items.append(ParsedItem(description, pending_identifier, amount, final_price=amount, confidence="review"))
            pending_description = ""
            pending_identifier = ""
            continue

        if len(line) > 3 and not lower.startswith(("subtotal", "tax", "total", "change", "visa", "mastercard", "original price")):
            pending_description = line

    return [item.to_dict() for item in items]


def parse_receipt_document(raw_text: str) -> dict:
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines() if line.strip()]
    tax = "0.00"
    total = "0.00"
    for line in lines:
        lower = line.lower()
        amount = _money(line)
        if not amount:
            continue
        if any(word in lower for word in TAX_WORDS):
            tax = amount
        if any(word in lower for word in TOTAL_WORDS) and "subtotal" not in lower:
            total = amount
    return {"store_name": "Ross", "tax": tax, "total": total, "items": parse_receipt_text(raw_text)}
