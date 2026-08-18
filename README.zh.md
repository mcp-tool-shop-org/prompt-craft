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

**说明图片必须包含的内容。检查它是否确实包含了这些内容。如果未包含，则拒绝。**

一个生成式图像流水线会很乐意为你提供一个拥有错误面部、错误调色板且没有任何阵营标志的英雄人物——并且报告成功，因为没有发现任何问题。prompt-craft 将不透明的文本提示替换为 **可描述声明的类型化合同**，并以相同的方式使用该列表两次——一次用于编写提示，另一次用于检查像素——并在 **缺少必需声明时阻止资产的使用**。

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

**核心思想：** 合同中的原子列表是 *两次使用的相同列表*。 编写提示和检查从同一来源读取的结果，因此你要求的内容就是被验证的内容。 这正是弥合不透明提示留下的差距。

## 安装

```bash
pip install prompt-crafter
pcraft --help
```

```bash
npm install -g @mcptoolshop/prompt-crafter   # the same command, as a launcher
```

该软件包的名称为 **`prompt-crafter`**，因为 `pcraft` 和 `prompt-craft` 都已在 PyPI 上占用；导入包和命令仍然是 `pcraft`。 npm 包是一个 **启动器，而不是一个端口**——在一个第二种语言中重新实现阈值会导致阈值发生漂移，因此它会转发到包含真实数据的 Python 代码，并继承其退出代码。

用于开发：

```bash
pip install -e ".[dev]"
```

核心是 **无需 GPU 即可运行，并且可以在任何地方运行**——整个测试套件都针对一个模拟生成器和验证器执行，这证明了插件边界确实有效。 `[image]` 额外的依赖项（torch/diffusers）和 `[synth]` 额外的依赖项（DSPy + 一个托管的 LM）连接真实的生成器、验证器和合成器。 **运行、测试或评估核心时不需要这两个依赖项。**

```bash
pcraft demo              # the whole loop end-to-end, no GPU, deterministic stubs
pcraft gate <image>      # check an image against a contract
pcraft replay <record>   # re-read a bound asset's provenance receipt
```

## 合同的外观

不是文本提示。 而是包含一系列 **原子性、可描述、可单独检查的声明**：

- **`must_have`**——一件服装、一种调色板、一个轮廓、一个徽章。 每个都携带一个 `check_type`（哪个门控层验证它）、一个 `severity`，并且可选地带有一个 `depends_on` 边缘，因此只有当其父级通过时，声明才有意义。 如果不存在一件斧头，那么就没有必要验证它的颜色。
- **`must_not`**——反约束条件，作为 **像素上的缺失** 进行验证。 不是负面提示：负面提示会留下残留特征并导致释义错误。
- **`identity_ref`**——参考图。 **身份是条件，而不是令牌。** 解剖学文本会导致扩散模型渲染出一个样本；一张参考图像绑定特定的面部。

合同具有继承性——一个角色扩展了一个阵营——并且继承是 **失败时关闭的**：子级可以 *提高* 一个要求，但绝不能放松或静默地删除它所继承的要求。

## 门控器

三个层级，最便宜的层级首先进行决策，只有当廉价答案不明确时才会升级。 依赖顺序传递意味着失败的父级会将其子级标记为“不可用”，而不是给出无意义的分数。

**验证器始终是与生成器不同的模型系列**，由一个守卫强制执行，否则将拒绝运行。 一个模型对其自身输出的判断能力较差，这是本设计中最不具推测性的部分。

**退出代码区分四种不同的情况**，因为读取单个数字的调用者需要能够区分它们：

| 退出 | 含义 |
|---|---|
| `0` | 门控器已运行，并且所有必需的原子都通过了验证 |
| `1` | 参数错误或合同格式不正确 |
| `2` | 它已经运行，但一个必需的原子 **失败** 了 |
| `3` | 它已经运行，并且结果是 **未确认的**——由人工团队进行判断 |
| `4` | 它 **无法运行**——没有可读的输入，或者没有可用的必需层级 |

最后一行是最重要的。 “我无法检查”和“我已经检查过，结果很糟糕”是不同的事实，将它们合并会导致实际损害——这就是浏览器对证书撤销进行软处理的原因，也是监控标准自 1990 年代以来一直包含一个明确的 *未知* 判决的原因。 每个门控器转录还报告 **实际上执行了多少个必需层级**，与判决结果无关，因此一个安静停止检查的门控器不能被视为通过。

**CLIPScore 不用作门控指标。** 它表现为一组概念——它无法区分哪个属性属于哪个对象、计数和关系。 验证器界面中已记录其存在已知问题，因此没有人会重新引入它。

## 诚实的状态

**v0.2.1——核心是真实的；GPU 路径从未在此处运行过。**

| | |
|---|---|
| 核心 | **105 个测试通过**，无需 GPU，确定性。 `verify` 运行该套件，然后在 `-O` 下再次运行该套件，并构建一个软件包 |
| 谓词 | 在 `core/` 中的十一个复合决策点都经过了 **突变测试**——20 个突变体中有 19 个被杀死，并且 [幸存者已命名](scripts/mutate_predicates.py)，而不是隐藏起来。 |
| 覆盖率 | 总体覆盖率为 81%；受 GPU 限制的生成器和验证器适配器是未测试的剩余部分。 |
| `[image]` 路径 | **从未在此机器上执行过。** `bind --no-mock` 会因缺少依赖项而报错。 插件边界以下的所有内容都未经测量证明。 |
| 阈值 | 精灵子门控器的下限和方差限制是 **硬编码的默认值，没有记录任何校准**——没有保留集、也没有引用。 将它们视为占位符。 |
| 真实的规范 | 已发布的示例合同是一个 **通用发明**，而不是任何真实项目的规范。 绑定真实的规范是一项有意的、由人工做出的决定。 |

本文档早期版本提出并测量结果未支持的两个声明，在此处进行更正，而不是静默删除：

- 这三个阈值被描述为“根据人工标注的测试集进行校准”。但事实并非如此。它们是默认值。
- 有人声称，生成模型永远不能作为自身的门控器，就好像有研究证实了这一点。然而，支持证据更多的是**间接的，而非直接的**——可测量的二元分类比开放式的文本描述更稳定；模型如果没有外部反馈，就无法可靠地自我纠正；并且自我识别会受到自身偏好的影响。没有单一的研究能够进行直接对比。这个规则是合理的；但对其确定性的描述过于夸大。

## 需求

| | |
|---|---|
| Python | **3.11+**（持续集成运行 3.13） |
| 平台 | 纯 Python，核心中没有编译的扩展——在 Windows 11 上开发，持续集成在 `ubuntu-latest` 上进行。 |
| 依赖项 | 核心只需要 `pydantic`。GPU 相关的功能位于可选模块中。 |

## 信任和威胁模型

- **涉及的数据**——你指向的 JSON 合约、你传递的图像以及写入到你指定的目录中的溯源记录。除此之外，不会读取任何其他数据。
- **不涉及的数据**——不会读取、存储或传输任何类型的凭据。**没有遥测、分析或使用量统计**：因为没有任何需要选择退出（opt-out）的内容，所以不需要提供退出选项。核心不导入任何网络库。
- **网络输出**——核心没有网络输出。可选的 `[image]` 和 `[synth]` 模块会通过其固有的方式连接到模型主机；这是唯一的网络路径，并且安装它们是一种选择。
- **权限**——普通用户权限。不需要提升权限、无需安装服务、无需写入注册表或系统设置。
- **一个重要的点，我们公开说明，而不是隐瞒**——**文件操作没有进行沙箱隔离。** `--records-dir` 和 `--db` 会将内容写入你指定的位置，这是有意的，因为这是一个本地优先的工具。请将其指向你想要的位置。
- **错误**——明确的拒绝会包含一个代码、一条消息和一个提示，并且会**引发异常，而不是 `assert`**，因此 `-O` 无法删除它们；测试套件会在 `-O` 下第二次运行以证明这一点。意外失败只会打印堆栈跟踪信息，并且仅在 `--debug` 下进行。

## 支持状态

`main` 是唯一受支持的状态。没有发布渠道、没有回溯策略、也没有 SLA（服务级别协议）。这是一个公开发布的开发基础设施，而不是带有支持合同的产品。

## 各个组件的组织方式

`core/` 不依赖于特定领域，并且不导入任何扩散或 PyTorch 符号——一个领域插件会导出三个内容：生成器、验证器列表和编码器规则集。添加新的领域是在 `domains/` 下创建一个新的子模块；`core/` 中的内容不会发生变化。GPU 免费的套件确保了这一声明的真实性。

```
src/pcraft/
  core/          contract · loop · gate · synth · optimize · receipt   (GPU-free)
  cli/           pcraft: synth | gate | bind | demo | replay | compile | sync-rules
  domains/       ── PLUGIN BOUNDARY ──
    image/       generators, the three verifier tiers, encoder rules, sprite subdomain
```

在 `domains/image/rules/` 中，编码器规则是从经过验证的配方数据库中**生成**的，而不是手动编写的，并且会包含一个生成头。每个绑定的资产都会写入一个**可重现的溯源收据**，其中包含合约哈希值、合成器工件、生成器和种子、验证器版本以及完整的逐原子门控记录。

设计理念、本仓库所遵循的标准以及对每个不可逆操作的撤销方法都位于 [`STANDARDS.md`](STANDARDS.md) 和 [`COMPENSATORS.md`](COMPENSATORS.md)。

## 许可证

MIT——请参阅 [LICENSE](LICENSE)。通过此工具使用的任何*模型*的许可证是单独的问题，不在其涵盖范围内。
