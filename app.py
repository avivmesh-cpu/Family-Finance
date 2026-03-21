from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from functools import wraps
from datetime import datetime
import requests as req_lib
import os, json, io

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# ── Database ─────────────────────────────────────────────────────
if DATABASE_URL:
    import pg8000.native, ssl as ssl_mod
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    _u = DATABASE_URL.replace('postgresql://', '')
    if '?' in _u: _u = _u.split('?')[0]
    _ui, _hi = _u.split('@', 1)
    _user, _pw = _ui.split(':', 1)
    _hp, _db = _hi.split('/', 1) if '/' in _hi else (_hi, 'postgres')
    _host, _port = (_hp.rsplit(':', 1)[0], int(_hp.rsplit(':', 1)[1])) if ':' in _hp else (_hp, 6543)

    def _ssl():
        ctx = ssl_mod.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl_mod.CERT_NONE
        return ctx

    def get_db():
        return pg8000.native.Connection(
            host=_host, port=_port, database=_db,
            user=_user, password=_pw, ssl_context=_ssl())

    def q(conn, sql, params=()):
        """Run SQL, return list of dicts."""
        sql = sql.replace('?', '%s')
        rows = conn.run(sql, *params)
        cols = [c['name'] for c in (conn.columns or [])]
        return [dict(zip(cols, r)) for r in rows] if rows and cols else []

    def run(conn, sql, params=()):
        """Run a write SQL statement with commit."""
        sql = sql.replace('?', '%s')
        conn.run('BEGIN')
        try:
            conn.run(sql, *params)
            conn.run('COMMIT')
        except Exception as e:
            conn.run('ROLLBACK')
            raise e

    def lastid(conn):
        return conn.run('SELECT lastval()')[0][0]

    def close_db(conn):
        try: conn.close()
        except: pass

    def run_ddl(conn, sql):
        """Run DDL (CREATE TABLE etc) - no transaction wrapper needed."""
        conn.run(sql)

    PG = True

else:
    import sqlite3
    _dbdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    os.makedirs(_dbdir, exist_ok=True)
    _dbpath = os.path.join(_dbdir, 'family_finance.db')

    def get_db():
        c = sqlite3.connect(_dbpath)
        c.row_factory = sqlite3.Row
        return c

    def q(conn, sql, params=()):
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def run(conn, sql, params=()):
        conn.execute(sql, params)
        conn.commit()

    def lastid(conn):
        return conn.execute('SELECT last_insert_rowid()').fetchone()[0]

    def close_db(conn):
        conn.close()

    def run_ddl(conn, sql):
        conn.execute(sql)
        conn.commit()

    PG = False

TBL = 'transactions' if PG else '"transaction"'
ID_TYPE = 'SERIAL PRIMARY KEY' if PG else 'INTEGER PRIMARY KEY AUTOINCREMENT'

def init_db():
    conn = get_db()
    for sql in [
        f'CREATE TABLE IF NOT EXISTS {TBL} (id {ID_TYPE}, year INT NOT NULL, month INT NOT NULL, type TEXT NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL)',
        f'CREATE TABLE IF NOT EXISTS asset_snapshot (id {ID_TYPE}, year INT NOT NULL, month INT NOT NULL, account_name TEXT NOT NULL, account_type TEXT NOT NULL, balance REAL NOT NULL)',
        f'CREATE TABLE IF NOT EXISTS mortgage_entry (id {ID_TYPE}, year INT NOT NULL, month INT NOT NULL, remaining_balance REAL NOT NULL)',
        f'CREATE TABLE IF NOT EXISTS stock_holding (id {ID_TYPE}, symbol TEXT NOT NULL, purchase_price REAL NOT NULL, quantity REAL NOT NULL, purchase_date TEXT DEFAULT \'\', notes TEXT DEFAULT \'\')',
        f'CREATE TABLE IF NOT EXISTS daughter_investment (id {ID_TYPE}, year INT NOT NULL, month INT NOT NULL, ils_invested REAL NOT NULL, usd_ils_rate REAL NOT NULL, ivv_price_usd REAL NOT NULL, shares_purchased REAL NOT NULL, cumulative_shares REAL NOT NULL)',
    ]:
        run_ddl(conn, sql)
    close_db(conn)

init_db()

@app.errorhandler(Exception)
def handle_error(e):
    import traceback
    return jsonify({'error': str(e), 'trace': traceback.format_exc()}), 500

# ── Auth ──────────────────────────────────────────────────────────
def auth_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if DASHBOARD_PASSWORD and not session.get('authenticated'):
            return redirect(url_for('login')) if not request.is_json else (jsonify({'error':'Unauthorized'}), 401)
        return f(*a, **kw)
    return dec

@app.route('/login', methods=['GET','POST'])
def login():
    err = None
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            session['authenticated'] = True; return redirect(url_for('index'))
        err = 'Incorrect password'
    return render_template('login.html', error=err)

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/health')
def health(): return jsonify({'status':'ok','db':'pg' if PG else 'sqlite'})

# ── Pages ─────────────────────────────────────────────────────────
@app.route('/')
@auth_required
def index(): return render_template('index.html')

@app.route('/income-spending')
@auth_required
def income_spending(): return render_template('income_spending.html')

@app.route('/assets')
@auth_required
def assets(): return render_template('assets.html')

@app.route('/mortgage')
@auth_required
def mortgage(): return render_template('mortgage.html')

@app.route('/stocks')
@auth_required
def stocks(): return render_template('stocks.html')

@app.route('/daughter-savings')
@auth_required
def daughter_savings(): return render_template('daughter_savings.html')

# ── Transactions ──────────────────────────────────────────────────
@app.route('/api/transactions', methods=['GET'])
@auth_required
def get_transactions():
    yr = request.args.get('year', type=int)
    mo = request.args.get('month', type=int)
    sql = f'SELECT * FROM {TBL} WHERE 1=1'
    p = []
    if yr:  sql += ' AND year=?';  p.append(yr)
    if mo:  sql += ' AND month=?'; p.append(mo)
    sql += ' ORDER BY type, id'
    conn = get_db(); r = q(conn, sql, p); close_db(conn); return jsonify(r)

@app.route('/api/transactions', methods=['POST'])
@auth_required
def add_transaction():
    d = request.json; conn = get_db()
    run(conn, f'INSERT INTO {TBL} (year,month,type,description,amount) VALUES (?,?,?,?,?)',
        (d['year'], d['month'], d['type'], d['description'], float(d['amount'])))
    close_db(conn); return jsonify({'status':'ok'})

@app.route('/api/transactions/<int:tid>', methods=['PUT'])
@auth_required
def update_transaction(tid):
    d = request.json; conn = get_db()
    run(conn, f'UPDATE {TBL} SET description=?,amount=?,type=? WHERE id=?',
        (d.get('description'), float(d.get('amount', 0)), d.get('type'), tid))
    close_db(conn); return jsonify({'status':'ok'})

@app.route('/api/transactions/<int:tid>', methods=['DELETE'])
@auth_required
def delete_transaction(tid):
    conn = get_db(); run(conn, f'DELETE FROM {TBL} WHERE id=?', (tid,)); close_db(conn)
    return jsonify({'status':'ok'})

@app.route('/api/transactions/summary', methods=['GET'])
@auth_required
def transactions_summary():
    conn = get_db(); rows = q(conn, f'SELECT * FROM {TBL}'); close_db(conn)
    s = {}
    for r in rows:
        k = f"{r['year']}-{r['month']:02d}"
        if k not in s: s[k] = {'salary':0,'other_income':0,'expenses':0}
        if r['type']=='income_salary': s[k]['salary']+=r['amount']
        elif r['type']=='income_other': s[k]['other_income']+=r['amount']
        else: s[k]['expenses']+=r['amount']
    return jsonify(s)

# ── Assets ────────────────────────────────────────────────────────
@app.route('/api/assets', methods=['GET'])
@auth_required
def get_assets():
    yr = request.args.get('year', type=int); mo = request.args.get('month', type=int)
    sql = 'SELECT * FROM asset_snapshot WHERE 1=1'; p = []
    if yr: sql+=' AND year=?'; p.append(yr)
    if mo: sql+=' AND month=?'; p.append(mo)
    conn = get_db(); r = q(conn, sql, p); close_db(conn); return jsonify(r)

@app.route('/api/assets', methods=['POST'])
@auth_required
def add_asset():
    d = request.json; conn = get_db()
    ex = q(conn, 'SELECT id FROM asset_snapshot WHERE year=? AND month=? AND account_name=?',
           (d['year'], d['month'], d['account_name']))
    if ex:
        run(conn, 'UPDATE asset_snapshot SET balance=?,account_type=? WHERE id=?',
            (float(d['balance']), d['account_type'], ex[0]['id']))
    else:
        run(conn, 'INSERT INTO asset_snapshot (year,month,account_name,account_type,balance) VALUES (?,?,?,?,?)',
            (d['year'], d['month'], d['account_name'], d['account_type'], float(d['balance'])))
    close_db(conn); return jsonify({'status':'ok'})

@app.route('/api/assets/<int:aid>', methods=['DELETE'])
@auth_required
def delete_asset(aid):
    conn = get_db(); run(conn, 'DELETE FROM asset_snapshot WHERE id=?', (aid,)); close_db(conn)
    return jsonify({'status':'ok'})

@app.route('/api/assets/history', methods=['GET'])
@auth_required
def assets_history():
    conn = get_db(); rows = q(conn, 'SELECT * FROM asset_snapshot ORDER BY year,month'); close_db(conn)
    h = {}
    for r in rows:
        k = f"{r['year']}-{r['month']:02d}"
        if k not in h: h[k] = {}
        h[k][r['account_name']] = r['balance']
    return jsonify(h)

# ── Mortgage ──────────────────────────────────────────────────────
@app.route('/api/mortgage', methods=['GET'])
@auth_required
def get_mortgage():
    conn = get_db(); r = q(conn, 'SELECT * FROM mortgage_entry ORDER BY year,month'); close_db(conn)
    return jsonify(r)

@app.route('/api/mortgage', methods=['POST'])
@auth_required
def add_mortgage():
    d = request.json; conn = get_db()
    ex = q(conn, 'SELECT id FROM mortgage_entry WHERE year=? AND month=?', (d['year'], d['month']))
    if ex:
        run(conn, 'UPDATE mortgage_entry SET remaining_balance=? WHERE id=?',
            (float(d['remaining_balance']), ex[0]['id']))
    else:
        run(conn, 'INSERT INTO mortgage_entry (year,month,remaining_balance) VALUES (?,?,?)',
            (d['year'], d['month'], float(d['remaining_balance'])))
    close_db(conn); return jsonify({'status':'ok'})

@app.route('/api/mortgage/<int:mid>', methods=['DELETE'])
@auth_required
def delete_mortgage(mid):
    conn = get_db(); run(conn, 'DELETE FROM mortgage_entry WHERE id=?', (mid,)); close_db(conn)
    return jsonify({'status':'ok'})

# ── Stocks ────────────────────────────────────────────────────────
@app.route('/api/stocks', methods=['GET'])
@auth_required
def get_stocks():
    conn = get_db(); r = q(conn, 'SELECT * FROM stock_holding'); close_db(conn); return jsonify(r)

@app.route('/api/stocks', methods=['POST'])
@auth_required
def add_stock():
    d = request.json; conn = get_db()
    run(conn, 'INSERT INTO stock_holding (symbol,purchase_price,quantity,purchase_date,notes) VALUES (?,?,?,?,?)',
        (d['symbol'].upper(), float(d['purchase_price']), float(d['quantity']),
         d.get('purchase_date',''), d.get('notes','')))
    close_db(conn); return jsonify({'status':'ok'})

@app.route('/api/stocks/<int:sid>', methods=['PUT'])
@auth_required
def update_stock(sid):
    d = request.json; conn = get_db()
    run(conn, 'UPDATE stock_holding SET symbol=?,purchase_price=?,quantity=?,notes=? WHERE id=?',
        (d.get('symbol','').upper(), float(d.get('purchase_price',0)),
         float(d.get('quantity',0)), d.get('notes',''), sid))
    close_db(conn); return jsonify({'status':'ok'})

@app.route('/api/stocks/<int:sid>', methods=['DELETE'])
@auth_required
def delete_stock(sid):
    conn = get_db(); run(conn, 'DELETE FROM stock_holding WHERE id=?', (sid,)); close_db(conn)
    return jsonify({'status':'ok'})

def _yahoo(sym):
    h = {'User-Agent':'Mozilla/5.0','Referer':'https://finance.yahoo.com'}
    rd = req_lib.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d",
                     timeout=10, headers=h).json()['chart']['result'][0]
    closes = [c for c in rd['indicators']['quote'][0].get('close',[]) if c]
    if closes: return closes[-1]
    m = rd['meta']
    return m.get('regularMarketPrice') or m.get('chartPreviousClose') or m.get('previousClose')

@app.route('/api/stocks/prices', methods=['GET'])
@auth_required
def get_stock_prices():
    conn = get_db(); rows = q(conn, 'SELECT DISTINCT symbol FROM stock_holding'); close_db(conn)
    prices = {}
    for r in rows:
        sym = r['symbol']
        if not sym: continue
        try: prices[sym] = _yahoo(sym)
        except: prices[sym] = None
    return jsonify(prices)

@app.route('/api/stock-price/<symbol>', methods=['GET'])
@auth_required
def get_single_price(symbol):
    try: return jsonify({'symbol':symbol.upper(),'price':_yahoo(symbol.upper())})
    except Exception as e: return jsonify({'symbol':symbol.upper(),'price':None,'error':str(e)})

# ── Daughter/Romi ─────────────────────────────────────────────────
@app.route('/api/daughter', methods=['GET'])
@auth_required
def get_daughter():
    conn = get_db(); r = q(conn, 'SELECT * FROM daughter_investment ORDER BY year,month'); close_db(conn)
    return jsonify(r)

@app.route('/api/daughter', methods=['POST'])
@auth_required
def add_daughter_entry():
    d = request.json
    ils = float(d.get('ils_invested',300)); rate = float(d['usd_ils_rate']); ivv = float(d['ivv_price_usd'])
    shares = (ils/rate)/ivv
    conn = get_db()
    rows = q(conn, 'SELECT * FROM daughter_investment ORDER BY year,month')
    prior = 0.0
    for r in rows:
        if (r['year'],r['month']) < (d['year'],d['month']): prior = r['cumulative_shares']
    cumulative = round(prior+shares, 6)
    run(conn, 'INSERT INTO daughter_investment (year,month,ils_invested,usd_ils_rate,ivv_price_usd,shares_purchased,cumulative_shares) VALUES (?,?,?,?,?,?,?)',
        (d['year'],d['month'],ils,rate,ivv,round(shares,6),cumulative))
    close_db(conn); _recompute_daughter(); return jsonify({'status':'ok'})

@app.route('/api/daughter/fetch-prices', methods=['GET'])
@auth_required
def fetch_ivv_prices():
    import calendar; from datetime import date as dt
    h = {'User-Agent':'Mozilla/5.0 Chrome/122','Referer':'https://finance.yahoo.com'}
    yr = request.args.get('year',type=int); mo = request.args.get('month',type=int)
    if yr and mo:
        td = min(15,calendar.monthrange(yr,mo)[1]); target = dt(yr,mo,td); epoch = dt(1970,1,1)
        p1 = int((target-epoch).days)*86400 - 5*86400
        p2 = int((target-epoch).days)*86400 + 10*86400
        iurl = f'https://query1.finance.yahoo.com/v8/finance/chart/IVV?interval=1d&period1={p1}&period2={p2}'
        rurl = f'https://query1.finance.yahoo.com/v8/finance/chart/USDILS=X?interval=1d&period1={p1}&period2={p2}'
    else:
        iurl = 'https://query1.finance.yahoo.com/v8/finance/chart/IVV?interval=1d&range=5d'
        rurl = 'https://query1.finance.yahoo.com/v8/finance/chart/USDILS=X?interval=1d&range=5d'
    def fp(url):
        rd = req_lib.get(url,timeout=10,headers=h).json()['chart']['result'][0]
        closes = [c for c in rd['indicators']['quote'][0].get('close',[]) if c]
        if closes: return closes[-1]
        m = rd['meta']; return m.get('regularMarketPrice') or m.get('chartPreviousClose') or m.get('previousClose')
    result = {}
    try: result['ivv_price'] = fp(iurl)
    except Exception as e: result['ivv_price'] = None; result['ivv_error'] = str(e)
    try: result['usd_ils_rate'] = fp(rurl)
    except: result['usd_ils_rate'] = None
    if not result.get('usd_ils_rate'):
        try: result['usd_ils_rate'] = req_lib.get('https://open.er-api.com/v6/latest/USD',timeout=10).json()['rates']['ILS']
        except: result['usd_ils_rate'] = None
    return jsonify(result)

@app.route('/api/daughter/<int:did>', methods=['DELETE'])
@auth_required
def delete_daughter(did):
    conn = get_db(); run(conn, 'DELETE FROM daughter_investment WHERE id=?',(did,)); close_db(conn)
    _recompute_daughter(); return jsonify({'status':'ok'})

def _recompute_daughter():
    conn = get_db(); rows = q(conn,'SELECT id,shares_purchased FROM daughter_investment ORDER BY year,month')
    c = 0.0
    for r in rows:
        c += r['shares_purchased']
        run(conn,'UPDATE daughter_investment SET cumulative_shares=? WHERE id=?',(round(c,6),r['id']))
    close_db(conn)

# ── Export / Import ───────────────────────────────────────────────
@app.route('/api/export', methods=['GET'])
@auth_required
def export_data():
    conn = get_db()
    data = {
        'exported_at': datetime.utcnow().isoformat(),
        'transactions': q(conn, f'SELECT year,month,type,description,amount FROM {TBL}'),
        'assets':       q(conn, 'SELECT year,month,account_name,account_type,balance FROM asset_snapshot'),
        'mortgage':     q(conn, 'SELECT year,month,remaining_balance FROM mortgage_entry'),
        'stocks':       q(conn, 'SELECT symbol,purchase_price,quantity,purchase_date,notes FROM stock_holding'),
        'daughter':     q(conn, 'SELECT year,month,ils_invested,usd_ils_rate,ivv_price_usd,shares_purchased,cumulative_shares FROM daughter_investment ORDER BY year,month'),
    }
    close_db(conn)
    buf = io.BytesIO(json.dumps(data,indent=2).encode('utf-8')); buf.seek(0)
    return send_file(buf, mimetype='application/json', as_attachment=True,
                     download_name=f"family_finance_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json")

@app.route('/api/import', methods=['POST'])
@auth_required
def import_data():
    if 'file' not in request.files: return jsonify({'error':'No file'}),400
    try: data = json.load(request.files['file'])
    except Exception as e: return jsonify({'error':str(e)}),400
    conn = get_db(); counts = {}
    for r in data.get('transactions',[]):
        run(conn, f'INSERT INTO {TBL} (year,month,type,description,amount) VALUES (?,?,?,?,?)',
            (r['year'],r['month'],r['type'],r['description'],r['amount']))
    counts['transactions'] = len(data.get('transactions',[]))
    for r in data.get('assets',[]):
        run(conn, 'INSERT INTO asset_snapshot (year,month,account_name,account_type,balance) VALUES (?,?,?,?,?)',
            (r['year'],r['month'],r['account_name'],r['account_type'],r['balance']))
    counts['assets'] = len(data.get('assets',[]))
    for r in data.get('mortgage',[]):
        run(conn, 'INSERT INTO mortgage_entry (year,month,remaining_balance) VALUES (?,?,?)',
            (r['year'],r['month'],r['remaining_balance']))
    counts['mortgage'] = len(data.get('mortgage',[]))
    for r in data.get('stocks',[]):
        run(conn, 'INSERT INTO stock_holding (symbol,purchase_price,quantity,purchase_date,notes) VALUES (?,?,?,?,?)',
            (r['symbol'],r['purchase_price'],r['quantity'],r.get('purchase_date',''),r.get('notes','')))
    counts['stocks'] = len(data.get('stocks',[]))
    for r in data.get('daughter',[]):
        run(conn, 'INSERT INTO daughter_investment (year,month,ils_invested,usd_ils_rate,ivv_price_usd,shares_purchased,cumulative_shares) VALUES (?,?,?,?,?,?,?)',
            (r['year'],r['month'],r['ils_invested'],r['usd_ils_rate'],r['ivv_price_usd'],r['shares_purchased'],r['cumulative_shares']))
    counts['daughter'] = len(data.get('daughter',[]))
    close_db(conn); return jsonify({'status':'ok','imported':counts})

@app.route('/api/debug-prices', methods=['GET'])
@auth_required
def debug_prices():
    h={'User-Agent':'Mozilla/5.0','Referer':'https://finance.yahoo.com'}; r={'db':'pg' if PG else 'sqlite'}
    try:
        rd=req_lib.get('https://query1.finance.yahoo.com/v8/finance/chart/IVV?interval=1d&range=5d',timeout=10,headers=h).json()['chart']['result'][0]
        r['ivv_meta']=rd['meta']; r['ivv_closes']=[c for c in rd['indicators']['quote'][0].get('close',[]) if c][-5:]
    except Exception as e: r['ivv_error']=str(e)
    try: r['usd_ils']=req_lib.get('https://open.er-api.com/v6/latest/USD',timeout=10).json()['rates'].get('ILS')
    except Exception as e: r['usd_ils_error']=str(e)
    return jsonify(r)

if __name__=='__main__': app.run(debug=True,port=5000)
