# Stock Platform

Script Python per ottenere la lista delle societa quotate su Borsa Italiana,
Xetra, LSE, NYSE o NASDAQ e scaricare metriche fondamentali correnti tramite
Yahoo Finance via `yfinance`.

## Installazione

Requisito: Python 3.10 o successivo. Eseguire i comandi dalla cartella
`tools/stock-platform`, indipendente da Bond Atlas.
Creare e attivare un ambiente virtuale (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Su macOS/Linux: `python3 -m venv .venv` e `source .venv/bin/activate`.
Poi installare la dipendenza per il download dei fondamentali:

```powershell
python -m pip install -r requirements.txt
```

Per avviare l'interfaccia completa: `python .\stock_platform.py`, poi aprire
http://127.0.0.1:8767/. Per arrestarla premere Ctrl+C. Su Windows si può usare
anche `Avvia Stock Platform.cmd`, che usa automaticamente `.venv` se presente.
Le porte dei due viewer separati sono 8765 e 8766; Bond Atlas usa 8787.

Sono inclusi gli script, le interfacce HTML e tutte le configurazioni originali,
comprese varianti e archivi. Gli export storici di `idea2` non sono versionati:
`outputs/` viene creata all'avvio, mentre CSV, JSONL, checkpoint e cache restano
locali. Per recuperare dati precedenti, copiarli nelle sottocartelle
`outputs/fundamentals/` e `outputs/fitness/` del tool.
Gli esempi con `test_dataset.csv` richiedono un proprio CSV di fondamentali.
Scoring e viewer funzionano offline; download dei fondamentali e cambi richiedono Internet.

## Verifiche

```powershell
python -m compileall -q .
python .\market_fundamentals.py --help
python .\fitness_score.py --help
python .\stock_platform.py --help
```

Per verificare il flusso completo, scaricare un piccolo CSV e calcolarne lo score:

```powershell
python .\market_fundamentals.py --market borsa --limit 3 --output prova.csv
python .\fitness_score.py --input prova.csv --config config --output prova_fitness.csv
```

## Export dei dati

Scarica i primi 30 titoli di Borsa Italiana in CSV:

```powershell
python .\market_fundamentals.py --market borsa --limit 30 --output borsa.csv
```

Scarica i primi 30 titoli Xetra in CSV:

```powershell
python .\market_fundamentals.py --market xetra --limit 30 --output xetra.csv
```

Scarica i primi 30 titoli LSE in CSV:

```powershell
python .\market_fundamentals.py --market lse --limit 30 --output lse.csv
```

Per diagnostica, includi anche i ticker senza settore nei fondamentali:

```powershell
python .\market_fundamentals.py --market all --include-sectorless --output all_markets_con_senza_settore.csv
```

Scarica NASDAQ completo in JSON Lines:

```powershell
python .\market_fundamentals.py --market nasdaq --format jsonl --output nasdaq.jsonl
```

Test veloce su NYSE:

```powershell
python .\market_fundamentals.py --market nyse --limit 20 --workers 2
```

Esporta tutti i mercati supportati nello stesso formato CSV, solo azioni:

```powershell
python .\market_fundamentals.py --market all --format csv --workers 2 --retries 3 --retry-sleep 10 --output all_markets.csv
```

Esporta anche fallback da bilanci e cash flow, piu lento ma piu completo:

```powershell
python .\market_fundamentals.py --market all --deep-fundamentals --format csv --workers 2 --retries 3 --retry-sleep 10 --output all_markets_deep.csv
```

Aggiungi anche l'ISIN all'anagrafica:

```powershell
python .\market_fundamentals.py --market all --include-isin --format csv --workers 2 --retries 3 --retry-sleep 10 --output all_markets_isin.csv
```

Durante l'esecuzione lo script scrive su console lo stato di avanzamento
tramite `stderr`, quindi non sporca CSV/JSON scritti su `stdout`. Per
disabilitare i messaggi:

```powershell
python .\market_fundamentals.py --market all --quiet --output all_markets.csv
```

Quando usi `--output`, durante l'export dei fondamentali lo script aggiorna
anche un checkpoint accanto al file finale, ad esempio
`all_markets.csv.partial`. Il checkpoint viene scritto agli stessi scatti dei
log di avanzamento, quindi di norma ogni 50 ticker nei run grandi, e viene
rimosso dopo una scrittura finale riuscita. Se lo script riparte e trova quel
`.partial`, chiede se vuoi riprendere dai record gia salvati; rispondi `y` per
saltare i ticker gia presenti, premi `Invio` per accettare il default `y`,
rispondi `n` per ricominciare da zero, oppure `Ctrl+C` per annullare il run.

Solo elenco simboli, senza fondamentali:

```powershell
python .\market_fundamentals.py --market nasdaq --list-only --output nasdaq_symbols.csv
```

Includi anche ETF o strumenti non ordinari:

```powershell
python .\market_fundamentals.py --market nyse --include-etfs --include-non-common
```

Includi anche il Global Equity Market di Borsa Italiana:

```powershell
python .\market_fundamentals.py --market borsa --include-borsa-gem --output borsa_con_gem.csv
```

## Calcolo fitness

Calcola un punteggio fitness 0-10 dal CSV dei fondamentali:

```powershell
python .\fitness_score.py --input .\test_dataset.csv --config .\config --output .\test_dataset_fitness.csv
```

La cartella di configurazione contiene uno o piu JSON di scoring. Ogni file
indica in `sectors` i settori per cui deve essere usato e in `scores` le
metriche da valutare. Una stringa vuota in `sectors` indica la configurazione
generale di fallback. In alternativa, un JSON puo indicare una lista
`industries`: queste configurazioni hanno precedenza su quelle per `sector`,
utile quando due industrie dello stesso settore richiedono metriche diverse.

Per ogni riga lo script sceglie il JSON in base alla colonna `sector`,
o prima alla colonna `industry` quando esiste una configurazione specifica,
moltiplica ogni valore CSV per `prefactor`, interpola linearmente sui `points`,
calcola la media pesata con `weight` e sottrae `penalty` quando il valore della
metrica manca o non e numerico. Nel CSV di output la colonna `fitness_config`
mostra quale JSON e stato usato per valutare ogni azienda.

`fitness_score.py` calcola anche metriche derivate da campi gia presenti nel
CSV, come `fcf_margin_pct`, `operating_cash_flow_to_net_income`,
`cash_to_debt_pct` e `net_cash_to_market_cap_pct`. Queste metriche possono
quindi essere usate dai JSON anche con export fondamentali vecchi. Se invece
manca una metrica non derivabile, lo script mostra un avviso e la valuta come
dato mancante, senza interrompere il calcolo.

La colonna `valid_score_weight_pct` indica in percentuale quanto peso della
configurazione scelta e entrato davvero nella media prima delle penalita.

## Stock Platform

Avvia la piattaforma locale unificata:

```powershell
python .\stock_platform.py
```

Poi apri `http://127.0.0.1:8767/`. La piattaforma racchiude in una singola
web app responsive:

- lancio di `market_fundamentals.py` con opzioni, output e progress log;
- lancio di `fitness_score.py` su CSV e configurazioni selezionate;
- cartelle operative in topbar per fondamentali, ranking e config, con chooser
  cartelle interno e inserimento manuale;
- pulizia guidata delle cartelle output con anteprima e conferma;
- storico job della sessione con log, percentuale stimata e cancellazione;
- viewer dei JSON in `config`, incluse regole, pesi, penalita e curve;
- viewer CSV con ricerca, filtri inclusa market cap, ordinamento, preset
  colonne, colonne fissabili, scroll laterale assistito, barre voto, basket
  builder, autofill, ribilanciamento ed export.

Le cartelle in topbar sono la sorgente per tutte le sezioni: il job fondamentali
scrive nella cartella fondamentali, il fitness score legge da li e scrive nella
cartella ranking, le valutazioni leggono solo i JSON nella root config
selezionata salvo checkbox per includere le sottocartelle, il cleanup pulisce le
cartelle output e il viewer ranking mostra solo i CSV presenti nella cartella
ranking selezionata. La piattaforma mantiene gli script originali separati e li
esegue come subprocess, cosi restano usabili anche da terminale.

## Score config viewer

Avvia il server locale della UI grafica:

```powershell
python .\score_config_viewer.py
```

Poi apri `http://127.0.0.1:8765/`. La UI legge i JSON in `config`,
mostra settori/industrie, pesi, penalita, punti, segmenti e la curva di
interpolazione lineare per ogni metrica.

## StockMix Lab

Avvia il server locale per consultare e filtrare i CSV prodotti dagli script:

```powershell
python .\csv_output_viewer.py
```

Poi apri `http://127.0.0.1:8766/`. La UI elenca i CSV nella cartella del
progetto, carica di default `test_dataset_fitness.csv` quando presente, e
permette ricerca globale, filtri multipli, ordinamento, scelta colonne,
dettaglio riga, basket di stock, composizione per settori/paesi, distribuzione
dei voti, grafici a torta per settori/paesi, autofill del basket ed export
delle righe filtrate o del basket.
Le colonne vengono lette direttamente dall'intestazione del CSV, quindi
metriche e score possono aumentare o diminuire senza modifiche al viewer.

Nel basket puoi scegliere la colonna voto da usare, aggiungere manualmente la
riga selezionata, oppure usare `Autofill` indicando il numero di stock e,
quando serve, il capitale totale da allocare. L'autofill usa le righe
correntemente filtrate come universo di partenza, puo applicare un filtro min/max
sulla market cap in EUR, un minimo di completezza `valid_score_weight_pct` e un
voto minimo per ogni indicatore `_score`, con un numero massimo configurabile di
eccezioni sotto soglia; poi seleziona i voti piu alti rispettando cap massimi per
settore e paese, e penalizza industrie gia rappresentate per diversificare meglio
le scelte. I pulsanti `Cfg out` e `Cfg in` esportano e importano un JSON con la
configurazione dell'autofill, inclusi numero stock, colonna voto, capitale, cap e
filtri market cap/qualita voto. Ogni stock del basket puo avere quantita e
prezzo:
se il CSV contiene una colonna prezzo riconoscibile viene proposta in automatico,
altrimenti il prezzo resta compilabile a mano. Il capitale e i controvalori sono
in EUR; se il CSV contiene una colonna `currency`, il viewer scarica i cambi ECB
tramite `/api/fx`, li tiene in cache lato server e converte i prezzi nella valuta
della riga. Quando esiste controvalore, i grafici di voti, paesi e settori sono
ponderati per valore investito invece che per semplice conteggio; l'export del
basket aggiunge anche quantita, valuta, prezzo originale, prezzo EUR e
controvalore EUR. I pulsanti `Mkt cap` e `Score` ricalcolano le quantita delle
stock gia presenti nel basket ripartendo il capitale EUR in proporzione alla
market cap o alla colonna voto selezionata, sempre usando quote intere. Il corpo
del basket puo essere compresso con `Comprimi`,
lasciando visibili riepilogo, selettori e pulsanti operativi. Nella lista del
basket il pulsante `Vai` porta subito la stock alla pagina corretta della tabella
e la evidenzia. Sulla tabella sono disponibili tasti di scroll orizzontale e ogni
intestazione ha una puntina per bloccare o sbloccare la colonna; quando esiste,
`name` viene bloccata di default.

## Fonti e note

- NYSE/NASDAQ: Nasdaq Trader Symbol Directory.
- Borsa Italiana: screener Yahoo Finance con `region=it`, `exchange=MIL` e
  filtro `intradaymarketcap > 0`.
- Xetra: screener Yahoo Finance con `region=de`, `exchange=GER` e filtro
  `intradaymarketcap > 0`.
- LSE: screener Yahoo Finance con `region=gb`, `exchange=LSE` e filtro
  `intradaymarketcap > 0`.
- Fondamentali: Yahoo Finance via `yfinance`.
- Con `--deep-fundamentals`, lo script scarica anche income statement, balance
  sheet e cash flow da Yahoo per riempire campi mancanti e calcolare metriche
  derivate. Per lo stato patrimoniale prova prima i dati trimestrali e poi
  ripiega sull'annuale. E piu lento e puo aumentare il rischio di rate limit.
- Con `--include-isin`, lo script aggiunge la colonna `isin` usando il lookup
  sperimentale di `yfinance`. E una chiamata aggiuntiva per ticker, quindi e
  piu lenta e non sempre disponibile per ogni quotazione/suffisso. I valori
  vengono validati con check-digit ISIN; se la fonte restituisce un valore
  non valido, il campo resta vuoto.
- Per default Borsa Italiana prova a restare sulle sole azioni: esclude
  ETF/ETP quando Yahoo li marca come tali, i ticker `.MI` che iniziano con una
  cifra, e codici certificate-like come `F68982.MI` che Yahoo a volte marca
  erroneamente come `EQUITY`. I `1...` sono trattati come Global Equity Market,
  per esempio `1AAPL.MI` o `19MW.MI`; puoi riattivare i soli GEM `1...` con
  `--include-borsa-gem`.
- Per default Xetra usa lo stesso filtro server-side sul market cap e scarta
  righe senza nome o con descrizioni tipiche di certificati/warrant, mantenendo
  i ticker azionari tedeschi anche se contengono numeri.
- Per default LSE usa lo stesso filtro server-side sul market cap e scarta
  righe senza nome, ticker che iniziano per `0`, o descrizioni tipiche di
  certificati/warrant. Il filtro sui ticker `0...` vale sia con `--market lse`
  sia quando LSE viene incluso da `--market all`.
- Per default l'export dei fondamentali scarta le righe senza `sector`, per
  tutti i mercati e anche con `--market all`. Puoi mantenerle con
  `--include-sectorless`. `--list-only` non applica questo filtro perche non
  scarica i fondamentali.
- Per default NYSE/NASDAQ esclude ETF e strumenti come rights, units,
  warrants, preferred e notes; puoi riattivarli con `--include-etfs` e
  `--include-non-common`.
- `--market all` esporta Borsa Italiana, Xetra, LSE, NYSE e NASDAQ nello
  stesso file; se usi `--limit`, il limite viene applicato a ciascun mercato.

Le colonne percentuali sono normalizzate in percentuale quando Yahoo restituisce
un rapporto, ad esempio `roe_pct = returnOnEquity * 100`. Per il debito su
equity vengono salvate entrambe le forme: `debt_to_equity_pct` e
`debt_to_equity_ratio`.

Alcuni valori possono restare vuoti anche con `--deep-fundamentals`: succede
quando Yahoo non pubblica bilanci per quel ticker/suffisso, quando il titolo e
un cross-listing con dati disponibili solo sulla quotazione principale, o quando
la metrica non e significativa per banche, assicurazioni o societa molto nuove.
La colonna `statements_loaded` indica se sono stati trovati dati di bilancio.

Metriche aggiuntive utili per analisi fondamentale includono ricavi, utile
netto, gross profit, EBITDA, EBIT, free cash flow, operating cash flow, equity,
asset, liabilities, net debt, margini, EV/Revenue, EV/EBITDA, Price/Sales,
FCF yield, leverage, interest coverage, asset turnover, payout ratio e dati
base su analyst target e ownership istituzionale/insider quando disponibili.
Quando operating cash flow e capital expenditure sono disponibili, il free cash
flow viene calcolato come `operating_cash_flow - capex` se il capex e positivo,
oppure `operating_cash_flow + capex` se Yahoo lo restituisce gia con segno
negativo. Il valore `freeCashflow` gia pronto di Yahoo viene usato solo come
fallback.

Yahoo Finance e `yfinance` sono comodi per ricerca/personale, ma non sono un
feed ufficiale garantito per uso professionale o trading.
