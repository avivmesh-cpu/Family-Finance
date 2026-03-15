from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
import requests
import os
import json
import io

# Use /data (Render persistent disk) if available, else local instance/
DB_DIR = '/data' if os.path.isdir('/data') else os.path.join(os.path.dirname(__file__), 'instance')
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, 'family_finance.db')

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-prod')
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')  # empty = no password
db = SQLAlchemy(app)

# ──────────────────────────────────────────────
# AUTH (optional password protection)
# ──────────────────────────────────────────────

def auth_required(f):
    from functools import wraps
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

# ──────────────────────────────────────────────
# MODELS
# ──────────────────────────────────────────────

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'income_salary','income_other','expense'
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AssetSnapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    account_name = db.Column(db.String(100), nullable=False)
    account_type = db.Column(db.String(50), nullable=False)  # bank/stocks/education/other
    balance = db.Column(db.Float, nullable=False)

class MortgageEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    remaining_balance = db.Column(db.Float, nullable=False)

class StockHolding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)
    purchase_price = db.Column(db.Float, nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    purchase_date = db.Column(db.String(20))
    notes = db.Column(db.String(200))

class DaughterInvestment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    ils_invested = db.Column(db.Float, default=300.0)
    usd_ils_rate = db.Column(db.Float, nullable=False)
    ivv_price_usd = db.Column(db.Float, nullable=False)
    shares_purchased = db.Column(db.Float, nullable=False)
    cumulative_shares = db.Column(db.Float, nullable=False)

# ──────────────────────────────────────────────
# PAGE ROUTES
# ──────────────────────────────────────────────

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

# ──────────────────────────────────────────────
# API: TRANSACTIONS
# ──────────────────────────────────────────────

@app.route('/api/transactions', methods=['GET'])
@auth_required
def get_transactions():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    q = Transaction.query
    if year: q = q.filter_by(year=year)
    if month: q = q.filter_by(month=month)
    rows = q.order_by(Transaction.type, Transaction.id).all()
    return jsonify([{
        'id': r.id, 'year': r.year, 'month': r.month,
        'type': r.type, 'description': r.description, 'amount': r.amount
    } for r in rows])

@app.route('/api/transactions', methods=['POST'])
@auth_required
def add_transaction():
    d = request.json
    t = Transaction(year=d['year'], month=d['month'], type=d['type'],
                    description=d['description'], amount=float(d['amount']))
    db.session.add(t)
    db.session.commit()
    return jsonify({'id': t.id, 'status': 'ok'})

@app.route('/api/transactions/<int:tid>', methods=['PUT'])
@auth_required
def update_transaction(tid):
    t = Transaction.query.get_or_404(tid)
    d = request.json
    t.description = d.get('description', t.description)
    t.amount = float(d.get('amount', t.amount))
    t.type = d.get('type', t.type)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/transactions/<int:tid>', methods=['DELETE'])
@auth_required
def delete_transaction(tid):
    t = Transaction.query.get_or_404(tid)
    db.session.delete(t)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/transactions/summary', methods=['GET'])
@auth_required
def transactions_summary():
    rows = Transaction.query.all()
    summary = {}
    for r in rows:
        key = f"{r.year}-{r.month:02d}"
        if key not in summary:
            summary[key] = {'salary': 0, 'other_income': 0, 'expenses': 0}
        if r.type == 'income_salary': summary[key]['salary'] += r.amount
        elif r.type == 'income_other': summary[key]['other_income'] += r.amount
        else: summary[key]['expenses'] += r.amount
    return jsonify(summary)

# ──────────────────────────────────────────────
# API: ASSETS
# ──────────────────────────────────────────────

@app.route('/api/assets', methods=['GET'])
@auth_required
def get_assets():
    year = request.args.get('year', type=int)
    month = request.args.get('month', type=int)
    q = AssetSnapshot.query
    if year: q = q.filter_by(year=year)
    if month: q = q.filter_by(month=month)
    rows = q.all()
    return jsonify([{
        'id': r.id, 'year': r.year, 'month': r.month,
        'account_name': r.account_name, 'account_type': r.account_type, 'balance': r.balance
    } for r in rows])

@app.route('/api/assets', methods=['POST'])
@auth_required
def add_asset():
    d = request.json
    existing = AssetSnapshot.query.filter_by(
        year=d['year'], month=d['month'], account_name=d['account_name']).first()
    if existing:
        existing.balance = float(d['balance'])
        existing.account_type = d['account_type']
    else:
        a = AssetSnapshot(year=d['year'], month=d['month'],
                          account_name=d['account_name'],
                          account_type=d['account_type'],
                          balance=float(d['balance']))
        db.session.add(a)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/assets/<int:aid>', methods=['DELETE'])
@auth_required
def delete_asset(aid):
    a = AssetSnapshot.query.get_or_404(aid)
    db.session.delete(a)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/assets/history', methods=['GET'])
@auth_required
def assets_history():
    rows = AssetSnapshot.query.order_by(AssetSnapshot.year, AssetSnapshot.month).all()
    history = {}
    for r in rows:
        key = f"{r.year}-{r.month:02d}"
        if key not in history: history[key] = {}
        history[key][r.account_name] = r.balance
    return jsonify(history)

# ──────────────────────────────────────────────
# API: MORTGAGE
# ──────────────────────────────────────────────

@app.route('/api/mortgage', methods=['GET'])
@auth_required
def get_mortgage():
    rows = MortgageEntry.query.order_by(MortgageEntry.year, MortgageEntry.month).all()
    return jsonify([{'id': r.id, 'year': r.year, 'month': r.month,
                     'remaining_balance': r.remaining_balance} for r in rows])

@app.route('/api/mortgage', methods=['POST'])
@auth_required
def add_mortgage():
    d = request.json
    existing = MortgageEntry.query.filter_by(year=d['year'], month=d['month']).first()
    if existing:
        existing.remaining_balance = float(d['remaining_balance'])
    else:
        m = MortgageEntry(year=d['year'], month=d['month'],
                          remaining_balance=float(d['remaining_balance']))
        db.session.add(m)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/mortgage/<int:mid>', methods=['DELETE'])
@auth_required
def delete_mortgage(mid):
    m = MortgageEntry.query.get_or_404(mid)
    db.session.delete(m)
    db.session.commit()
    return jsonify({'status': 'ok'})

# ──────────────────────────────────────────────
# API: STOCKS
# ──────────────────────────────────────────────

@app.route('/api/stocks', methods=['GET'])
@auth_required
def get_stocks():
    rows = StockHolding.query.all()
    return jsonify([{
        'id': r.id, 'symbol': r.symbol, 'purchase_price': r.purchase_price,
        'quantity': r.quantity, 'purchase_date': r.purchase_date, 'notes': r.notes
    } for r in rows])

@app.route('/api/stocks', methods=['POST'])
@auth_required
def add_stock():
    d = request.json
    s = StockHolding(symbol=d['symbol'].upper(), purchase_price=float(d['purchase_price']),
                     quantity=float(d['quantity']),
                     purchase_date=d.get('purchase_date', ''),
                     notes=d.get('notes', ''))
    db.session.add(s)
    db.session.commit()
    return jsonify({'id': s.id, 'status': 'ok'})

@app.route('/api/stocks/<int:sid>', methods=['PUT'])
@auth_required
def update_stock(sid):
    s = StockHolding.query.get_or_404(sid)
    d = request.json
    s.symbol = d.get('symbol', s.symbol).upper()
    s.purchase_price = float(d.get('purchase_price', s.purchase_price))
    s.quantity = float(d.get('quantity', s.quantity))
    s.notes = d.get('notes', s.notes)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/stocks/<int:sid>', methods=['DELETE'])
@auth_required
def delete_stock(sid):
    s = StockHolding.query.get_or_404(sid)
    db.session.delete(s)
    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/stocks/prices', methods=['GET'])
@auth_required
def get_stock_prices():
    """Fetch current prices from Yahoo Finance (free, no API key)"""
    rows = StockHolding.query.all()
    symbols = list(set(r.symbol for r in rows))
    prices = {}
    for sym in symbols:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d"
            resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
            data = resp.json()
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
            prices[sym] = price
        except Exception:
            prices[sym] = None
    return jsonify(prices)

# ──────────────────────────────────────────────
# API: DAUGHTER SAVINGS
# ──────────────────────────────────────────────

@app.route('/api/daughter', methods=['GET'])
@auth_required
def get_daughter():
    rows = DaughterInvestment.query.order_by(DaughterInvestment.year, DaughterInvestment.month).all()
    return jsonify([{
        'id': r.id, 'year': r.year, 'month': r.month,
        'ils_invested': r.ils_invested, 'usd_ils_rate': r.usd_ils_rate,
        'ivv_price_usd': r.ivv_price_usd, 'shares_purchased': r.shares_purchased,
        'cumulative_shares': r.cumulative_shares
    } for r in rows])

@app.route('/api/daughter', methods=['POST'])
@auth_required
def add_daughter_entry():
    d = request.json
    ils = float(d.get('ils_invested', 300))
    rate = float(d['usd_ils_rate'])
    ivv_price = float(d['ivv_price_usd'])
    usd_amount = ils / rate
    shares = usd_amount / ivv_price

    # Get cumulative shares from all sorted entries
    all_entries = DaughterInvestment.query.order_by(
        DaughterInvestment.year, DaughterInvestment.month).all()
    # Find insertion point
    new_key = (d['year'], d['month'])
    prior_cumulative = 0
    for r in all_entries:
        if (r.year, r.month) < new_key:
            prior_cumulative = r.cumulative_shares
    cumulative = prior_cumulative + shares

    entry = DaughterInvestment(
        year=d['year'], month=d['month'], ils_invested=ils,
        usd_ils_rate=rate, ivv_price_usd=ivv_price,
        shares_purchased=round(shares, 6), cumulative_shares=round(cumulative, 6)
    )
    db.session.add(entry)
    db.session.commit()

    # Recompute all entries after this one
    _recompute_daughter_cumulative()
    return jsonify({'status': 'ok', 'shares_purchased': shares, 'cumulative': cumulative})

@app.route('/api/daughter/fetch-prices', methods=['GET'])
@auth_required
def fetch_ivv_prices():
    """Fetch current IVV price and USD/ILS rate"""
    result = {}
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/IVV?interval=1d&range=1d"
        resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        data = resp.json()
        result['ivv_price'] = data['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception as e:
        result['ivv_price'] = None
        result['ivv_error'] = str(e)
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/USDILS=X?interval=1d&range=1d"
        resp = requests.get(url, timeout=5, headers={'User-Agent': 'Mozilla/5.0'})
        data = resp.json()
        result['usd_ils_rate'] = data['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception as e:
        result['usd_ils_rate'] = None
        result['rate_error'] = str(e)
    return jsonify(result)

@app.route('/api/daughter/<int:did>', methods=['DELETE'])
@auth_required
def delete_daughter(did):
    entry = DaughterInvestment.query.get_or_404(did)
    db.session.delete(entry)
    db.session.commit()
    _recompute_daughter_cumulative()
    return jsonify({'status': 'ok'})

def _recompute_daughter_cumulative():
    """Recalculate cumulative shares in chronological order."""
    rows = DaughterInvestment.query.order_by(
        DaughterInvestment.year, DaughterInvestment.month).all()
    cumulative = 0.0
    for r in rows:
        cumulative += r.shares_purchased
        r.cumulative_shares = round(cumulative, 6)
    db.session.commit()

# ──────────────────────────────────────────────
# API: BACKUP / EXPORT / IMPORT
# ──────────────────────────────────────────────

@app.route('/api/export', methods=['GET'])
@auth_required
def export_data():
    """Export entire database as a JSON backup file."""
    data = {
        'exported_at': datetime.utcnow().isoformat(),
        'transactions': [{'year': r.year, 'month': r.month, 'type': r.type,
                          'description': r.description, 'amount': r.amount}
                         for r in Transaction.query.all()],
        'assets': [{'year': r.year, 'month': r.month, 'account_name': r.account_name,
                    'account_type': r.account_type, 'balance': r.balance}
                   for r in AssetSnapshot.query.all()],
        'mortgage': [{'year': r.year, 'month': r.month, 'remaining_balance': r.remaining_balance}
                     for r in MortgageEntry.query.all()],
        'stocks': [{'symbol': r.symbol, 'purchase_price': r.purchase_price,
                    'quantity': r.quantity, 'purchase_date': r.purchase_date, 'notes': r.notes}
                   for r in StockHolding.query.all()],
        'daughter': [{'year': r.year, 'month': r.month, 'ils_invested': r.ils_invested,
                      'usd_ils_rate': r.usd_ils_rate, 'ivv_price_usd': r.ivv_price_usd,
                      'shares_purchased': r.shares_purchased, 'cumulative_shares': r.cumulative_shares}
                     for r in DaughterInvestment.query.order_by(
                         DaughterInvestment.year, DaughterInvestment.month).all()],
    }
    buf = io.BytesIO(json.dumps(data, indent=2).encode('utf-8'))
    buf.seek(0)
    filename = f"family_finance_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    return send_file(buf, mimetype='application/json',
                     as_attachment=True, download_name=filename)

@app.route('/api/import', methods=['POST'])
@auth_required
def import_data():
    """Restore database from a JSON backup (merges, does not wipe)."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    try:
        data = json.load(request.files['file'])
    except Exception as e:
        return jsonify({'error': f'Invalid JSON: {e}'}), 400

    counts = {}
    for row in data.get('transactions', []):
        db.session.add(Transaction(**row))
    counts['transactions'] = len(data.get('transactions', []))

    for row in data.get('assets', []):
        db.session.add(AssetSnapshot(**row))
    counts['assets'] = len(data.get('assets', []))

    for row in data.get('mortgage', []):
        db.session.add(MortgageEntry(**row))
    counts['mortgage'] = len(data.get('mortgage', []))

    for row in data.get('stocks', []):
        db.session.add(StockHolding(**row))
    counts['stocks'] = len(data.get('stocks', []))

    for row in data.get('daughter', []):
        db.session.add(DaughterInvestment(**row))
    counts['daughter'] = len(data.get('daughter', []))

    db.session.commit()
    return jsonify({'status': 'ok', 'imported': counts})

# ──────────────────────────────────────────────
# INIT DB
# ──────────────────────────────────────────────

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
