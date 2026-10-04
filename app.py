import argparse, json, os, secrets, sqlite3
from pathlib import Path
from flask import Flask, jsonify, request, render_template, session, send_from_directory

def connect(app):
    conn=sqlite3.connect(app.config["DATABASE"],timeout=10)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn

def setup(app,data_dir):
    folder=Path(data_dir);folder.mkdir(parents=True,exist_ok=True)
    keyfile=folder/".session-key"
    try:
        descriptor=os.open(keyfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,"w") as handle: handle.write(secrets.token_hex(32))
    except FileExistsError: pass
    app.secret_key=keyfile.read_text().strip()
    app.config.update(DATABASE=str(folder/"app.sqlite"),DATA_DIR=str(folder),MAX_CONTENT_LENGTH=5*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Strict",TRUSTED_HOSTS=["localhost","127.0.0.1"])
    @app.before_request
    def protect():
        if request.method in {"POST","PUT","DELETE","PATCH"}:
            expected=session.get("csrf")
            if not expected or not secrets.compare_digest(str(request.headers.get("X-CSRF-Token","")),expected): return jsonify(error="CSRF token missing or invalid"),403
            origin=request.headers.get("Origin")
            if origin and origin!=request.host_url.rstrip("/"): return jsonify(error="Cross-origin writes are blocked"),403
    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Content-Security-Policy"]="default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        response.headers["Cache-Control"]="no-store"
        return response
    @app.errorhandler(413)
    def too_large(error): return jsonify(error="Request exceeds 5 MB"),413
    @app.errorhandler(ValueError)
    def invalid(error): return jsonify(error=str(error)),400
    @app.errorhandler(sqlite3.OperationalError)
    def database_busy(error): return jsonify(error="Database unavailable; retry the action"),503
    @app.get("/api/session")
    def token():
        session.setdefault("csrf",secrets.token_hex(24))
        return jsonify(csrf_token=session["csrf"])
    @app.get("/")
    def index(): return render_template("index.html")

def json_object():
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict): raise ValueError("Expected a JSON object")
    return payload

def revision(value):
    if isinstance(value,bool) or not isinstance(value,int) or value<1: raise ValueError("Revision must be a positive integer")
    return value

from domain import validate,parse,evaluate
from fixtures import DEMO_QUOTES
import io, threading
from PIL import Image, UnidentifiedImageError
_ocr_engine=None
_ocr_lock=threading.Lock()

def recognize(data):
    global _ocr_engine
    try:
        with Image.open(io.BytesIO(data)) as picture:
            if picture.format not in {"PNG","JPEG"}: raise ValueError("Only actual PNG and JPEG images are accepted")
            if picture.width*picture.height>12_000_000 or min(picture.size)<40: raise ValueError("Image must contain 40–12000000 pixels per supported dimensions")
            picture.load()
            rgb=picture.convert("RGB")
    except (UnidentifiedImageError,Image.DecompressionBombError,OSError): raise ValueError("Invalid or unsafe image")
    import numpy as np
    with _ocr_lock:
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
        rows,_=_ocr_engine(np.asarray(rgb))
    if not rows: raise ValueError("No readable text found; paste the quote text instead")
    return "\n".join(row[1] for row in rows),sum(float(row[2]) for row in rows)/len(rows)

def quote(row):
    data=json.loads(row["fields"])
    return dict(data,id=row["id"],revision=row["revision"],verified=bool(row["verified"]),source=row["source"],text=row["text"],image=row["image"],recognition_score=row["score"])

def create_app(data_dir=None,no_demo=False):
    app=Flask(__name__);setup(app,data_dir or Path(__file__).parent/"data-local");app.config["SESSION_COOKIE_NAME"]="tulna_session"
    with connect(app) as conn:
        conn.executescript("CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY,fields TEXT NOT NULL,text TEXT NOT NULL,source TEXT NOT NULL,image TEXT,score REAL,verified INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 1); CREATE TABLE IF NOT EXISTS comparisons(id INTEGER PRIMARY KEY,payload TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);")
        if not no_demo and conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]==0:
            for transcript in DEMO_QUOTES:
                fields=validate(parse(transcript))
                conn.execute("INSERT INTO quotes(fields,text,source,verified) VALUES(?,?,?,1)",(json.dumps(fields),transcript,"synthetic-transcript"))
    @app.get("/api/health")
    def health(): return jsonify(status="ok",app="Tulna",model="local RapidOCR; deterministic comparison",demo="synthetic")
    @app.get("/api/quotes")
    def list_quotes():
        with connect(app) as conn: rows=[quote(row) for row in conn.execute("SELECT * FROM quotes ORDER BY id")]
        return jsonify(quotes=rows)
    @app.post("/api/quotes")
    def ingest():
        image_name=None;score=None
        if request.files:
            uploaded=request.files.get("file")
            if uploaded is None: raise ValueError("Upload field must be file")
            raw=uploaded.read(5*1024*1024+1)
            if len(raw)>5*1024*1024: raise ValueError("Image exceeds 5 MB")
            text,score=recognize(raw);source="rapidocr"
            image_name=secrets.token_hex(16)+".png"
            folder=Path(app.config["DATA_DIR"])/"uploads";folder.mkdir(exist_ok=True)
            with Image.open(io.BytesIO(raw)) as picture: picture.convert("RGB").save(folder/image_name)
        else:
            data=json_object();text=data.get("text")
            if not isinstance(text,str) or not text.strip() or len(text)>20000 or len(text.splitlines())>1000: raise ValueError("Text needs 1–20000 characters and at most 1000 lines")
            source="pasted-text"
        fields=parse(text)
        # Draft fields are deliberately editable and may be incomplete until verification.
        with connect(app) as conn:
            result=conn.execute("INSERT INTO quotes(fields,text,source,image,score) VALUES(?,?,?,?,?)",(json.dumps(fields),text,source,image_name,score))
            row=conn.execute("SELECT * FROM quotes WHERE id=?",(result.lastrowid,)).fetchone()
        return jsonify(quote=quote(row)),201
    @app.put("/api/quotes/<int:quote_id>")
    def update(quote_id):
        payload=json_object();rev=revision(payload.get("revision"));fields=validate(payload)
        if fields["evidence_line"]>1000: raise ValueError("Invalid evidence line")
        with connect(app) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT * FROM quotes WHERE id=?",(quote_id,)).fetchone()
            if row is None: return jsonify(error="Quote not found"),404
            if row["revision"]!=rev: return jsonify(error="Quote changed; reload before saving"),409
            if fields["evidence_line"]>len(row["text"].splitlines()): raise ValueError("Evidence line must exist in the source")
            conn.execute("UPDATE quotes SET fields=?,verified=1,revision=revision+1 WHERE id=?",(json.dumps(fields),quote_id))
            updated=conn.execute("SELECT * FROM quotes WHERE id=?",(quote_id,)).fetchone()
        return jsonify(quote=quote(updated))
    @app.post("/api/comparisons")
    def compare():
        data=json_object();selected=data.get("quotes")
        if not isinstance(selected,list) or not 2<=len(selected)<=8 or any(not isinstance(v,dict) for v in selected): raise ValueError("Select 2–8 quote revisions")
        ids=[v.get("id") for v in selected]
        if any(isinstance(i,bool) or not isinstance(i,int) for i in ids) or len(set(ids))!=len(ids): raise ValueError("Quote IDs must be unique integers")
        with connect(app) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows=[]
            for selected_quote in selected:
                row=conn.execute("SELECT * FROM quotes WHERE id=?",(selected_quote["id"],)).fetchone()
                if row is None: return jsonify(error="Selected quote missing"),404
                if row["revision"]!=revision(selected_quote.get("revision")): return jsonify(error="A quote changed; reload the comparison"),409
                if not row["verified"]: raise ValueError("Human verification required for every quote")
                rows.append(quote(row))
            report=evaluate(rows);report["quotes"]=rows
            result=conn.execute("INSERT INTO comparisons(payload) VALUES(?)",(json.dumps(report),));report["id"]=result.lastrowid
        return jsonify(comparison=report),201
    @app.get("/api/comparisons")
    def history():
        with connect(app) as conn: rows=[dict(id=r["id"],created_at=r["created_at"],report=json.loads(r["payload"])) for r in conn.execute("SELECT * FROM comparisons ORDER BY id DESC LIMIT 25")]
        return jsonify(comparisons=rows)
    @app.get("/uploads/<name>")
    def image(name):
        if not name.endswith(".png") or len(name)!=36 or any(c not in "0123456789abcdef" for c in name[:-4]): return jsonify(error="Not found"),404
        return send_from_directory(Path(app.config["DATA_DIR"])/"uploads",name)
    return app

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--port",type=int,default=8110);parser.add_argument("--data-dir");parser.add_argument("--no-demo",action="store_true");args=parser.parse_args()
    create_app(args.data_dir,args.no_demo).run(host="127.0.0.1",port=args.port,debug=False)
