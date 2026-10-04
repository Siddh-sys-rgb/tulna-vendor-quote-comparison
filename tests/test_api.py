import io,json
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image,ImageDraw,ImageFont
import app as module
from app import connect,create_app
from fixtures import DEMO_QUOTES
from domain import parse

def selection(client): return [{"id":q["id"],"revision":q["revision"]} for q in client.get("/api/quotes").json["quotes"][:2]]
def update_payload(client,ident=1):
    q=client.get("/api/quotes").json["quotes"][ident-1]
    return dict(parse(DEMO_QUOTES[ident-1]),revision=q["revision"])
def test_health_and_headers(client):
    r=client.get("/api/health");assert r.json["status"]=="ok"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert client.get("/").status_code==200
def test_cookie_name_and_host(client,app):
    assert app.config["SESSION_COOKIE_NAME"]=="tulna_session"
    assert client.get("/api/health",headers={"Host":"evil.example"}).status_code==400
@pytest.mark.parametrize("method,path",[("post","/api/quotes"),("put","/api/quotes/1"),("post","/api/comparisons")])
def test_csrf_required(client,method,path): assert getattr(client,method)(path,json={}).status_code==403
def test_cross_origin(client,headers):
    r=client.post("/api/quotes",json={"text":"hello"},headers=dict(headers,Origin="https://evil.example"));assert r.status_code==403
def test_draft_ingest_and_verification(client,headers):
    r=client.post("/api/quotes",json={"text":DEMO_QUOTES[0]},headers=headers)
    assert r.status_code==201 and not r.json["quote"]["verified"]
    ident=r.json["quote"]["id"];payload=dict(parse(DEMO_QUOTES[0]),revision=1)
    saved=client.put(f"/api/quotes/{ident}",json=payload,headers=headers)
    assert saved.json["quote"]["revision"]==2 and saved.json["quote"]["verified"]
    assert client.put(f"/api/quotes/{ident}",json=payload,headers=headers).status_code==409
@pytest.mark.parametrize("text",["",None,[],"x"*20001,"x\n"*1001])
def test_bad_transcript(client,headers,text): assert client.post("/api/quotes",json={"text":text},headers=headers).status_code==400
def test_missing_price_cannot_verify(client,headers):
    r=client.post("/api/quotes",json={"text":"Supplier: Mehta"},headers=headers)
    assert r.json["quote"]["unit_price"]==""
    payload=dict(r.json["quote"],revision=1)
    assert client.put('/api/quotes/'+str(r.json["quote"]["id"]),json=payload,headers=headers).status_code==400
@pytest.mark.parametrize("field,value",[("unit",[]),("supplier",{}),("shipping",[]),("exclusions",{}),("revision",True),("evidence_line",500)])
def test_edit_invalid_fields(client,headers,field,value):
    payload=update_payload(client);payload[field]=value
    assert client.put('/api/quotes/1',json=payload,headers=headers).status_code==400
@pytest.mark.parametrize("selected",[[],[{}],None,[{"id":1,"revision":1},{"id":1,"revision":1}],[{"id":[],"revision":1},{"id":2,"revision":1}]])
def test_bad_selection(client,headers,selected): assert client.post('/api/comparisons',json={"quotes":selected},headers=headers).status_code==400
def test_unknown_quote(client,headers):
    assert client.post('/api/comparisons',json={"quotes":[{"id":999,"revision":1},{"id":2,"revision":1}]},headers=headers).status_code==404
    assert client.put('/api/quotes/999',json=update_payload(client),headers=headers).status_code==404
def test_unverified_not_compared(client,headers):
    q=client.post('/api/quotes',json={"text":DEMO_QUOTES[0]},headers=headers).json['quote']
    assert client.post('/api/comparisons',json={"quotes":[{"id":q['id'],"revision":1},{"id":1,"revision":1}]},headers=headers).status_code==400
def test_immutable_snapshot_and_stale(client,headers):
    chosen=selection(client);r=client.post('/api/comparisons',json={"quotes":chosen},headers=headers)
    old=r.json['comparison']['rows'][0]['total_paise']
    payload=update_payload(client);payload['unit_price']='250.00'
    assert client.put('/api/quotes/1',json=payload,headers=headers).status_code==200
    assert client.post('/api/comparisons',json={"quotes":chosen},headers=headers).status_code==409
    assert client.get('/api/comparisons').json['comparisons'][0]['report']['rows'][0]['total_paise']==old
    assert client.get('/api/comparisons').json['comparisons'][0]['report']['quotes'][0]['text']==DEMO_QUOTES[0]
def test_invalid_image(client,headers):
    assert client.post('/api/quotes',data={'file':(io.BytesIO(b'fake png'),'x.png')},headers=headers).status_code==400
@pytest.mark.parametrize('size,fmt', [((20,20),'PNG'),((100,100),'GIF'),((4000,4000),'PNG')])
def test_image_constraints(client,headers,size,fmt):
    output=io.BytesIO();Image.new('RGB',size,'white').save(output,format=fmt);output.seek(0)
    assert client.post('/api/quotes',data={'file':(output,'x.png')},headers=headers).status_code==400
def test_ocr_upload_roundtrip(client,headers,monkeypatch):
    monkeypatch.setattr(module,'recognize',lambda raw:(DEMO_QUOTES[0],.97))
    output=io.BytesIO();Image.new('RGB',(200,200),'white').save(output,format='PNG');output.seek(0)
    r=client.post('/api/quotes',data={'file':(output,'../quote.png')},headers=headers)
    assert r.status_code==201 and r.json['quote']['source']=='rapidocr'
    name=r.json['quote']['image'];assert len(name)==36
    assert client.get('/uploads/'+name).status_code==200
    assert client.get('/uploads/not-a-generated-name.png').status_code==404
def test_request_limit(client,headers):
    assert client.post('/api/quotes',data=b'x'*(5*1024*1024+1),headers=headers,content_type='application/json').status_code==413
def test_literal_markup_is_data(client,headers):
    r=client.post('/api/quotes',json={'text':'Supplier: <script>alert(1)</script>\nItem: A4\nQuantity: 2\nUnit: sheet\nUnit price: 5'},headers=headers)
    assert r.json['quote']['supplier']=='<script>alert(1)</script>'
def test_empty_workspace(tmp_path): assert create_app(tmp_path,no_demo=True).test_client().get('/api/quotes').json['quotes']==[]
def test_concurrent_updates_have_one_winner(app):
    def save():
        client=app.test_client();headers={'X-CSRF-Token':client.get('/api/session').json['csrf_token']}
        return client.put('/api/quotes/1',json=dict(parse(DEMO_QUOTES[0]),revision=1),headers=headers).status_code
    with ThreadPoolExecutor(max_workers=2) as pool: codes=list(pool.map(lambda _:save(),range(2)))
    assert sorted(codes)==[200,409]
    with connect(app) as conn: assert conn.execute('SELECT revision FROM quotes WHERE id=1').fetchone()[0]==2
