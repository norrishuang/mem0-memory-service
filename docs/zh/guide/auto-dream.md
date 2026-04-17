# AutoDream：沉睡的大脑

> *「每天夜里，当 Agent 进入「睡眠」，它的记忆正在被悄悄整理、晋升和精简——就像人类大脑在 REM 睡眠中所做的事情。」*

## 设计理念

人类的记忆巩固分两个阶段：**潜意识**在白天持续处理和编码经历，**深度睡眠**则将重要的内容重组并提升为长期存储。

AutoDream 管道正是对这一机制的镜像设计：

- **Auto Digest = 潜意识处理** — 在白天持续运行，悄悄吸收每一次对话
- **Auto Dream = 深度睡眠** — 每晚运行一次（UTC 02:00），完成繁重的认知工作：反思一周规律、晋升老化的短期记忆、清理长期记忆中的冗余

两个阶段均无需人工干预。Agent 第二天醒来时，拥有更丰富、更有条理的记忆。

---

## 第一阶段：Auto Digest（潜意识）

`auto_digest.py --today` 每 **15 分钟**运行一次。它读取日记文件（`memory/YYYY-MM-DD.md`）自上次运行以来的新增内容，交给 mem0 做事实提取。

**具体做了什么：**

对每个新日记块，`auto_digest` 并行执行**两轮提取 Pass**：

| Pass | 提示词 | 输出 | 目的 |
|------|--------|------|------|
| **Pass ①** | mem0 默认提示词 | `category=short_term` | 通用事实、上下文、项目状态 |
| **Pass ②** | 任务专项 `custom_extraction_prompt` | `category=task` | 仅提取已完成的工作成果，格式为 `[类型] 描述` |

Pass ② 存在的原因：通用事实提取容易产生混杂、粒度不一的条目。专项任务 Pass 提取出干净、可操作的记录，例如：

```
[开发] 完成 Step 3 候选对处理，找到12个候选对（dev agent）
[分析] 分析 auto_dream_reflect 写入数为0的原因（记忆重复问题）
[配置] 将当前会话关键记忆写入 memory/2026-04-17.md 日记文件
```

这些条目打上 `category=task` 标签，可以通过精确召回查询「最近完成的任务」直接定位——无需在散乱的事实里筛选。

**关键设计：通过 `run_id` 限定去重范围**

`auto_digest` 写入的每条记忆都携带 `run_id = YYYY-MM-DD`（今天的日期）。mem0 处理 `infer=True` 写入时，去重范围仅限于同一 `run_id` 内。这意味着：

- 每 15 分钟写入是安全的——同天条目会互相合并，但绝不会静默覆盖长期记忆
- 今天的短期条目在自己的隔离命名空间中累积，直到 Auto Dream 决定保留什么

```
每 15 分钟：
  日记新增内容
    ├─ Pass ①  → mem0 短期记忆  (run_id=今天, category=short_term)
    └─ Pass ②  → mem0 短期记忆  (run_id=今天, category=task)
```

---

## 第二阶段：Auto Dream（深度睡眠）

`auto_dream.py` 每晚 **UTC 02:00** 运行一次，依次执行三个步骤。

### Step 1：跨日反思

Auto Dream 读取每个 Agent **近 7 天的日记文件**，拼接成单一文本语料，配合专门设计的 `REFLECTION_PROMPT` 提交给 mem0。

这个提示词与 Auto Digest 的通用提取有本质区别——它明确指示 LLM **忽略单次事件**，专注于跨越多天、反复出现的规律：

> *「是同类错误在多天中出现 2 次以上？Agent 自身失误模式？被 Boss 纠正的行为规律？反复出现的绕路模式？」*

四个反思维度：

| 维度 | 捕捉内容 |
|------|---------|
| **反复出现的错误** | 同类问题跨不同天出现 2 次以上 |
| **Agent 自身失误模式** | 判断错误、跳过确认步骤、自作主张导致返工 |
| **被用户纠正的行为规律** | 用户明确异议或纠正的操作方式，出现多次 |
| **耗时/绕路模式** | 反复出现走弯路、回退操作的任务类型 |

输出结果——跨日、具有规律性的洞察——**直接写入长期记忆**（无 `run_id`）。这是刻意的设计：单次事件停留在短期；只有经历多天考验的规律，才通过反思晋升为长期记忆。

```
7天日记语料
    │
    ▼  REFLECTION_PROMPT（仅提取跨日规律）
    ▼  mem0 infer=True
    │
    ▼  长期记忆（无 run_id）
       metadata: source=auto_dream_reflect, reflect_range=YYYY-MM-DD~YYYY-MM-DD
```

### Step 2：短期记忆 → 长期记忆晋升

Auto Dream 以精确 **7 天前**的 `run_id` 为目标，对那批短期记忆逐条处理：

1. 以 `infer=True` 重新提交记忆文本给 mem0，**不携带 `run_id`**
2. mem0 搜索全量长期记忆库，作出决策：`ADD`、`UPDATE`、`DELETE` 或 `NONE`
3. 原始短期条目无论决策结果如何，均被删除

这是整个记忆历史中**唯一一次全局去重**的时机。去掉 `run_id` 意味着去重范围从「同一天」扩展到「全部历史」——mem0 现在可以判断这条记忆是否已在长期库中有所记录，并决定合并、更新或丢弃。

```
7天前的短期记忆
    │
    ▼  重新提交给 mem0（infer=True，无 run_id）
    ▼  mem0 全局去重：ADD / UPDATE / DELETE / NONE
    │
    ├─ ADD     → 创建新的长期记忆条目
    ├─ UPDATE  → 更新已有长期记忆条目
    ├─ DELETE  → 与已有知识冲突，丢弃
    └─ NONE    → 已被捕获，静默丢弃
    （原始短期条目在所有情况下均被删除）
```

**为什么是 7 天？**

7 天足够让一条短期记忆被反思覆盖（Step 1 读取过去 7 天日记）。到 Step 2 处理某个 `run_id` 时，Step 1 已经有多次机会从那段时间的日记中提取跨日规律。进入 Step 2 的，是没有被规律吸收的原始短期层——那些需要做最终决策的个别事实：保留、合并还是丢弃。

### Step 3：长期记忆整合

即使经过干净的晋升，随着数周数月不断新增条目，长期记忆中仍会积累语义上的冗余。Step 3 执行周期性清理。

**运作方式：**

1. 加载该 Agent 的全量长期记忆
2. 使用轮转 offset 选取当前批次（每次 50 条）
3. 对批次中每条记忆，执行向量相似度搜索
4. 发现近似重复对（score > 0.85）时，将两条文本合并提交给 mem0（`infer=True`）
5. 若 mem0 产生 `ADD` 或 `UPDATE` 事件 → 删除两条原始记忆，保留合并后的条目
6. 若 mem0 返回 `NONE` → 该对实际上并不冗余，保持不变
7. 保存更新后的 offset 供下次运行使用

轮转机制确保所有长期记忆都能被定期审查，同时避免单次运行时间过长。

---

## 为什么这样设计

| 设计目标 | AutoDream 如何实现 |
|----------|-------------------|
| **白天写入低风险** | `auto_digest` 使用 `run_id` 作用域隔离——从不触碰长期记忆 |
| **长期记忆保持紧凑** | 全局去重仅在 Auto Dream 时发生，而非每次写入 |
| **规律比个别事件更持久** | `REFLECTION_PROMPT` 明确过滤掉单次发生的事实 |
| **无需人工整理** | mem0 自身的 LLM 决定 ADD/UPDATE/DELETE/NONE，Agent 不写去重逻辑 |
| **记忆不会无限增长** | Step 2 晋升后删除原始条目；Step 3 整合冗余对 |
| **不同阶段不同提取粒度** | 潜意识（Auto Digest）= 快速 + 广泛；深度睡眠（Auto Dream）= 缓慢 + 有选择 |

最终结果：**Agent 像人一样积累知识**——日常经历持续流入，反复出现的规律结晶为长期记忆，冗余事实在沉睡中悄然清除。

---

## 真实示例

以下是这套系统在实际部署中，一条知识经历完整管道的真实追踪。

### Day T：工作发生

2026-04-17，dev agent 正在处理 `auto_dream.py` Step 3 整合逻辑。期间，`session_snapshot.py` 每 5 分钟将对话写入 `memory/2026-04-17.md`。

15 分钟内，`auto_digest --today` 对新增日记内容执行了两轮 Pass。

**Pass ① 产出（通用事实）：**
```
- Python developer (based on code snippets)
- The project involves server.py and Memory.from_config()
- Using reflect_week function for memory reflection
```

**Pass ② 产出（任务提取）：**
```
[开发] 完成 Step 3 候选对处理，找到12个候选对（dev agent）
[分析] 分析 auto_dream_reflect 写入数为0的原因（记忆重复问题）
[分析] 验证 reflect_week 逻辑工作正常，7天日记合并读取成功
[开发] blog agent 完成7天日记反射，生成88,923字符记忆
```

两组条目均以 `run_id=2026-04-17` 存入短期记忆，可立即查询——工作发生后 20 分钟内，同一 Agent 的另一个 session 就能搜到：

```json
{
  "memory": "[开发] 完成 Step 3 候选对处理，找到12个候选对（dev agent）",
  "memory_type": "short_term",
  "run_id": "2026-04-17",
  "metadata": { "source": "auto_digest_task", "category": "task" }
}
```

### 当晚：Auto Dream 运行

UTC 02:00，`auto_dream.py` 执行 Step 1：读取 7 天日记语料（2026-04-11 至 2026-04-17），配合 `REFLECTION_PROMPT` 提交。LLM 识别出一个跨日规律——dev agent 在多个 session 中反复分析和调试 Auto Dream 内部逻辑——并将这一观察**直接写入长期记忆**（无 `run_id`）：

```json
{
  "memory": "Agent 在多天内反复分析和调试 auto_dream 管道内部逻辑——反映出对记忆系统可靠性和正确性的持续关注",
  "memory_type": "long_term",
  "metadata": { "source": "auto_dream_reflect", "reflect_range": "2026-04-11~2026-04-17" }
}
```

Step 3（整合）同晚运行，发现若干关于 `mem0-memory-service` 项目状态的长期条目语义近似重复。9 对被整合为更简洁的合并条目，标记 `source=auto_dream_consolidation`：

```json
{
  "memory": "mem0-memory-service 正在活跃开发中；dev agent 是主要贡献者，专注于管道可靠性、embedding 模型切换和记忆整合功能",
  "metadata": { "source": "auto_dream_consolidation" }
}
```

### Day T+7：晋升发生

2026-04-24，Auto Dream Step 2 以 `run_id=2026-04-17` 为目标。每条短期条目不携带 `run_id` 重新提交给 mem0，mem0 搜索全量长期历史并作出决策：

| 短期条目 | mem0 决策 | 原因 |
|---------|-----------|------|
| `[开发] 完成 Step 3 候选对处理，找到12个候选对` | `ADD` → 长期记忆 | 长期库中无对应条目 |
| `Using reflect_week function for memory reflection` | `NONE` | 已被 Step 1 反思条目覆盖 |
| `Python developer (based on code snippets)` | `UPDATE` | 合并入已有「dev agent 技术栈」记忆 |

原始短期条目全部删除。重要的知识——任务完成记录、技术规律——在长期库中留存；通用或冗余的条目被静默丢弃。

### 结果

原本的原始对话片段，演变为：
- **15 分钟内** → 结构化任务记录，可按 category 精确查询
- **当晚** → 反复出现的规律结晶为长期洞察
- **7 天后** → 个别事实晋升，冗余条目丢弃，长期记忆库保持紧凑

全程无需任何人工整理。这就是 AutoDream 的设计初衷：*不只是归档过去，而是提炼它。*

---

## 时序总结

| 时间 | 脚本 | 发生了什么 |
|------|------|-----------|
| 每 5 分钟 | `session_snapshot.py` | 对话 → 日记文件 |
| 每 15 分钟 | `auto_digest.py --today` | 日记 → 短期记忆（Pass ①：通用事实 + Pass ②：任务提取） |
| UTC 02:00 | `auto_dream.py` Step 1 | 7天日记语料 → 长期记忆（跨日反思，`REFLECTION_PROMPT`） |
| UTC 02:00 | `auto_dream.py` Step 2 | 7天前短期记忆 → 重新提交至长期（全局去重）→ 删除原始条目 |
| UTC 02:00 | `auto_dream.py` Step 3 | 长期记忆整合：轮转批次扫描 → 合并近似重复对 |
