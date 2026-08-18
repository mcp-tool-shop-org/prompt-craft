<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.md">English</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

**Indiquez ce que l’image doit contenir. Vérifiez qu’elle le fait. Refusez si ce n’est pas le cas.**

Un pipeline de génération d’images vous fournira volontiers un personnage avec le mauvais visage, la mauvaise palette et aucun des éléments distinctifs de la faction — et indiquera que l’opération a réussi, car rien ne semblait incorrect. L’approche « prompt-craft » remplace le texte opaque du prompt par un **contrat typé contenant des revendications vérifiables**, utilise cette même liste deux fois : une fois pour rédiger le prompt, une fois pour vérifier les pixels, et **bloque l’élément lorsque la revendication requise est absente**.

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

**L’idée maîtresse :** la liste des éléments du contrat est *la même liste utilisée deux fois*. La rédaction du prompt et la vérification du résultat sont effectuées à partir d’une seule source, de sorte que ce que vous avez demandé est bien ce qui est vérifié. C’est ce qui boucle le processus qu’un prompt opaque laisse ouvert.

## Installation

```bash
pip install prompt-crafter
pcraft --help
```

```bash
npm install -g @mcptoolshop/prompt-crafter   # the same command, as a launcher
```

La distribution est **`prompt-crafter`** car `pcraft` et `prompt-craft` sont tous deux disponibles sur PyPI ; le paquet d’importation et la commande restent `pcraft`. Le paquet npm est un **lanceur, pas un port** — réimplémenter un seuil dans un deuxième langage est la façon dont un seuil dérive, il transmet donc les informations à Python, qui détient la vérité et hérite de son code de sortie.

Pour le développement :

```bash
pip install -e ".[dev]"
```

Le noyau est **sans GPU et fonctionne partout** — l’ensemble des tests s’exécute sur un générateur et un vérificateur simulés, ce qui prouve que la limite du plugin est réellement respectée. L’extra `[image]` (torch/diffusers) et l’extra `[synth]` (DSPy + un modèle de langage hébergé) connectent le générateur, les vérificateurs et le synthétiseur réels. **Aucun n’est nécessaire pour exécuter, tester ou évaluer le noyau.**

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft gate <image>      # check an image against a contract
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## À quoi ressemble un contrat

Pas un prompt textuel. Une liste de **revendications atomiques, vérifiables individuellement et représentables** :

- **`must_have`** — un vêtement, une palette, une silhouette, un symbole. Chacun comporte un `check_type` (qui détermine le niveau de validation), un `severity` et éventuellement un `depends_on` pour qu’une revendication ne soit significative que si son élément parent a réussi. Il n’est pas utile de vérifier la couleur d’une hache qui n’existe pas.
- **`must_not`** — des contraintes inverses, vérifiées comme étant **absentes dans les pixels**. Pas un prompt négatif : les prompts négatifs laissent des éléments résiduels et se réduisent à une paraphrase.
- **`identity_ref`** — une image de référence. **L’identité est une condition, pas des jetons.** Un texte anatomique amène un modèle de diffusion à rendre un spécimen ; une image de référence lie le visage spécifique.

Les contrats héritent — un personnage étend une faction — et l’héritage est **à sécurité renforcée** : un élément enfant peut *ajouter* une exigence, mais jamais la relâcher ou l’omettre silencieusement.

## La porte d’entrée

Trois niveaux, le moins coûteux décidant en premier, et ne passant à un niveau supérieur que si une réponse peu coûteuse est incertaine. Un passage ordonné par dépendance signifie qu’un élément parent qui échoue marque ses éléments enfants comme N/A plutôt que de renvoyer des résultats absurdes.

**Le vérificateur est toujours un modèle d’une famille différente du générateur**, ce qui est imposé par une protection qui refuse de s’exécuter dans le cas contraire. Un modèle est un mauvais juge de sa propre sortie, et c’est la partie la moins spéculative de cette conception.

**Les codes de sortie distinguent quatre choses différentes**, car un appelant qui lit un seul nombre doit pouvoir les différencier :

| sortie | signification |
|---|---|
| `0` | la porte d’entrée s’est exécutée et tous les éléments atomiques requis ont réussi |
| `1` | arguments incorrects ou contrat malformé |
| `2` | elle s’est exécutée, et un élément atomique requis **a échoué** |
| `3` | elle s’est exécutée, et le résultat est **non confirmé** — la bande humaine |
| `4` | elle **n’a pas pu s’exécuter** — aucune entrée lisible ou aucun niveau requis disponible |

Cette dernière ligne est celle qui compte. « Je n’ai pas pu vérifier » et « J’ai vérifié et c’est mauvais » sont des faits différents, et les réduire à un seul est une source de préjudice réelle documentée — c’est pourquoi les navigateurs échouent en douceur la révocation des certificats, et pourquoi les normes de surveillance incluent depuis les années 1990 un verdict *inconnu* distinct. Chaque transcription de la porte d’entrée indique également **combien de niveaux requis ont réellement été exécutés**, indépendamment du verdict, de sorte qu’une porte d’entrée qui a arrêté silencieusement la vérification ne peut pas être interprétée comme une réussite.

**CLIPScore n’est pas utilisé comme métrique pour la porte d’entrée.** Il se comporte comme un ensemble de concepts — ignorant l’attribut auquel appartient chaque objet, les nombres et les relations. Il est documenté comme étant défectueux dans l’interface du vérificateur afin que personne ne le réintroduise.

## État honnête

**v0.2.1 — le noyau est réel ; la fixation de pose et la liaison d’identité n’ont pas été implémentées.**

| | |
|---|---|
| Noyau | **205 tests réussis**, sans GPU, déterministe. `verify` exécute la suite, puis à nouveau sous `-O`, et enfin effectue une construction du paquet. |
| Prédicats | les onze points de décision composés dans `core/` sont **testés par mutation** — 20 des 21 mutants ont été éliminés, et [le survivant est nommé](scripts/mutate_predicates.py) plutôt que d’être caché. |
| Couverture | les adaptateurs de générateur et de vérificateur liés au GPU restent la partie non testée. |
| Le chemin `[image]` | **n’a jamais été exécuté sur cette machine.** `bind --no-mock` refuse avec une erreur de dépendance manquante. |
| Conditionnement | la boucle assemble `pose_refs` et `identity_refs`, puis les écrit dans le reçu. Aucun des générateurs disponibles ne lit une clé de ce dictionnaire. Si ces références sont présentes, `generate()` **refuse**. La fixation de pose et la liaison d’identité n’ont pas été implémentées, elles ne sont pas simplement non utilisées. |
| Seuils | les limites inférieure et de variance du sous-module sprite sont des **valeurs par défaut codées en dur sans calibration enregistrée** — pas d’ensemble de validation, pas de citation. Considérez-les comme des espaces réservés. |
| Canon réel | le contrat exemple fourni est une **invention générique**, et non le canon d’un projet réel. Lier un canon réel est une décision humaine délibérée. |

Trois affirmations que les versions antérieures de ce document ont faites, mais que la mesure n’a pas confirmées, corrigées ici plutôt qu’omises silencieusement :

- Les seuils à trois zones ont été décrits comme étant *calibrés par rapport à un ensemble de données étiqueté par des humains*. Ce n’est pas le cas. Il s’agit de valeurs par défaut.
- La règle selon laquelle un modèle génératif ne peut jamais servir de « gardien » a été énoncée comme si une étude l’avait établie. Les preuves à l’appui sont **plutôt convergentes que directes** : les tests discriminatifs du type oui/non se révèlent mesurablement plus stables que la génération de légendes ouverte, les modèles ne peuvent pas s’auto-corriger de manière fiable sans rétroaction externe et la reconnaissance automatique suit un biais d’autopréférence. Aucune étude unique n’effectue une comparaison directe. La règle est valable ; le degré de certitude a été exagéré.
- Tout ce qui se trouve en dessous de la limite du module a été décrit comme *n’ayant pas fait l’objet de tests*. Cela sous-estime les générateurs : le conditionnement n’a pas été vérifié. Le chemin d’accès n’est pas implémenté, mais il n’a pas été testé.

## Exigences

| | |
|---|---|
| Python | **3.11+** (les tests CI utilisent la version 3.13) |
| Plateformes | Python pur, sans extensions compilées dans le noyau — développé sur Windows 11, tests CI sur `ubuntu-latest` |
| Dépendances | le noyau n’a besoin que de `pydantic`. Les fonctions liées au GPU sont disponibles via des modules optionnels. |

## Modèle de confiance et de sécurité

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

## État du support

`main` est le seul état pris en charge. Pas de canal de publication, pas de politique de rétroportage, pas d’accord sur les niveaux de service (SLA). Il s’agit d’une infrastructure de studio publiée en open source, et non d’un produit doté d’un contrat de support.

## Organisation des différents éléments

`core/` est indépendant du domaine et n’importe aucun symbole de diffusion ou de torch — un module spécifique à un domaine exporte exactement trois éléments : un générateur, une liste de vérificateurs et un ensemble de règles d’encodeur. L’ajout d’un nouveau domaine consiste à créer un nouveau module frère sous `domains/` ; rien dans `core/` ne change. La suite sans GPU est ce qui garantit la validité de cette affirmation.

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
  cli/           pcraft: synth | gate | bind | demo | replay | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, the three verifier tiers, encoder rules, sprite subdomain
```

Les règles d’encodeur sous `domains/image/rules/` sont **générées** à partir d’une base de données de recettes vérifiées, et non écrites manuellement, et comportent un en-tête de génération. Chaque actif lié écrit un **enregistrement de provenance reproductible** qui fixe le hachage du contrat, l’artefact du synthétiseur, le générateur et la graine, la version du vérificateur et la transcription complète des portes par atome.

La justification de la conception, les normes auxquelles ce dépôt se compare et les mécanismes d’annulation pour chaque action irréversible sont disponibles dans [`STANDARDS.md`](STANDARDS.md) et [`COMPENSATORS.md`](COMPENSATORS.md).

## Licence

MIT — voir [LICENSE](LICENSE). La licence de tout *modèle* utilisé via cet outil est une question distincte et n’est pas couverte par celle-ci.
