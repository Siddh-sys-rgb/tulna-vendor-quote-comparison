"""Human-reviewed quote normalization; monetary calculations use integer paise."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
UNITS = {"sheet": ("sheet", 1), "ream": ("sheet", 500), "each": ("each", 1)}

def money(value, optional=False):
    if optional and value in (None, ""): return None
    try: amount = Decimal(str(value))
    except (InvalidOperation, ValueError): raise ValueError("Enter a valid INR amount")
    if not amount.is_finite() or amount < 0 or amount > 10000000 or amount.as_tuple().exponent < -2:
        raise ValueError("INR amounts need 0–2 decimal places and must be within 1 crore")
    return int(amount * 100)

def integer(value, field, maximum=1000000):
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)): raise ValueError(field + " must be a whole number")
    number=int(value)
    if not 1 <= number <= maximum: raise ValueError(field + " is out of range")
    return number

def validate(data):
    if not isinstance(data, dict): raise ValueError("Quote must be an object")
    supplier=str(data.get("supplier", "")).strip()
    item=str(data.get("item", "")).strip()
    if not supplier or len(supplier)>100 or not item or len(item)>100: raise ValueError("Supplier and item need 1–100 characters")
    unit=data.get("unit", "sheet")
    if unit not in UNITS: raise ValueError("Unit must be sheet, ream or each")
    quantity=integer(data.get("quantity"), "Quantity")
    line=integer(data.get("evidence_line"), "Evidence line", 1000)
    tax=data.get("tax_percent")
    if tax in (None, ""): tax=None
    else:
        try: tax=Decimal(str(tax))
        except InvalidOperation: raise ValueError("Invalid tax percent")
        if not tax.is_finite() or tax < 0 or tax > 100 or tax.as_tuple().exponent < -2: raise ValueError("Tax must be 0–100 with at most 2 decimals")
        tax=str(tax)
    delivery=data.get("delivery_days")
    if delivery in (None, ""): delivery=None
    else: delivery=integer(delivery,"Delivery days",365)
    exclusions=str(data.get("exclusions", "")).strip()
    if len(exclusions)>500: raise ValueError("Exclusions exceed 500 characters")
    return dict(supplier=supplier,item=item,unit=unit,quantity=quantity,unit_price_paise=money(data.get("unit_price")),shipping_paise=money(data.get("shipping"), True),tax_percent=tax,delivery_days=delivery,exclusions=exclusions,evidence_line=line)

def parse(text):
    lines=text.splitlines()
    fields={}
    aliases={"supplier":"supplier","item":"item","quantity":"quantity","unit":"unit","unit price":"unit_price","shipping":"shipping","tax":"tax_percent","delivery":"delivery_days","exclusions":"exclusions"}
    evidence=1
    for index,line in enumerate(lines,1):
        parts=line.split(":",1)
        if len(parts)==2 and parts[0].strip().lower() in aliases:
            key=aliases[parts[0].strip().lower()]
            fields[key]=parts[1].strip().replace("₹", "").replace("INR", "").strip()
            if key=="unit_price": evidence=index
    fields.setdefault("supplier","New supplier");fields.setdefault("item","A4 paper 80 GSM");fields.setdefault("quantity","1");fields.setdefault("unit","sheet");fields.setdefault("unit_price","0");fields["evidence_line"]=evidence
    return fields

def evaluate(quotes):
    rows=[]
    keys={(q["item"].strip().casefold(),UNITS[q["unit"]][0]) for q in quotes}
    for q in quotes:
        group,factor=UNITS[q["unit"]]
        base=q["quantity"]*q["unit_price_paise"]
        tax=None if q["tax_percent"] is None else int((Decimal(base)*Decimal(q["tax_percent"])/100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        flags=[]
        if tax is None: flags.append("Tax missing")
        if q["shipping_paise"] is None: flags.append("Shipping missing")
        if q["delivery_days"] is None: flags.append("Delivery not confirmed")
        if q["exclusions"]: flags.append("Supplier exclusions: " + q["exclusions"])
        total=None if tax is None or q["shipping_paise"] is None else base+tax+q["shipping_paise"]
        normalized=q["quantity"]*factor
        landed=None if total is None else str((Decimal(total)/100/normalized).quantize(Decimal("0.0001"),rounding=ROUND_HALF_UP))
        rows.append(dict(id=q["id"],supplier=q["supplier"],subtotal_paise=base,tax_paise=tax,total_paise=total,normalized_quantity=normalized,normalized_unit=group,landed_unit_inr=landed,flags=flags))
    comparable=len(keys)==1
    candidates=[r for r in rows if r["total_paise"] is not None]
    winner=min(candidates,key=lambda r:Decimal(r["landed_unit_inr"]))["id"] if comparable and len(candidates)==len(rows) and rows else None
    return dict(rows=rows,comparable=comparable,winner_id=winner,notes=["Compare quantities and exclusions before choosing a vendor."] + ([] if comparable else ["Different items or unit families cannot be ranked."]))
