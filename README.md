# Stockbonder

Raccolta di strumenti finanziari indipendenti. Ogni strumento vive nella propria cartella sotto `tools/`, con dipendenze, istruzioni e avvio propri.

## Strumenti

| Strumento | Descrizione | Percorso |
| --- | --- | --- |
| Bond Atlas | Curve governative globali e confronto dei singoli governativi in euro per rendimento e duration | [tools/bond-atlas](tools/bond-atlas/README.md) |

## Avviare Bond Atlas in locale

Occorre Node.js 24 o successivo. Dalla cartella della repository:

```sh
cd tools/bond-atlas
npm ci
npm run build:local
npm run start:local
```

La dashboard si apre su http://127.0.0.1:8787. Per arrestarla: `npm run stop:local` dalla stessa cartella.

Su Windows, dopo installazione e build, si possono usare anche `Avvia Bond Atlas.cmd` e `Arresta Bond Atlas.cmd` nella cartella del tool. Non è richiesto un account ChatGPT. L'aggiornamento dei dati richiede Internet; le rilevazioni salvate restano consultabili offline con la data originale.

## Aggiungere un altro strumento

Creare `tools/nome-strumento/` e includere un README con requisiti, installazione, avvio e verifiche. Aggiungere il tool alla tabella sopra. Non occorre modificare o condividere le dipendenze di Bond Atlas.

Dipendenze installate, build, credenziali e cache locali non vanno aggiunte alla repository.

## Cronologia

La repository parte da un unico commit iniziale con Bond Atlas in `tools/bond-atlas/`, pronto per accogliere altri strumenti finanziari.
