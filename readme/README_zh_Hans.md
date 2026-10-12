# Dify JSON Schema 插件

**作者：** [EFT](https://github.com/ztistic)
**仓库：** [dify-plugin-json-schema](https://github.com/ztistic/dify-plugin-json-schema)
**版本：** 1.0.0
**类型：** tool

> 本文件为中文说明。发布到 Dify 市场时，仓库根目录的 `README.md` 为英文版本。

## 简介

Dify 的 LLM 节点虽然可以用 JSON Schema 引导输出，但**并不保证结果真的符合**。
一旦模型输出漂移，下游节点要么解析失败，要么静默拿到错误结构，且没有清晰的原因。

本插件在 LLM 节点之后提供一个**确定性的质量门禁**：解析模型输出，用
[jsonschema](https://pypi.org/project/jsonschema/) 按 Schema 校验，并返回可被下游
条件分支消费的带类型结果。它把三类问题区分开来，这正是自动化修复得以进行的前提：

- 模型压根没输出合法 JSON；
- 你的 JSON Schema 本身是坏的；
- JSON 合法但不满足 Schema。

校验全部在插件运行时内完成：无需凭证、无需端点、无需网络。

## 环境要求

- Dify 1.14.2 及以上

## 安装

1. 市场安装：在插件页搜索 "JSON Schema" 并安装。
2. 本地安装：插件 -> 安装插件 -> 通过本地文件，选择 `.difypkg`。

## 工具：JSON Schema Validator

| 参数 | 类型 | 必填 | 默认值 | 形式 | 说明 |
|---|---|---|---|---|---|
| `json_input` | `string` | 是 | - | `llm` | 需要校验的 JSON 字符串 |
| `schema_input` | `string` | 是 | - | `llm` | 用于校验的 JSON Schema 字符串 |
| `strict_mode` | `select` | 否 | `false` | `form` | 开启后拒绝 Schema 未定义的字段 |

参数若已经是对象/数组结构，会先序列化回 JSON；允许 JSON 外面包一层 Markdown
代码围栏（LLM 常见输出习惯，围栏前带一句自然语言也可以），但纯非法输入仍会报
`invalid_json`。

### 嵌套深度

`jsonschema` 用元 Schema 校验 Schema 本身是纯 Python 递归，每层约消耗 10 个栈帧。
CPython 默认递归上限 1000 下，可支持约 95 层深的 Schema；对自引用 Schema，
数据可深到约 100~200 层。

插件**刻意不动这个上限**。这个余量远超 LLM 输出或人工编写的实际深度（真实 Schema
一般在 3~30 层），而超出边界的输入依然返回结构化错误而不是抛异常。抬高上限等于用
没人需要的能力去换进程级全局状态的改动——`sys.setrecursionlimit()` 会影响共享同一
插件进程的所有任务，不划算。

超过上述边界、或 JSON 文档深到标准解析器都无法处理时，工具依然返回结构化错误而不会崩溃：

| 情况 | `error_type` |
|---|---|
| JSON 数据深到 `json.loads` 无法解析 | `invalid_json` |
| JSON Schema 深到 `json.loads` 无法解析 | `invalid_schema_json` |
| Schema 深到无法做元 Schema 校验 | `schema_error` |
| 数据或 Schema 深到无法校验 | `internal_error` |

### 性能

用仓库测试用的负载（含嵌套对象的记录数组）实测，Python 3.12，单次调用：

| 数据量 | 总耗时 |
|---|---|
| 8 KB | ~3 ms |
| 32 KB | ~7 ms |
| 128 KB | ~22 ms |
| 512 KB | ~82 ms |
| 1 MB | ~160 ms |

其中约 95% 的时间花在 `jsonschema` 自身遍历文档上，这是纯 Python 校验库的固有代价，
也是当初选型时接受的权衡。严格模式因需要先深拷贝 Schema，约增加 10% 耗时。

### 输出

每次调用产生两条消息：

- **text**：人类可读摘要，成功为 `Validation passed.`，失败为
  `Validation failed [错误类型]: ...`，并附带 JSON 路径与 Schema 路径。
- **json**：结构化结果，供下游节点解析。

成功：

```json
{
  "is_valid": true,
  "message": "Validation passed."
}
```

失败（四个字段恒存在）：

```json
{
  "is_valid": false,
  "error_type": "validation_failed",
  "error": "'age' is a required property",
  "path": [],
  "schema_path": ["required"]
}
```

- `path`：错误在数据中的位置（根节点为 `[]`）；
- `schema_path`：被违反的 Schema 规则位置。

### 错误类型

| `error_type` | 含义 | 建议动作 |
|---|---|---|
| `invalid_input` | `json_input` 或 `schema_input` 为空 | 检查节点接线 |
| `invalid_json` | 数据不是合法 JSON | 让模型重新输出，或重试 |
| `invalid_schema_json` | Schema 不是合法 JSON | 修正 Schema 文本 |
| `schema_error` | 是合法 JSON，但不是合法 Schema | 修正 Schema 结构 |
| `unsupported_draft` | `$schema` 声明了不支持的 Draft | 换成支持的 Draft |
| `ref_resolution_error` | `$ref` 无法解析 | 把引用内联进来 |
| `validation_failed` | JSON 合法但不匹配 Schema | 按 `path` 修字段后重试 |
| `internal_error` | 预期外失败（不会抛异常） | 作为缺陷反馈 |

任何输入都不会导致工具抛异常，所有失败路径都返回结构化结果。

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

仅支持**内联** `$ref`（例如 `#/$defs/Address`）；远端引用不会被联网拉取，而是返回
`ref_resolution_error`。

## 严格模式

开启 `strict_mode` 后，插件会遍历 Schema，为所有**尚未约束额外字段**的 object 子
Schema 加上 `additionalProperties: false`，从而拒绝未定义字段。遍历覆盖
`properties`、`patternProperties`、`$defs`、`definitions`、`dependentSchemas`、
`items`、`prefixItems`、`allOf`、`anyOf`、`oneOf`、`not`、`if`/`then`/`else`、
`contains`、`propertyNames` 以及 Draft-07 的 `dependencies`。子 Schema 在以下情况
按对象处理：`type` 为 `"object"`、`type` 数组中包含 `"object"`（例如
`["object", "null"]` 这种可空对象）、或写了 `properties`/`required` 但没写 `type`。
原始 Schema 不会被修改。

## 工作流用法

```
LLM 节点 -> JSON Schema 校验 -> is_valid true  -> 正常流程
                             -> is_valid false -> 按 error_type 分支
                                                  validation_failed -> 带上错误信息重试
                                                  invalid_json      -> 加强提示词后重试
                                                  schema_error      -> 告警给流程作者
```

把 `error`、`path`、`schema_path` 回填到重试提示词中，模型即可精确修掉出错的字段。

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

打包：

```bash
dify plugin package . -o json-schema-1.0.0.difypkg
```

远程调试：复制 `.env.example` 为 `.env`，填入 Dify 实例提供的
`REMOTE_INSTALL_URL` 与 `REMOTE_INSTALL_KEY`，然后执行 `python -m main`。

## 目录结构

```
dify-plugin-json-schema/
├── main.py                          # 插件入口
├── manifest.yaml                    # 插件元数据
├── requirements.txt                 # 运行依赖
├── provider/
│   ├── json-schema.yaml             # Provider 配置
│   └── json-schema.py               # Provider 凭证校验（无需凭证）
├── tools/
│   ├── json_schema_validator.yaml   # 工具定义
│   └── json_schema_validator.py     # 工具实现
├── utils/
│   └── schema_utils.py              # 纯校验逻辑
├── tests/                           # 单元测试
└── _assets/icon.svg                 # 插件图标
```

## 图标

插件图标采用 JSON Schema 官方 Logo（<https://json-schema.org/logo-blue.svg>），
在浅色背景上居中放置。

## 许可证

[MIT](../LICENSE)
