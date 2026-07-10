from app.ocr import parse_receipt_document, parse_receipt_text


def test_discount_line_attaches_to_previous_item():
    raw = """
    LADIES TOP 123456789012 14.99
    EMPLOYEE DISCOUNT -3.00
    SHOES 998877665544 29.99
    ASSOC DISC 7.50-
    """
    items = parse_receipt_text(raw)
    assert len(items) == 2
    assert items[0]["identifier"] == "123456789012"
    assert items[0]["original_price"] == "14.99"
    assert items[0]["discount"] == "3.00"
    assert items[1]["identifier"] == "998877665544"
    assert items[1]["discount"] == "7.50"


def test_identifier_on_separate_line_is_grouped():
    raw = """
    MENS SHIRT
    400123456789
    19.99
    EMP DISC 4.00-
    """
    items = parse_receipt_text(raw)
    assert len(items) == 1
    assert items[0]["description"] == "MENS SHIRT"
    assert items[0]["identifier"] == "400123456789"
    assert items[0]["discount"] == "4.00"


def test_ross_three_line_item_uses_original_discount_and_final_price():
    raw = """
    400297705808 X NIKE WHT (L) U N $10.19R
    Associate Discount 40% -$6.80
    Original Price: $16.99
    """
    item = parse_receipt_text(raw)[0]
    assert item["identifier"] == "400297705808"
    assert item["final_price"] == "10.19"
    assert item["discount"] == "6.80"
    assert item["original_price"] == "16.99"
    assert item["confidence"] == "verified"


def test_document_parses_tax_and_total():
    raw = """
    SUBTOTAL $100.00
    SALES TAX $6.00
    TOTAL $106.00
    """
    document = parse_receipt_document(raw)
    assert document["tax"] == "6.00"
    assert document["total"] == "106.00"
