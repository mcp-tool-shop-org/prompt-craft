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

Un flusso di lavoro generativo per la creazione di immagini ti fornirà volentieri un personaggio con il volto sbagliato, una palette colori errata e nessun segno distintivo della fazione, e segnalerà comunque che l'operazione è andata a buon fine, perché nulla sembrava fuori posto. Il prompt-craft sostituisce il testo opaco del prompt con un **contratto tipizzato di affermazioni rappresentabili**, utilizza la stessa lista due volte: una volta per scrivere il prompt e una volta per verificare i pixel, e **blocca l'asset quando un'affermazione richiesta non è presente**.

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

**L'idea principale:** la lista degli elementi del contratto è *la stessa lista utilizzata due volte*. Scrivere il prompt e verificare il risultato ottenuto da una singola fonte garantisce che ciò per cui si è chiesto sia effettivamente ciò che viene verificato. Questo è ciò che chiude il ciclo aperto da un prompt opaco.

## Installa

```bash
pip install prompt-crafter
pcraft --help
```

```bash
npm install -g @mcptoolshop/prompt-crafter   # the same command, as a launcher
```

La distribuzione è **`prompt-crafter`** perché `pcraft` e `prompt-craft` sono entrambi disponibili su PyPI; il pacchetto di importazione e il comando rimangono `pcraft`. Il pacchetto npm è un **launcher, non una porta**: reimplementare una soglia in un secondo linguaggio è ciò che fa sì che la soglia si modifichi, quindi reindirizza a Python, che contiene i dati corretti e ne eredita il codice di uscita.

Per lo sviluppo:

```bash
pip install -e ".[dev]"
```

Il nucleo è **privo di GPU e funziona ovunque**: l'intero set di test viene eseguito su un generatore e un verificatore simulati, il che dimostra che i limiti del plugin sono effettivamente validi. L'extra `[image]` (torch/diffusers) e l'extra `[synth]` (DSPy + un LM ospitato) collegano il generatore, i verificatori e il sintetizzatore reali. **Nessuno dei due è necessario per eseguire, testare o valutare il nucleo.**

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft gate <image>      # check an image against a contract
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## Come appare un contratto

Non si tratta di un prompt in forma di testo. Si tratta di una lista di **affermazioni atomiche, rappresentabili e verificabili individualmente**:

- **`must_have`** — un indumento, una palette colori, una silhouette, un sigillo. Ognuno contiene un `check_type` (che determina quale livello di verifica lo esamina), un `severity` e, facoltativamente, un limite `depends_on` in modo che un'affermazione abbia senso solo quando l'elemento padre ha superato il test. Non ha senso verificare il colore di un'ascia che non è presente.
- **`must_not`** — vincoli negativi, verificati come **assenza nei pixel**. Non si tratta di un prompt negativo: i prompt negativi lasciano residui e portano a parafrasi.
- **`identity_ref`** — un'immagine di riferimento. **L'identità è una condizione, non dei token.** Un testo anatomico fa sì che un modello di diffusione renda un esemplare; un'immagine di riferimento lega il volto specifico.

I contratti ereditano: un personaggio estende una fazione e l'ereditarietà è **fail-closed**: un elemento figlio può *aumentare* un requisito, ma non può mai ridurlo o eliminarlo silenziosamente.

## Il gate (cancello)

Tre livelli, con il più economico che decide per primo, e si passa al successivo solo quando una risposta economica è poco chiara. Un passaggio ordinato in base alle dipendenze significa che un elemento padre che fallisce contrassegna i suoi elementi figli come N/A anziché assegnare loro un punteggio senza senso.

**Il verificatore è sempre un modello di una famiglia diversa dal generatore**, e questo viene applicato da una guardia che si rifiuta di eseguire l'operazione in caso contrario. Un modello è un giudice scadente del proprio output, ed è la parte meno speculativa di questo progetto.

**I codici di uscita distinguono quattro cose diverse**, perché chi chiama e legge un singolo numero deve essere in grado di distinguerle:

| uscita | significato |
|---|---|
| `0` | il gate è stato eseguito e tutti gli elementi atomici richiesti hanno superato il test |
| `1` | argomenti errati o un contratto non valido |
| `2` | è stato eseguito, ma un elemento atomico **richiesto ha fallito** |
| `3` | è stato eseguito, e il risultato è **non confermato**: l'intervento umano |
| `4` | **non è stato possibile eseguire**: nessun input leggibile o nessun livello richiesto disponibile |

Quest'ultima riga è quella che conta. "Non sono stato in grado di verificare" e "Ho verificato ed è sbagliato" sono fatti diversi, e combinarli è una fonte documentata di danni reali: è per questo che i browser eseguono un fail-soft della revoca dei certificati e perché gli standard di monitoraggio hanno incluso fin dagli anni '90 un verdetto distinto *sconosciuto*. Ogni trascrizione del gate segnala anche **quanti livelli richiesti sono stati effettivamente eseguiti**, indipendentemente dal verdetto, in modo che un gate che ha smesso silenziosamente di verificare non possa essere interpretato come un successo.

**CLIPScore non viene utilizzato come metrica del gate.** Si comporta come un insieme di concetti: ignora a quale oggetto appartiene un determinato attributo, i conteggi e le relazioni. È documentato come noto per essere difettoso nell'interfaccia del verificatore, in modo che nessuno lo reintroduca.

## Stato corretto

**v0.2.1: il nucleo è reale; il blocco della posa e l'associazione dell'identità non sono implementati.**

| | |
|---|---|
| Nucleo | **205 test superati**, privo di GPU, deterministico. `verify` esegue la suite, la suite viene eseguita nuovamente sotto `-O` e viene creato un pacchetto. |
| Predicati | gli undici punti decisionali composti in `core/` sono **testati tramite mutazione**: 20 su 21 mutanti eliminati, e [il sopravvissuto è nominato](scripts/mutate_predicates.py) anziché nascosto. |
| Copertura | gli adattatori del generatore e del verificatore vincolati alla GPU rimangono l'unica parte non testata. |
| Il percorso `[image]` | **non è mai stato eseguito su questa macchina.** `bind --no-mock` rifiuta con un errore di dipendenza mancante. |
| Condizionamento | il ciclo assembla `pose_refs` e `identity_refs` e li scrive sulla ricevuta. Nessuno dei generatori distribuiti legge una chiave di quel dizionario. Se questi riferimenti sono presenti, `generate()` **rifiuta**. Il blocco della posa e l'associazione dell'identità non sono implementati, ma semplicemente non vengono utilizzati. |
| Soglie | i limiti inferiore e di varianza del sottogate sprite sono **valori predefiniti hardcoded senza alcuna calibrazione registrata**: nessun set di dati di controllo, nessuna citazione. Trattali come segnaposto. |
| Canone reale | il contratto di esempio distribuito è un'**invenzione generica**, non il canone di un progetto reale. Collegare il canone reale è una decisione umana deliberata. |

Tre affermazioni che le versioni precedenti di questo documento hanno fatto e che la misurazione non ha supportato, corrette qui anziché eliminate silenziosamente:

- Le soglie delle tre zone sono state descritte come *calibrate rispetto a un set di dati etichettato manualmente*. In realtà, non lo sono. Si tratta di valori predefiniti.
- La regola secondo cui un modello generativo non può mai essere il proprio "gatekeeper" è stata presentata come se fosse stata stabilita da uno studio. Le prove a sostegno sono **indirette piuttosto che dirette**: l'analisi discriminativa sì/no si dimostra misurabilmente più stabile rispetto alla generazione di didascalie aperte, i modelli non possono correggersi in modo affidabile senza un feedback esterno e il riconoscimento automatico traccia le distorsioni delle preferenze. Nessuno studio singolo esegue un confronto diretto. La regola è valida; la certezza è stata sopravvalutata.
- Tutto ciò che si trova al di sotto del limite del plugin è stato descritto come *non verificato tramite misurazione*. Questo sottostima le capacità dei generatori: il condizionamento non viene letto. Il percorso non è implementato, ma non testato.

## Requisiti

| | |
|---|---|
| Python | **3.11+** (il sistema di integrazione continua esegue la versione 3.13) |
| Piattaforme | Python puro, senza estensioni compilate nel core: sviluppato su Windows 11, il sistema di integrazione continua è eseguito su `ubuntu-latest`. |
| Dipendenze | il core necessita solo di `pydantic`. Le funzionalità relative alla GPU sono disponibili tramite moduli opzionali. |

## Modello di fiducia e minacce

- **Data touched** — contract JSON you point it at, the images you pass it, and provenance
  records written under the directory you name. Nothing else is read.
- **Data NOT touched** — no credentials of any kind are read, stored or transmitted. **No
  telemetry, analytics or usage counting**: there is no opt-out because there is nothing to opt
  out of. The core imports no networking library at all.
- **Network egress** — none from the core. The optional `[image]` and `[synth]` extras reach a
  model host by their nature; that is the only network path, and installing them is a choice.
- **Permissions** — ordinary user permissions. No elevation, no service installation, no registry
  or system-settings writes.
- **The sharp edge, disclosed rather than claimed away** — **file operations are not sandboxed.**
  `--records-dir` and `--db` write wherever you point them, deliberately, because this is a
  local-first tool. Point them somewhere you intend.
- **Errors** — deliberate refusals carry a code, a message and a hint, and **raise rather than
  `assert`**, so `-O` cannot delete them; the suite runs a second time under `-O` to prove it.
  Unexpected failures print a traceback only under `--debug`.

## Stato del supporto

`main` è l'unico stato supportato. Nessun canale di rilascio, nessuna politica di backporting, nessun SLA. Si tratta di un'infrastruttura di studio pubblicata in modalità open source, non di un prodotto con un contratto di supporto.

## Come sono organizzati i componenti

`core/` è indipendente dal dominio e non importa simboli relativi alla diffusione o a torch: un plugin di dominio esporta esattamente tre elementi: un generatore, un elenco di verificatori e un set di regole per l'encoder. L'aggiunta di un nuovo dominio consiste nell'aggiungere un nuovo elemento secondario sotto `domains/`; nulla in `core/` cambia. La suite senza GPU è ciò che garantisce la validità di tale affermazione.

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
  cli/           pcraft: synth | gate | bind | demo | replay | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, the three verifier tiers, encoder rules, sprite subdomain
```

Le regole dell'encoder sotto `domains/image/rules/` sono **generate** da un database di ricette verificate, non scritte manualmente, e includono un header di generazione. Ogni risorsa associata scrive una **prova di provenienza riproducibile**, che registra l'hash del contratto, l'artefatto del sintetizzatore, il generatore e il seme, la versione del verificatore e la trascrizione completa per ogni "gate".

La motivazione alla base della progettazione, gli standard rispetto ai quali questo repository si auto-valuta e le procedure di annullamento per ogni azione irreversibile sono disponibili in [`STANDARDS.md`](STANDARDS.md) e [`COMPENSATORS.md`](COMPENSATORS.md).

## Licenza

MIT: vedere [LICENSE](LICENSE). La licenza di qualsiasi *modello* utilizzato tramite questo strumento è una questione separata e non è coperta da essa.
