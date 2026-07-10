from __future__ import annotations

import json
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from app.ocr import extract_text, parse_receipt_text

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
OCR_DIR = DATA_DIR / "ocr_drafts"
for directory in (DATA_DIR, UPLOAD_DIR, OCR_DIR):
    directory.mkdir(exist_ok=True)
DATABASE_URL = f"sqlite:///{DATA_DIR / 'ross_splitter.db'}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class ShoppingSession(Base):
    __tablename__ = "shopping_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    shopping_date: Mapped[date] = mapped_column(Date, default=date.today)
    participants: Mapped[list[Participant]] = relationship(back_populates="session", cascade="all, delete-orphan")
    receipts: Mapped[list[Receipt]] = relationship(back_populates="session", cascade="all, delete-orphan")

class Participant(Base):
    __tablename__ = "participants"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("shopping_sessions.id"))
    name: Mapped[str] = mapped_column(String(80))
    session: Mapped[ShoppingSession] = relationship(back_populates="participants")
    items: Mapped[list[ReceiptItem]] = relationship(back_populates="participant")

class Receipt(Base):
    __tablename__ = "receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("shopping_sessions.id"))
    store_name: Mapped[str] = mapped_column(String(120), default="Ross")
    tax_cents: Mapped[int] = mapped_column(Integer, default=0)
    charged_total_cents: Mapped[int] = mapped_column(Integer, default=0)
    session: Mapped[ShoppingSession] = relationship(back_populates="receipts")
    items: Mapped[list[ReceiptItem]] = relationship(back_populates="receipt", cascade="all, delete-orphan")

class ReceiptItem(Base):
    __tablename__ = "receipt_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"))
    participant_id: Mapped[int | None] = mapped_column(ForeignKey("participants.id"), nullable=True)
    description: Mapped[str] = mapped_column(String(160), default="Item")
    identifier: Mapped[str] = mapped_column(String(40))
    original_price_cents: Mapped[int] = mapped_column(Integer)
    discount_cents: Mapped[int] = mapped_column(Integer, default=0)
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    receipt: Mapped[Receipt] = relationship(back_populates="items")
    participant: Mapped[Participant | None] = relationship(back_populates="items")

    @property
    def last_four(self) -> str:
        digits = "".join(c for c in self.identifier if c.isdigit())
        return digits[-4:] if digits else self.identifier[-4:]

    @property
    def net_cents(self) -> int:
        return max(self.original_price_cents - self.discount_cents, 0)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def parse_money(value: str) -> int:
    cleaned = value.replace("$", "").replace(",", "").strip()
    return int((Decimal(cleaned or "0") * 100).quantize(Decimal("1")))

def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"

def allocate_tax(receipt: Receipt) -> dict[int, int]:
    assigned = [item for item in receipt.items if item.participant_id and item.taxable]
    taxable_total = sum(item.net_cents for item in assigned)
    if receipt.tax_cents <= 0 or taxable_total <= 0:
        return {}
    exact = [(item.id, Decimal(receipt.tax_cents) * Decimal(item.net_cents) / Decimal(taxable_total)) for item in assigned]
    allocated = {item_id: int(share.quantize(Decimal("1"), rounding=ROUND_DOWN)) for item_id, share in exact}
    remainder = receipt.tax_cents - sum(allocated.values())
    for item_id, _ in sorted(exact, key=lambda pair: pair[1] - int(pair[1]), reverse=True)[:remainder]:
        allocated[item_id] += 1
    return allocated

def receipt_summary(receipt: Receipt) -> dict:
    tax_by_item = allocate_tax(receipt)
    participant_totals = {}
    for participant in receipt.session.participants:
        items = [item for item in receipt.items if item.participant_id == participant.id]
        merchandise = sum(item.net_cents for item in items)
        tax = sum(tax_by_item.get(item.id, 0) for item in items)
        participant_totals[participant.id] = {"name": participant.name, "item_count": len(items), "merchandise_cents": merchandise, "tax_cents": tax, "total_cents": merchandise + tax}
    assigned_total = sum(value["total_cents"] for value in participant_totals.values())
    expected_total = receipt.charged_total_cents or sum(item.net_cents for item in receipt.items) + receipt.tax_cents
    return {"participant_totals": participant_totals, "assigned_total_cents": assigned_total, "expected_total_cents": expected_total, "difference_cents": expected_total - assigned_total, "unassigned_count": sum(1 for item in receipt.items if item.participant_id is None)}

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield

app = FastAPI(title="Ross Receipt Splitter", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["money"] = money

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    sessions = db.scalars(select(ShoppingSession).order_by(ShoppingSession.id.desc())).all()
    return templates.TemplateResponse(request, "index.html", {"sessions": sessions})

@app.post("/sessions")
def create_session(name: str = Form(...), shopping_date: date = Form(default=date.today()), db: Session = Depends(get_db)):
    session = ShoppingSession(name=name.strip(), shopping_date=shopping_date)
    db.add(session); db.commit()
    return RedirectResponse(f"/sessions/{session.id}", status_code=303)

@app.get("/sessions/{session_id}", response_class=HTMLResponse)
def session_page(session_id: int, request: Request, db: Session = Depends(get_db)):
    shopping_session = db.get(ShoppingSession, session_id)
    if not shopping_session: raise HTTPException(404, "Shopping session not found")
    return templates.TemplateResponse(request, "session.html", {"shopping_session": shopping_session})

@app.post("/sessions/{session_id}/participants")
def add_participant(session_id: int, name: str = Form(...), db: Session = Depends(get_db)):
    if not db.get(ShoppingSession, session_id): raise HTTPException(404, "Shopping session not found")
    db.add(Participant(session_id=session_id, name=name.strip())); db.commit()
    return RedirectResponse(f"/sessions/{session_id}", status_code=303)

@app.post("/sessions/{session_id}/receipts")
def add_receipt(session_id: int, store_name: str = Form("Ross"), tax: str = Form("0"), charged_total: str = Form("0"), db: Session = Depends(get_db)):
    if not db.get(ShoppingSession, session_id): raise HTTPException(404, "Shopping session not found")
    receipt = Receipt(session_id=session_id, store_name=store_name.strip() or "Ross", tax_cents=parse_money(tax), charged_total_cents=parse_money(charged_total))
    db.add(receipt); db.commit()
    return RedirectResponse(f"/receipts/{receipt.id}", status_code=303)

@app.get("/receipts/{receipt_id}", response_class=HTMLResponse)
def receipt_page(receipt_id: int, request: Request, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id)
    if not receipt: raise HTTPException(404, "Receipt not found")
    return templates.TemplateResponse(request, "receipt.html", {"receipt": receipt, "summary": receipt_summary(receipt)})

@app.post("/receipts/{receipt_id}/ocr")
def upload_receipt_ocr(receipt_id: int, receipt_image: UploadFile = File(...), db: Session = Depends(get_db)):
    if not db.get(Receipt, receipt_id): raise HTTPException(404, "Receipt not found")
    if receipt_image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(400, "Upload a JPG, PNG, or WebP image.")
    draft_id = uuid.uuid4().hex
    suffix = Path(receipt_image.filename or "receipt.jpg").suffix.lower() or ".jpg"
    original = UPLOAD_DIR / f"{draft_id}{suffix}"
    processed = UPLOAD_DIR / f"{draft_id}-processed.png"
    with original.open("wb") as destination:
        shutil.copyfileobj(receipt_image.file, destination)
    raw_text = extract_text(original, processed)
    draft = {"id": draft_id, "receipt_id": receipt_id, "raw_text": raw_text, "items": parse_receipt_text(raw_text), "original": original.name, "processed": processed.name}
    (OCR_DIR / f"{draft_id}.json").write_text(json.dumps(draft, indent=2), encoding="utf-8")
    return RedirectResponse(f"/receipts/{receipt_id}/ocr/{draft_id}", status_code=303)

@app.get("/receipts/{receipt_id}/ocr/{draft_id}", response_class=HTMLResponse)
def review_receipt_ocr(receipt_id: int, draft_id: str, request: Request, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id); path = OCR_DIR / f"{draft_id}.json"
    if not receipt or not path.exists(): raise HTTPException(404, "OCR draft not found")
    draft = json.loads(path.read_text(encoding="utf-8"))
    if draft["receipt_id"] != receipt_id: raise HTTPException(400, "OCR draft does not belong to this receipt")
    return templates.TemplateResponse(request, "receipt_ocr_review.html", {"receipt": receipt, "draft": draft})

@app.post("/receipts/{receipt_id}/ocr/{draft_id}/confirm")
async def confirm_receipt_ocr(receipt_id: int, draft_id: str, request: Request, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id); path = OCR_DIR / f"{draft_id}.json"
    if not receipt or not path.exists(): raise HTTPException(404, "OCR draft not found")
    form = await request.form(); count = int(form.get("count", 0))
    for index in range(count):
        identifier = str(form.get(f"identifier_{index}", "")).strip()
        price = str(form.get(f"price_{index}", "")).strip()
        if not identifier or not price: continue
        db.add(ReceiptItem(receipt_id=receipt_id, description=str(form.get(f"description_{index}", "Receipt item")).strip() or "Receipt item", identifier=identifier, original_price_cents=parse_money(price), discount_cents=parse_money(str(form.get(f"discount_{index}", "0"))), taxable=f"taxable_{index}" in form))
    db.commit(); path.unlink(missing_ok=True)
    return RedirectResponse(f"/receipts/{receipt_id}?ocr_imported=1", status_code=303)

@app.post("/receipts/{receipt_id}/items")
def add_item(receipt_id: int, description: str = Form("Item"), identifier: str = Form(...), original_price: str = Form(...), discount: str = Form("0"), taxable: bool = Form(False), db: Session = Depends(get_db)):
    if not db.get(Receipt, receipt_id): raise HTTPException(404, "Receipt not found")
    db.add(ReceiptItem(receipt_id=receipt_id, description=description.strip() or "Item", identifier=identifier.strip(), original_price_cents=parse_money(original_price), discount_cents=parse_money(discount), taxable=taxable)); db.commit()
    return RedirectResponse(f"/receipts/{receipt_id}", status_code=303)

@app.post("/receipts/{receipt_id}/assign")
def assign_item(receipt_id: int, participant_id: int = Form(...), scanned_code: str = Form(...), db: Session = Depends(get_db)):
    receipt, participant = db.get(Receipt, receipt_id), db.get(Participant, participant_id)
    if not receipt or not participant or participant.session_id != receipt.session_id: raise HTTPException(400, "Invalid receipt or participant")
    digits = "".join(c for c in scanned_code if c.isdigit()); suffix = digits[-4:] if digits else scanned_code.strip()[-4:]
    candidates = [item for item in receipt.items if item.participant_id is None and item.last_four == suffix]
    if len(candidates) == 1:
        candidates[0].participant_id = participant_id; db.commit()
        return RedirectResponse(f"/receipts/{receipt_id}?assigned=1", status_code=303)
    error = "no-match" if not candidates else "multiple"
    return RedirectResponse(f"/receipts/{receipt_id}?error={error}&code={suffix}", status_code=303)

@app.post("/items/{item_id}/assign")
def assign_specific_item(item_id: int, participant_id: int = Form(...), db: Session = Depends(get_db)):
    item, participant = db.get(ReceiptItem, item_id), db.get(Participant, participant_id)
    if not item or not participant or participant.session_id != item.receipt.session_id: raise HTTPException(400, "Invalid assignment")
    item.participant_id = participant_id; db.commit()
    return RedirectResponse(f"/receipts/{item.receipt_id}", status_code=303)

@app.post("/items/{item_id}/unassign")
def unassign_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(ReceiptItem, item_id)
    if not item: raise HTTPException(404, "Item not found")
    item.participant_id = None; receipt_id = item.receipt_id; db.commit()
    return RedirectResponse(f"/receipts/{receipt_id}", status_code=303)
