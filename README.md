# Soldoni

Soldoni is a local Windows application for tracking and analysing a securities
portfolio. It imports Fineco transaction exports and combines them with market
data to provide portfolio analytics and planning tools.

## Screens and components

The sidebar provides six screens. Each screen groups the controls and results
for a specific part of portfolio management.

### Dashboard

- **Aggiorna prezzi** downloads recent prices and exchange rates used by the
  analyses, then reports what was updated and any unavailable data.
- **Stato dei dati** shows how many instruments are included, manually excluded
  or missing data. Its table reports the ticker, latest cached price and exchange
  rate dates, and the status of each holding.
- **Strumenti posseduti** lists held stocks and ETFs with their quantity and
  analysis status. Selecting a row shows its ISIN and ticker and lets you include
  or exclude it from all analyses.
- **Portfolio summary** shows residual invested capital, current value, realised
  net result, unrealised net result and total net gain.
- **Quanto mi costano gli ETF** shows each included ETF's current value, saved TER,
  estimated annual cost, data source and save date, plus the weighted TER and total
  estimated cost. **Aggiorna TER** retrieves available fund expense ratios from
  Yahoo on demand; manually entered values take precedence and can be removed.
  Missing prices or TERs produce an explicitly partial summary. Estimates assume
  constant current holdings values; fund expenses are not deducted again from returns.
- **Benchmark and TWR chart** compares the portfolio with the selected S&P 500 or
  MSCI World benchmark on a base-100, time-weighted basis.
- **Riepilogo per periodo** selects a month, quarter, year or custom date range.
  It shows the result, portfolio TWR, benchmark return, their difference, cash
  movements and the contribution of each instrument.
- **Rendimento & rischio** reports XIRR, annualised volatility, maximum drawdown,
  Sharpe ratio, Sortino ratio and beta against the selected benchmark.
- **Geographical and sector allocation** uses pie charts to show where the
  current portfolio is invested.
- **Positions table** shows each ISIN, instrument name, quantity, average cost,
  current value and gross profit or loss.
- **Attribuzione P/L (lordo)** shows, in a chart and table, how much each holding
  contributes to unrealised, realised and total gross profit or loss.
- **Diversificazione & valuta** reports concentration through HHI, effective
  positions and Top 3/Top 5 weights, and warns about positions above 20%.
- **Currency exposure** shows the portfolio split by quotation currency.
- **P/L latente: prezzo vs cambio** separates unrealised profit or loss caused by
  the instrument price from that caused by exchange-rate movements.
- **Investito vs valore** compares cumulative invested capital with market value
  over time.
- **Mappa del portafoglio** is a treemap in which area represents portfolio weight
  and colour represents each position's profit or loss percentage.
- **Drawdown (TWR)** shows how far the portfolio was below its previous peak at
  each point in time.
- **Investimenti per mese** charts monthly net purchases and sales.
- **Reddito (dividendi)** reports gross and estimated net dividends, gross yield
  on cost and an annual estimate, followed by the cumulative dividend chart.
- **Fisco** reports realised gains, losses, estimated capital-gains tax and the
  remaining tax-loss balance. The year selector creates a downloadable Excel tax
  report.
- **Rischio nel tempo** charts rolling 60-day volatility and beta.
- **Correlazioni tra posizioni** displays a heatmap of daily-return correlations
  between priced holdings.
- **Rendimenti mensili** displays a year-by-month heatmap of portfolio TWR.
- **Rendimento per posizione** compares total return and annualised XIRR for each
  holding using a chart and a table.

### Ribilanciamento

- **Target allocation editor** lists current value and weight for every priced
  holding and lets you enter the desired percentage for each one.
- **Target validation and save** shows the total target percentage, validates that
  the allocation equals 100% and saves the allocation for later use.
- **Operazioni simulate** starts from the average purchases of the previous 12
  complete months. You can enter new cash, choose between purchases and sales or
  new cash only, and set the assumed commission per operation.
- **Operations table** shows the suggested buy or sell action, amount, indicative
  quantity and resulting weight for every affected instrument.
- **Cost summary** reports the number of operations, estimated commissions and
  estimated taxes on sales.
- **Allocation comparison** charts current weights beside the simulated weights.
  The screen only simulates operations and never sends orders to a broker.

### Simulazione

- **Obiettivo capitale** shows the current securities value and the average
  monthly purchases over the previous 12 complete months.
- **Goal inputs** set the target capital, monthly contribution, custom expected
  annual return and volatility, inflation, maximum horizon and whether the target
  should retain today's purchasing power.
- **Goal results** compare the custom scenario with available historical portfolio,
  S&P 500 and MSCI World assumptions. The table shows time to target, success
  probability, favourable and prudent times, and projected final capital.
- **Capital projection chart** plots the median path of every scenario, the
  custom 10th-90th percentile range and the target path.
- **Finanziare o vendere** compares selling securities with a personal loan and a
  mortgage while keeping the same monthly budget.
- **Expense and sale inputs** set the expense, available cash, monthly budget,
  estimated capital-gains tax rate and selling commission.
- **Personal loan inputs** enable or disable the option and set its amount,
  duration, TAN, stated TAEG, initial costs and monthly costs.
- **Mortgage inputs** enable or disable the option and set its amount, duration,
  TAN, stated TAEG, initial costs, monthly costs and estimated annual tax benefit.
- **Financing horizon** sets the comparison period and annual inflation before
  running the alternatives.
- **Financing results** show portfolio value, remaining expense and monthly
  budget, followed by a strategy table with monthly outflow, median net worth,
  difference from selling, probability of doing better, adverse outcome and
  remaining debt.
- **Financing charts and details** show the median net-worth path for each
  historical scenario and a detailed table containing returns, volatility,
  financing costs, estimated sale taxes and break-even return.
- **Stress test - Shock personalizzato** applies a preset or individually edited
  percentage shock to every current position.
- **Stress test - Replay storico** selects a past date range and applies each
  instrument's observed total return in euros to its current value.
- **Stress-test results** report covered value, estimated impact and data coverage,
  with a table containing each instrument's current value, shock, impact and
  stressed value.

### Analizzatore

- **ISIN or ticker search** resolves the entered instrument and starts the market
  and fundamental analysis.
- **Scorecard** shows instrument type and sector, price, composite score, native
  and euro 12-month returns, pillar scores and the underlying metric judgements.
- **Radar and gauges** visualise strengths and weaknesses across scoring pillars
  and place key valuation or ETF cost metrics within coloured threshold bands.
- **Giudizio analisti** shows the mean target, potential upside, recommendation,
  number of analysts and target range when available.
- **Price charts** show the last year of prices in the native currency and the
  corresponding one-year drawdown.
- **P/E storico** shows an equity's trailing P/E over time against its mean and
  standard-deviation band when sufficient EPS data is available.
- **Annual fundamentals** can use absolute or base-100 values and chart revenue,
  net income and free cash flow. It also shows their CAGR, margins, year-on-year
  growth, EPS and the relationship between operating cash flow, capex and FCF.
- **Quarterly fundamentals** show recent revenue, net income and free cash flow,
  together with their latest year-on-year and trailing-twelve-month values.
- **Add to watchlist** stores the analysed instrument for comparisons.
- **I miei ETF vs le mie azioni vs S&P 500** groups all imported ETF and stock
  transactions, including closed positions and respecting analysis exclusions.
  **Confronta tutto il mio storico** loads histories on demand. Returns in euros
  include recorded dividends and trading commissions. **Dall'inizio** shows each
  group's full history; **Stesso periodo** rebases the lines on common dates.
  The summary compares returns, maximum drawdown and the S&P 500 total-return
  benchmark over that common period. Missing data prevents a partial group from
  being presented as the return of all holdings.
- **Confronto ETF e azioni** compares two to six holdings or watchlist instruments
  over one, three or five years, or a custom date range. **Confronta** loads adjusted
  price histories and exchange rates on demand and charts total returns in euros,
  starting from 100 on common quotation dates. The chart reports its actual period,
  supports interactive legend toggles and identifies instruments with unavailable data.
- **Tavolo di confronto** ranks watchlist instruments by composite and pillar
  scores and displays the composite-score chart.
- **Confronto fondamentale** compares selected watchlist companies by financial
  metric and view, with a historical chart and summary table.
- **Watchlist removal** removes the selected ticker from the comparison list.

### Scopri

- **Instrument type** switches the search between stocks and ETFs.
- **Basic filters** select regions. Stock searches also provide sector and minimum
  market capitalisation, while ETF searches explain the EU/UCITS consideration.
- **Advanced stock filters** cover valuation, profitability, margins, growth,
  dividends, leverage and liquidity ratios.
- **Advanced ETF filters** cover category, maximum TER, minimum one-, three- and
  five-year returns, Morningstar rating and assets under management.
- **Candidate limit and search** choose how many instruments to analyse and query
  the Yahoo screener. Existing holdings and watchlist entries are excluded.
- **Results table** ranks candidates by composite and pillar scores and includes
  the most relevant raw stock or ETF metrics.
- **Candidate detail** shows every metric, its value and its scoring band for the
  selected result.
- **Composite-score chart** compares the ranked candidates visually.
- **Add to watchlist** adds one or more selected candidates to the Analyzer
  watchlist.
- **Availability notices** report active filters when no result is found and list
  candidates skipped because price or fundamental data was unavailable.

### Import & Anagrafica

- **Fineco Excel import** accepts the `Movimenti Dossier Titoli` workbook and
  prepares an import preview before changing stored data.
- **Import preview** reports read, new and duplicate operations and new instrument
  records. It shows new rows, duplicate details and accounting conflicts, then
  confirms only valid new data and creates a safety backup.
- **Backup e ripristino** creates a backup on demand, lists available copies with
  date and size, downloads the selected copy and restores it after explicit
  confirmation. A preventive copy is created before restoring.
- **Inserimento manuale operazione** records date, ISIN, operation type, quantity,
  euro amount and an optional commission.
- **Anagrafica strumenti** highlights unmapped ISINs and edits the selected
  instrument's Yahoo ticker, analysis status, name, native currency, macro area,
  type and sector.
- **Ticker verification** can resolve or verify the Yahoo ticker automatically
  when the instrument record is saved.
- **Optional allocation details** accept geographical and sector weights as JSON
  for more accurate allocation charts.

## Requirements

- Windows 10 or Windows 11.
- Python 3.13, available from [python.org](https://www.python.org/downloads/windows/).
- An internet connection during setup and when downloading market data.

## Quick start

Download or clone the project, extract the ZIP if needed, and double-click
**Start Soldoni.cmd** in the project folder.

The launcher installs the required dependencies on first use. Once setup succeeds,
later launches open the application directly. If setup fails, fix the reported
problem and double-click the same launcher again.

Python 3.13 must already be installed. If it is missing, the launcher shows where
to download it.

Streamlit opens the application in the default web browser. Keep the terminal
window open while using the application.

## Fineco import

In Fineco, export the securities transactions workbook containing the
`Movimenti Dossier Titoli` sheet. Open **Import & Anagrafica** in Soldoni,
select the workbook, review the preview and confirm the import.

## Desktop application

To build the native Windows application, run:

```powershell
.\build.ps1
```

The build uses the same virtual environment prepared by `setup.cmd`. The
resulting application is written to `dist\Soldoni\Soldoni.exe`.

## Project structure

- `soldoni/app`: Streamlit dashboard and desktop launcher.
- `soldoni/core`: portfolio calculations and analysis.
- `soldoni/data`: storage, imports and market-data access.
- `tests`: automated tests.

## Disclaimer

Soldoni is provided for informational and educational purposes only. It does
not provide financial, investment or tax advice. Always verify calculations
and decisions independently.
