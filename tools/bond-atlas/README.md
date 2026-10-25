# Bond Atlas

Dashboard in italiano con selezione di singoli governativi EUR di 21 paesi europei e curve ufficiali di USA, Germania, Regno Unito, Giappone e Canada.

## Avvio
- Versione locale Windows: doppio clic su `Avvia Bond Atlas.cmd`; per chiuderla, `Arresta Bond Atlas.cmd`. Indirizzo `http://127.0.0.1:8787`.
- La versione locale usa Node 24, una build Vite separata e un server HTTP sul solo loopback. Non richiede ChatGPT, account cloud o Cloudflare. Conserva le rilevazioni scaricate in `.sites-runtime/local-app`; le date dei dati e i limiti di freschezza restano invariati.
- Rigenerare solo la versione locale: `node node_modules/vite/bin/vite.js build --config vite.local.config.mts`. Avvio da terminale: `node scripts/local-launcher.mjs start`; arresto: stesso comando con `stop`. `start --offline` usa esclusivamente le copie locali, senza chiamare le fonti; `--no-browser` evita l'apertura del browser.
- Node 24 o successivo.
- Da una copia appena scaricata: `npm ci`, poi `npm run build:local`. Avviare con `npm run start:local` o con il file Windows.
- I comandi di questo documento si eseguono dalla cartella `tools/bond-atlas`.
- Anteprima: `npm run dev`
- Verifica: `node scripts/verify.mjs`, `node scripts/verify-euro.mjs` e `npx tsc --noEmit`
- Build: `npm run build`
- Aggiornamento dello snapshot distribuito: `node scripts/snapshot.mjs`

## Dati e metodo
Le fonti pubbliche sono U.S. Treasury, Bundesbank, Bank of England, Ministry of Finance Japan e Bank of Canada. La route /api/curves recupera le cinque curve e memorizza le risposte per 15 minuti. In caso di errore mantiene l'ultima rilevazione o lo snapshot incorporato, esplicitamente segnalato.

Le curve sono mostrate con la propria data, valuta e metodo. Il Canada viene pubblicato con ritardo. La Germania copre 1–10 anni; gli altri mercati fino a 30 anni. UK/Canada: spot continui trasformati in par annuali. USA/Giappone: tassi semestrali trasformati in equivalenti annui. I JGB sono benchmark, non una curva par pura.

La duration e gli shock si riferiscono a un titolo teorico con cedola annuale pari al rendimento e rimborso a 100. Con rendimenti negativi si usa cedola zero. Non rappresentano la duration dei singoli ISIN. Gli shock sono variazioni immediate del prezzo da riprezzamento dei flussi, non previsioni di rendimento totale.

Lo sweet spot massimizza y − λD entro il limite di duration, considerando solo punti non dominati e risolvendo le parità a favore della duration minore. Non comprende cambio/copertura valutaria, rischio di credito, liquidità, imposte, costi, roll-down o reinvestimento.

## Verifiche
I controlli automatici includono prezzi noti, duration numerica e analitica, tassi zero/negativi, conversione di curve piatte, vincoli, curve inverse, preferenze monotone, scenari di prezzo e parser CSV/XML/XLSX con campioni ufficiali registrati il 7 ottobre 2026. I campioni sotto tests/fixtures sono immutabili e non costituiscono un feed aggiornato.

Lettura delle cinque fonti e risposta della route locale verificate. La versione di produzione è stata verificata localmente in Edge senza errori JavaScript: cambio paese, selezione degli assi, confronto curve, cursori da tastiera, scenario tassi, tabella e layout desktop/mobile. WebMCP non disponibile nel browser di verifica: i relativi strumenti opzionali si registrano solo quando document.modelContext è disponibile.

## Estensioni
La vista iniziale «Titoli in euro» copre Austria, Belgio, Bulgaria, Cipro, Croazia, Estonia, Finlandia, Francia, Germania, Grecia, Irlanda, Italia, Lettonia, Lituania, Paesi Bassi, Polonia, Portogallo, Romania, Slovenia, Spagna e Ungheria. Sono comprese le sole emissioni EUR coperte dalla fonte, non l'intero debito di ogni Stato.

### Dati dei singoli titoli
Fonte indipendente: [Simple tools for investors, export End of Day](https://www.simpletoolsforinvestors.eu/documentivari.php), con [guida ai calcoli](https://www.simpletoolsforinvestors.eu/monitors-guide.shtml). Si scopre il collegamento CSV corrente dalla pagina download, senza fissarne il nome. Prezzo, yield lordo e duration provengono dalla stessa riga e dalla stessa data; il monitor europeo fornisce il tipo di calcolo e il collegamento alla scheda. Le strutture non riconosciute sono escluse, mai inferite dal prefisso ISIN. Il paese viene dal campo emittente GOV_XX. Non si usa scraping di Borsa Italiana.

La route `/api/bonds` ha cache in memoria di sei ore e condivide le richieste in corso. In caso di errore usa la copia salvata, la segnala e attende cinque minuti prima di ritentare. La data originaria non cambia. Lo snapshot distribuito si aggiorna con `node scripts/euro-snapshot.mjs`; non viene generato alcun prezzo simulato. Nessuna automazione ricorrente o scrittura di dati utente.

Sono ammessi solo tasso fisso semplice e zero coupon, escludendo indicizzati, step-up e opzioni. Il candidato di ogni paese massimizza y − λD fra i titoli compatibili: rilevazione entro quattro giorni di calendario, tipo prezzo LP con volume positivo, lotto massimo, volume giornaliero minimo, scadenza residua minima e duration massima. Parità: duration minore, poi volume maggiore, poi ISIN. Se non ci sono titoli compatibili, il candidato è assente. Il rischio di credito non è modellato e non c'è una graduatoria fra Stati. I volumi sono nominali giornalieri, non spread denaro/lettera. Prezzi di chiusura/ultimo scambio, non prezzi lettera eseguibili.

Il grafico collega titoli reali con scambi recenti; non è una curva ufficiale par/spot. Le curve globali conservano il metodo precedente. Gli scenari del singolo titolo sono solo l'approssimazione lineare −D × Δy, senza convessità o rendimento da detenzione; gli scenari globali restano riprezzamenti dei titoli teorici.

I test EUR usano export e monitor del 20 ottobre 2026 congelati sotto `tests/fixtures`. Verificano coerenza della riga di origine, date, strutture ammesse, tutti i filtri, assenza di vincitore, dominanza, parità e shock. Gli snapshot non sono presentati come dati in tempo reale. Il sito resta privato con il pubblico esistente.
