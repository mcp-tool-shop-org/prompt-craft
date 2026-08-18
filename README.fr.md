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

Un pipeline de génération d’images vous fournira volontiers un personnage avec le mauvais visage, la mauvaise palette de couleurs et aucun des éléments distinctifs de la faction — et indiquera que l’opération a réussi, car rien ne semblait incorrect. L’approche « prompt-craft » remplace le texte opaque du prompt par un **contrat typé d’éléments descriptibles**, utilise cette même liste deux fois : une fois pour rédiger le prompt, une fois pour vérifier les pixels, et **bloque l’élément lorsque l’un des éléments requis est absent**.

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

**L’idée maîtresse :** la liste des éléments du contrat est *la même liste utilisée deux fois*. La rédaction du prompt et la vérification du résultat obtenu à partir d’une source unique garantissent que ce que vous avez demandé est bien ce qui est vérifié. C’est ce qui boucle le processus, contrairement à un prompt opaque qui laisse une porte ouverte.

## Installation

```bash
pip install prompt-crafter
pcraft --help
```

```bash
npm install -g @mcptoolshop/prompt-crafter   # the same command, as a launcher
```

La distribution est **`prompt-crafter`** car `pcraft` et `prompt-craft` sont tous deux disponibles sur PyPI ; le paquet d’importation et la commande restent `pcraft`. Le paquet npm est un **lanceur, pas un port** — réimplémenter un seuil dans un deuxième langage est la façon dont un seuil dérive, il redirige donc vers Python qui détient la vérité et hérite de son code de sortie.

Pour le développement :

```bash
pip install -e ".[dev]"
```

Le cœur du système est **sans GPU et fonctionne partout** — l’ensemble des tests s’exécute sur un générateur et un vérificateur simulés, ce qui prouve que la limite du plugin est réellement respectée. L’extra `[image]` (torch/diffusers) et l’extra `[synth]` (DSPy + un modèle de langage hébergé) connectent le générateur, les vérificateurs et le synthétiseur réels. **Aucun des deux n’est nécessaire pour exécuter, tester ou évaluer le cœur du système.**

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft list              # contract ids in the store
pcraft validate          # resolve + compile the question DAG, no generate
pcraft gate <image>      # check an image against a contract
pcraft recipe            # emit the Cloud Kontext + fist-only Fill graph
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## À quoi ressemble un contrat

Pas un prompt textuel. Une liste d’**éléments atomiques, descriptibles et vérifiables individuellement** :

- **`must_have`** — un vêtement, une palette de couleurs, une silhouette, un symbole. Chacun porte un `check_type` (qui détermine le niveau de vérification), un `severity` et éventuellement une `depends_on` qui indique qu’un élément n’est significatif que si son parent a réussi la vérification. Il est inutile de vérifier la couleur d’une hache qui n’existe pas.
- **`must_not`** — des contraintes négatives, vérifiées comme l’**absence sur les pixels**. Pas un prompt négatif : les prompts négatifs laissent des éléments résiduels et se réduisent à une paraphrase.
- **`identity_ref`** — une image de référence. **L’identité est une condition, pas des jetons.** Un texte anatomique amène un modèle de diffusion à rendre un spécimen ; une image de référence lie le visage spécifique.

Les contrats sont hérités : un personnage étend une faction, et l’héritage est **fail-closed** : un enfant peut *ajouter* une exigence, mais jamais la relâcher ou l’ignorer silencieusement.

## La porte d’entrée

Trois niveaux, le moins coûteux décidant en premier, et ne passant à un niveau supérieur que si une réponse peu coûteuse est incertaine. Un passage ordonné par dépendance signifie qu’un parent qui échoue marque ses enfants comme N/A plutôt que de donner des résultats absurdes.

**Le vérificateur est toujours un modèle d’une famille différente du générateur**, ce qui est imposé par une protection qui refuse de s’exécuter dans le cas contraire. Un modèle est un mauvais juge de sa propre sortie, et c’est la partie la moins spéculative de cette conception.

**Les codes de sortie distinguent quatre choses différentes**, car un appelant qui lit un seul nombre doit pouvoir les différencier :

| code de sortie | signification |
|---|---|
| `0` | la porte d’entrée s’est exécutée et tous les éléments requis ont été validés |
| `1` | arguments incorrects ou contrat malformé |
| `2` | il s’est exécuté, et un élément requis a **échoué** |
| `3` | il s’est exécuté, et le résultat est **non confirmé** — la bande humaine |
| `4` | il **n’a pas pu s’exécuter** — aucune entrée lisible ou aucun niveau requis disponible |

Cette dernière ligne est celle qui compte. « Je n’ai pas pu vérifier » et « J’ai vérifié et c’est mauvais » sont des faits différents, et les réduire à un seul est une source documentée de préjudice réel — c’est pourquoi les navigateurs échouent en douceur la révocation des certificats, et pourquoi les normes de surveillance incluent depuis les années 1990 un verdict distinct *inconnu*. Chaque transcription de la porte d’entrée indique également **combien de niveaux requis ont réellement été exécutés**, indépendamment du verdict, de sorte qu’une porte d’entrée qui a arrêté silencieusement la vérification ne peut pas être interprétée comme une réussite.

**CLIPScore n’est pas utilisé comme métrique pour la porte d’entrée.** Il se comporte comme un ensemble de concepts — ignorant l’attribut auquel appartient chaque objet, les quantités et les relations. Il est documenté comme étant défectueux dans l’interface du vérificateur afin que personne ne le réintroduise.

## Statut honnête

**Version 0.3.0 : le noyau est opérationnel. Le conditionnement SDXL est intégré dans le code. Un modèle local 5090 `generate()` a été testé. Une recette Cloud a été exécutée en direct.**

| | |
|---|---|
| Cœur du système | **338 tests réussis** (comptés le 2026-08-18), sans utilisation de GPU, résultats déterministes. `verify` exécute l’analyse statique du code, la vérification des types, la suite de tests, puis à nouveau la suite de tests sous `-O`, et effectue une compilation du paquet. |
| Prédicats | les onze points de décision composés dans `core/` sont **testés par mutation** — 20 des 21 mutants ont été éliminés, et [le survivant est nommé](scripts/mutate_predicates.py) plutôt que caché. |
| Conditionnement SDXL | ControlNet OpenPose, IP-Adapter, LoRA, **InstantID** et l’inpaint régional sont **intégrés et couverts par des tests « fake-torch »**. InstantID et IP-Adapter ne peuvent pas partager une même génération. Deux plaques IP-Adapter restent sur un seul adaptateur (toutes les images ; l’échelle est la contrainte la plus forte). L’instance locale `generate()` a été **exécutée** sur le 5090 (2026-08-18, seed `169405236028824`, type `controlnet_ip`). Le rendu est de style orc ; les éléments « grip », « sigil » et « bracer » n’ont pas été correctement intégrés. |
| Encodeur Flux | Les options texte seul et **remplissage** sont intégrées (tests « fake-torch »). ControlNet pose, IP-Adapter et LoRA continuent d’être refusés (famille incorrecte). `method=reference` écrit le graphe de la recette Cloud et refuse de prétendre que Kontext a été exécuté localement (`GATE_CLOUD_SUBMIT`). |
| Recette Cloud | `pcraft recipe` émet un assemblage Kontext, une découpe à gauche dans le graphique et un remplissage Flux avec uniquement le poing. `method=reference` est ce chemin. Une soumission Cloud en direct (tâche `06668d4c`, 2026-08-18) a produit une seule image découpée et a conservé le bracelet. |
| Porte d’entrée | Le niveau 2 est une expansion DSG réelle (entité / attribut / relation). L’escalade est un point de contrôle contrastif. Les reçus stockent l’historique des tentatives, et pas seulement le nombre de nouvelles tentatives. |
| Synthèse hors ligne | `compile_synthesizer` s’appuie sur une métrique de porte **externe** (`dspy.GEPA` lorsque `[synth]` est installé). Une compilation en direct a été exécutée le 2026-08-18 sur l’instance locale Ollama `hermes3:8b` (600B n’était pas actif). L’élément `sprite.synth.v1-gepa.json` est fixé (`generated_by=gepa`). Le seed `sprite.synth.v1.json` reste inchangé. La boucle par ressource utilise toujours `TemplateSynthesizer`. L’interface en ligne de commande ne générera toujours pas une métrique de pixel. |
| Sous-porte d’entrée pour l’identité | calcule les scores CLIP-I et **n’est pas connectée** à `orchestrate`. Les seuils de 0,55 / 0,05 n’ont pas de données de validation. Valeurs réservées. |
| Le véritable modèle de référence | l’exemple de contrat fourni est une **invention générique**, et non le modèle de référence d’un projet réel. Définir un véritable modèle de référence est une décision humaine délibérée. |

Trois affirmations que les versions antérieures de ce document contenaient et que les mesures n’ont pas corroborées, sont corrigées ici plutôt que simplement supprimées :

- Les seuils à trois zones étaient décrits comme *calibrés par rapport à un ensemble de données étiqueté par des humains*. Ce n’est pas le cas. Il s’agit de valeurs par défaut.
- La règle selon laquelle un modèle génératif ne peut jamais être son propre filtre a été énoncée comme si une étude l’avait établie. Les preuves à l’appui sont **plus convergentes que directes** : les tests discriminatifs oui/non se révèlent mesurablement plus stables que la génération de légendes ouverte, les modèles ne peuvent pas s’auto-corriger de manière fiable sans rétroaction externe et la reconnaissance automatique suit les biais de préférence personnelle. Aucune étude unique n’effectue une comparaison directe. La règle est valable ; le degré de certitude a été exagéré.
- Le conditionnement était décrit comme non lu, puis comme non implémenté. SDXL **lit** désormais les références assemblées dans le code. Ce qui reste sans utilisation est un processus local `generate()` sur cette machine, et non le câblage.

## Exigences

| | |
|---|---|
| Python | **3.11+** (l’intégration continue exécute les versions 3.11 et 3.13 sur le noyau + `[dev]`. L’avantage supplémentaire de `[image]` n’est pas pris en compte pour la version 3.11.) |
| Plateformes | Python pur, sans extensions compilées dans le noyau : développé sur Windows 11, tests CI sur `ubuntu-latest` |
| Dépendances | le noyau n’a besoin que de `pydantic`. Les opérations GPU sont réalisées à l’aide d’extensions optionnelles. |

## Modèle de confiance et de menace

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

`main` est le seul état pris en charge. Aucun canal de publication, aucune politique de rétroportage, aucun SLA. Il s’agit d’une infrastructure de studio publiée en open source, et non d’un produit doté d’un contrat de support.

## Organisation des éléments

`core/` est indépendant du domaine et n’importe aucun symbole de diffusion ou de torch : un module complémentaire de domaine exporte exactement trois éléments : un générateur, une liste de vérificateurs et un ensemble de règles d’encodeur. L’ajout d’un nouveau domaine consiste à créer un nouvel élément frère sous `domains/` ; rien dans `core/` ne change. La suite sans GPU est ce qui garantit la validité de cette affirmation.

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
  cli/           pcraft: synth | gate | bind | list | validate | demo | replay | doctor | schema | recipe | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, the three verifier tiers, encoder rules, sprite subdomain
```

Les règles d’encodeur sous `domains/image/rules/` sont **générées** à partir d’une base de données de recettes vérifiées, et non écrites manuellement, et contiennent un en-tête de génération. Chaque ressource liée écrit un **reçu de provenance reproductible** qui fixe le hachage du contrat, l’artefact du synthétiseur, le générateur et la graine, la version du vérificateur et la transcription complète des portes par atome.

La justification de la conception, les normes auxquelles ce dépôt se compare et la possibilité d’annuler chaque action irréversible sont disponibles dans [`STANDARDS.md`](STANDARDS.md) et [`COMPENSATORS.md`](COMPENSATORS.md).

## Contributeurs

Voir [CONTRIBUTORS.md](CONTRIBUTORS.md). Auteur : mcp-tool-shop. Test en interne (dogfood) sur cet arbre : Grok (xAI).

## Licence

MIT : voir [LICENSE](LICENSE). La licence de tout *modèle* utilisé avec cet outil est une question distincte et n’est pas couverte par celle-ci.
