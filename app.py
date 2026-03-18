from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from functools import wraps
from datetime import datetime
import requests
import os, json, io, urllib.parse

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# ── Database layer ──────────────────────────────────────────────
if DATABASE_URL:
    import pg8000.native
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    _p = urllib.parse.urlparse(DATABASE_URL)

    class DB:
        """Thin wrapper around pg8000 that gives dict rows and ? placeholders."""
        def __init__(self):
            self._conn = pg8000.native.Connection(
                host=_p.hostname, port=_p.port or 5432,
                database=_p.path.lstrip('/'),
                user=_p.username, password=_p.password, ssl_context=True)

        def execute(self, sql, params=()):
            sql = sql.replace('?', '%s').replace('"transaction"', 'transactions')
            sql = sql.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'SERIAL PRIMARY KEY')
            rows = self._conn.run(sql, *params)
            cols = [c['name'] for c in (self._conn.columns or [])]
            if rows and cols:
                return [dict(zip(cols, r)) for r in rows]
            return []

        def lastid(self):
            r = self._conn.run('SELECT lastval()')
            return r[0][0] if r else None

        def close(self): pass  # pg8000 native manages connection

    def get_db(): return DB()
    PG = True

else:
    import sqlite3
    DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    os.makedirs(DB_DIR, exist_ok=True)
    DB_PATH = os.path.join(DB_DIR, 'family_finance.db')

    class DB:
        def __init__(self):
            self._conn = sqlite3.connect(DB_PATH)
            self._conn.row_factory = sqlite3.Row

        def execute(self, sql, params=()):
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            rows = cur.fetchall()
            return [dict(r) for r in rows] if rows else []

        def lastid(self): return self._conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        def close(self): self._conn.close()

    def get_db(): return DB()
    PG = False

def init_db():
    db = get_db()
    tbl = 'transactions' if PG else '"transaction"'
    for sql in [
        f'''CREATE TABLE IF NOT EXISTS {tbl} (
            id {"SERIAL" if PG else "INTEGER"} PRIMARY KEY {"" if PG else "AUTOINCREMENT"},
            year INTEGER NOT NULL, month INTEGER NOT NULL,
            type TEXT NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL)''',
        f'''CREATE TABLE IF NOT EXISTS asset_snapshot (
            id {"SERIAL" if PG else "INTEGER"} PRIMARY KEY {"" if PG else "AUTOINCREMENT"},
            year INTEGER NOT NULL, month INTEGER NOT NULL,
            account_name TEXT NOT NULL, account_type TEXT NOT NULL, balance REAL NOT NULL)''',
        f'''CREATE TABLE IF NOT EXISTS mortgage_entry (
            id {"SERIAL" if PG else "INTEGER"} PRIMARY KEY {"" if PG else "AUTOINCREMENT"},
            year INTEGER NOT NULL, month INTEGER NOT NULL, remaining_balance REAL NOT NULL)''',
        f'''CREATE TABLE IF NOT EXISTS stock_holding (
            id {"SERIAL" if PG else "INTEGER"} PRIMARY KEY {"" if PG else "AUTOINCREMENT"},
            symbol TEXT NOT NULL, purchase_price REAL NOT NULL, quantity REAL NOT NULL,
            purchase_date TEXT DEFAULT \'\', notes TEXT DEFAULT \'\')''',
        f'''CREATE TABLE IF NOT EXISTS daughter_investment (
            id {"SERIAL" if PG else "INTEGER"} PRIMARY KEY {"" if PG else "AUTOINCREMENT"},
            year INTEGER NOT NULL, month INTEGER NOT NULL,
            ils_invested REAL NOT NULL DEFAULT 300, usd_ils_rate REAL NOT NULL,
            ivv_price_usd REAL NOT NULL, shares_purchased REAL NOT NULL, cumulative_shares REAL NOT NULL)''',
    ]:
        db.execute(sql)
    db.close()

init_db()

# ── Auth ────────────────────────────────────────────────────────
def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if DASHBOARD_PASSWORD and not session.get('authenticated'):
            return redirect(url_for('login')) if not request.is_json else (jsonify({'error':'Unauthorized'}), 401)
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET','POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            session['authenticated'] = True; return redirect(url_for('index'))
        error = 'Incorrect password'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/health')
def health(): return jsonify({'status':'ok','db':'postgresql' if PG else 'sqlite'})

# ── Pages ───────────────────────────────────────────────────────
@app.route('/') @auth_required
def index(): return render_template('index.html')

@app.route('/income-spending') @auth_required
def income_spending(): return render_template('income_spending.html')

@app.route('/assets') @auth_required
def assets(): return render_template('assets.html')

@app.route('/mortgage') @auth_required
def mortgage(): return render_template('mortgage.html')

@app.route('/stocks') @auth_required
def stocks(): return render_template('stocks.html')

@app.route('/daughter-savings') @auth_required
def daughter_savings(): return render_template('daughter_savings.html')


TBL = 'transactions' if PG else '"transaction"'

# ── Transactions ─────────────────────────────────────────────────
@app.route('/api/transactions', methods=['GET'])
@auth_required
def get_transactions():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    sql = f'SELECT * FROM {TBL} WHERE 1=1'
    params = []
    if year:  sql += ' AND year=?';  params.append(year)
    if month: sql += ' AND month=?'; params.append(month)
    sql += ' ORDER BY type, id'
    db = get_db()
    result = db.execute(sql, params); db.close()
    return jsonify(result)

@app.route('/api/transactions', methods=['POST'])
@auth_required
def add_transaction():
    d = request.json
    db = get_db()
    db.execute(f'INSERT INTO {TBL} (year,month,type,description,amount) VALUES (?,?,?,?,?)',
               (d['year'],d['month'],d['type'],d['description'],float(d['amount'])))
    db.close(); return jsonify({'status':'ok'})

@app.route('/api/transactions/<int:tid>', methods=['PUT'])
@auth_required
def update_transaction(tid):
    d = request.json; db = get_db()
    db.execute(f'UPDATE {TBL} SET description=?,amount=?,type=? WHERE id=?',
               (d.get('description'),float(d.get('amount',0)),d.get('type'),tid))
    db.close(); return jsonify({'status':'ok'})

@app.route('/api/transactions/<int:tid>', methods=['DELETE'])
@auth_required
def delete_transaction(tid):
    db = get_db(); db.execute(f'DELETE FROM {TBL} WHERE id=?',(tid,)); db.close()
    return jsonify({'status':'ok'})

@app.route('/api/transactions/summary', methods=['GET'])
@auth_required
def transactions_summary():
    db = get_db(); rows = db.execute(f'SELECT * FROM {TBL}'); db.close()
    summary = {}
    for r in rows:
        key = f"{r['year']}-{r['month']:02d}"
        if key not in summary: summary[key] = {'salary':0,'other_income':0,'expenses':0}
        if r['type']=='income_salary': summary[key]['salary']+=r['amount']
        elif r['type']=='income_other': summary[key]['other_income']+=r['amount']
        else: summary[key]['expenses']+=r['amount']
    return jsonify(summary)

# ── Assets ───────────────────────────────────────────────────────
@app.route('/api/assets', methods=['GET'])
@auth_required
def get_assets():
    year=request.args.get('year',type=int); month=request.args.get('month',type=int)
    sql='SELECT * FROM asset_snapshot WHERE 1=1'; params=[]
    if year: sql+=' AND year=?'; params.append(year)
    if month: sql+=' AND month=?'; params.append(month)
    db=get_db(); result=db.execute(sql,params); db.close(); return jsonify(result)

@app.route('/api/assets', methods=['POST'])
@auth_required
def add_asset():
    d=request.json; db=get_db()
    ex=db.execute('SELECT id FROM asset_snapshot WHERE year=? AND month=? AND account_name=?',
                  (d['year'],d['month'],d['account_name']))
    if ex: db.execute('UPDATE asset_snapshot SET balance=?,account_type=? WHERE id=?',
                      (float(d['balance']),d['account_type'],ex[0]['id']))
    else: db.execute('INSERT INTO asset_snapshot (year,month,account_name,account_type,balance) VALUES (?,?,?,?,?)',
                     (d['year'],d['month'],d['account_name'],d['account_type'],float(d['balance'])))
    db.close(); return jsonify({'status':'ok'})

@app.route('/api/assets/<int:aid>', methods=['DELETE'])
@auth_required
def delete_asset(aid):
    db=get_db(); db.execute('DELETE FROM asset_snapshot WHERE id=?',(aid,)); db.close()
    return jsonify({'status':'ok'})

@app.route('/api/assets/history', methods=['GET'])
@auth_required
def assets_history():
    db=get_db(); rows=db.execute('SELECT * FROM asset_snapshot ORDER BY year,month'); db.close()
    history={}
    for r in rows:
        key=f"{r['year']}-{r['month']:02d}"
        if key not in history: history[key]={}
        history[key][r['account_name']]=r['balance']
    return jsonify(history)

# ── Mortgage ─────────────────────────────────────────────────────
@app.route('/api/mortgage', methods=['GET'])
@auth_required
def get_mortgage():
    db=get_db(); r=db.execute('SELECT * FROM mortgage_entry ORDER BY year,month'); db.close()
    return jsonify(r)

@app.route('/api/mortgage', methods=['POST'])
@auth_required
def add_mortgage():
    d=request.json; db=get_db()
    ex=db.execute('SELECT id FROM mortgage_entry WHERE year=? AND month=?',(d['year'],d['month']))
    if ex: db.execute('UPDATE mortgage_entry SET remaining_balance=? WHERE id=?',(float(d['remaining_balance']),ex[0]['id']))
    else: db.execute('INSERT INTO mortgage_entry (year,month,remaining_balance) VALUES (?,?,?)',(d['year'],d['month'],float(d['remaining_balance'])))
    db.close(); return jsonify({'status':'ok'})

@app.route('/api/mortgage/<int:mid>', methods=['DELETE'])
@auth_required
def delete_mortgage(mid):
    db=get_db(); db.execute('DELETE FROM mortgage_entry WHERE id=?',(mid,)); db.close()
    return jsonify({'status':'ok'})

# ── Stocks ───────────────────────────────────────────────────────
@app.route('/api/stocks', methods=['GET'])
@auth_required
def get_stocks():
    db=get_db(); r=db.execute('SELECT * FROM stock_holding'); db.close(); return jsonify(r)

@app.route('/api/stocks', methods=['POST'])
@auth_required
def add_stock():
    d=request.json; db=get_db()
    db.execute('INSERT INTO stock_holding (symbol,purchase_price,quantity,purchase_date,notes) VALUES (?,?,?,?,?)',
               (d['symbol'].upper(),float(d['purchase_price']),float(d['quantity']),d.get('purchase_date',''),d.get('notes','')))
    db.close(); return jsonify({'status':'ok'})

@app.route('/api/stocks/<int:sid>', methods=['PUT'])
@auth_required
def update_stock(sid):
    d=request.json; db=get_db()
    db.execute('UPDATE stock_holding SET symbol=?,purchase_price=?,quantity=?,notes=? WHERE id=?',
               (d.get('symbol','').upper(),float(d.get('purchase_price',0)),float(d.get('quantity',0)),d.get('notes',''),sid))
    db.close(); return jsonify({'status':'ok'})

@app.route('/api/stocks/<int:sid>', methods=['DELETE'])
@auth_required
def delete_stock(sid):
    db=get_db(); db.execute('DELETE FROM stock_holding WHERE id=?',(sid,)); db.close()
    return jsonify({'status':'ok'})

def _yahoo_price(sym):
    headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36','Referer':'https://finance.yahoo.com'}
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
    resp=requests.get(url,timeout=10,headers=headers)
    rd=resp.json()['chart']['result'][0]
    closes=[c for c in rd['indicators']['quote'][0].get('close',[]) if c]
    if closes: return closes[-1]
    meta=rd['meta']
    return meta.get('regularMarketPrice') or meta.get('chartPreviousClose') or meta.get('previousClose')

@app.route('/api/stocks/prices', methods=['GET'])
@auth_required
def get_stock_prices():
    db=get_db(); rows=db.execute('SELECT DISTINCT symbol FROM stock_holding'); db.close()
    prices={}
    for r in rows:
        sym=r['symbol']
        if not sym: continue
        try: prices[sym]=_yahoo_price(sym)
        except: prices[sym]=None
    return jsonify(prices)

@app.route('/api/stock-price/<symbol>', methods=['GET'])
@auth_required
def get_single_price(symbol):
    try: return jsonify({'symbol':symbol.upper(),'price':_yahoo_price(symbol.upper())})
    except Exception as e: return jsonify({'symbol':symbol.upper(),'price':None,'error':str(e)})

# ── Romi/Daughter Savings ────────────────────────────────────────
@app.route('/api/daughter', methods=['GET'])
@auth_required
def get_daughter():
    db=get_db(); r=db.execute('SELECT * FROM daughter_investment ORDER BY year,month'); db.close()
    return jsonify(r)

@app.route('/api/daughter', methods=['POST'])
@auth_required
def add_daughter_entry():
    d=request.json
    ils=float(d.get('ils_invested',300)); rate=float(d['usd_ils_rate']); ivv=float(d['ivv_price_usd'])
    shares=(ils/rate)/ivv
    db=get_db()
    rows=db.execute('SELECT * FROM daughter_investment ORDER BY year,month')
    prior=0.0
    for r in rows:
        if (r['year'],r['month'])<(d['year'],d['month']): prior=r['cumulative_shares']
    cumulative=round(prior+shares,6)
    db.execute('INSERT INTO daughter_investment (year,month,ils_invested,usd_ils_rate,ivv_price_usd,shares_purchased,cumulative_shares) VALUES (?,?,?,?,?,?,?)',
               (d['year'],d['month'],ils,rate,ivv,round(shares,6),cumulative))
    db.close(); _recompute_daughter(); return jsonify({'status':'ok'})

@app.route('/api/daughter/fetch-prices', methods=['GET'])
@auth_required
def fetch_ivv_prices():
    import calendar; from datetime import date as dt
    result={}
    headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36','Referer':'https://finance.yahoo.com'}
    year=request.args.get('year',type=int); month=request.args.get('month',type=int)
    if year and month:
        td=min(15,calendar.monthrange(year,month)[1]); target=dt(year,month,td); epoch=dt(1970,1,1)
        p1=int((target-epoch).days)*86400-5*86400; p2=int((target-epoch).days)*86400+10*86400
        ivv_url=f'https://query1.finance.yahoo.com/v8/finance/chart/IVV?interval=1d&period1={p1}&period2={p2}'
        ils_url=f'https://query1.finance.yahoo.com/v8/finance/chart/USDILS=X?interval=1d&period1={p1}&period2={p2}'
    else:
        ivv_url='https://query1.finance.yahoo.com/v8/finance/chart/IVV?interval=1d&range=5d'
        ils_url='https://query1.finance.yahoo.com/v8/finance/chart/USDILS=X?interval=1d&range=5d'
    def fp(url):
        rd=requests.get(url,timeout=10,headers=headers).json()['chart']['result'][0]
        closes=[c for c in rd['indicators']['quote'][0].get('close',[]) if c]
        if closes: return closes[-1]
        m=rd['meta']; return m.get('regularMarketPrice') or m.get('chartPreviousClose') or m.get('previousClose')
    try: result['ivv_price']=fp(ivv_url)
    except Exception as e: result['ivv_price']=None; result['ivv_error']=str(e)
    try: result['usd_ils_rate']=fp(ils_url)
    except: result['usd_ils_rate']=None
    if not result.get('usd_ils_rate'):
        try: result['usd_ils_rate']=requests.get('https://open.er-api.com/v6/latest/USD',timeout=10).json()['rates']['ILS']
        except: result['usd_ils_rate']=None
    return jsonify(result)

@app.route('/api/daughter/<int:did>', methods=['DELETE'])
@auth_required
def delete_daughter(did):
    db=get_db(); db.execute('DELETE FROM daughter_investment WHERE id=?',(did,)); db.close()
    _recompute_daughter(); return jsonify({'status':'ok'})

def _recompute_daughter():
    db=get_db(); rows=db.execute('SELECT id,shares_purchased FROM daughter_investment ORDER BY year,month')
    c=0.0
    for r in rows:
        c+=r['shares_purchased']
        db.execute('UPDATE daughter_investment SET cumulative_shares=? WHERE id=?',(round(c,6),r['id']))
    db.close()

# ── Export / Import ──────────────────────────────────────────────
@app.route('/api/export', methods=['GET'])
@auth_required
def export_data():
    db=get_db()
    data={'exported_at':datetime.utcnow().isoformat(),
          'transactions':db.execute(f'SELECT year,month,type,description,amount FROM {TBL}'),
          'assets':db.execute('SELECT year,month,account_name,account_type,balance FROM asset_snapshot'),
          'mortgage':db.execute('SELECT year,month,remaining_balance FROM mortgage_entry'),
          'stocks':db.execute('SELECT symbol,purchase_price,quantity,purchase_date,notes FROM stock_holding'),
          'daughter':db.execute('SELECT year,month,ils_invested,usd_ils_rate,ivv_price_usd,shares_purchased,cumulative_shares FROM daughter_investment ORDER BY year,month')}
    db.close()
    buf=io.BytesIO(json.dumps(data,indent=2).encode('utf-8')); buf.seek(0)
    return send_file(buf,mimetype='application/json',as_attachment=True,
                     download_name=f"family_finance_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json")

@app.route('/api/import', methods=['POST'])
@auth_required
def import_data():
    if 'file' not in request.files: return jsonify({'error':'No file'}),400
    try: data=json.load(request.files['file'])
    except Exception as e: return jsonify({'error':str(e)}),400
    db=get_db(); counts={}
    for row in data.get('transactions',[]):
        db.execute(f'INSERT INTO {TBL} (year,month,type,description,amount) VALUES (?,?,?,?,?)',
                   (row['year'],row['month'],row['type'],row['description'],row['amount']))
    counts['transactions']=len(data.get('transactions',[]))
    for row in data.get('assets',[]):
        db.execute('INSERT INTO asset_snapshot (year,month,account_name,account_type,balance) VALUES (?,?,?,?,?)',
                   (row['year'],row['month'],row['account_name'],row['account_type'],row['balance']))
    counts['assets']=len(data.get('assets',[]))
    for row in data.get('mortgage',[]):
        db.execute('INSERT INTO mortgage_entry (year,month,remaining_balance) VALUES (?,?,?)',
                   (row['year'],row['month'],row['remaining_balance']))
    counts['mortgage']=len(data.get('mortgage',[]))
    for row in data.get('stocks',[]):
        db.execute('INSERT INTO stock_holding (symbol,purchase_price,quantity,purchase_date,notes) VALUES (?,?,?,?,?)',
                   (row['symbol'],row['purchase_price'],row['quantity'],row.get('purchase_date',''),row.get('notes','')))
    counts['stocks']=len(data.get('stocks',[]))
    for row in data.get('daughter',[]):
        db.execute('INSERT INTO daughter_investment (year,month,ils_invested,usd_ils_rate,ivv_price_usd,shares_purchased,cumulative_shares) VALUES (?,?,?,?,?,?,?)',
                   (row['year'],row['month'],row['ils_invested'],row['usd_ils_rate'],row['ivv_price_usd'],row['shares_purchased'],row['cumulative_shares']))
    counts['daughter']=len(data.get('daughter',[]))
    db.close(); return jsonify({'status':'ok','imported':counts})

@app.route('/api/debug-prices', methods=['GET'])
@auth_required
def debug_prices():
    headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.yahoo.com'}
    r={}
    try:
        resp=requests.get('https://query1.finance.yahoo.com/v8/finance/chart/IVV?interval=1d&range=5d',timeout=10,headers=headers)
        rd=resp.json()['chart']['result'][0]
        r['ivv_meta']=rd['meta']; r['ivv_closes']=[c for c in rd['indicators']['quote'][0].get('close',[]) if c][-5:]
    except Exception as e: r['ivv_error']=str(e)
    try: r['usd_ils']=requests.get('https://open.er-api.com/v6/latest/USD',timeout=10).json()['rates'].get('ILS')
    except Exception as e: r['usd_ils_error']=str(e)
    r['db']='postgresql' if PG else 'sqlite'
    return jsonify(r)

if __name__=='__main__': app.run(debug=True,port=5000)
