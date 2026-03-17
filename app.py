from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from functools import wraps
from datetime import datetime
import sqlite3
import requests
import os
import json
import io

# ── Database path: use /data on Render (persistent disk), else local ──
DB_DIR = '/data' if os.path.isdir('/data') else os.path.join(os.path.dirname(__file__), 'instance')
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, 'family_finance.db')

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS "transaction" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL, month INTEGER NOT NULL,
                type TEXT NOT NULL, description TEXT NOT NULL, amount REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS asset_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL, month INTEGER NOT NULL,
                account_name TEXT NOT NULL, account_type TEXT NOT NULL, balance REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mortgage_entry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL, month INTEGER NOT NULL, remaining_balance REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stock_holding (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL, purchase_price REAL NOT NULL, quantity REAL NOT NULL,
                purchase_date TEXT DEFAULT '', notes TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS daughter_investment (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year INTEGER NOT NULL, month INTEGER NOT NULL,
                ils_invested REAL NOT NULL DEFAULT 300, usd_ils_rate REAL NOT NULL,
                ivv_price_usd REAL NOT NULL, shares_purchased REAL NOT NULL, cumulative_shares REAL NOT NULL
            );
        ''')

init_db()

def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if DASHBOARD_PASSWORD and not session.get('authenticated'):
            if request.is_json:
                return jsonify({'error': 'Unauthorized'}), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('index'))
        error = 'Incorrect password'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/')
@auth_required
def index():
    return render_template('index.html')

@app.route('/income-spending')
@auth_required
def income_spending():
    return render_template('income_spending.html')

@app.route('/assets')
@auth_required
def assets():
    return render_template('assets.html')

@app.route('/mortgage')
@auth_required
def mortgage():
    return render_template('mortgage.html')

@app.route('/stocks')
@auth_required
def stocks():
    return render_template('stocks.html')

@app.route('/daughter-savings')
@auth_required
def daughter_savings():
    return render_template('daughter_savings.html')

# TRANSACTIONS
@app.route('/api/transactions', methods=['GET'])
@auth_required
def get_transactions():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    q = 'SELECT * FROM "transaction" WHERE 1=1'
    params = []
    if year:  q += ' AND year=?';  params.append(year)
    if month: q += ' AND month=?'; params.append(month)
    q += ' ORDER BY type, id'
    with get_db() as conn:
        rows = conn.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/transactions', methods=['POST'])
@auth_required
def add_transaction():
    d = request.json
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO "transaction" (year,month,type,description,amount) VALUES (?,?,?,?,?)',
            (d['year'], d['month'], d['type'], d['description'], float(d['amount'])))
    return jsonify({'id': cur.lastrowid, 'status': 'ok'})

@app.route('/api/transactions/<int:tid>', methods=['PUT'])
@auth_required
def update_transaction(tid):
    d = request.json
    with get_db() as conn:
        conn.execute(
            'UPDATE "transaction" SET description=?, amount=?, type=? WHERE id=?',
            (d.get('description'), float(d.get('amount', 0)), d.get('type'), tid))
    return jsonify({'status': 'ok'})

@app.route('/api/transactions/<int:tid>', methods=['DELETE'])
@auth_required
def delete_transaction(tid):
    with get_db() as conn:
        conn.execute('DELETE FROM "transaction" WHERE id=?', (tid,))
    return jsonify({'status': 'ok'})

@app.route('/api/transactions/summary', methods=['GET'])
@auth_required
def transactions_summary():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM "transaction"').fetchall()
    summary = {}
    for r in rows:
        key = f"{r['year']}-{r['month']:02d}"
        if key not in summary:
            summary[key] = {'salary': 0, 'other_income': 0, 'expenses': 0}
        if r['type'] == 'income_salary':  summary[key]['salary'] += r['amount']
        elif r['type'] == 'income_other': summary[key]['other_income'] += r['amount']
        else:                             summary[key]['expenses'] += r['amount']
    return jsonify(summary)

# ASSETS
@app.route('/api/assets/seed-fixed', methods=['POST'])
@auth_required
def seed_fixed_accounts():
    """Ensure fixed accounts exist for a given month."""
    d = request.json
    year, month = d['year'], d['month']
    fixed = [
        ('Bank Hapoalim', 'bank'),
        ('Bank Mizrachi', 'bank'),
        ('IBI', 'stocks'),
        ('Education fund - MTRX', 'education'),
        ('Education fund - Symetrium', 'education'),
        ('Education fund - Get sat', 'education'),
    ]
    with get_db() as conn:
        for name, atype in fixed:
            ex = conn.execute(
                'SELECT id FROM asset_snapshot WHERE year=? AND month=? AND account_name=?',
                (year, month, name)).fetchone()
            if not ex:
                conn.execute(
                    'INSERT INTO asset_snapshot (year,month,account_name,account_type,balance) VALUES (?,?,?,?,?)',
                    (year, month, name, atype, 0))
    return jsonify({'status': 'ok'})


@auth_required
def get_assets():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    q = 'SELECT * FROM asset_snapshot WHERE 1=1'
    params = []
    if year:  q += ' AND year=?';  params.append(year)
    if month: q += ' AND month=?'; params.append(month)
    with get_db() as conn:
        rows = conn.execute(q, params).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/assets', methods=['POST'])
@auth_required
def add_asset():
    d = request.json
    with get_db() as conn:
        ex = conn.execute(
            'SELECT id FROM asset_snapshot WHERE year=? AND month=? AND account_name=?',
            (d['year'], d['month'], d['account_name'])).fetchone()
        if ex:
            conn.execute('UPDATE asset_snapshot SET balance=?, account_type=? WHERE id=?',
                         (float(d['balance']), d['account_type'], ex['id']))
        else:
            conn.execute(
                'INSERT INTO asset_snapshot (year,month,account_name,account_type,balance) VALUES (?,?,?,?,?)',
                (d['year'], d['month'], d['account_name'], d['account_type'], float(d['balance'])))
    return jsonify({'status': 'ok'})

@app.route('/api/assets/<int:aid>', methods=['DELETE'])
@auth_required
def delete_asset(aid):
    with get_db() as conn:
        conn.execute('DELETE FROM asset_snapshot WHERE id=?', (aid,))
    return jsonify({'status': 'ok'})

@app.route('/api/assets/history', methods=['GET'])
@auth_required
def assets_history():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM asset_snapshot ORDER BY year, month').fetchall()
    history = {}
    for r in rows:
        key = f"{r['year']}-{r['month']:02d}"
        if key not in history: history[key] = {}
        history[key][r['account_name']] = r['balance']
    return jsonify(history)

# MORTGAGE
@app.route('/api/mortgage', methods=['GET'])
@auth_required
def get_mortgage():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM mortgage_entry ORDER BY year, month').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/mortgage', methods=['POST'])
@auth_required
def add_mortgage():
    d = request.json
    with get_db() as conn:
        ex = conn.execute('SELECT id FROM mortgage_entry WHERE year=? AND month=?',
                          (d['year'], d['month'])).fetchone()
        if ex:
            conn.execute('UPDATE mortgage_entry SET remaining_balance=? WHERE id=?',
                         (float(d['remaining_balance']), ex['id']))
        else:
            conn.execute('INSERT INTO mortgage_entry (year,month,remaining_balance) VALUES (?,?,?)',
                         (d['year'], d['month'], float(d['remaining_balance'])))
    return jsonify({'status': 'ok'})

@app.route('/api/mortgage/<int:mid>', methods=['DELETE'])
@auth_required
def delete_mortgage(mid):
    with get_db() as conn:
        conn.execute('DELETE FROM mortgage_entry WHERE id=?', (mid,))
    return jsonify({'status': 'ok'})

# STOCKS
@app.route('/api/stocks', methods=['GET'])
@auth_required
def get_stocks():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM stock_holding').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/stocks', methods=['POST'])
@auth_required
def add_stock():
    d = request.json
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO stock_holding (symbol,purchase_price,quantity,purchase_date,notes) VALUES (?,?,?,?,?)',
            (d['symbol'].upper(), float(d['purchase_price']), float(d['quantity']),
             d.get('purchase_date',''), d.get('notes','')))
    return jsonify({'id': cur.lastrowid, 'status': 'ok'})

# NOTE: /api/stocks/prices MUST come before /api/stocks/<int:sid> to avoid routing conflict
@app.route('/api/stocks/prices', methods=['GET'])
@auth_required
def get_stock_prices():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.yahoo.com',
    }
    with get_db() as conn:
        rows = conn.execute('SELECT DISTINCT symbol FROM stock_holding').fetchall()
    prices = {}
    for r in rows:
        sym = r['symbol']
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
            resp = requests.get(url, timeout=8, headers=headers)
            data = resp.json()
            meta = data['chart']['result'][0]['meta']
            price = meta.get('regularMarketPrice') or meta.get('chartPreviousClose') or meta.get('previousClose')
            if not price:
                closes = data['chart']['result'][0]['indicators']['quote'][0].get('close', [])
                closes = [c for c in closes if c is not None]
                if closes: price = closes[-1]
            prices[sym] = price
        except Exception:
            prices[sym] = None
    return jsonify(prices)

@app.route('/api/stock-price/<symbol>', methods=['GET'])
@auth_required
def get_single_price(symbol):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.yahoo.com',
    }
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}?interval=1d&range=5d"
        resp = requests.get(url, timeout=8, headers=headers)
        data = resp.json()
        meta = data['chart']['result'][0]['meta']
        price = meta.get('regularMarketPrice') or meta.get('chartPreviousClose') or meta.get('previousClose')
        if not price:
            closes = data['chart']['result'][0]['indicators']['quote'][0].get('close', [])
            closes = [c for c in closes if c is not None]
            if closes: price = closes[-1]
        return jsonify({'symbol': symbol.upper(), 'price': price})
    except Exception as e:
        return jsonify({'symbol': symbol.upper(), 'price': None, 'error': str(e)})

@app.route('/api/stocks/<int:sid>', methods=['PUT'])
@auth_required
def update_stock(sid):
    d = request.json
    with get_db() as conn:
        conn.execute(
            'UPDATE stock_holding SET symbol=?, purchase_price=?, quantity=?, notes=? WHERE id=?',
            (d.get('symbol','').upper(), float(d.get('purchase_price',0)),
             float(d.get('quantity',0)), d.get('notes',''), sid))
    return jsonify({'status': 'ok'})

@app.route('/api/stocks/<int:sid>', methods=['DELETE'])
@auth_required
def delete_stock(sid):
    with get_db() as conn:
        conn.execute('DELETE FROM stock_holding WHERE id=?', (sid,))
    return jsonify({'status': 'ok'})

# DAUGHTER SAVINGS
@app.route('/api/daughter', methods=['GET'])
@auth_required
def get_daughter():
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM daughter_investment ORDER BY year, month').fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/daughter', methods=['POST'])
@auth_required
def add_daughter_entry():
    d = request.json
    ils = float(d.get('ils_invested', 300))
    rate = float(d['usd_ils_rate'])
    ivv_price = float(d['ivv_price_usd'])
    shares = (ils / rate) / ivv_price
    with get_db() as conn:
        rows = conn.execute('SELECT * FROM daughter_investment ORDER BY year, month').fetchall()
        prior = 0.0
        for r in rows:
            if (r['year'], r['month']) < (d['year'], d['month']):
                prior = r['cumulative_shares']
        cumulative = round(prior + shares, 6)
        conn.execute(
            'INSERT INTO daughter_investment (year,month,ils_invested,usd_ils_rate,ivv_price_usd,shares_purchased,cumulative_shares) VALUES (?,?,?,?,?,?,?)',
            (d['year'], d['month'], ils, rate, ivv_price, round(shares,6), cumulative))
    _recompute_daughter_cumulative()
    return jsonify({'status': 'ok', 'shares_purchased': shares, 'cumulative': cumulative})

@app.route('/api/daughter/fetch-prices', methods=['GET'])
@auth_required
def fetch_ivv_prices():
    import calendar
    from datetime import date as dt_date

    result = {}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Referer': 'https://finance.yahoo.com',
    }

    year  = request.args.get('year',  type=int)
    month = request.args.get('month', type=int)

    if year and month:
        # Build Unix timestamps around the 15th of the month (±5 days to catch trading days)
        target_day = min(15, calendar.monthrange(year, month)[1])
        target = dt_date(year, month, target_day)
        epoch  = dt_date(1970, 1, 1)
        p1 = int((target - epoch).days) * 86400 - (5 * 86400)   # 5 days before
        p2 = int((target - epoch).days) * 86400 + (10 * 86400)  # 10 days after
        ivv_url = f'https://query1.finance.yahoo.com/v8/finance/chart/IVV?interval=1d&period1={p1}&period2={p2}'
        ils_url = f'https://query1.finance.yahoo.com/v8/finance/chart/USDILS=X?interval=1d&period1={p1}&period2={p2}'
        result['requested_period'] = f'{p1} to {p2} (around {target})'
    else:
        ivv_url = 'https://query1.finance.yahoo.com/v8/finance/chart/IVV?interval=1d&range=5d'
        ils_url = 'https://query1.finance.yahoo.com/v8/finance/chart/USDILS=X?interval=1d&range=5d'

    def fetch_price(url):
        resp = requests.get(url, timeout=10, headers=headers)
        data = resp.json()
        result_data = data['chart']['result'][0]
        meta = result_data['meta']
        # For historical: use the closes array (most reliable for past dates)
        closes = result_data['indicators']['quote'][0].get('close', [])
        closes = [c for c in closes if c is not None]
        if closes:
            return closes[-1]  # last close in the period = closest to the 15th
        # Fallback to meta fields
        return (meta.get('regularMarketPrice') or
                meta.get('chartPreviousClose') or
                meta.get('previousClose'))

    # IVV
    try:
        result['ivv_price'] = fetch_price(ivv_url)
    except Exception as e:
        result['ivv_price'] = None
        result['ivv_error'] = str(e)

    # USD/ILS via Yahoo
    try:
        result['usd_ils_rate'] = fetch_price(ils_url)
    except Exception:
        result['usd_ils_rate'] = None

    # USD/ILS fallback: live exchange rate API
    if not result.get('usd_ils_rate'):
        try:
            resp = requests.get('https://open.er-api.com/v6/latest/USD', timeout=10)
            result['usd_ils_rate'] = resp.json()['rates']['ILS']
        except Exception:
            result['usd_ils_rate'] = None

    return jsonify(result)

@app.route('/api/daughter/<int:did>', methods=['DELETE'])
@auth_required
def delete_daughter(did):
    with get_db() as conn:
        conn.execute('DELETE FROM daughter_investment WHERE id=?', (did,))
    _recompute_daughter_cumulative()
    return jsonify({'status': 'ok'})

def _recompute_daughter_cumulative():
    with get_db() as conn:
        rows = conn.execute(
            'SELECT id, shares_purchased FROM daughter_investment ORDER BY year, month').fetchall()
        cumulative = 0.0
        for r in rows:
            cumulative += r['shares_purchased']
            conn.execute('UPDATE daughter_investment SET cumulative_shares=? WHERE id=?',
                         (round(cumulative,6), r['id']))

# EXPORT / IMPORT
@app.route('/api/export', methods=['GET'])
@auth_required
def export_data():
    with get_db() as conn:
        data = {
            'exported_at': datetime.utcnow().isoformat(),
            'transactions': [dict(r) for r in conn.execute('SELECT year,month,type,description,amount FROM "transaction"').fetchall()],
            'assets':       [dict(r) for r in conn.execute('SELECT year,month,account_name,account_type,balance FROM asset_snapshot').fetchall()],
            'mortgage':     [dict(r) for r in conn.execute('SELECT year,month,remaining_balance FROM mortgage_entry').fetchall()],
            'stocks':       [dict(r) for r in conn.execute('SELECT symbol,purchase_price,quantity,purchase_date,notes FROM stock_holding').fetchall()],
            'daughter':     [dict(r) for r in conn.execute('SELECT year,month,ils_invested,usd_ils_rate,ivv_price_usd,shares_purchased,cumulative_shares FROM daughter_investment ORDER BY year,month').fetchall()],
        }
    buf = io.BytesIO(json.dumps(data, indent=2).encode('utf-8'))
    buf.seek(0)
    filename = f"family_finance_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    return send_file(buf, mimetype='application/json', as_attachment=True, download_name=filename)

@app.route('/api/import', methods=['POST'])
@auth_required
def import_data():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    try:
        data = json.load(request.files['file'])
    except Exception as e:
        return jsonify({'error': f'Invalid JSON: {e}'}), 400
    counts = {}
    with get_db() as conn:
        for row in data.get('transactions', []):
            conn.execute('INSERT INTO "transaction" (year,month,type,description,amount) VALUES (?,?,?,?,?)',
                         (row['year'],row['month'],row['type'],row['description'],row['amount']))
        counts['transactions'] = len(data.get('transactions',[]))
        for row in data.get('assets', []):
            conn.execute('INSERT INTO asset_snapshot (year,month,account_name,account_type,balance) VALUES (?,?,?,?,?)',
                         (row['year'],row['month'],row['account_name'],row['account_type'],row['balance']))
        counts['assets'] = len(data.get('assets',[]))
        for row in data.get('mortgage', []):
            conn.execute('INSERT INTO mortgage_entry (year,month,remaining_balance) VALUES (?,?,?)',
                         (row['year'],row['month'],row['remaining_balance']))
        counts['mortgage'] = len(data.get('mortgage',[]))
        for row in data.get('stocks', []):
            conn.execute('INSERT INTO stock_holding (symbol,purchase_price,quantity,purchase_date,notes) VALUES (?,?,?,?,?)',
                         (row['symbol'],row['purchase_price'],row['quantity'],row.get('purchase_date',''),row.get('notes','')))
        counts['stocks'] = len(data.get('stocks',[]))
        for row in data.get('daughter', []):
            conn.execute('INSERT INTO daughter_investment (year,month,ils_invested,usd_ils_rate,ivv_price_usd,shares_purchased,cumulative_shares) VALUES (?,?,?,?,?,?,?)',
                         (row['year'],row['month'],row['ils_invested'],row['usd_ils_rate'],row['ivv_price_usd'],row['shares_purchased'],row['cumulative_shares']))
        counts['daughter'] = len(data.get('daughter',[]))
    return jsonify({'status': 'ok', 'imported': counts})

@app.route('/api/debug-prices', methods=['GET'])
@auth_required
def debug_prices():
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.yahoo.com',
    }
    results = {}
    try:
        resp = requests.get('https://query1.finance.yahoo.com/v8/finance/chart/IVV?interval=1d&range=5d', timeout=10, headers=headers)
        data = resp.json()
        meta = data['chart']['result'][0]['meta']
        closes = data['chart']['result'][0]['indicators']['quote'][0].get('close', [])
        results['all_meta'] = meta
        results['last_5_closes'] = [c for c in closes if c is not None][-5:]
    except Exception as e:
        results['error'] = str(e)
    try:
        resp2 = requests.get('https://open.er-api.com/v6/latest/USD', timeout=10)
        d2 = resp2.json()
        results['usd_ils'] = d2['rates'].get('ILS')
    except Exception as e:
        results['usd_ils_error'] = str(e)
    return jsonify(results)



@app.route('/api/debug-stock/<symbol>', methods=['GET'])
@auth_required
def debug_stock(symbol):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.yahoo.com',
    }
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}?interval=1d&range=5d"
        resp = requests.get(url, timeout=10, headers=headers)
        data = resp.json()
        result_data = data['chart']['result'][0]
        meta = result_data['meta']
        closes = result_data['indicators']['quote'][0].get('close', [])
        closes_clean = [c for c in closes if c is not None]
        return jsonify({
            'status': resp.status_code,
            'symbol': symbol.upper(),
            'regularMarketPrice': meta.get('regularMarketPrice'),
            'chartPreviousClose': meta.get('chartPreviousClose'),
            'previousClose': meta.get('previousClose'),
            'closes': closes_clean,
            'meta_keys': list(meta.keys())
        })
    except Exception as e:
        return jsonify({'error': str(e)})



if __name__ == '__main__':
    app.run(debug=True, port=5000)
