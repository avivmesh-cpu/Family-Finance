# October 2026 dashboard import — from screenshots (user sends, no spreadsheet)

Status: collecting. Rule: subscriptions standalone; variable aggregated; mortgage standalone (user reports fresh monthly).

## Confirmed amounts (2026-10-16)
- משכנתא (mortgage, Oct): ₪12,527.22 — Bank Hapoalim screenshot
- Mortgage balance: ₪1,458,094.02
- Account balance (עו"ש): ₪8,568.34

## Income (screenshot 2)
- Aviv salary (Oct 1, "המבצע: סיטי בנק"): +₪15,723
- Inbal salary (Oct 7, Bank Mizrahi): +₪24,688.32

## Bank balances (reference)
- Bank Hapoalim עו"ש: ₪8,568.34
- Bank Mizrahi עו"ש: ₪12,285.20

## Expenses (screenshot 2)
- ועד הבית (טירת צבי 8 תל א, הוראת קבע, Oct 9): ₪305
- עמלות בנק (ע.מפעולות-ישיר, Oct 4): ₪8.75
- עמ' הקצאת אשראי (Oct 4, ערך 1.10): ₪12

Running expense subtotal: ₪325.75

## Card exports received 2026-10-16 (user decisions)
- Inbal's card: ₪32,057.62 (billed 11/10/2026), 63 transactions.
- Aviv's card (6132): ₪10,009.39 (billed 10/10/2026), 76 transactions.
- A THIRD card is still coming — do NOT import until it arrives.
- Bit transfers ₪2,923 (1000 + 1820 + 103) → expense, category שונות.
- PayBox ₪250 (Aviv) → expense, category שונות.
- PayPal MEI-AVIVIM ₪206.68 → [Utilities] חשבון מים (water bill).
- Bank fees ₪8.75 + ₪12 = ₪20.75 → both Bank Hapoalim → [Other] עמלות בנק הפועלים. Mizrahi fees stay 0.
- Planned mapping: ארנונה ₪957.11 → [Housing] ארנונה; חשמל ₪1,024.26 → [Utilities] חשבון חשמל; גז ₪154.61 → [Utilities] חשבון גז; subs standalone (HOT/Partner/Cellcom/HOT Mobile/Google One/Spotify ₪67.80/CELLO ₪387.95/Netflix ₪65.80 new line); mortgage ₪12,527.22; ועד בית ₪305.

## Import executed 2026-10-16
- Built /tmp/october-2026-dashboard-lines.xlsx from both card exports (29 lines, ₪42,392.76 reconciled exactly: Inbal 32,057.62 + Aviv 10,009.39 + manual 325.75).
- Ran import_expenses.py --year 2026 --month 10 --mortgage 12527.22: 22 updated, 8 created (Netflix, [Housing] ארנונה, [Housing] ועד בית, [Other] עמלות בנק הפועלים, [Utilities] חשבון חשמל/גז/מים, משכנתא).
- Income set: Inbal Salary ₪24,688.32, Aviv Salary ₪15,723.
- Expense total ₪54,919.98; income total ₪40,411.32.
- Fixed import_expenses.py login bugs (missing Content-Type on /login POST; session cookie lost across redirect — now uses CookieJar).
- PRECISION BUG: transactions.amount was Postgres REAL (float4) — 12527.22 stored as 12527.2, 24688.32 as 24688.3. Fixed in app.py: DDL now DOUBLE PRECISION + startup migration (DO block, PG-only). Pushed b358f7e to GitHub; awaiting Render redeploy, then re-PUT the two values.
- NOTE: gh-push needs PYTHONPATH=/opt/muse/skills/custom-connector-setup/bin (dynamic_credentials moved from templates/skill/bin after a deployment).
