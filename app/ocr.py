from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import pytesseract

MONEY_RE = re.compile(r"(?P<amount>-?\$?\d+[.,]\d{2})\s*-?$")
DIGITS_RE = re.compile(r"\d{4,}")
DISCOUNT_WORDS = ("discount", "disc", "employee", "emp disc", "associate")


@dataclass
class ParsedItem:
    description: str
    identifier: str
    original_price: str
    discount: str = "0.00"
    taxable: bool = True
    confidence: str = "review"

    def to_dict(self) -> dict:
        return asdict(self)


def preprocess_image(source: Path, output: Path) -> None:
    image = cv2.imread(str(source))
    if image is None:
        raise ValueError("The uploaded image could not be read.")
    _, width = image.shape[:2]
    if width < 1600:
        scale = 1600 / width
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, h=12)
    thresholded = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 13
    )
    cv2.imwrite(str(output), thresholded)


def extract_text(image_path: Path, processed_path: Path) -> str:
    preprocess_image(image_path, processed_path)
    return pytesseract.image_to_string(processed_path, config="--oem 3 --psm 6")


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

        if any(word in lower for word in DISCOUNT_WORDS) and amount and items:
            items[-1].discount = amount
            items[-1].confidence = "parsed"
            continue

        if identifier and not amount:
            pending_identifier = identifier
            text_without_id = line.replace(identifier, "").strip(" -")
            if text_without_id:
                pending_description = text_without_id
            continue

        if amount:
            description = MONEY_RE.sub("", line).strip(" -")
            if identifier:
                description = description.replace(identifier, "").strip(" -")
            if not description:
                description = pending_description or "Receipt item"
            item_identifier = identifier or pending_identifier
            if item_identifier:
                items.append(ParsedItem(description, item_identifier, amount, confidence="parsed"))
                pending_description = ""
                pending_identifier = ""
            continue

        if len(line) > 3 and not lower.startswith(("subtotal", "tax", "total", "change", "visa", "mastercard")):
            pending_description = line

    return [item.to_dict() for item in items]
