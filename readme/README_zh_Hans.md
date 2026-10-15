# JSON Schema

为 Dify 工作流提供可靠的结构化输出：提取 LLM 产生的 JSON，依据 JSON Schema 校验，
并输出可供下游分支处理的带类型错误。

**作者：** [EFT](https://github.com/ztistic)
**仓库：** [dify-plugin-json-schema](https://github.com/ztistic/dify-plugin-json-schema)
**版本：** 1.0.0 **类型：** tool

## 为什么

LLM 节点虽然可以用 JSON Schema 引导输出，但无法保证结果真的符合——甚至无法保证是
可解析的 JSON。一旦模型输出漂移，下游节点要么解析失败，要么静默拿到错误结构。
本插件在 LLM 节点之后放置一道确定性的质量门，把坏输出变成带类型的、可分支的结果，
而不是静默的失败。

## 功能

- **JSON 提取**——从文本（通常是原始 LLM 回答）中取出第一段可解析的 JSON 字符串。
  默认识别整体 JSON 与受信任的代码围栏；内嵌在散文中的 JSON 对象或数组仅在开启
  `scan_embedded` 时查找。不猜测、不清洗、不修复。
- **JSON 校验**——依据 JSON Schema 校验 JSON 字符串
  （支持 Draft 2020-12 / 2019-09 / 07 / 06 / 04），并把每种失败归类为带类型的
  `error_type`。
- 离线运行：不访问网络、不调用模型。

## 安装

要求 Dify ≥ 1.14.2，无需凭证或配置。

可从 Dify Marketplace 安装 **JSON Schema**，或通过 *插件 → 安装 → 本地安装包*
上传已打包的 `json-schema-1.0.0.difypkg`。

## 使用

```
LLM 节点 -> JSON 提取 -> JSON 校验 -> 按结果分支
```

两个工具共用同一份输出契约：

- 工具不向外抛异常：所有已分类的失败都返回带类型的结构化 payload，未预期的
  内部错误也会报为 `internal_error`。
- 每次调用先发出 text 消息（人类可读摘要），再发出 JSON payload，最后为每个
  已声明的输出字段各发一条变量消息——下游节点可将已声明字段作为类型化变量引用。
- 参数值以非字符串形式到达时（例如上游节点传来的已解析对象），先转换为
  JSON 文本再处理。

### JSON 提取

| 参数            | 类型    | 必填 | 说明                                |
|-----------------|---------|------|-------------------------------------|
| `text`          | string  | 是   | 包含 JSON 的文本，通常是 LLM 的输出 |
| `scan_embedded` | boolean | 否   | 默认关闭；开启后启用下方第 3 种形态 |

`scan_embedded` 按严格布尔读取：只有布尔值 `true` 会开启内嵌扫描，其它真值
（如字符串 `"true"`）不生效。

#### 识别形态

按以下顺序尝试三种形态，取第一个命中：

1. **整体 JSON**——整个输入本身就是 JSON。
2. **代码围栏**——```` ```json ```` 或无语言标记的代码围栏。语言标记大小写
   不敏感，围栏必须闭合；第一个内容可解析的围栏胜出。
3. **内嵌扫描**——文本中第一段完整的 JSON 对象或数组，仅在开启
   `scan_embedded` 时启用。扫描只以 `{`、`[` 为种子，散文中的裸数字、裸字符串
   和字面量不会成为候选；其它语言围栏或未闭合围栏中的 JSON 在此形态下可达。

每个候选都先解析成功才被采纳；返回的字符串是输入的逐字切片（首尾空白除外），
不会重新序列化。已检查的形态都取不到时按 `no_json_found` 处理，错误详情会说明
内嵌扫描是否处于关闭状态。

#### 输出

| 字段           | 类型    | 何时出现 | 说明                                   |
|----------------|---------|----------|----------------------------------------|
| `found`        | boolean | 总是     | 是否提取到可解析的 JSON 字符串         |
| `json_text`    | string  | 成功时   | 提取出的 JSON 文本——交给校验器         |
| `error_type`   | string  | 失败时   | 失败类别，见下表                       |
| `error_detail` | string  | 失败时   | 人类可读的原因说明                     |

text 消息在成功时为提取出的 JSON 字符串，失败时为空。

| `error_type`     | 含义                                       |
|------------------|--------------------------------------------|
| `invalid_input`  | `text` 缺失、为空白或无法转为 JSON 文本    |
| `no_json_found`  | 已检查的形态中都取不到 JSON                |
| `internal_error` | 预期外失败，如输入嵌套过深                 |

### JSON 校验

| 参数           | 类型   | 必填 | 说明                                             |
|----------------|--------|------|--------------------------------------------------|
| `json_input`   | string | 是   | 待校验的 JSON 字符串——通常是提取器的 `json_text` |
| `schema_input` | string | 是   | JSON Schema；仅解析内联 `$ref` 指针              |

#### Draft 选择

校验器类按 Schema 的 `$schema` 声明选择：

- 未声明、为空白或为通用 URI `http(s)://json-schema.org/schema#` → Draft 2020-12；
- 官方 Draft URI（`.../draft/2020-12/schema`、`.../draft-07/schema#` 等）或
  裸简写（`draft-07`、`draft/2020-12`）→ 对应 Draft；
- 其它取值——包括只是提到 Draft 编号的第三方 URI——按 `unsupported_draft` 拒绝。

Schema 为布尔值（`true` / `false`）同样合法。

#### 输出

| 字段                   | 类型    | 何时出现 | 说明                                                                                          |
|------------------------|---------|----------|-----------------------------------------------------------------------------------------------|
| `is_valid`             | boolean | 总是     | 输入是否满足 Schema                                                                           |
| `error_type`           | string  | 失败时   | 失败类别，见下表                                                                              |
| `error_detail`         | string  | 失败时   | 人类可读的原因，可直接回填重试提示词                                                          |
| `json_path`            | string  | 失败时   | JSON 中出错的位置，JSONPath 字符串，如 `$.tags[1]`；不适用时为空                              |
| `absolute_path`        | array   | 失败时   | 同一位置的原始路径段，如 `["tags", 1]`；不适用时为空                                          |
| `absolute_schema_path` | array   | 失败时   | Schema 中被违反关键字的位置，原始路径段，如 `["properties", "age", "minimum"]`；不适用时为空 |

成功时载荷恰为 `{"is_valid": true}`；失败时六个字段全部存在，分支无需防御性检查。
text 消息成功时为 `Validation passed.`，失败时为带 JSON 路径与 Schema 路径的
`Validation failed [error_type]` 摘要。

| `error_type`           | 含义                                                                       |
|------------------------|----------------------------------------------------------------------------|
| `invalid_input`        | 参数缺失、为空白或无法转为 JSON 文本                                       |
| `invalid_json`         | `json_input` 不是可解析的 JSON；`error_detail` 带行号列号                  |
| `invalid_schema_json`  | `schema_input` 不是可解析的 JSON                                           |
| `schema_error`         | Schema 不是对象或布尔值，或违反其元 Schema                                 |
| `unsupported_draft`    | `$schema` 声明了 2020-12 / 2019-09 / 07 / 06 / 04 之外的 Draft             |
| `ref_resolution_error` | 内联 `$ref` 指针无法解析；远程引用从不拉取                                 |
| `validation_failed`    | JSON 合法、Schema 合法，但数据不匹配；三个路径字段指向失败处               |
| `internal_error`       | 预期外失败，如嵌套超出解释器深度或 `$ref` 循环引用                         |

注意：

- 校验器不清洗输入：`json_input` 直接交给 `json.loads` 解析，任何本身不是
  合法 JSON 的输入都会报 `invalid_json`。
- Schema 按原样生效；仅在 Schema 声明 `additionalProperties: false` 的位置
  拒绝未声明属性。
- `error_detail`、`json_path`、`absolute_schema_path` 适合回填到重试提示词中。

## 限制

- 嵌套深度的边界来自解释器的递归深度。CPython 3.12 默认递归限制下实测：
  Schema 约 95 层、数据约 100–200 层以内可正常处理，更深的输入返回结构化错误。
- 只解析内联 `$ref` 指针——从不解析远程引用，因为插件不访问网络。

## 实现

纯 Python 实现。校验基于 [jsonschema](https://pypi.org/project/jsonschema/) 库：
元 Schema 检查与实例校验均由其各 Draft 校验器类完成，内联 `$ref` 解析经由其附带的
`referencing` 库。提取只使用标准库（`json`、`re`）。全流程不访问网络。

## 隐私

插件离线运行，不收集数据。见 [PRIVACY.md](../PRIVACY.md)。

## 本地开发

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
dify plugin package . -o json-schema-1.0.0.difypkg
```

远程调试：复制 `.env.example` 为 `.env`，填入 Dify 实例提供的
`REMOTE_INSTALL_URL` 与 `REMOTE_INSTALL_KEY`，然后执行 `python -m main`。

## 图标

插件图标采用 JSON Schema 官方 Logo（<https://json-schema.org/logo-blue.svg>）。

## 许可证

[MIT](../LICENSE)
