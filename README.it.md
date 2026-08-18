<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.md">English</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="docs/assets/logo.png" alt="prompt-craft" width="820">
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/prompt-craft/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/prompt-craft/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
</p>

#

**Indica cosa deve contenere l'immagine. Verifica che lo contenga. Rifiuta se non lo fa.**

Un flusso di lavoro generativo per la creazione di immagini ti fornirà volentieri un personaggio con il volto sbagliato, una palette colori errata e senza elementi distintivi della fazione, segnalando comunque l'avvenuta esecuzione perché apparentemente tutto sembra a posto. L'approccio "prompt-craft" sostituisce le istruzioni testuali opache con un **contratto tipizzato di requisiti rappresentabili**, utilizza la stessa lista due volte: una per scrivere il prompt e una per verificare i pixel, e **blocca l'asset quando un requisito non è soddisfatto**.

```
   CONTRACT  ──atoms──▶  SYNTHESIZE  ──prompt──▶  GENERATE
   typed, depictable     every token traces      diffusion + control
        │                to an atom                     │
        │ the same atoms                                │ pixels
        └──────────────────────▶  GATE  ◀───────────────┘
                    a DIFFERENT model family checks the
                    contract against the image, cheapest
                    tier deciding first
                         │                    │
                       PASS                FAIL / UNCERTAIN
                         ▼                    ▼
                    BIND to canon      REPAIR ladder, or a
                  (only when every     human checkpoint when
                   required atom       the gate is unsure
                   actually passed)
```

**L'idea principale:** la lista degli elementi del contratto è *la stessa lista utilizzata due volte*. Scrivendo il prompt e verificando il risultato ottenuto da una singola fonte, si garantisce che ciò per cui si è chiesto sia effettivamente ciò che viene verificato. Questo è ciò che chiude il ciclo aperto da un prompt opaco.

## Installazione

```bash
pip install prompt-crafter
pcraft --help
```

```bash
npm install -g @mcptoolshop/prompt-crafter   # the same command, as a launcher
```

La distribuzione è **`prompt-crafter`** perché `pcraft` e `prompt-craft` sono entrambi disponibili su PyPI; il pacchetto di importazione e il comando rimangono `pcraft`. Il pacchetto npm è un **launcher, non una porta**; reimplementare una soglia in un secondo linguaggio è la causa della sua deriva, quindi reindirizza a Python, che detiene la verità e ne eredita il codice di uscita.

Per lo sviluppo:

```bash
pip install -e ".[dev]"
```

Il nucleo è **privo di GPU e funziona ovunque**: l'intera suite di test viene eseguita su un generatore e un verificatore simulati, il che dimostra che i limiti del plugin sono effettivamente validi. L'extra `[image]` (torch/diffusers) e l'extra `[synth]` (DSPy + un LM ospitato) collegano il generatore, i verificatori e il sintetizzatore reali. **Nessuno dei due è necessario per eseguire, testare o valutare il nucleo.**

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft gate <image>      # check an image against a contract
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## Come appare un contratto

Non si tratta di un prompt testuale. È una lista di **requisiti atomici, rappresentabili e verificabili individualmente**:

- **`must_have`** — un indumento, una palette colori, una silhouette, un simbolo. Ognuno ha un `check_type` (che indica il livello di verifica), un `severity` e, facoltativamente, un limite `depends_on` in modo che un requisito abbia senso solo se l'elemento padre è stato superato. Non ha senso verificare il colore di un'ascia che non c'è.
- **`must_not`** — vincoli negativi, verificati come **assenza nei pixel**. Non si tratta di un prompt negativo: i prompt negativi lasciano residui e portano a parafrasi.
- **`identity_ref`** — un'immagine di riferimento. **L'identità è una condizione, non dei token.** Un testo anatomico fa sì che un modello di diffusione renda un esemplare; un'immagine di riferimento lega il volto specifico.

I contratti ereditano: un personaggio estende una fazione e l'ereditarietà è **fail-closed**: un elemento figlio può *aumentare* un requisito, ma non può mai allentarlo o eliminarlo silenziosamente.

## Il gate (cancello)

Tre livelli, con il più economico che decide per primo, e si passa al successivo solo quando la risposta economica è poco chiara. Un passaggio ordinato in base alle dipendenze significa che un elemento padre non superato contrassegna i suoi elementi figli come N/A anziché assegnare loro un punteggio senza senso.

**Il verificatore è sempre un modello di una famiglia diversa dal generatore**, e questo viene applicato da una guardia che altrimenti si rifiuta di eseguire il processo. Un modello è un giudice scadente del proprio output, ed è la parte meno speculativa di questo progetto.

**I codici di uscita distinguono quattro cose diverse**, perché chi chiama e legge un singolo numero deve essere in grado di distinguerle:

| uscita | significato |
|---|---|
| `0` | il gate è stato eseguito e tutti gli elementi atomici richiesti sono stati superati |
| `1` | argomenti errati o un contratto non valido |
| `2` | è stato eseguito, ma un elemento atomico **non è stato superato** |
| `3` | è stato eseguito e il risultato è **inconfermato**: intervento umano |
| `4` | **non è stato possibile eseguire il processo**: nessun input leggibile o nessun livello richiesto disponibile |

Quest'ultima riga è quella che conta. "Non sono riuscito a verificare" e "Ho verificato ed è sbagliato" sono fatti diversi, e combinarli è una fonte documentata di danni reali: è per questo che i browser eseguono un fail-soft della revoca dei certificati e perché gli standard di monitoraggio hanno incluso fin dagli anni '90 un verdetto distinto *sconosciuto*. Ogni trascrizione del gate segnala anche **quanti livelli richiesti sono stati effettivamente eseguiti**, indipendentemente dal verdetto, in modo che un gate che ha smesso silenziosamente di verificare non possa essere interpretato come superato.

**CLIPScore non viene utilizzato come metrica del gate.** Si comporta come un insieme di concetti: ignora a quale oggetto appartiene un attributo, i conteggi e le relazioni. È documentato come noto per essere difettoso nell'interfaccia del verificatore, in modo che nessuno lo reintroduca.

## Stato corretto

**v0.2.0: il nucleo è reale; il percorso GPU non è mai stato eseguito qui.**

| | |
|---|---|
| Nucleo | **105 test superati**, privo di GPU, deterministico. `verify` esegue la suite, la suite viene eseguita nuovamente sotto `-O` e viene creato un pacchetto. |
| Predicati | gli undici punti decisionali composti in `core/` sono **testati con mutazioni**: 20 su 21 mutanti eliminati, e [il sopravvissuto è nominato](scripts/mutate_predicates.py) anziché nascosto. |
| Copertura | 81% complessiva; gli adattatori del generatore e del verificatore vincolati alla GPU sono la parte non testata rimanente. |
| Il percorso `[image]` | **non è mai stato eseguito su questa macchina.** `bind --no-mock` rifiuta con un errore di dipendenza mancante. Tutto ciò che si trova al di sotto del limite del plugin non è stato verificato tramite misurazione. |
| Soglie | i limiti inferiore e di varianza del sottogate degli sprite sono **valori predefiniti hardcoded senza una calibrazione registrata**: nessun set di dati di controllo, nessuna citazione. Trattali come segnaposto. |
| Canone reale | il contratto di esempio fornito è un'**invenzione generica**, non il canone di un progetto reale. Collegare un canone reale è una decisione umana deliberata. |

Due affermazioni che le versioni precedenti di questo documento hanno fatto e che la misurazione non ha supportato, corrette qui anziché eliminate silenziosamente:

- Le soglie delle tre zone sono state descritte come *calibrate rispetto a un set di dati etichettato manualmente*. In realtà, non lo sono. Si tratta di valori predefiniti.
- La regola secondo cui un modello generativo non può mai essere il proprio "gatekeeper" è stata presentata come se fosse stata stabilita da uno studio. Le prove a sostegno sono **indirette piuttosto che dirette**: l'analisi discriminativa binaria (sì/no) risulta misurabilmente più stabile rispetto alla generazione di didascalie aperte, i modelli non possono autocorregersi in modo affidabile senza un feedback esterno e il riconoscimento automatico traccia le distorsioni delle preferenze. Nessuno studio singolo esegue un confronto diretto. La regola è valida; la certezza è stata sopravvalutata.

## Requisiti

| | |
|---|---|
| Python | **3.11+** (il sistema di integrazione continua utilizza la versione 3.13) |
| Piattaforme | Python puro, senza estensioni compilate nel nucleo; sviluppato su Windows 11, il sistema di integrazione continua è eseguito su `ubuntu-latest`. |
| Dipendenze | il nucleo necessita solo di `pydantic`. Le funzionalità relative alla GPU sono disponibili tramite moduli opzionali. |

## Modello di fiducia e sicurezza

- **Dati accessibili**: il file JSON del contratto a cui si fa riferimento, le immagini fornite in input e i record di provenienza scritti nella directory specificata. Non vengono letti altri dati.
- **Dati NON accessibili**: non vengono lette, archiviate o trasmesse credenziali di alcun tipo. **Nessuna telemetria, analisi o conteggio dell'utilizzo**: non è prevista alcuna opzione per disattivare queste funzioni perché non sono presenti. Il nucleo non importa alcuna libreria di rete.
- **Comunicazione in uscita dalla rete**: nessuna comunicazione dal nucleo. I moduli opzionali `[image]` e `[synth]` accedono a un host del modello, ed è questo l'unico percorso di rete; l'installazione di questi moduli è una scelta.
- **Autorizzazioni**: autorizzazioni utente standard. Nessun aumento dei privilegi, nessuna installazione di servizi, nessuna scrittura nel registro di sistema o nelle impostazioni di sistema.
- **Aspetto critico, reso esplicito piuttosto che nascosto**: **le operazioni sui file non sono eseguite in un ambiente isolato (sandbox).** `--records-dir` e `--db` scrivono ovunque vengano indirizzati, intenzionalmente, perché si tratta di uno strumento progettato per essere utilizzato principalmente in locale. Indirizzarli verso una posizione desiderata.
- **Errori**: i rifiuti intenzionali includono un codice, un messaggio e un suggerimento, e **generano un'eccezione anziché restituire un valore** (`assert`), quindi `-O` non può eliminarli; la suite viene eseguita una seconda volta in `-O` per dimostrarlo. I fallimenti imprevisti stampano solo il traceback in `--debug`.

## Stato del supporto

`main` è l'unico stato supportato. Nessun canale di rilascio, nessuna politica di backporting, nessun SLA. Si tratta di un'infrastruttura di studio pubblicata in modalità open source, non di un prodotto con un contratto di supporto.

## Come sono organizzati i componenti

`core/` è indipendente dal dominio e non importa simboli relativi alla diffusione o a PyTorch; un plugin di dominio esporta esattamente tre elementi: un generatore, un elenco di verificatori e un set di regole per l'encoder. L'aggiunta di un nuovo dominio consiste nell'aggiungere un nuovo modulo secondario in `domains/`; nulla in `core/` cambia. La suite senza GPU è ciò che garantisce la validità di questa affermazione.

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
  cli/           pcraft: synth | gate | bind | demo | replay | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, the three verifier tiers, encoder rules, sprite subdomain
```

Le regole dell'encoder in `domains/image/rules/` sono **generate** da un database di ricette verificate, non scritte manualmente, e includono un header di generazione. Ogni risorsa associata scrive una **prova di provenienza riproducibile** che registra l'hash del contratto, l'artefatto del sintetizzatore, il generatore e il seme, la versione del verificatore e la trascrizione completa per ogni "gate".

La motivazione alla base della progettazione, gli standard rispetto ai quali questo repository viene valutato e le procedure di annullamento per ogni azione irreversibile sono disponibili in [`STANDARDS.md`](STANDARDS.md) e [`COMPENSATORS.md`](COMPENSATORS.md).

## Licenza

MIT: vedere [LICENSE](LICENSE). La licenza di qualsiasi *modello* utilizzato tramite questo strumento è una questione separata e non è coperta da essa.
