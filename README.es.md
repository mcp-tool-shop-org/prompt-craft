<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.md">English</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

**Indica qué debe contener la imagen. Verifica que lo contenga. Rechaza si no es así.**

Un proceso generativo de imágenes te proporcionará con gusto un personaje con la cara equivocada, la paleta de colores incorrecta y ninguno de los distintivos de la facción, e informará que fue un éxito, porque nada parecía estar mal. prompt-craft reemplaza la prosa opaca de la instrucción con un **contrato tipificado de afirmaciones representables**, utiliza esa misma lista dos veces: una para escribir la instrucción y otra para verificar los píxeles, y **bloquea el activo cuando una afirmación requerida no está presente**.

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

**La idea principal:** la lista atómica del contrato es *la misma lista que se utiliza dos veces*. Se escribe la instrucción y se verifica el resultado obtenido de una fuente, por lo que lo que se solicitó es lo que se verifica. Esto es lo que cierra el ciclo que deja abierto una instrucción opaca.

## Instalar

```bash
pip install prompt-crafter
pcraft --help
```

```bash
npm install -g @mcptoolshop/prompt-crafter   # the same command, as a launcher
```

La distribución es **`prompt-crafter`** porque `pcraft` y `prompt-craft` ya están disponibles en PyPI; el paquete de importación y el comando siguen siendo `pcraft`. El paquete npm es un **lanzador, no un puerto**: reimplementar un umbral en un segundo lenguaje es la forma en que un umbral se desvía, por lo que redirige a Python, que contiene la verdad e hereda su código de salida.

Para el desarrollo:

```bash
pip install -e ".[dev]"
```

El núcleo es **independiente de la GPU y funciona en cualquier lugar**: toda la suite de pruebas se ejecuta contra un generador y verificador simulados, lo que demuestra que el límite del complemento realmente se mantiene. El paquete adicional `[image]` (torch/diffusers) y el paquete adicional `[synth]` (DSPy + un modelo de lenguaje alojado) conectan el generador, los verificadores y el sintetizador reales. **Ninguno es necesario para ejecutar, probar o evaluar el núcleo.**

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft gate <image>      # check an image against a contract
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## Cómo se ve un contrato

No es una instrucción en prosa. Es una lista de **afirmaciones atómicas, representables e individualmente verificables**:

- **`must_have`** — una prenda, una paleta de colores, una silueta, un emblema. Cada uno lleva consigo un `check_type` (que el nivel de puerta verifica), un `severity` y, opcionalmente, un borde `depends_on` para que una afirmación solo tenga sentido cuando su elemento principal haya superado la prueba. No tiene sentido verificar el color de un hacha que no está presente.
- **`must_not`** — restricciones negativas, verificadas como **ausencia en los píxeles**. No es una instrucción negativa: las instrucciones negativas dejan características residuales y terminan siendo paráfrasis.
- **`identity_ref`** — una imagen de referencia. **La identidad es un condicionante, no tokens.** El texto anatómico hace que un modelo de difusión renderice un espécimen; una imagen de referencia vincula la cara específica.

Los contratos se heredan: un personaje extiende una facción, y la herencia es **de fallo cerrado**: un elemento secundario puede *elevar* un requisito, pero nunca relajarlo ni eliminarlo silenciosamente.

## La puerta

Tres niveles, el más económico decide primero, escalando solo cuando una respuesta económica no es clara. Un paso ordenado por dependencias significa que un elemento principal fallido marca a sus elementos secundarios como N/A en lugar de puntuar tonterías.

**El verificador siempre es un modelo de una familia diferente al generador**, lo cual se aplica mediante un guardián que se niega a ejecutarse si no se cumple esta condición. Un modelo es un juez deficiente de su propia salida, y esa es la parte menos especulativa de este diseño.

**Los códigos de salida distinguen cuatro cosas diferentes**, porque un llamador que lee un solo número debe poder diferenciarlas:

| salida | significado |
|---|---|
| `0` | la puerta se ejecutó y cada átomo requerido superó la prueba |
| `1` | argumentos incorrectos o un contrato mal formado |
| `2` | se ejecutó, y un átomo requerido **falló** |
| `3` | se ejecutó, y el resultado es **no confirmado**: la banda humana |
| `4` | no **pudo ejecutarse**: no hay entrada legible o no hay ningún nivel requerido disponible |

Esa última fila es la que importa. "No pude verificar" y "Verifiqué y está mal" son hechos diferentes, y colapsarlos es una fuente documentada de daño real: por eso los navegadores fallan suavemente la revocación de certificados, y por eso los estándares de monitoreo han tenido un veredicto *desconocido* distinto desde la década de 1990. Cada transcripción de puerta también informa **cuántos niveles requeridos se ejecutaron realmente**, independientemente del veredicto, por lo que una puerta que dejó de verificar silenciosamente no puede interpretarse como una aprobación.

**CLIPScore no se utiliza como métrica de la puerta.** Se comporta como un conjunto de conceptos: ignora qué atributo pertenece a qué objeto, las cantidades y las relaciones. Está documentado como conocido por ser defectuoso en la interfaz del verificador para que nadie lo reintroduzca.

## Estado honesto

**v0.2.1: el núcleo es real; la ruta de la GPU nunca se ha ejecutado aquí.**

| | |
|---|---|
| Núcleo | **105 pruebas superadas**, independiente de la GPU, determinista. `verify` ejecuta la suite, la suite nuevamente bajo `-O` y una construcción del paquete. |
| Predicados | los once puntos de decisión compuestos en `core/` se **prueban mediante mutación**: se eliminaron 20 de 21 mutantes, y [el superviviente tiene nombre](scripts/mutate_predicates.py) en lugar de estar oculto. |
| Cobertura | 81% en general; los adaptadores del generador y verificador dependientes de la GPU son el resto no probado. |
| La ruta `[image]` | **nunca se ha ejecutado en esta máquina.** `bind --no-mock` rechaza con un error de dependencia faltante. Todo lo que está por debajo del límite del complemento no se ha comprobado mediante mediciones. |
| Umbrales | los límites inferior y de varianza de la sub-puerta de sprites son **valores predeterminados codificados con una calibración no registrada**: sin datos de reserva, ni citas. Trátalos como marcadores de posición. |
| Canon real | el contrato de ejemplo incluido es una **invención genérica**, no el canon de ningún proyecto real. Vincular un canon real es una decisión humana deliberada. |

Dos afirmaciones que las versiones anteriores de este documento hicieron y que la medición no respaldó, corregidas aquí en lugar de eliminadas silenciosamente:

- Los umbrales de las tres zonas se describieron como *calibrados con un conjunto de datos etiquetado por humanos*. No lo están. Son valores predeterminados.
- Se afirmó que la regla de que un modelo generativo nunca puede ser su propio filtro, como si un estudio lo hubiera establecido. La evidencia que lo respalda es **convergente en lugar de directa**: el sondeo discriminatorio de sí/no es mediblemente más estable que la generación de subtítulos sin restricciones, los modelos no pueden corregirse de manera fiable sin retroalimentación externa y el reconocimiento propio rastrea sesgos de preferencia propia. No hay ningún estudio único que lo compare directamente. La regla es sólida; la certeza se exageró.

## Requisitos

| | |
|---|---|
| Python | **3.11+** (el entorno de integración continua utiliza la versión 3.13) |
| Plataformas | Python puro, sin extensiones compiladas en el núcleo; desarrollado en Windows 11, entorno de integración continua en `ubuntu-latest`. |
| Dependencias | el núcleo solo necesita `pydantic`. El trabajo con GPU se realiza a través de módulos opcionales. |

## Modelo de confianza y amenazas

- **Datos accedidos**: el archivo JSON del contrato al que se apunta, las imágenes que se le pasan y los registros de procedencia escritos en el directorio especificado. No se lee nada más.
- **Datos NO accedidos**: no se lee, almacena ni transmite ninguna credencial. **No hay telemetría, análisis ni recuento de uso**: no hay opción para desactivarlo porque no hay nada que desactivar. El núcleo no importa ninguna biblioteca de red.
- **Comunicación de red**: ninguna desde el núcleo. Los módulos opcionales `[image]` y `[synth]` acceden a un host de modelo por su propia naturaleza; ese es el único camino de la red, e instalarlo es una elección.
- **Permisos**: permisos de usuario normales. Sin elevación de privilegios, sin instalación de servicios, sin escritura en el registro o en la configuración del sistema.
- **El punto crítico, que se revela en lugar de ocultar**: **las operaciones con archivos no están aisladas**. `--records-dir` y `--db` escriben dondequiera que se les indique, deliberadamente, porque esta es una herramienta diseñada para funcionar principalmente localmente. Indícales un lugar donde quieras que escriban.
- **Errores**: los rechazos deliberados llevan un código, un mensaje y una pista, y **generan una excepción en lugar de `assert`**, por lo que `-O` no puede eliminarlos; la suite se ejecuta una segunda vez bajo `-O` para demostrarlo. Los fallos inesperados imprimen un rastreo solo bajo `--debug`.

## Estado del soporte

`main` es el único estado compatible. No hay canal de lanzamiento, ni política de compatibilidad con versiones anteriores, ni SLA. Esto es infraestructura de estudio publicada en código abierto, no un producto con un contrato de soporte.

## Cómo se organizan las partes

`core/` es independiente del dominio e importa cero símbolos de difusión o de PyTorch; un complemento de dominio exporta exactamente tres cosas: un generador, una lista de verificadores y un conjunto de reglas de codificador. Agregar un nuevo dominio es agregar un nuevo elemento secundario bajo `domains/`; nada en `core/` cambia. La suite sin GPU es lo que mantiene esa afirmación veraz.

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
  cli/           pcraft: synth | gate | bind | demo | replay | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, the three verifier tiers, encoder rules, sprite subdomain
```

Las reglas del codificador bajo `domains/image/rules/` se **generan** a partir de una base de datos de recetas verificadas, no están escritas manualmente y llevan un encabezado de generación. Cada activo vinculado escribe un **registro de procedencia reproducible** que registra el hash del contrato, el artefacto del sintetizador, el generador y la semilla, la versión del verificador y la transcripción completa por átomo del filtro.

La justificación del diseño, los estándares con los que este repositorio se evalúa a sí mismo y las acciones de deshacer para cada acción irreversible se encuentran en [`STANDARDS.md`](STANDARDS.md) y [`COMPENSATORS.md`](COMPENSATORS.md).

## Licencia

MIT: consulte [LICENSE](LICENSE). La licencia de cualquier *modelo* utilizado a través de esta herramienta es una cuestión separada y no está cubierta por ella.
