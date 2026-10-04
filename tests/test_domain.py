import pytest
from domain import money,validate,parse,evaluate
from fixtures import DEMO_QUOTES

def base(): return parse(DEMO_QUOTES[0])
def test_exact_money(): assert money("0.29")==29
@pytest.mark.parametrize("value",["NaN","Infinity","-1","0.001",{},[],None,True,"10000001"])
def test_invalid_money(value):
    with pytest.raises(ValueError): money(value)
@pytest.mark.parametrize("field,value",[("supplier",{}),("item",[]),("unit",[]),("unit","box"),("quantity",True),("quantity","1.5"),("quantity",0),("tax_percent",{}),("tax_percent","NaN"),("tax_percent",101),("shipping",[]),("delivery_days",False),("evidence_line",0),("exclusions",{})])
def test_validate_types_and_bounds(field,value):
    data=base();data[field]=value
    with pytest.raises(ValueError): validate(data)
def test_missing_fields_not_invented():
    result=parse("Shipping: 10.00")
    assert result["supplier"]==result["item"]==result["quantity"]==result["unit_price"]==""
    with pytest.raises(ValueError): validate(result)
def test_partial_costs_do_not_rank():
    quotes=[dict(validate(parse(t)),id=i) for i,t in enumerate(DEMO_QUOTES)]
    report=evaluate(quotes)
    assert report["winner_id"] is None
    assert report["rows"][2]["total_paise"] is None
    assert "Shipping missing" in report["rows"][2]["flags"]
def test_ream_sheet_normalization():
    quotes=[dict(validate(parse(t)),id=i) for i,t in enumerate(DEMO_QUOTES[:2])]
    report=evaluate(quotes)
    assert report["comparable"] and report["rows"][0]["normalized_quantity"]==5000
    assert report["rows"][0]["total_paise"]==259800
    assert report["winner_id"]==1
@pytest.mark.parametrize("field,value",[("unit","each"),("item","A3 paper")])
def test_incomparable(field,value):
    a=validate(base());b=dict(a);b[field]=value
    assert evaluate([dict(a,id=1),dict(b,id=2)])["winner_id"] is None
def test_different_quantity_flag():
    a=validate(base());b=dict(a,quantity=20)
    assert any("quantities differ" in flag for flag in evaluate([dict(a,id=1),dict(b,id=2)])["rows"][0]["flags"])
def test_tax_half_up():
    data=base();data.update(quantity=1,unit_price="0.05",tax_percent="10",shipping="0")
    assert evaluate([dict(validate(data),id=1)])["rows"][0]["tax_paise"]==1
