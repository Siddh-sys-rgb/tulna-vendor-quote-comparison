"""Actual bundled model inference on a clean authored image, not a benchmark."""
from pathlib import Path
from app import recognize
from domain import parse

def test_real_ocr_reads_authored_quote(client,headers):
    image=Path(__file__).resolve().parents[1]/"demo/synthetic-quote.png"
    text,score=recognize(image.read_bytes())
    fields=parse(text)
    assert "Desai" in text and fields["quantity"]=="10" and fields["unit_price"]=="205.00"
    assert 0 < score <= 1
    with image.open("rb") as handle:
        response=client.post("/api/quotes",data={"file":(handle,"quote.png")},headers=headers)
    assert response.status_code==201
    assert response.json["quote"]["source"]=="rapidocr" and not response.json["quote"]["verified"]
