# Dify JSON Schema 插件

**作者：** [EFT](https://github.com/ztistic)
**仓库：** [dify-plugin-json-schema](https://github.com/ztistic/dify-plugin-json-schema)
**版本：** 1.0.0
**类型：** tool

依据 JSON Schema 校验大模型结构化输出，并按错误类型输出结构化结果，便于下游条件分支处理。

## 简介

Dify 的 LLM 节点虽然可以用 JSON Schema 引导输出，但无法保证结果真的符合。
一旦模型输出漂移，下游节点要么解析失败，要么静默拿到错误结构，且没有清晰的原因。

本插件是一道放置在 LLM 节点之后的**确定性质量门**。它解析模型输出，用
[jsonschema](https://pypi.org/project/jsonschema/) 按你的 Schema 校验，
并返回可被下游条件分支消费的带类型结果。它把三类容易被混淆的问题区分开来——
而这种区分正是自动化修复得以进行的前提：

- 模型压根没输出合法 JSON；
- 你的 JSON Schema 本身是坏的；
- JSON 合法但不满足 Schema。

校验全部在插件运行时内完成：无需凭证、无需端点、无需网络。

## 环境要求

- Dify 1.14.2 及以上

## 安装

1. 从 Dify 市场安装：在插件页搜索 "JSON Schema" 并安装。
2. 从本地文件安装：插件 -> 安装插件 -> 通过本地文件，选择 `.difypkg`。

## 工具：JSON Schema Validator

### 参数

| 参数 | 类型 | 必填 | 形式 | 说明 |
|---|---|---|---|---|
| `json_input` | `string` | 是 | `llm` | 需要校验的 JSON 字符串 |
| `schema_input` | `string` | 是 | `llm` | 用于校验的 JSON Schema |

参数若已经是解码后的对象或数组，会先序列化回 JSON。

### 入参必须是干净的 JSON

本插件只做校验，**不处理入参**。`json_input` 直接交给 `json.loads`，任何本身不是
合法 JSON 的输入都会报 `invalid_json`——包括 JSON 外面包一层 Markdown 代码围栏，
这正是 LLM 包裹结构化输出的常见方式。

这是刻意的。工具只输出校验结论，从不回吐解析后的 JSON，所以下游节点拿到的变量仍然
是那个原始字符串。如果插件替你把围栏拆掉再校验，`is_valid: true` 证明的就只是
"拆掉围栏后的内容合法"——可下游拿到的还是带围栏的原始字符串，照样解析失败。
校验显示通过，流程却依然坏着，这样的结论没有意义。

因此，如果数据源是 LLM 的回答，请先提取 JSON 再校验——插件自带的 JSON 提取器
可以处理"整段就是 JSON"和"代码围栏"这两种情况。`invalid_json` 的
错误信息带行号列号，通常足以判断问题出在围栏或多余的一句话上，而不是 JSON 本身。

### Schema 按原样生效

本插件从不改写你的 Schema：写了什么就校验什么，不多也不少。没有全局的"严格模式"
开关——JSON Schema 本身没有这个概念，而一刀切的开关会覆盖你逐对象做好的选择。

要拒绝未声明的属性，就在需要的对象上声明：

```json
{
  "type": "object",
  "properties": { "name": { "type": "string" } },
  "additionalProperties": false
}
```

`additionalProperties` 只作用于没有被 `properties` 或 `patternProperties` 匹配到的属性，
所以关上的对象依然接受 Schema 声明过的全部字段。

### 输出

每次调用产生两条消息：

- **text**——人类可读摘要，以 `Validation passed.` 或
  `Validation failed [error_type]: ...` 开头，并附带 JSON 路径与 Schema 路径。
- **json**——结构化结果，供下游节点解析。

成功结果：

```json
{
  "is_valid": true,
  "message": "Validation passed."
}
```

失败结果（四个字段恒存在）：

```json
{
  "is_valid": false,
  "error_type": "validation_failed",
  "error": "'age' is a required property",
  "path": [],
  "schema_path": ["required"]
}
```

- `path`——指向错误在 JSON 数据中位置的列表（根节点为 `[]`）。
- `schema_path`——指向被违反的 Schema 规则的列表。

### 错误类型

| `error_type` | 含义 | 建议动作 |
|---|---|---|
| `invalid_input` | `json_input` 或 `schema_input` 为空 | 检查节点接线 |
| `invalid_json` | 数据不是合法 JSON（含带围栏的） | 修好提取步骤后重试 |
| `invalid_schema_json` | Schema 不是合法 JSON | 修正 Schema 文本 |
| `schema_error` | 是合法 JSON，但不是合法 JSON Schema | 修正 Schema 结构 |
| `unsupported_draft` | `$schema` 指向不支持的 Draft | 换成支持的 Draft |
| `ref_resolution_error` | `$ref` 无法解析 | 把引用的定义内联进来 |
| `validation_failed` | 数据是合法 JSON 但不匹配 Schema | 按 `path` 修字段后重试 |
| `internal_error` | 预期外失败，不会以异常形式抛出 | 作为缺陷反馈 |

任何输入都不会导致工具抛异常：所有失败路径都返回结构化结果。

## 工具：JSON Extractor

LLM 经常把结构化输出裹在散文或 Markdown 代码围栏里。JSON 提取器从原始 LLM 回答中
取出第一段可解析的 JSON 字符串，以便交给校验器。它完全由确定性规则驱动——
不调用模型、不清洗、不修复。

### 参数

| 参数         | 类型   | 必填 | 说明                       |
|--------------|--------|------|----------------------------|
| `llm_output` | string | 是   | 上游 LLM 节点的原始输出文本 |

### 识别范围

只识别两种没有歧义的形态，按顺序尝试，第一个能解析的候选胜出：

1. 整个输入本身就是 JSON，原样返回；
2. ```` ```json ```` 或无语言标记的代码围栏，内容逐字返回。

散文中裸嵌的 JSON **不做**提取：在自由文本里扫描配对括号必然伴随猜测，
而本插件宁可如实报告也不猜测。带其他语言标记的围栏
（` ```python `、` ```bash ` 等）会被跳过。提取结果是输入的逐字切片，
从不重新序列化，因此数字写法与键顺序原封不动。

### 输出

| 字段         | 类型    | 说明                           |
|--------------|---------|--------------------------------|
| `found`      | boolean | 是否提取到可解析的 JSON 字符串 |
| `json`       | string  | 提取出的 JSON 文本（找到时）   |
| `error_type` | string  | 失败类别（未找到时）           |
| `error`      | string  | 人类可读的原因（未找到时）     |

`error_type` 取值：`invalid_input`、`no_json_found`、`internal_error`。

## 支持的 Draft

| Draft | `$schema` URI |
|---|---|
| 2020-12 | `https://json-schema.org/draft/2020-12/schema` |
| 2019-09 | `https://json-schema.org/draft/2019-09/schema` |
| 7 | `http://json-schema.org/draft-07/schema#` |
| 6 | `http://json-schema.org/draft-06/schema#` |
| 4 | `http://json-schema.org/draft-04/schema#` |

未声明 `$schema`，或使用旧的通用指针 `http://json-schema.org/schema#` 时，按
Draft 2020-12 处理。Draft 3 及未知 URI 返回 `unsupported_draft`。

仅支持**内联** `$ref` 指针（例如 `#/$defs/Address`）；远端引用不会被联网拉取，
而是返回 `ref_resolution_error`。

## 嵌套深度

`jsonschema` 用元 Schema 校验 Schema 时是纯 Python 递归，每层嵌套约消耗 10 个
解释器栈帧。在 CPython 默认递归上限 1000 下，可支持约 95 层深的 Schema；对自引用
Schema，可校验约 100~200 层深的数据。

插件刻意不动这个上限。这些上限远超 LLM 输出或人工编写的实际深度——真实 Schema
一般在 3~30 层——而超出边界的输入依然返回结构化错误而不是异常。抬高上限换来的
是没人需要的能力，却改动了进程级全局状态——`sys.setrecursionlimit()` 会影响共享
同一插件进程的所有任务。

超过上述边界、或 JSON 文档深到标准解析器都无法处理时，工具依然返回结构化错误
而不会崩溃：

| 情况 | `error_type` |
|---|---|
| JSON 数据深到 `json.loads` 无法解析 | `invalid_json` |
| JSON Schema 深到 `json.loads` 无法解析 | `invalid_schema_json` |
| Schema 深到无法做元 Schema 校验 | `schema_error` |
| 数据深到无法校验，或存在循环 `$ref` | `internal_error` |

## 工作流用法

把提取器放在 LLM 节点之后，校验器放在提取器与消费端之间，对两个结果分别分支：

```
LLM 节点 -> JSON 提取器 -> JSON Schema 校验 -> is_valid true  -> 正常流程
             |                              is_valid false -> 按 error_type 分支
             |                                                  validation_failed -> 带上错误信息重试
             |                                                  invalid_json      -> 告警（提取结果不是 JSON）
             |                                                  schema_error      -> 告警给流程作者
             found false -> no_json_found：模型把 JSON 裹在散文里，
                            提取器拒绝猜测 -> 用更严格的提示词重试
                            （要求输出 ```json 代码块）
```

提取器只负责拆开模型包上的外壳，拆出来的内容结构对不对由校验器判断。
拆开两步，每个结论才能如实说明到底坏在哪一步。

把 `error`、`path`、`schema_path` 回填到重试提示词中，模型即可精确修掉出错的字段。

## 性能

用随仓库附带的测试负载（含嵌套对象的记录数组）实测，Python 3.12，单次调用：

| 数据量 | 总耗时 |
|---|---|
| 8 KB | ~3 ms |
| 32 KB | ~7 ms |
| 128 KB | ~22 ms |
| 512 KB | ~82 ms |
| 1 MB | ~160 ms |

其中约 95% 的时间花在 `jsonschema` 自身遍历文档上，这是纯 Python 校验库的固有代价，
也是当初选型时接受的权衡。

## 隐私

校验全程在插件运行时内存中完成，不收集、不存储、不记录、不传输任何数据，也不发起
任何出网连接。详见 [PRIVACY.md](../PRIVACY.md)。

## 本地开发

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

使用 [Dify Plugin CLI](https://github.com/langgenius/dify-plugin-daemon/releases) 打包：

```bash
dify plugin package . -o json-schema-1.0.0.difypkg
```

远程调试：复制 `.env.example` 为 `.env`，填入 Dify 实例提供的
`REMOTE_INSTALL_URL` 与 `REMOTE_INSTALL_KEY`，然后执行 `python -m main`。

## 图标

插件图标采用 JSON Schema 官方 Logo（<https://json-schema.org/logo-blue.svg>）

## 许可证

[MIT](../LICENSE)
