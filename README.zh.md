<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
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

**说明图片必须包含什么。检查它是否确实包含了这些内容。如果未包含，则拒绝。**

一个生成式图像流水线会很乐意为你提供一张主角的图片，但这张图片可能面部错误、颜色不正确，并且没有任何阵营标志——然后报告成功，因为没有发现任何问题。prompt-craft 将不透明的文本提示替换为**可描述的主题的明确规范**，并以相同的方式使用该列表两次——一次用于编写提示，另一次用于检查像素——并在**缺少必需主题时阻止生成资源**。

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

**核心思想：**规范中的原子列表是*两次使用的相同列表*。编写提示和检查从同一来源读取的结果，因此你要求的内容就是被验证的内容。这解决了不透明的提示所遗留的问题，从而形成一个完整的闭环。

## 安装

```bash
pip install prompt-crafter
pcraft --help
```

```bash
npm install -g @mcptoolshop/prompt-crafter   # the same command, as a launcher
```

该软件包为 **`prompt-crafter`**，因为 `pcraft` 和 `prompt-craft` 都已在 PyPI 上发布；导入包和命令仍然是 `pcraft`。npm 包是一个**启动器，而不是一个端口**——在一个第二种语言中重新实现阈值会导致阈值发生漂移，因此它会转发到包含真实数据的 Python 代码，并继承其退出代码。

用于开发：

```bash
pip install -e ".[dev]"
```

核心是**无需 GPU 即可运行，并且可以在任何地方运行**——整个测试套件都针对一个模拟生成器和验证器执行，这证明了插件边界确实有效。额外的 `[image]`（torch/diffusers）和 `[synth]` 额外组件（DSPy + 一个托管的 LM）连接到真实的生成器、验证器和合成器。**运行、测试或评估核心时不需要这两个组件。**

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft list              # contract ids in the store
pcraft validate          # resolve + compile the question DAG, no generate
pcraft gate <image>      # check an image against a contract
pcraft recipe            # emit the Cloud Kontext + fist-only Fill graph
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## 规范的外观

不是文本提示，而是一个**原子化、可描述、可以单独检查的主题列表**：

- **`must_have`**——一件服装、一种配色方案、一个轮廓、一个标志。每个主题都包含一个 `check_type`（哪个验证层会验证它）、一个 `severity`，并且可选地包含一个 `depends_on` 边缘，这样只有当其父主题通过验证时，该主题才有意义。如果不存在一件盔甲，那么验证盔甲的颜色就没有意义。
- **`must_not`**——反约束条件，作为**像素上的缺失**进行验证。不是负面提示：负面提示会留下残留特征并导致释义错误。
- **`identity_ref`**——参考图。**身份是条件，而不是令牌。**解剖学文本会导致扩散模型渲染出一个样本；一张参考图像可以绑定到特定的面部。

规范具有继承性——一个角色扩展了一个阵营——并且继承是**失败时关闭的**：子主题可以*提高*要求，但不能放宽或静默地删除它所继承的要求。

## 验证门

三个层级，最便宜的层级首先进行决策，只有当廉价答案不明确时才会升级。依赖顺序传递意味着失败的父主题会将其子主题标记为“不可用”，而不是给出无意义的分数。

**验证器始终是与生成器不同的模型系列**，由一个守卫强制执行，如果未满足此条件，则不会运行。一个模型不能很好地判断自己的输出，这是该设计中最不具推测性的部分。

**退出代码区分四种不同的情况**，因为读取单个数字的调用者需要能够区分它们：

| 退出 | 含义 |
|---|---|
| `0` | 验证门已运行，并且所有必需的主题都通过了验证。 |
| `1` | 参数错误或规范格式不正确。 |
| `2` | 它已经运行，但一个必需的主题**失败**了。 |
| `3` | 它已经运行，但结果是**未确认的**——由人工团队进行判断。 |
| `4` | 它**无法运行**——没有可读的输入，或者缺少所需的层级。 |

最后一行是最重要的。“我无法检查”和“我已经检查过，结果不好”是不同的事实，将它们合并会导致实际损害——这就是浏览器对证书吊销进行软处理的原因，也是监控标准自 1990 年代以来一直包含一个明确的*未知*判决的原因。每个验证门记录还会报告**实际上执行了多少个必需层级**，与判决结果无关，因此如果一个验证门悄悄停止检查，则不能将其视为通过。

**CLIPScore 不用作验证门指标。**它的行为就像一个概念集合——它无法区分哪个属性属于哪个对象、计数和关系。在验证器界面中明确记录了其已知存在问题，因此没有人会重新引入它。

## 诚实的状态

**v0.2.1——核心功能已实现。SDXL条件控制已在代码中组装完毕。现在已经在一台本地的5090 `generate()`设备上进行了测试。一个云端配方也已进行实时测试。**

| | |
|---|---|
| 核心 | **338 个测试通过**（统计日期为 2026-08-18），无需 GPU，结果可重复。`verify` 执行代码风格检查、类型检查、以及完整的测试套件，并在 `-O` 环境下再次运行该测试套件，并构建一个软件包。 |
| 谓词 | `core/` 中的十一个复合决策点都经过了**突变测试**——21 个突变体中有 20 个被杀死，并且[幸存者已命名](scripts/mutate_predicates.py)，而不是隐藏。 |
| SDXL 条件 | ControlNet OpenPose、IP-Adapter、LoRA、《InstantID》和区域修复功能均已连接并使用“假torch”测试覆盖。InstantID和IP-Adapter不能共享一次生成过程。两个IP-Adapter图层停留在同一个适配器上（所有图像；比例是最强的限制）。本地`generate()`在5090设备上运行（2026-08-18，种子`169405236028824`，类型`controlnet_ip`）。生成的画面带有兽人的风格；握持、标志和护腕没有正确呈现。 |
| Flux 编码器 | 仅文本和“填充修复”功能已连接（fake-torch）。ControlNet 姿势、IP-Adapter 和 LoRA 仍被拒绝（家族类型错误）。`method=reference` 会写入云端配方图，并拒绝模拟在本地运行（`GATE_CLOUD_SUBMIT`）。 |
| 云端配方 | `pcraft recipe` 输出 Kontext stitch + 图形中左侧裁剪 + 仅限拳头的 Flux Fill。`method=reference` 是该路径。一个实时云端提交（任务 `06668d4c`，2026-08-18）生成了一个单面板裁剪图并保留了护腕。 |
| 验证门 | 第二层是一个真实的 DSG 扩展（实体/属性/关系）。升级是一个对比检查点。收据存储尝试历史，而不仅仅是重试计数。 |
| 离线合成 | `compile_synthesizer`与**外部**门控指标进行比较（当安装`[synth]`时为`dspy.GEPA`）。一个实时编译过程于2026-08-18在本地Ollama `hermes3:8b`上运行（600B未启动）。固定了`sprite.synth.v1-gepa.json`（`generated_by=gepa`）。种子`sprite.synth.v1.json`保持不变。每个资产的循环仍然使用`TemplateSynthesizer`。命令行界面仍然无法生成像素指标。 |
| 身份子验证门 | 分数是 CLIP-I，并且**未连接到** `orchestrate`。阈值 0.55 / 0.05 没有保留集。占位符。 |
| 真正的规范 | 提供的示例合同是一个**通用发明**，而不是任何实际项目的规范。确定真正的规范是一项经过深思熟虑的人工决策。 |

以下是本文档早期版本提出的三个主张，但测量结果并未支持这些主张，因此在此进行更正，而不是简单地删除：

- 之前描述的三区阈值被认为是*基于人工标注的保留数据集进行校准的*。实际上并非如此。它们是默认值。
- 之前提到生成模型永远不会成为自身的“守门人”，这似乎暗示着一项研究已经证实了这一点。支持证据**更多的是趋同性而非直接性**——可区分的“是/否”投票在可测量上比开放式的描述更稳定，模型无法可靠地进行自我纠正，除非有外部反馈，并且自我识别会追踪自我偏好偏差。没有单一的研究能够进行直接对比。该规则是合理的；只是之前的确定性被夸大了。
- 之前描述的条件输入是不读取的，后来又说是未实现的。SDXL现在**读取**代码中组装好的引用。目前尚未使用的部分是在这台机器上的一个本地`generate()`，而不是线路本身。

## 要求

| | |
|---|---|
| Python | **3.11+**（持续集成环境同时运行 3.11 和 3.13 版本，以及 `[dev]`。在 3.11 版本中，额外的 `[image]` 功能未被声明。） |
| 平台 | 纯Python，核心中没有编译的扩展——在Windows 11上开发，CI在`ubuntu-latest`上进行。 |
| 依赖项 | 核心只需要`pydantic`。GPU相关的工作位于可选的附加组件中。 |

## 信任和威胁模型

- **访问的数据**——你指向它的合同JSON，你传递给它的图像，以及在指定的目录中写入的来源记录。不会读取其他任何内容。
- **未访问的数据**——不会读取、存储或传输任何类型的凭据。**没有遥测、分析或使用量统计**：因为没有任何需要选择退出，所以不需要提供退出选项。核心不导入任何网络库。
- **网络输出**——核心没有网络输出。可选的`[image]`和`[synth]`附加组件会通过其自身的性质连接到模型主机；这是唯一的网络路径，并且安装它们是一种选择。
- **权限**——普通用户权限。不需要提升权限、服务安装或写入注册表或系统设置。
- **一个重要的方面，公开说明而不是隐瞒**——**文件操作没有进行沙箱隔离。**`--records-dir`和`--db`会按照你指定的路径进行写入，这是有意的，因为这是一个本地优先的工具。请将它们指向你想要的位置。
- **错误**——经过深思熟虑的拒绝会包含一个代码、一条消息和一个提示，并且**抛出异常而不是`assert`**，因此`-O`无法删除它们；该套件会在`-O`下第二次运行以证明这一点。意外故障只会打印堆栈跟踪信息，且仅在`--debug`下进行。

## 支持状态

`main`是唯一受支持的状态。没有发布渠道、回溯策略或SLA（服务级别协议）。这是一个公开发布的工作室基础设施，而不是具有支持合同的产品。

## 各个组件的排列方式

`core/`与领域无关，不导入任何扩散或torch符号——一个领域插件会导出以下三个内容：一个生成器、一个验证器列表和一个编码器规则集。添加一个新的领域是在`domains/`下创建一个新的同级；`core/`中的任何内容都不会改变。GPU免费的套件是保证这一声明真实性的关键。

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
  cli/           pcraft: synth | gate | bind | list | validate | demo | replay | doctor | schema | recipe | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, the three verifier tiers, encoder rules, sprite subdomain
```

`domains/image/rules/`下的编码器规则是从经过验证的配方数据库**生成**的，而不是手动编写的，并且包含一个生成头。每个绑定的资产都会写入一个**可重现的来源收据**，其中包含合同哈希值、合成器工件、生成器和种子、验证器版本以及完整的逐原子门控记录。

设计原理、本仓库所依据的标准以及对每个不可逆操作的撤销措施都位于[`STANDARDS.md`](STANDARDS.md)和[`COMPENSATORS.md`](COMPENSATORS.md)。

## 贡献者

请参阅 [CONTRIBUTORS.md](CONTRIBUTORS.md)。作者：mcp-tool-shop。Dogfood swarm，该项目在 Grok（xAI）上进行测试。

## 许可证

MIT——请参阅[LICENSE](LICENSE)。通过此工具使用的任何*模型*的许可证是另一个问题，不在其涵盖范围内。
