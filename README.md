# hand-drawn-to-whiteboard

> 将手绘结构图/脑图照片，自动识别后生成专业结构图，并写入飞书云文档画板（双击可编辑）。

## 适用场景

- 开会时白板拍照 → 一键转成可编辑画板
- 纸笔画的流程图 / 架构图 / 思维导图 → 飞书画板
- 团队分享时直接给链接，手机也能看也能改

## 5 步流程

| 步骤 | 做什么 | 用到 |
|------|--------|------|
| 1. 读图 | 识别节点、连线、箭头方向、分组、文字 | 视觉模型 |
| 2. 生成 HTML | 出专业结构图（语义色、连线、字体） | [diagram-maker](https://github.com/youli-aa/diagram-maker) |
| 3. HTML→SVG | 解析 CSS class、`var()` 变量、`viewBox`，转纯 SVG | `scripts/html_to_svg.py` |
| 4. 写画板 | `docs +create` 一步嵌入 `<whiteboard type="svg">` | lark-cli |
| 5. 交付 | 只返回飞书文档链接 | — |

## 触发方式

发一张手绘图片 + 类似下面的任一句话：

- "帮我生成结构图"
- "转成画板"
- "做成脑图"
- "放到画板里"
- "把这个图转成可以编辑的"

## 依赖

- **diagram-maker** skill（生成结构图 HTML/SVG）
- **lark-cli**（飞书文档 + 画板写入）

## 文件结构

```
hand-drawn-to-whiteboard/
├── SKILL.md                          # 主入口
├── references/whiteboard-guide.md    # 画板写入详细参考
└── scripts/html_to_svg.py            # HTML→SVG 转换（含 CSS class 解析）
```

## 已知能力

- 解析 `<style>` 里的 CSS class 规则
- 解析元素属性里的 `var(--xxx)` 变量
- 修正 bs4 转小写导致的 `viewBox` 问题
- 一步嵌入飞书画板（不再需要 create→update→query→update 四步）

## License

MIT
