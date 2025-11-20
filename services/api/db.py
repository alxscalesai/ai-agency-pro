import os, sqlite3, json, pathlib

DB_PATH = os.environ.get("API_DB_PATH","/app/data.db")
pathlib.Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY, name TEXT, email TEXT, brand TEXT, niche TEXT, website TEXT)")
    con.commit()
    con.close()

def insert_lead(lead: dict):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("INSERT INTO leads (name,email,brand,niche,website) VALUES (?,?,?,?,?)",
                (lead.get('name'), lead.get('email'), lead.get('brand',''), lead.get('niche',''), lead.get('website','')))
    con.commit()
    con.close()

def list_leads():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT id,name,email,brand,niche,website FROM leads ORDER BY id DESC LIMIT 100")
    rows = cur.fetchall()
    con.close()
    keys = ["id","name","email","brand","niche","website"]
    return [dict(zip(keys, r)) for r in rows]
