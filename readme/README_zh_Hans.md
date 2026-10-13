# JSON Schema

为 Dify 工作流提供可靠的结构化输出：提取 LLM 产生的 JSON，依据 JSON Schema 校验，
并输出可供下游分支处理的带类型错误。

**作者：** [EFT](https://github.com/ztistic)
**仓库：** [dify-plugin-json-schema](https://github.com/ztistic/dify-plugin-json-schema)
**版本：** 1.0.0
**类型：** tool

## 为什么

LLM 节点虽然可以用 JSON Schema 引导输出，但无法保证结果真的符合——甚至无法保证是
可解析的 JSON。一旦模型输出漂移，下游节点要么解析失败，要么静默拿到错误结构。
本插件在 LLM 节点之后放置一道确定性的质量门，把坏输出变成带类型的、可分支的结果，
而不是静默的失败。

## 功能

- **JSON 提取**——从文本（通常是原始 LLM 回答）中取出第一段可解析的
  JSON 字符串。不猜测、不清洗、不修复。
- **JSON 校验**——依据 JSON Schema 校验 JSON 字符串
  （支持 Draft 2020-12 / 2019-09 / 07 / 06 / 04），并把每种失败归类为
  带类型的 `error_type`。
- 离线运行：不访问网络、不调用模型。

## 安装

要求 Dify ≥ 1.14.2，无需凭证或配置。

从 Dify Marketplace 安装 **JSON Schema**，或通过 *插件 → 安装 → 本地安装包*
上传已打包的 `json-schema-1.0.0.difypkg`。

## 使用

```
LLM 节点 -> JSON 提取 -> JSON 校验 -> 按结果分支
```

### JSON 提取

| 参数   | 类型   | 必填 | 说明                             |
|--------|--------|------|----------------------------------|
| `text` | string | 是   | 包含 JSON 的文本，通常是 LLM 的输出 |

只识别两种没有歧义的形态，按以下顺序尝试：

1. 整个输入本身就是 JSON，原样返回；
2. ```` ```json ```` 或无语言标记的代码围栏，内容逐字返回。

散文中裸嵌的 JSON 不在识别范围内，按 `no_json_found` 处理。

#### 输出

工具按不向外抛异常设计：所有已分类的失败都返回带类型的结构化 payload，
未预期的内部错误也会报为 `internal_error`，而不是继续上抛。
以下字段已在工具的 `output_schema` 中声明，下游节点可将它们作为类型化变量选用。

| 字段         | 类型    | 何时出现 | 说明                           |
|--------------|---------|----------|--------------------------------|
| `found`      | boolean | 总是     | 是否提取到可解析的 JSON 字符串 |
| `json`       | string  | 成功时   | 提取出的 JSON 文本（逐字）——交给校验器 |
| `error_type` | string  | 失败时   | 失败类别，见下表               |
| `error`      | string  | 失败时 | 人类可读的原因说明            |

text 消息在成功时为提取出的 JSON 字符串，失败时为空。

##### 错误类型

| `error_type`     | 含义                                    |
|------------------|-----------------------------------------|
| `invalid_input`  | `text` 缺失或为空白                     |
| `no_json_found`  | 整体不是 JSON，也没有可解析的 json 围栏 |
| `internal_error` | 预期外失败，如输入嵌套过深              |

### JSON 校验

| 参数           | 类型   | 必填 | 说明                                  |
|----------------|--------|------|---------------------------------------|
| `json_input`   | string | 是   | 待校验的 JSON 字符串——通常是提取器的 `json` |
| `schema_input` | string | 是   | JSON Schema；仅解析内联 `$ref` 指针   |

#### 输出

工具按不向外抛异常设计：所有已分类的失败都返回带类型的结构化 payload，
未预期的内部错误也会报为 `internal_error`，而不是继续上抛。
以下字段已在工具的 `output_schema` 中声明，下游节点可将它们作为类型化变量选用。

| 字段          | 类型    | 何时出现 | 说明                                       |
|---------------|---------|----------|--------------------------------------------|
| `is_valid`    | boolean | 总是     | 输入是否满足 Schema                        |
| `message`     | string  | 成功时   | `"Validation passed."`                     |
| `error_type`  | string  | 失败时   | 失败类别，见下表                           |
| `error`       | string  | 失败时   | 人类可读的原因，可直接回填重试提示词       |
| `path`        | array   | 失败时   | JSON 中出错的位置，如 `["tags", 2]`——始终存在，不适用时为空 |
| `schema_path` | array   | 失败时 | Schema 中被违反关键字的位置，如 `["properties", "age", "minimum"]`——失败时始终存在，不适用时为空数组 |

##### 错误类型

| `error_type`         | 含义                                                         |
|----------------------|--------------------------------------------------------------|
| `invalid_input`      | 参数缺失、为空白或无法转为 JSON 文本                         |
| `invalid_json`       | `json_input` 不是可解析的 JSON；`error` 带行号列号           |
| `invalid_schema_json`| `schema_input` 不是可解析的 JSON                             |
| `schema_error`       | Schema 本身违反其元 Schema                                   |
| `unsupported_draft`  | `$schema` 声明了 2020-12 / 2019-09 / 07 / 06 / 04 之外的 Draft |
| `ref_resolution_error` | 内联 `$ref` 指针无法解析；远程引用从不拉取                 |
| `validation_failed`  | JSON 合法、Schema 合法，但数据不匹配；`path` 与 `schema_path` 指向失败处 |
| `internal_error`     | 预期外失败，如嵌套超出解释器深度                             |

注意：

- 校验器不清洗输入：`json_input` 直接交给 `json.loads` 解析，任何本身不是
  合法 JSON 的输入都会报 `invalid_json`。
- Schema 按原样生效；拒绝未声明属性通过 `additionalProperties: false` 表达。
- `error`、`path`、`schema_path` 适合回填到重试提示词中。

## 限制

- 嵌套深度的边界来自解释器的递归深度。CPython 3.12 默认递归限制
  （未修改全局递归深度）下实测：Schema 约 95 层、数据约 100–200 层以内可
  正常处理，更深的输入返回结构化错误。
- 只解析内联 `$ref` 指针——从不解析远程引用，因为插件不访问网络。

## 实现

纯 Python 实现，基于 [jsonschema](https://pypi.org/project/jsonschema/) 库：
元 Schema 检查与实例校验均由其各 Draft 校验器类完成，内联 `$ref` 解析经由
其附带的 `referencing` 库。全流程不访问网络。

## 隐私

插件离线运行，不收集数据。见 [PRIVACY.md](../PRIVACY.md)。

## 本地开发

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
dify plugin package . -o json-schema-1.0.0.difypkg
```

远程调试：复制 `.env.example` 为 `.env`，填入 Dify 实例提供的
`REMOTE_INSTALL_URL` 与 `REMOTE_INSTALL_KEY`，然后执行 `python -m main`。

## 图标

插件图标采用 JSON Schema 官方 Logo（<https://json-schema.org/logo-blue.svg>）。

## 许可证

[MIT](../LICENSE)
