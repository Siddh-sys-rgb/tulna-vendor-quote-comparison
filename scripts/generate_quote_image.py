from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[1]
FONT_CANDIDATES=["/System/Library/Fonts/Supplemental/Courier New.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
font=next((ImageFont.truetype(path,30) for path in FONT_CANDIDATES if Path(path).exists()),ImageFont.load_default(size=30))
image=Image.new("RGB",(1100,700),"white");draw=ImageDraw.Draw(image)
lines=["SUPPLIER QUOTE / SYNTHETIC FIXTURE", "Supplier: Desai Paper House", "Item: A4 paper 80 GSM", "Quantity: 10", "Unit: ream", "Unit price: 205.00", "Tax: 18", "Shipping: 0.00", "Delivery: 3", "Exclusions: none"]
for index,line in enumerate(lines): draw.text((40,35+index*58),line,font=font,fill="black")
image.save(ROOT/"demo/synthetic-quote.png")
print("Generated an authored fixture, not a screenshot")
