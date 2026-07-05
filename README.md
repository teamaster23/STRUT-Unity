# STRUT-Unity

STRUT-Unity 是一个把 STRUT 风格的 C 语言测试用例生成流程接到 Unity C 单元测试框架上的工具。给定一个 C 源文件和目标函数后，它会分析函数上下文，生成结构化测试用例，生成 Unity 测试代码，编译并运行测试二进制文件，并在可用时收集 `gcov` 覆盖率。

当前项目的核心判断方式是：LLM 或规则生成的结构化用例包含 `inputs`、`outputs`、`stubins`；其中 `outputs` 会被直接写成 Unity 断言。项目还会生成一个不包含断言的 `pass_only` 版本，用来区分“输入和 stub 是否能正常执行”和“outputs 断言是否通过”。

## 项目结构树

```text
STRUT-Unity/
├── README.md
├── Makefile
├── run_dataset.py
├── zhizengzeng.env
├── Test Cases Generation Prompts.md
├── Test Suite Optimization Prompts Used By STRUT.md
├── json structure.md
├── Prompts Used by LLM baseline method.md
├── Liu 等 - 2025 - STRUT Structured Seed Case Guided Unit Test Generation for C Programs using LLMs.pdf
├── strut_unity/
│   ├── __init__.py
│   ├── __main__.py
│   ├── analyzer.py
│   ├── cases.py
│   ├── coverage.py
│   ├── llm_cases.py
│   ├── llm_client.py
│   ├── pipeline.py
│   ├── prompts.py
│   ├── source_rewriter.py
│   ├── stubs.py
│   └── unity_writer.py
├── unity/
│   ├── unity.c
│   ├── unity.h
│   └── unity_internals.h
├── tests/
│   ├── test_llm_cases_json.py
│   ├── test_llm_trace.py
│   ├── test_pass_only_mode.py
│   └── test_standard_library_stubs.py
├── _dataset/
│   └── data_structures/
└── build/
    └── 运行时生成的测试、可执行文件、覆盖率和批处理结果
```

`build/`、`__pycache__/`、`.pyc`、`.gcda`、`.gcno`、`.gcov` 都是中间产物，可以删除。

## 环境要求

安装 Python 依赖：

```sh
pip install clang tree-sitter tree-sitter-c
```

运行时还需要这些本地工具：

- `clang`：编译生成的 Unity 测试；
- `gcc` 和 `gcov`：收集覆盖率；
- OpenAI-compatible chat-completions endpoint：仅 `llm` 和 `hybrid` 模式需要。

`rules` 模式不调用大模型，适合先做本地冒烟测试。

## 命令行使用

### 单个函数

只用规则生成测试用例：

```sh
python3 -m strut_unity _dataset/data_structures/array/carray.c \
  --function insertValueCArray \
  --case-source rules \
  --no-optimize
```

使用默认 `hybrid` 模式：

```sh
python3 -m strut_unity _dataset/data_structures/array/carray.c \
  --function insertValueCArray
```

`python3 -m strut_unity` 的参数：

- `source`：必填，包含目标函数的 C 源文件。
- `--function` / `-f`：目标函数名；不传时默认选第一个函数定义。
- `--case-source rules|llm|hybrid`：选择用例来源，默认 `hybrid`。
- `--llm-base-url`：OpenAI-compatible API 地址；默认读 `STRUT_LLM_BASE_URL`，否则使用本地 Ollama 地址。
- `--llm-model`：模型名；默认读 `STRUT_LLM_MODEL`。
- `--llm-api-key`：API key；默认读 `STRUT_LLM_API_KEY` 或 `OPENAI_API_KEY`。
- `--no-optimize`：跳过 LLM 优化 pass。

`--case-source` 三种模式：

- `rules`：只使用确定性种子用例。
- `llm`：直接让 LLM 生成结构化测试用例。
- `hybrid`：先生成规则种子用例，把它们作为结构化示例提供给 LLM，再使用 LLM 输出作为测试套件。

每次运行会打印 JSON 摘要，并在 `build/` 下写入：

- `<function>_context.json`
- `<function>_cases.json`
- `<function>_pass_only_cases.json`
- `test_<function>.c`
- `test_<function>_pass_only.c`
- `test_<function>`
- `test_<function>_pass_only`
- 可选的 LLM prompt/response trace
- 可选的 `coverage_<function>_<stage>/`

### 本地 LLM

本地默认按 Ollama 兼容接口处理：

```sh
export STRUT_LLM_BASE_URL=http://127.0.0.1:11434/v1
export STRUT_LLM_MODEL=qwen3.5:latest
```

运行：

```sh
python3 -m strut_unity _dataset/data_structures/array/carray.c \
  --function insertValueCArray \
  --case-source hybrid
```

也可以全部写成命令行参数：

```sh
python3 -m strut_unity _dataset/data_structures/array/carray.c \
  --function insertValueCArray \
  --case-source llm \
  --llm-base-url http://127.0.0.1:11434/v1 \
  --llm-model qwen3.5:latest
```

如果本地 URL 下没有设置 `STRUT_LLM_MODEL`，客户端会尝试执行 `ollama list`，优先选择已安装的 `qwen3.5` 模型；否则回退到 `qwen3.5:latest`。

### 在线 LLM

任意 OpenAI-compatible chat-completions API 都可以使用：

```sh
export STRUT_LLM_BASE_URL=https://api.openai.com/v1
export STRUT_LLM_API_KEY=...
export STRUT_LLM_MODEL=...
```

运行：

```sh
python3 -m strut_unity _dataset/data_structures/array/carray.c \
  --function insertValueCArray \
  --case-source hybrid
```

或者：

```sh
python3 -m strut_unity _dataset/data_structures/array/carray.c \
  --function insertValueCArray \
  --case-source llm \
  --llm-base-url https://api.openai.com/v1 \
  --llm-model YOUR_MODEL \
  --llm-api-key YOUR_API_KEY
```

### 批量运行数据集

`run_dataset.py` 会扫描 `_dataset/data_structures`，跳过测试驱动文件和 `main.c`，发现函数定义，并逐个调用 `python3 -m strut_unity`。

小规模规则模式冒烟测试：

```sh
python3 run_dataset.py \
  --case-source rules \
  --limit 5 \
  --no-optimize
```

本地 LLM 批量运行：

```sh
export STRUT_LLM_BASE_URL=http://127.0.0.1:11434/v1
export STRUT_LLM_MODEL=qwen3.5:latest

python3 run_dataset.py \
  --case-source hybrid \
  --llm-model qwen3.5:latest \
  --timeout 300
```

在线 LLM 批量运行：

```sh
export STRUT_LLM_BASE_URL=https://api.openai.com/v1
export STRUT_LLM_API_KEY=...
export STRUT_LLM_MODEL=...

python3 run_dataset.py \
  --case-source hybrid \
  --llm-model "$STRUT_LLM_MODEL" \
  --timeout 300
```

`run_dataset.py` 的参数：

- `--dataset-dir`：要扫描的数据集目录，默认 `_dataset/data_structures`。
- `--output-dir`：批量结果输出目录，默认 `build/dataset_results`。
- `--case-source rules|llm|hybrid`：用例生成模式。
- `--llm-model`：批处理传给单函数 pipeline 的模型名。
- `--limit N`：只运行前 `N` 个目标函数。
- `--timeout SECONDS`：每个函数的超时时间。
- `--include-main`：包含 `main` 函数。
- `--no-optimize`：跳过 LLM 优化 pass。

批量产物会移动到：

```text
build/dataset_results/<relative-source>/<source-stem>/<function>/
```

### Makefile 快捷命令

```sh
make rules-demo
make llm-demo
make hybrid-demo
make clean
```

当前 `Makefile` 的 demo 目标引用 `examples/classify_score.c`。如果 checkout 中没有这个文件，请使用上面的 `_dataset/data_structures/...` 直接命令。

### 运行测试

```sh
python3 -m unittest discover -s tests
```

## Python 文件与函数说明

下面按源码文件列出主要类和函数。以下划线开头的函数是内部辅助函数，通常不作为外部 API 使用。

### `strut_unity/__init__.py`

模块说明字符串，无函数。

### `strut_unity/__main__.py`

作为 `python3 -m strut_unity` 的入口，导入并调用 `pipeline.main()`。

### `strut_unity/analyzer.py`

数据类：

- `TypeField`：描述结构体字段、数组字段、指针字段等类型信息。
- `Parameter`：描述目标函数参数。
- `DependencyItem`：描述宏、全局变量、typedef、结构体等依赖片段。
- `CalleeInterface`：描述目标函数调用到的函数接口。
- `DependencyDetails`：聚合依赖项、被调函数接口和函数调用名称。
- `FunctionDefinition`：表示一个 C 函数定义的位置和名称。
- `FunctionContext`：pipeline 使用的完整函数上下文。

函数：

- `analyze_function`：分析 C 文件中的目标函数，返回 `FunctionContext`。
- `list_function_definitions`：列出 C 文件中的函数定义，供批处理发现目标。
- `_parameter_from_cursor`：从 libclang cursor 构造 `Parameter`。
- `_looks_like_array_parameter`：判断参数是否应按数组参数处理。
- `_type_info`：从 clang 类型提取类型种类、指针元素、数组元素和字段。
- `_fields_for_type`：递归提取结构体字段信息。
- `_dependency_details`：收集目标函数所需的宏、全局变量、类型和被调函数。
- `_dependency_item_from_cursor`：把 clang cursor 转为依赖项。
- `_callee_declaration_item`：为被调函数生成声明依赖。
- `_callee_interface`：提取被调函数签名和返回类型。
- `_function_prototype`：生成函数原型字符串。
- `_referenced_macro_names`：找出目标函数引用的宏名。
- `_record_kind_name`：获取结构体、联合体等 record 类型名。
- `_cursor_type_spelling`：读取 cursor 的类型文本。
- `_cursor_location`：读取 cursor 的文件、行、列位置。
- `_cursor_is_local`：判断 cursor 是否位于当前源文件。
- `_source_excerpt`：按行读取源代码片段。
- `_macro_source`：获取宏定义源码。
- `_dedupe_items`：依赖项去重。
- `_dedupe_callee_interfaces`：被调函数接口去重。
- `_record_type`：从 C 类型中解析 record 类型。
- `_is_record_type`：判断是否为结构体或联合体类型。
- `_is_basic_type`：判断是否为基础标量类型。
- `_strip_pointer`：去掉类型字符串里的指针符号。
- `_tree_sitter_summary`：用 tree-sitter 检查语法错误和函数数量。
- `_find_function`：在语法树中定位目标函数。
- `_condition_from_if`：从 `if` 语句提取条件文本。
- `_compact_condition`：压缩条件 token 为可读字符串。

### `strut_unity/cases.py`

数据类：

- `InputValue`：结构化输入项。
- `OutputValue`：结构化输出断言项。
- `StubIn`：结构化 stub 输入，描述被调函数及其返回值/副作用。
- `ArgumentBinding`：把结构化输入转换成 C 局部声明和实参。
- `TestCase`：内部测试用例模型，包含输入绑定、stub 和 outputs。

函数：

- `default_ptr_entries`：生成默认指针参数到本地目标变量的映射。
- `to_original_seed_case`：把内部 `TestCase` 转回 STRUT 风格 JSON。
- `convert_inputs_with_default_ptr`：把用户表达式转换成生成测试里的本地指针变量表达式。
- `_stub_to_json`：把 `StubIn` 转为 JSON。
- `_return_expr`：生成目标函数调用形式的返回值表达式。
- `is_return_output`：判断某个 output 是否表示返回值。
- `case_return_output`：取得某个 case 的返回值 output。
- `case_outputs`：返回规范化后的 outputs。
- `case_declarations`：收集 case 需要的 C 局部声明。
- `generate_seed_cases`：根据参数类型和分支条件生成确定性种子用例。
- `case_from_structured_inputs`：从 LLM 的 `inputs` 构造内部 case。
- `case_from_args`：从简单 `args` 数组构造内部 case。
- `_append_case`：按输入 identity 去重后追加 case。
- `_normalize_return_output`：把返回值 output 规范成目标函数调用表达式。
- `_output_type`：取得 output 的 C 类型。
- `_is_generic_return_expr`：识别 `returnValue`、`retval` 等通用返回值名字。
- `_generic_return_exprs`：返回通用返回值名字集合。
- `_binding_for_parameter`：根据参数类型选择具体绑定策略。
- `_basic_binding`：生成基础类型参数绑定。
- `_array_binding`：生成数组参数绑定。
- `_pointer_binding`：生成指针参数绑定。
- `_null_pointer_binding`：生成 `NULL` 指针参数绑定。
- `_composite_pointer_binding`：生成结构体指针参数绑定。
- `_field_initialization`：生成结构体字段初始化代码。
- `_pointer_target_length`：推断指针目标数组长度。
- `_indexed_override_values`：提取数组下标覆盖值。
- `_positive_int`：把字符串解析为正整数。
- `_interesting_values`：从分支条件中提取边界值。
- `_interesting_field_values`：从结构体字段相关条件中提取边界值。
- `_default_value`：给参数生成默认值。
- `_value_for_parameter`：从结构化输入中查找某个参数的值。
- `_parameter_expr_candidates`：生成参数可能出现的表达式名字。
- `_format_overrides`：格式化字段或数组元素覆盖值。
- `_default_values_for_type`：给类型生成默认候选值集合。
- `_default_value_for_type`：给类型生成单个默认值。
- `_literal_for_type`：把值格式化成 C 字面量。
- `_boundary_values`：根据比较操作符生成边界测试值。
- `_condition_mentions_null`：判断条件是否涉及某指针的 `NULL` 检查。
- `_is_composite_type`：判断类型是否为结构体类复合类型。
- `_is_numeric_type`、`_is_int_like`、`_is_float_type`、`_is_bool_type`、`_is_char_type`：类型分类辅助函数。
- `_strip_pointer`、`_normalize_type`、`_normalize_expr`：类型和表达式规范化。
- `_format_value`：把 JSON 值格式化为内部字符串值。
- `_sort_key`：为候选值排序。
- `_safe_name`：把表达式转换成可用作 C 变量名的安全名字。
- `_convert_expr_with_default_ptr`：把原始指针表达式改写为测试代码里的本地变量表达式。
- `_flip`：翻转比较操作符方向。

### `strut_unity/coverage.py`

- `collect_gcov_coverage`：编译带覆盖率插桩的测试并运行 `gcov`。
- `_parse_gcov_output`：解析 `gcov` 标准输出中的文件级覆盖率。
- `_parse_function_gcov_file`：解析 `.gcov` 文件并抽取目标函数范围内的覆盖率。
- `_is_instrumented_count`：判断某行是否被 gcov 计为可执行。
- `_is_executed_count`：判断某行是否已执行。
- `_branch_was_taken`：判断分支是否被命中。
- `_uncovered_branch`：构造未覆盖分支的描述对象。
- `_branch_direction`：根据 gcov 分支编号推断方向描述。
- `_control_for_line`：定位分支行对应的控制语句。
- `_control_statement_from_line`：拼接跨行控制语句。
- `_extract_control_condition`：从 `if`、`while`、`for` 等语句中提取条件。
- `_prefix_keys`：给字典 key 加前缀。
- `_source_gcov_section`：从 gcov 输出中找出源文件对应段落。

### `strut_unity/llm_cases.py`

- `generate_llm_cases`：构造生成 prompt，调用 LLM，并解析测试用例。
- `generate_optimized_llm_cases`：构造覆盖率优化 prompt，调用 LLM，并解析补充用例。
- `parse_llm_cases`：从 LLM 文本响应中解析 `cases`。
- `_case_from_item`：把单个 JSON case 转成内部 `TestCase`。
- `_parse_stubins`：解析 `stubins` 或兼容字段 `stubs`。
- `_parse_outputs`：解析 `outputs`。
- `_output_value`：把 JSON output 项转成 `OutputValue`。
- `_load_llm_payload`：从文本中加载 JSON payload。
- `_extract_json`：从包含代码块或说明文字的响应里提取 JSON。
- `_json_candidates`：生成可能的 JSON 片段候选。
- `_has_cases`：判断 JSON 字符串是否包含可用的 `cases`。

### `strut_unity/llm_client.py`

数据类和客户端：

- `LLMConfig`：保存 LLM base URL、模型名、API key 和超时时间。
- `LLMConfig.from_env`：从环境变量构造配置。
- `LLMConfig.from_values`：从参数和环境变量合并构造配置。
- `OpenAICompatibleClient`：最小 OpenAI-compatible chat-completions 客户端。
- `OpenAICompatibleClient.chat_completion`：发送 chat-completions 请求并返回文本。

函数：

- `_is_local_url`：判断 endpoint 是否为本机地址。
- `_default_local_ollama_model`：从 `ollama list` 中选择默认本地模型。
- `write_llm_trace`：把 prompt 和 response 写入 `build/`。
- `_trace_prompt`：把 prompt 转成可读 trace。
- `_trace_message`：处理单条消息的 trace 表示。
- `_readable_content`：把长 prompt 拆成可读结构。
- `_content_sections`：按 Markdown 标题拆分内容。
- `_append_section`：追加一个 trace section。
- `_strip_fenced_code`：剥离 fenced code block。
- `_try_parse_json`：尝试解析 JSON。

### `strut_unity/pipeline.py`

- `run_pipeline`：主流程；分析函数、生成 cases、写测试、编译运行、收集覆盖率、必要时做优化 pass。
- `_write_compile_run_collect`：写 cases 和 Unity 测试，编译运行，并收集覆盖率结果。
- `_with_metric_summary`：合并完整断言运行和 pass-only 运行的状态摘要。
- `_result_status`：把编译/运行返回码转换成状态字符串。
- `_generate_cases`：按 `rules`、`llm`、`hybrid` 生成测试用例。
- `_merge_cases`：合并优化前后的用例并去重。
- `main`：命令行入口。

### `strut_unity/prompts.py`

- `build_case_generation_messages`：构造首次用例生成的 LLM messages。
- `build_optimization_messages`：构造覆盖率优化用的 LLM messages。
- `cases_to_structured_json`：把 seed cases 转成 prompt 中的结构化 JSON。
- `cases_to_strut_json`：把内部 cases 转成 STRUT 风格 JSON。
- `_render_template`：渲染 prompt 模板。
- `_structured_system_prompt`：返回系统提示词。
- `_to_prompt_seed_case`：把内部 seed case 转成 LLM 示例。
- `_global_inputs`：把全局变量依赖转成输入提示项。
- `_default_prompt_stubs`：为被调函数生成默认 stub 提示。
- `_stub_changed_variables`：为单个 stub 生成返回值和副作用字段。
- `_default_prompt_outputs`：生成默认 outputs 提示项。
- `_pointer_values`：为指针参数生成输入或输出提示项。
- `_field_values`：递归生成结构体字段提示项。
- `_callee_call_counts`：统计源码中被调函数调用次数。
- `_global_initial_value`：从全局变量源码中推断初始值。
- `_default_value_for_type`：按 C 类型生成默认值。
- `_strip_pointer`、`_normalize_type`：类型字符串辅助处理。
- `_read_prompt`：读取 prompt 模板文件。

### `strut_unity/source_rewriter.py`

- `prepare_test_source`：为测试构建准备源文件，必要时重命名 `main` 和被 stub 函数。
- `_identifier_replacements`：基于 tree-sitter 计算标识符替换位置。
- `_function_identifier`：取得函数定义中的函数名节点。
- `_first_identifier`：查找第一个 identifier 节点。
- `_walk_tree`：遍历 tree-sitter 节点。

### `strut_unity/stubs.py`

数据类：

- `StubSignature`：描述 stub 函数名、返回类型和参数列表。

函数：

- `should_stub_function`：判断某个函数是否应该被 stub，标准库直调函数会被排除。
- `stub_function_names`：从上下文和 cases 中收集需要 stub 的函数名。
- `stub_name`：把结构化 stub 描述映射到实际函数名。
- `stub_prelude`：生成 stub 所需的声明和宏。
- `stub_case_setup`：生成每个测试 case 的 stub 调用计数初始化代码。
- `stub_definitions`：生成完整 C stub 函数定义。
- `_call_index_name`：生成 stub 调用计数变量名。
- `_stub_signatures`：收集所有 stub 签名。
- `_stub_type_declarations`：为 stub 参数或返回类型补充必要类型声明。
- `_type_identifiers`：从类型文本中提取类型标识符。
- `_forward_typedef`：从依赖源码中生成前置 typedef。
- `_parse_signature`：解析函数签名。
- `_split_params`：拆分参数列表。
- `_normalize_parameter`：给缺少名字的参数补名字。
- `_prototype`：生成函数原型。
- `_definition_header`：生成函数定义头。
- `_stub_case_body`：生成单个 case 下 stub 的行为。
- `_assignment`：把副作用 output 转成赋值语句。
- `_is_return_expr`：识别 stub 返回值字段。
- `_default_return`：为没有指定返回值的 stub 生成默认 return。
- `_literal`：把 JSON 值转成 C 字面量。
- `_normalize_type`：规范化 C 类型字符串。

### `strut_unity/unity_writer.py`

- `write_unity_test`：把 `TestCase` 列表写成可编译的 Unity C 测试文件。
- `_assertions`：为目标函数返回值生成断言。
- `_pointer_assertions`：为指针返回值生成断言。
- `_struct_assertions`：为结构体返回值生成断言。
- `_output_assertions`：为普通 output 生成断言。
- `_resolve_output_expr`：把 output 表达式转换到测试代码变量空间。
- `_generic_output_assertions`：递归处理普通值、指针、结构体字段等 output。
- `_field_assertions`：为结构体字段生成断言。
- `_assertion`：按 C 类型选择 Unity 断言宏。
- `_literal_for_assertion`：把 expected 值转成断言字面量。
- `_zero_for_type`：生成类型对应的零值。
- `_normalize_type`：规范化类型字符串。
- `_strip_pointer`：去掉类型中的指针符号。

### `run_dataset.py`

- `discover_files`：扫描数据集目录下的 C 文件，并跳过测试驱动和 `main.c`。
- `discover_targets`：调用 analyzer 发现每个 C 文件中的目标函数。
- `move_build_artifacts`：把单次运行产生的 `build/` 产物移动到批处理结果目录。
- `_contains_path`：判断一个路径是否包含另一个路径。
- `parse_pipeline_stdout`：从 pipeline stdout 中解析 JSON 摘要。
- `resolve_cli_path`：把命令行路径解析为绝对路径。
- `run_single`：对单个源文件和函数运行 `python3 -m strut_unity`。
- `main`：批处理命令行入口。

## 测试文件说明

- `tests/test_llm_cases_json.py`：验证 LLM JSON 解析、inputs/outputs/stubins 保留和数组字段处理。
- `tests/test_llm_trace.py`：验证 LLM prompt trace 的可读化输出。
- `tests/test_pass_only_mode.py`：验证 pass-only 模式不会写断言，并验证 pipeline 的 pass-only/complete 状态摘要。
- `tests/test_standard_library_stubs.py`：验证标准库函数不会被错误 stub，普通依赖函数会生成 stub。

## 行为说明

- LLM 输出的 `outputs` 会直接成为 Unity 断言；项目不会再用单独 oracle 回填返回值。
- `pass_only_result` 表示不带 outputs 断言时测试是否能编译和运行。
- `complete_status` 表示带 outputs 断言的完整测试是否通过。
- 如果 `pass_only` 通过但 `complete` 失败，通常说明输入和 stub 可以执行，但生成的 outputs 断言不正确。
