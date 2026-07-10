from app.ocr import parse_receipt_text


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
