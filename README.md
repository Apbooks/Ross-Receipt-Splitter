# Ross Receipt Splitter

A mobile-friendly, self-hosted web app for splitting Ross employee-discount shopping receipts. Each receipt item stores its own printed discount, can be assigned by the last four digits of its tag, and receives a proportional share of the receipt's actual tax.

## Current features

- Create shopping sessions and participants
- Add multiple receipts per session
- Upload JPG, PNG, or WebP receipt photos from a phone
- Preprocess thermal receipt images with OpenCV
- Extract receipt text locally with Tesseract OCR
- Propose structured item rows and attach printed discount lines to the preceding item
- Review and correct every OCR field before importing
- Enter item identifiers, original prices, and exact printed discounts manually
- Assign items by full barcode or last four digits
- Manual assignment and undo controls for duplicate suffixes
- Allocate actual receipt tax across taxable assigned items
- Reconcile assigned totals against the amount charged
- Persistent SQLite storage and OCR drafts in the Docker data volume
- Responsive phone-friendly interface

The current OCR milestone handles one clear receipt photo or receipt section at a time. Guided overlapping multi-photo capture and automatic section merging remain on the roadmap.

## Start with Docker Compose

```bash
git clone https://github.com/Apbooks/Ross-Receipt-Splitter.git
cd Ross-Receipt-Splitter
docker compose up -d --build
```

Open `http://SERVER-IP:8088`.

Data, uploaded receipt images, processed images, and temporary OCR drafts are stored in the local `data` directory and mounted into the container.

When updating an existing installation:

```bash
git pull
docker compose up -d --build
```

## OCR workflow

1. Open a receipt in the app.
2. Choose **Scan receipt with OCR**.
3. Photograph or upload one clear receipt section.
4. Review the extracted text and proposed rows.
5. Correct the description, identifier, price, and item-specific discount.
6. Import the reviewed rows into the receipt.
7. Repeat for additional receipt sections.

OCR is intentionally review-first. Thermal paper, wrinkles, shadows, and long receipts can cause recognition errors, so imported financial values should always be verified against the physical receipt.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
uvicorn app.main:app --reload
```

Health check: `GET /health`

## Roadmap

1. Collect and analyze real Ross receipts and matching product tags
2. Improve Ross-specific item and discount parsing from real samples
3. Add guided overlapping multi-photo receipt capture and section deduplication
4. Add browser camera barcode scanning
5. Match by full UPC, suffix, price, and description confidence
6. Add exportable settlement reports and payment tracking
