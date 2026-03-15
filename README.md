# Family Finance Dashboard

A personal financial dashboard built with Flask + SQLite. Track income, expenses, assets, mortgage, stock portfolio, and your daughter's IVV savings.

## Quick Start (Local)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
python app.py

# 3. Open http://localhost:5000
```

## Project Structure

```
family-finance/
├── app.py                    # Flask app + all API routes
├── requirements.txt
├── Procfile                  # For Render/Railway deployment
├── README.md
├── instance/
│   └── family_finance.db     # SQLite database (auto-created)
├── static/
│   ├── css/main.css          # All styles
│   └── js/utils.js           # Shared JS utilities
└── templates/
    ├── base.html             # Layout + navigation
    ├── index.html            # Overview dashboard
    ├── income_spending.html  # Income & expenses
    ├── assets.html           # Total assets
    ├── mortgage.html         # Mortgage tracking
    ├── stocks.html           # Stock portfolio
    └── daughter_savings.html # Daughter IVV savings
```

## Database Schema

### `transaction` table
| Column | Type | Description |
|---|---|---|
| id | Integer PK | |
| year, month | Integer | Entry month |
| type | String | `income_salary`, `income_other`, `expense` |
| description | String | Line item description |
| amount | Float | Amount in ILS |

### `asset_snapshot` table
| Column | Type | Description |
|---|---|---|
| id | Integer PK | |
| year, month | Integer | Snapshot month |
| account_name | String | e.g. "Bank Hapoalim" |
| account_type | String | `bank`, `stocks`, `education`, `other` |
| balance | Float | Balance in ILS |

### `mortgage_entry` table
| Column | Type | Description |
|---|---|---|
| id | Integer PK | |
| year, month | Integer | Entry month |
| remaining_balance | Float | Remaining mortgage in ILS |

### `stock_holding` table
| Column | Type | Description |
|---|---|---|
| id | Integer PK | |
| symbol | String | Ticker, e.g. "AAPL" |
| purchase_price | Float | Average cost in USD |
| quantity | Float | Number of shares |
| purchase_date | String | Optional |
| notes | String | Optional |

### `daughter_investment` table
| Column | Type | Description |
|---|---|---|
| id | Integer PK | |
| year, month | Integer | Investment month |
| ils_invested | Float | ILS amount (default 300) |
| usd_ils_rate | Float | Exchange rate at purchase |
| ivv_price_usd | Float | IVV price at purchase |
| shares_purchased | Float | Shares bought that month |
| cumulative_shares | Float | Running total |

## Deployment on Render.com (Free)

1. Push this folder to a GitHub repository
2. Go to [render.com](https://render.com) → New Web Service
3. Connect your GitHub repo
4. Set:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Environment:** `SECRET_KEY = your-random-secret`
5. Deploy! Free tier spins down after inactivity but works great for personal use.

## Deployment on Railway.app (Alternative Free)

1. Install Railway CLI: `npm install -g @railway/cli`
2. `railway login && railway init && railway up`

## API Endpoints

| Method | URL | Description |
|---|---|---|
| GET/POST | `/api/transactions` | List or add transactions |
| PUT/DELETE | `/api/transactions/<id>` | Edit or delete |
| GET | `/api/transactions/summary` | Monthly summaries |
| GET/POST | `/api/assets` | Asset snapshots |
| DELETE | `/api/assets/<id>` | Delete asset |
| GET | `/api/assets/history` | Historical balances |
| GET/POST | `/api/mortgage` | Mortgage entries |
| DELETE | `/api/mortgage/<id>` | Delete entry |
| GET/POST | `/api/stocks` | Stock holdings |
| PUT/DELETE | `/api/stocks/<id>` | Edit/delete holding |
| GET | `/api/stocks/prices` | Live prices (Yahoo Finance) |
| GET/POST | `/api/daughter` | Daughter savings entries |
| DELETE | `/api/daughter/<id>` | Delete (auto-recalculates) |
| GET | `/api/daughter/fetch-prices` | Live IVV price + USD/ILS rate |

## Data Entry Workflow (15th of each month)

1. **Income & Spending** → Select month → Add salary rows + expense rows → Save
2. **Total Assets** → Select month → Update all account balances → Save All
3. **Mortgage** → Add remaining balance for the month
4. **Stocks** → Update positions as needed → Refresh prices
5. **Daughter Savings** → Click "Fetch Live Prices" → Save investment

## Notes

- Stock prices and IVV/USD rates are fetched from Yahoo Finance (no API key needed)
- All data is stored locally in SQLite — back up `instance/family_finance.db` regularly
- For production, consider adding basic HTTP auth (e.g. Flask-HTTPAuth) to protect the dashboard
