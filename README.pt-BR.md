<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.zh.md">中文</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.md">English</a>
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

**Diga o que a imagem deve conter. Verifique se ela contém. Recuse quando não contiver.**

Um pipeline de geração de imagens fornecerá alegremente um personagem com o rosto errado, a paleta de cores errada e nenhum dos elementos distintivos da facção — e reportará sucesso, porque nada pareceu fora do lugar. O prompt-craft substitui o texto opaco do prompt por um **contrato tipificado de afirmações representáveis**, usa essa mesma lista duas vezes — uma para escrever o prompt, outra para verificar os pixels — e **bloqueia o recurso quando uma afirmação necessária não estiver presente**.

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

**A ideia principal:** a lista atômica do contrato é *a mesma lista usada duas vezes*. Escrever o prompt e verificar o resultado obtido de uma única fonte, para que aquilo que você pediu seja exatamente aquilo que será verificado. É isso que fecha o ciclo que um prompt opaco deixa em aberto.

## Instalar

```bash
pip install prompt-crafter
pcraft --help
```

```bash
npm install -g @mcptoolshop/prompt-crafter   # the same command, as a launcher
```

A distribuição é **`prompt-crafter`** porque `pcraft` e `prompt-craft` estão ambos disponíveis no PyPI; o pacote de importação e o comando permanecem `pcraft`. O pacote npm é um **lançador, não uma porta** — reimplementar um limite em uma segunda linguagem é a forma como um limite se desvia, então ele encaminha para o Python que contém a verdade e herda seu código de saída.

Para desenvolvimento:

```bash
pip install -e ".[dev]"
```

O núcleo é **livre de GPU e funciona em qualquer lugar** — todo o conjunto de testes é executado contra um gerador e verificador simulados, o que prova que a fronteira do plugin realmente se mantém. O extra `[image]` (torch/diffusers) e o extra `[synth]` (DSPy + um LM hospedado) conectam o gerador, os verificadores e o sintetizador reais. **Nenhum deles é necessário para executar, testar ou avaliar o núcleo.**

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft gate <image>      # check an image against a contract
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## Como é um contrato

Não é um prompt em prosa. Uma lista de **afirmações atômicas, representáveis e verificáveis individualmente**:

- **`must_have`** — uma peça de vestuário, uma paleta de cores, uma silhueta, um símbolo. Cada um carrega um `check_type` (que determina qual nível de verificação o valida), um `severity` e, opcionalmente, uma borda `depends_on` para que uma afirmação só tenha significado quando seu elemento pai for validado. Não faz sentido verificar a cor de um machado que não está presente.
- **`must_not`** — restrições anti-, verificadas como **ausência nos pixels**. Não é um prompt negativo: prompts negativos deixam características residuais e acabam sendo parafraseados.
- **`identity_ref`** — uma imagem de referência. **A identidade é condicionamento, não tokens.** Um texto anatômico faz com que um modelo de difusão renderize um espécime; uma imagem de referência vincula o rosto específico.

Os contratos herdam — um personagem estende uma facção — e a herança é **fail-closed**: um filho pode *aumentar* um requisito, nunca relaxá-lo ou descartá-lo silenciosamente.

## O portão

Três níveis, o mais barato decidindo primeiro, escalonando apenas quando uma resposta barata for pouco clara. Uma passagem ordenada por dependência significa que um elemento pai com falha marca seus filhos como N/A em vez de atribuir resultados sem sentido.

**O verificador é sempre um modelo de família diferente do gerador**, imposto por uma proteção que se recusa a executar caso contrário. Um modelo é um juiz ruim de sua própria saída, e essa é a parte menos especulativa deste projeto.

**Os códigos de saída distinguem quatro coisas diferentes**, porque um chamador que lê um único número precisa diferenciá-las:

| saída | significado |
|---|---|
| `0` | o portão foi executado e cada átomo necessário foi validado |
| `1` | argumentos inválidos ou um contrato malformado |
| `2` | ele foi executado, e um átomo necessário **falhou** |
| `3` | ele foi executado, e o resultado é **não confirmado** — a banda humana |
| `4` | ele **não pôde ser executado** — nenhuma entrada legível ou nenhum nível necessário disponível |

Essa última linha é a que importa. "Eu não pude verificar" e "Eu verifiquei e está ruim" são fatos diferentes, e colapsá-los é uma fonte documentada de danos reais — é por isso que os navegadores falham suavemente na revogação de certificados e por que os padrões de monitoramento têm um veredicto *desconhecido* distinto desde a década de 1990. Cada transcrição do portão também relata **quantos níveis necessários foram realmente executados**, independentemente do veredicto, para que um portão que parou silenciosamente de verificar não possa ser interpretado como uma aprovação.

**CLIPScore não é usado como a métrica do portão.** Ele se comporta como um conjunto de conceitos — ignorando qual atributo pertence a qual objeto, às contagens e às relações. Está documentado como conhecido por apresentar falhas na interface do verificador para que ninguém o reintroduza.

## Status honesto

**v0.2.1 — o núcleo é real; o bloqueio de pose e a vinculação de identidade não foram implementados.**

| | |
|---|---|
| Núcleo | **205 testes aprovados**, livre de GPU, determinístico. `verify` executa o conjunto de testes, o conjunto novamente sob `-O` e uma construção do pacote |
| Predicados | os onze pontos de decisão compostos em `core/` são **testados por mutação** — 20 de 21 mutantes eliminados, e [o sobrevivente tem nome](scripts/mutate_predicates.py) em vez de estar oculto |
| Cobertura | os adaptadores do gerador e verificador vinculados à GPU permanecem como o restante não testado |
| O caminho `[image]` | **nunca foi executado nesta máquina.** `bind --no-mock` recusa com um erro de dependência ausente |
| Condicionamento | o loop monta `pose_refs` e `identity_refs` e os escreve no recibo. Nenhum dos geradores enviados lê uma chave desse dicionário. Se essas referências estiverem presentes, `generate()` **recusa**. O bloqueio de pose e a vinculação de identidade não foram implementados, apenas não estão sendo usados. |
| Limites | os limites mínimo e de variância do sub-portão sprite são **padrões rígidos sem calibração registrada** — sem retenção, nenhuma citação. Trate-os como espaços reservados |
| Canone real | o contrato de exemplo enviado é uma **invenção genérica**, não o canone de nenhum projeto real. Vincular um canone real é uma decisão humana deliberada |

Três afirmações que versões anteriores deste documento fizeram e que a medição não suportou, corrigidas aqui em vez de descartadas silenciosamente:

- Os limites de três zonas foram descritos como *calibrados em relação a um conjunto de dados rotulado por humanos*. Não é o caso. São valores padrão.
- A regra de que um modelo generativo nunca pode ser seu próprio avaliador foi apresentada como se um estudo tivesse comprovado isso. As evidências de suporte são **convergentes, e não diretas** — a avaliação discriminativa do tipo sim/não é mensuravelmente mais estável do que a geração de legendas abertas; os modelos não podem se autocorrigir de forma confiável sem feedback externo, e o rastreamento do reconhecimento próprio revela um viés de preferência própria. Nenhum estudo único realiza uma comparação direta. A regra é válida; a certeza foi exagerada.
- Tudo abaixo da fronteira do plugin foi descrito como *não comprovado por meio de medição*. Isso subestimou os geradores: o condicionamento não é lido. O caminho não está implementado, e sim não testado.

## Requisitos

| | |
|---|---|
| Python | **3.11+** (o CI executa a versão 3.13) |
| Plataformas | Python puro, sem extensões compiladas no núcleo — desenvolvido no Windows 11, CI em `ubuntu-latest` |
| Dependências | o núcleo precisa apenas de `pydantic`. O trabalho com GPU está disponível por meio de módulos opcionais |

## Modelo de confiança e ameaças

- **Dados acessados** — o arquivo JSON do contrato que você aponta, as imagens que você fornece e os registros de proveniência gravados no diretório especificado. Nada mais é lido.
- **Dados NÃO acessados** — nenhuma credencial de qualquer tipo é lida, armazenada ou transmitida. **Sem telemetria, análise ou contagem de uso**: não há opção para desativar porque não há nada para desativar. O núcleo não importa nenhuma biblioteca de rede.
- **Comunicação de rede** — nenhuma comunicação do núcleo. Os módulos opcionais `[image]` e `[synth]` acessam um host de modelo por sua própria natureza; esse é o único caminho de rede, e a instalação deles é uma escolha.
- **Permissões** — permissões de usuário comuns. Sem elevação de privilégios, sem instalação de serviço, sem gravações no registro ou nas configurações do sistema.
- **O ponto crítico, divulgado em vez de ocultado** — **as operações de arquivo não são executadas em um ambiente isolado.** `--records-dir` e `--db` gravam onde você os direciona, intencionalmente, porque esta é uma ferramenta que prioriza o uso local. Direcione-os para um local onde você pretende usá-los.
- **Erros** — as recusas deliberadas carregam um código, uma mensagem e uma dica, e **geram uma exceção em vez de `assert`**, para que `-O` não possa excluí-las; o conjunto é executado uma segunda vez sob `-O` para provar isso. Falhas inesperadas imprimem um rastreamento apenas sob `--debug`.

## Status de suporte

`main` é o único estado suportado. Sem canal de lançamento, sem política de retrocompatibilidade, sem SLA. Esta é uma infraestrutura de estúdio publicada em código aberto, e não um produto com um contrato de suporte.

## Como as partes são organizadas

`core/` é independente do domínio e importa zero símbolos de difusão ou torch — um plugin de domínio exporta exatamente três coisas: um gerador, uma lista de verificadores e um conjunto de regras de codificador. Adicionar um novo domínio é criar um novo módulo subordinado em `domains/`; nada em `core/` muda. O conjunto sem GPU é o que mantém essa afirmação verdadeira.

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
  cli/           pcraft: synth | gate | bind | demo | replay | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, the three verifier tiers, encoder rules, sprite subdomain
```

As regras do codificador sob `domains/image/rules/` são **geradas** a partir de um banco de dados de receitas verificadas, e não escritas manualmente, e carregam um cabeçalho de geração. Cada ativo vinculado grava um **registro de proveniência reproduzível**, que registra o hash do contrato, o artefato do sintetizador, o gerador e a semente, a versão do verificador e a transcrição completa por átomo da avaliação.

A justificativa do projeto, os padrões pelos quais este repositório se avalia e as ações de desfazer nomeadas para cada ação irreversível estão disponíveis em [`STANDARDS.md`](STANDARDS.md) e [`COMPENSATORS.md`](COMPENSATORS.md).

## Licença

MIT — consulte [LICENSE](LICENSE). A licença de qualquer *modelo* usado por meio desta ferramenta é uma questão separada e não está coberta por ela.
