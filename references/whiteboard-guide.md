# 飞书画板写入指南

## 前置条件

- 需要 `larksuite-cli-guide` skill 已加载
- 使用 `--as user` 身份操作

## 主方案：一步到位（推荐）

创建文档时直接嵌入 SVG 画板，一步完成：

```bash
lark-cli docs +create --title "<图表标题>" \
  --content '<whiteboard type="svg"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600">...</svg></whiteboard>' \
  --as user
```

从返回结果中获取 `doc_url`，直接交付给用户。

> **注意：** SVG 内容需要先从 `.svg` 文件中读取，整体嵌入 `<whiteboard type="svg">` 标签。

## 备选方案：传统 4 步流程

当主方案不支持时使用。

### 1. 创建飞书云文档（承载画板）

```bash
lark-cli docs +create --title "<图表标题>" --as user
```

从返回结果中获取 `doc_url` 和 `doc_token`。

### 2. 在文档中插入空白画板

```bash
lark-cli docs +update --doc <doc_token> --command append \
  --content '<whiteboard type="blank"></whiteboard>' --as user
```

### 3. 查询画板 ID

```bash
lark-cli whiteboard +query --doc <doc_token> --as user
```

从返回结果中获取 `whiteboard_token`。

### 4. 写入 SVG 到画板

```bash
cd <svg所在目录> && lark-cli whiteboard +update \
  --whiteboard-token <whiteboard_token> \
  --input_format svg \
  --source @./<filename>.svg \
  --overwrite --as user
```

**注意：** `--source` 必须使用相对路径（`@./filename.svg`），不支持绝对路径。需要先 `cd` 到 SVG 所在目录。

## 已知坑点

### 1. CSS 类被剥离 → ✅ 已修复（v2.0）

`html_to_svg.py` 现已支持：
- 解析 `<style>` 块中的 CSS 变量（`:root { --xxx: #xxx; }`）
- 解析 class 规则（`.node { fill: var(--input); }`）并解析 `var()` 引用
- 将所有 class-bound 样式内联为 presentation attributes（`fill="#bfdbfe"` 等）
- 处理 `var()` 直接写在元素属性上的情况（如 `fill="var(--line)"`）
- 修复 bs4 将 `viewBox` 转小写的问题

**无需手动处理，脚本自动完成。**

### 2. 路径相关

| 问题 | 解决 |
|------|------|
| `--source` 报"路径不在沙箱" | `cd` 到目标目录用 `@./file.svg` |
| 预览图已存在 | `--query --output` 加 `--overwrite` 覆盖 |

### 3. SVG 格式要求

- 根元素必须有 `xmlns="http://www.w3.org/2000/svg"` 和 `viewBox`
- `<text>` 上加 `font-family="Noto Sans SC, sans-serif"` 避免中文渲染问题
- 箭头必须用 `<marker>` 元素定义，并在路径上用 `marker-end="url(#arrow)"` 引用

## 验证

```bash
lark-cli whiteboard +query \
  --whiteboard-token <whiteboard_token> \
  --output_as image \
  --output ./preview \
  --as user
```

生成 `./preview.png`，检查渲染效果。