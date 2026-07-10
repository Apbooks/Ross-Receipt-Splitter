# Ross Receipt Splitter

A mobile-friendly, self-hosted web app for splitting Ross employee-discount shopping receipts. Each receipt item stores its own printed discount, can be assigned by the last four digits of its tag, and receives a proportional share of the receipt's actual tax.

## Current MVP features

- Create shopping sessions and participants
- Add multiple receipts per session
- Enter item identifiers, original prices, and exact printed discounts
- Assign items by full barcode or last four digits
- Manual assignment and undo controls for duplicate suffixes
- Allocate actual receipt tax across taxable assigned items
- Reconcile assigned totals against the amount charged
- Persistent SQLite storage
- Responsive phone-friendly interface

Receipt OCR and in-browser camera barcode scanning are planned next. The current assignment field works with manual entry or a Bluetooth barcode scanner.

## Start with Docker Compose

```bash
git clone https://github.com/Apbooks/Ross-Receipt-Splitter.git
cd Ross-Receipt-Splitter
docker compose up -d --build
```

Open `http://SERVER-IP:8088`.

Data is stored in the local `data` directory and mounted into the container.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Health check: `GET /health`

## Roadmap

1. Analyze real Ross receipts and product tags
2. Add guided multi-photo receipt capture
3. Add OCR preprocessing and receipt parsing
4. Add browser camera barcode scanning
5. Match by UPC, suffix, price, and description
6. Add exportable settlement reports and payment tracking
