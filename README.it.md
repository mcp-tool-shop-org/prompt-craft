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

Un flusso di generazione di immagini fornirà volentieri un personaggio con il volto sbagliato, la palette colori errata e nessuno degli elementi distintivi della fazione, per poi segnalare l'avvenuto completamento perché apparentemente tutto è a posto. L'approccio "prompt-craft" sostituisce le istruzioni testuali opache con un **contratto tipizzato di requisiti rappresentabili**, utilizza la stessa lista due volte: una volta per scrivere il prompt e una volta per verificare i pixel, e **blocca l'asset quando un requisito non è soddisfatto**.

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

**L'idea principale:** la lista degli elementi del contratto è *la stessa lista utilizzata due volte*. Scrivere il prompt e verificare il risultato partendo dalla stessa fonte garantisce che ciò per cui si è chiesto sia effettivamente ciò che viene verificato. Questo chiude il ciclo aperto da un prompt opaco.

## Installa

```bash
pip install prompt-crafter
pcraft --help
```

```bash
npm install -g @mcptoolshop/prompt-crafter   # the same command, as a launcher
```

La distribuzione è **`prompt-crafter`** perché `pcraft` e `prompt-craft` sono entrambi disponibili su PyPI; il pacchetto di importazione e il comando rimangono `pcraft`. Il pacchetto npm è un **launcher, non una porta**; reimplementare una soglia in un secondo linguaggio è la causa della sua deriva, quindi reindirizza a Python, che contiene i dati corretti e ne eredita il codice di uscita.

Per lo sviluppo:

```bash
pip install -e ".[dev]"
```

Il nucleo è **privo di GPU e funziona ovunque**: l'intero set di test viene eseguito su un generatore e un verificatore simulati, il che dimostra che i limiti del plugin sono effettivamente validi. L'extra `[image]` (torch/diffusers) e l'extra `[synth]` (DSPy + un LM ospitato) collegano il generatore, i verificatori e il sintetizzatore reali. **Nessuno dei due è necessario per eseguire, testare o valutare il nucleo.**

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft list              # contract ids in the store
pcraft validate          # resolve + compile the question DAG, no generate
pcraft gate <image>      # check an image against a contract
pcraft recipe            # emit the Cloud Kontext + fist-only Fill graph
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## Come appare un contratto

Non si tratta di un prompt testuale. È una lista di **requisiti atomici, rappresentabili e verificabili individualmente**:

- **`must_have`** — un indumento, una palette colori, una silhouette, un sigillo. Ognuno ha un `check_type` (che determina il livello di verifica), un `severity` e, facoltativamente, un limite `depends_on` in modo che un requisito abbia senso solo se l'elemento padre è stato superato. Non ha senso verificare il colore di un'ascia che non c'è.
- **`must_not`** — vincoli negativi, verificati come **assenza nei pixel**. Non si tratta di un prompt negativo: i prompt negativi lasciano residui e portano a parafrasi.
- **`identity_ref`** — un'immagine di riferimento. **L'identità è una condizione, non dei token.** Un testo anatomico fa sì che un modello di diffusione generi un esemplare; un'immagine di riferimento lega il volto specifico.

I contratti ereditano: un personaggio estende una fazione e l'ereditarietà è **fail-closed**: un elemento figlio può *aumentare* un requisito, ma non può mai ridurlo o eliminarlo silenziosamente.

## Il gate (cancello)

Tre livelli, con il più economico che decide per primo, e si passa al successivo solo quando la risposta economica è poco chiara. Un passaggio ordinato in base alle dipendenze significa che un elemento padre non superato contrassegna i suoi elementi figli come N/A anziché assegnare loro un punteggio senza senso.

**Il verificatore è sempre un modello di una famiglia diversa dal generatore**, e questo viene applicato da una guardia che si rifiuta di eseguire il processo altrimenti. Un modello è un giudice scadente del proprio output, ed è la parte meno speculativa di questo progetto.

**I codici di uscita distinguono quattro cose diverse**, perché chi chiama e legge un singolo numero deve essere in grado di distinguerle:

| uscita | significato |
|---|---|
| `0` | il gate è stato eseguito e tutti gli elementi atomici richiesti sono stati superati |
| `1` | argomenti errati o un contratto non valido |
| `2` | è stato eseguito, ma un elemento atomico **non è stato superato** |
| `3` | è stato eseguito e il risultato è **inconfermato**: intervento umano |
| `4` | **non è stato possibile eseguire**: nessun input leggibile o nessun livello richiesto disponibile |

Quest'ultima riga è quella che conta. "Non sono riuscito a verificare" e "Ho verificato ed è sbagliato" sono fatti diversi, e combinarli è una fonte documentata di danni reali: è per questo che i browser eseguono un fail-soft della revoca dei certificati e perché gli standard di monitoraggio hanno incluso fin dagli anni '90 un verdetto distinto *sconosciuto*. Ogni trascrizione del gate segnala anche **quanti livelli richiesti sono stati effettivamente eseguiti**, indipendentemente dal verdetto, in modo che un gate che ha smesso silenziosamente di verificare non possa essere considerato superato.

**CLIPScore non viene utilizzato come metrica del gate.** Si comporta come un insieme di concetti: ignora a quale oggetto appartiene un attributo, i conteggi e le relazioni. È documentato come noto per essere difettoso nell'interfaccia del verificatore, in modo che nessuno lo reintroduca.

## Stato corretto

**v0.3.0: il nucleo è operativo. Il sistema di condizionamento SDXL è stato implementato tramite codice. È stata eseguita una prova su una scheda grafica locale 5090 `generate()`. È stata eseguita una dimostrazione dal vivo con un modello Cloud.**

| | |
|---|---|
| Nucleo | **337 test superati** (conteggiati il 2026-08-18), eseguiti senza GPU, risultati deterministici. `verify` esegue linting, controllo dei tipi, l'intera suite di test, la suite di nuovo sotto `-O` e compila un pacchetto. |
| Predicati | gli undici punti decisionali composti in `core/` sono **testati con mutazioni**: 20 su 21 mutanti eliminati, e [il sopravvissuto è nominato](scripts/mutate_predicates.py) anziché nascosto. |
| Condizionamento SDXL | ControlNet OpenPose, IP-Adapter, LoRA, **InstantID** e il ritocco regionale sono **integrati e coperti dai test fake-torch**. InstantID e IP-Adapter non possono condividere la stessa generazione. Due immagini di input per IP-Adapter vengono elaborate con un singolo adattatore (tutte le immagini; la scala è il fattore limitante più forte). `generate()` è stato eseguito localmente sulla scheda 5090 (2026-08-18, seme `169405236028824`, tipo `controlnet_ip`). L'immagine risultante ha un aspetto orchesesco; gli elementi "grip", "sigil" e "bracer" non sono stati applicati correttamente. |
| Encoder Flux | Le funzioni “solo testo” e “riempimento inpaint” sono state integrate (fake-torch). ControlNet pose, IP-Adapter e LoRA continuano a essere rifiutate (famiglia errata). `method=reference` scrive il grafico della ricetta Cloud e si rifiuta di simulare l’esecuzione locale di Kontext (`GATE_CLOUD_SUBMIT`). |
| Ricetta Cloud | `pcraft recipe` emette un'immagine cucita con Kontext, un ritaglio sinistro nel grafico e un riempimento Flux che mostra solo il pugno. `method=reference` è quel percorso. Un invio Cloud in diretta (lavoro `06668d4c`, 2026-08-18) ha prodotto un singolo pannello ritagliato e ha mantenuto il bracciale. |
| Gate | Il livello 2 è una vera espansione DSG (entità / attributo / relazione). L'escalation è un checkpoint contrastivo. Le ricevute memorizzano la storia del tentativo, non solo il numero di tentativi. |
| Sintesi offline | `compile_synthesizer` si basa su una **metrica esterna** (`dspy.GEPA` quando `[synth]` è installato). È stata eseguita una compilazione in diretta il 18 agosto 2026 sull'istanza locale di Ollama `hermes3:8b` (la versione 600B non era attiva). Valore fissato a `sprite.synth.v1-gepa.json` (`generated_by=gepa`). Il seed `sprite.synth.v1.json` è rimasto invariato. Il ciclo per ogni risorsa continua a utilizzare `TemplateSynthesizer`. L'interfaccia a riga di comando non riesce ancora a generare una metrica basata sui pixel. |
| Sub-gate dell'identità | valuta CLIP-I e **non è collegato** a `orchestrate`. Le soglie 0,55 / 0,05 non hanno un set di dati di esclusione. Segnaposto. |
| Canone reale | l'esempio di contratto fornito è un'**invenzione generica**, non il canone di un progetto reale. Definire un canone reale è una decisione umana deliberata. |

Tre affermazioni che le versioni precedenti di questo documento hanno fatto e che i test non hanno supportato, sono state corrette qui invece di essere semplicemente eliminate:

- Le soglie a tre zone sono state descritte come *calibrate rispetto a un set di dati etichettato manualmente*. Non lo sono. Sono valori predefiniti.
- La regola secondo cui un modello generativo non può mai essere il proprio "gatekeeper" è stata affermata come se uno studio l'avesse dimostrato. Le prove a sostegno sono **convergenti piuttosto che dirette**: i test discriminativi sì/no si sono dimostrati misurabilmente più stabili rispetto alla generazione di didascalie aperte, i modelli non possono autocorregersi in modo affidabile senza feedback esterno e il riconoscimento automatico traccia le preferenze. Nessuno studio singolo ha condotto un confronto diretto. La regola è valida; la certezza è stata esagerata.
- Il processo di "conditioning" è stato inizialmente descritto come non implementato, poi come non utilizzato. SDXL ora **legge** i riferimenti assemblati nel codice. Ciò che rimane inutilizzato è un'istanza locale attiva `generate()` su questa macchina, non il cablaggio.

## Requisiti

| | |
|---|---|
| Python | **3.11+:** (il sistema di integrazione continua esegue le versioni 3.11 e 3.13 sul nucleo + `[dev]`. Il vantaggio aggiuntivo `[image]` non è garantito con la versione 3.11). |
| Piattaforme | solo Python, nessuna estensione compilata nel core: sviluppato su Windows 11, test CI su `ubuntu-latest` |
| Dipendenze | il core necessita solo di `pydantic`. Le operazioni GPU sono implementate tramite moduli opzionali. |

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

`core/` è indipendente dal dominio e non importa simboli relativi alla diffusione o a torch: un plugin di dominio esporta esattamente tre elementi: un generatore, un elenco di verificatori e un set di regole per l'encoder. L'aggiunta di un nuovo dominio crea un nuovo modulo secondario sotto `domains/`; nulla in `core/` cambia. La suite senza GPU è ciò che mantiene valida questa affermazione.

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
  cli/           pcraft: synth | gate | bind | list | validate | demo | replay | doctor | schema | recipe | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, the three verifier tiers, encoder rules, sprite subdomain
```

Le regole dell'encoder sotto `domains/image/rules/` sono **generate** da un database di ricette verificate, non scritte a mano, e contengono un header di generazione. Ogni risorsa associata scrive una **prova di provenienza riproducibile** che registra l'hash del contratto, l'artefatto del sintetizzatore, il generatore e il seed, la versione del verificatore e la trascrizione completa per ogni "gate".

La motivazione del progetto, gli standard rispetto ai quali questo repository si auto-valuta e le azioni di annullamento per ogni azione irreversibile sono disponibili in [`STANDARDS.md`](STANDARDS.md) e [`COMPENSATORS.md`](COMPENSATORS.md).

## Collaboratori

Consultare il file [CONTRIBUTORS.md](CONTRIBUTORS.md). Autore: mcp-tool-shop. Test interni (dogfood) eseguiti su questo ramo: Grok (xAI).

## Licenza

MIT: vedere [LICENSE](LICENSE). La licenza di qualsiasi *modello* utilizzato tramite questo strumento è una questione separata e non è coperta da essa.
