# 设计决策记录：记忆沉淀管道的演化

> 记录时间：2026-03-28
> 作者：norrishuang + Dev Agent

本页记录 `session_snapshot → mem0` 这条记忆沉淀管道从最初设计到今日架构的完整演化过程，
梳理每次变更背后的动机、发现的问题、以及最终取舍。

---

## 阶段一：最初方案（快照直接写 mem0）

### 做了什么

在 `session_snapshot.py` 每次运行时，将新增的会话消息**同步推送**给 mem0 API。
目的是实现"实时记忆"——5 分钟快照周期内写入的对话，mem0 会立刻提炼成记忆，供下次 Agent 召回。

```
session → [snapshot 5min] → diary file
                          ↘ mem0 (直接 POST，实时写入)
```

### 发现的问题

1. **线程爆炸**：session_snapshot 是单进程处理多个 Agent session，每次直接 POST mem0 都要等 Bedrock LLM（fact extraction 约 3–10 秒）。当 session 数量多时，并发等待叠加，导致线程数量快速膨胀，进程占用暴涨。
2. **写入噪音大**：5 分钟内的碎片对话（几句话）直接喂给 mem0，LLM 提炼出的"记忆"质量差，大量无用短期记忆堆积在向量库中。
3. **职责耦合**：snapshot 同时承担"写日记"和"写记忆"两件事，任何一个失败都会相互影响。

### 修复（commit `a841494`）

从 session_snapshot 中移除 mem0 写入逻辑，**快照只写日记文件**，mem0 写入完全交给 auto_digest。

---

## 阶段二：更激进的实时沉淀方案（两层管道）

### 做了什么

为了弥补阶段一修复后"记忆只有每天 UTC 01:30 才更新一次"的问题，
引入了 `auto_digest.py --today` 增量模式，每 **15 分钟**运行一次：

1. 读取今天日记文件**自上次运行以来新增的字节**（通过 `auto_digest_offset.json` 追踪 byte offset）
2. 以 **50KB 为一批**直接 POST 给 mem0（由 mem0 内部做 fact extraction，不经过本地 LLM）
3. 每批成功后立即持久化 offset（断点续传）

形成了一个"两层"管道：

```
session → [snapshot 5min]  → diary
          [digest --today 15min] → mem0 (STM, 近实时)
          [digest 全量 01:30]    → mem0 (STM, 高质量)
          [archive 02:00]        → mem0 (LTM)
```

### 发现的问题

这个方案在技术上是可行的，但跑了一段时间后发现了一批新问题：

1. **日记文件膨胀失控**
   - session_snapshot 的原始去重逻辑用 `line not in existing_content` 做内容对比。
   - 但 diary 文件被 trim（裁剪）之后，历史内容消失，去重失效，导致相同消息反复写入。
   - 单日日记最大膨胀到 **2.6MB**（正常应 ≤ 200KB），里面有 **114 次重复快照**。

2. **trim 大小计算不准**
   - 原来用 `MAX_DIARY_LINES=800` 控制大小，实际每行长度不固定，800 行可以轻松超过 200KB 上限，trim 完全没有意义。

3. **auto_digest offset 和 diary trim 互相打架**
   - diary 被 trim 截断后，`auto_digest_offset.json` 记录的 byte offset 指向的内容已经不存在，
     下次运行时 offset 越界，导致重复或跳过读取。

4. **event=NONE 日志噪音**
   - mem0 内部 LLM 判断某条记忆不需要更新时返回 `event=NONE`，
     但 update API 不接受这个值，导致 server.py 每次都打 ERROR，日志非常吵。

---

## 阶段三：回归方案 + 精准修复（当前）

### 核心决策：退回到更简单的架构，精准修复已知 Bug

我们发现"更激进沉淀"方案带来的复杂度远高于收益，决定：

- **保留** `auto_digest.py --today` 增量写入，但不再依赖它做"实时"——它只是日记→mem0的补充通道
- **重点修复** session_snapshot 的根本问题，而不是在它之上堆更多逻辑

### 具体修复

#### Bug 1：重复写入（PR #20，commit `f3d87f2`）

**根因**：去重逻辑依赖文件内容，trim 之后历史行消失，去重失效。

**修复**：改为在 `offsets.json` 中持久化每条消息的 MD5 hash 集合（`written_hashes`）。
Hash 集合不受 trim 影响，即使日记被裁剪，下次运行仍能正确去重。

```python
# Before: 内容级去重（trim 后失效）
if line not in existing_content:
    write(line)

# After: hash 持久化去重（trim 不影响）
msg_hash = md5(message_content)
if msg_hash not in offsets["written_hashes"]:
    write(line)
    offsets["written_hashes"].add(msg_hash)
```

**验证**：连跑两次 session_snapshot，第二次写入 0 条 ✅

#### Bug 2：trim 大小不准（PR #20，commit `f3d87f2`）

**根因**：`MAX_DIARY_LINES=800` 不控制字节大小，实际文件大小不可预测。

**修复**：删除行数限制，改为**按字节预算循环裁剪**——每次丢弃前 10% 的行，直到文件 ≤ 200KB。

```python
MAX_DIARY_BYTES = 200 * 1024  # 严格 200KB 上限

while len(content.encode()) > MAX_DIARY_BYTES:
    lines = content.splitlines()
    drop = max(1, len(lines) // 10)  # 每次丢弃前 10%
    content = "\n".join(lines[drop:])
```

#### Bug 3：event=NONE 日志噪音（PR #20，commit `43893fe`）

**修复**：在 server.py 的 `add_memory` 异常捕获中识别 `event=NONE` 类错误，
降级为 `logger.warning()`，返回正常空响应，不影响调用方。

---

## 现状与取舍分析

### 当前架构

```
session → [snapshot 5min]         → diary（hash 去重，200KB 上限）
          [digest --today 15min]  → mem0 STM（50KB 分批，近实时）
          [digest 全量 01:30]     → mem0 STM（LLM 提炼，昨日完整上下文）
          [archive 02:00]         → mem0 LTM（活跃升级，不活跃删除）
```

### 优势

| 优势 | 说明 |
|------|------|
| **去重可靠** | Hash 持久化，trim 不影响去重逻辑，日记不再无限膨胀 |
| **大小可控** | 严格 200KB 字节预算，trim 保证文件始终可管理 |
| **近实时** | 15 分钟增量写入，今天发生的重要事情不用等到明天 01:30 才能被召回 |
| **高质量全量** | 每天 01:30 对昨日完整日记做 LLM 提炼，利用全天上下文产出更高质量记忆 |
| **容错隔离** | snapshot 和 digest 职责分离，任一失败不影响另一个 |

### 劣势 / 已知问题

| 劣势 | 说明 | 缓解方案 |
|------|------|----------|
| **diary trim 会丢失早期对话** | 文件超 200KB 时裁剪头部，当天早期对话可能在 01:30 全量 digest 前被丢弃 | digest --today 每 15 分钟已将新内容写入 mem0，trim 时那部分内容应已被提取 |
| **auto_digest offset 与 trim 仍有潜在冲突** | trim 后 offset 可能越界 | 已知问题，待后续修复（auto_digest 运行前需校验 offset 不超出当前文件大小） |
| **mem0 写入延迟高** | add 操作均值 ~9s，偶发 >10s 慢请求 | Bedrock 调用延迟，暂无绕过方案；semaphore 限流避免了并发爆炸 |
| **15min timer 重复拍同一会话** | user systemd timer 有时会在同一会话还未结束时重复触发 | hash 去重已覆盖这个问题，不会重复写入 |

---

## 核心经验

1. **"激进沉淀"不等于"更好的记忆"**——碎片对话直接喂给 LLM，提炼出的记忆质量差，不如积累完整上下文后一次处理。

2. **去重逻辑必须对存储操作鲁棒**——依赖文件内容做去重，在有 trim/rotate 的场景下必然失效；持久化 hash 才是正确做法。

3. **字节预算 > 行数限制**——用行数控制文件大小是反模式，单行长度不固定，只有字节才是准确的度量单位。

4. **职责分离比实时更重要**——snapshot 只写日记，digest 只写 mem0，边界清晰后每个组件都可以独立优化和排查。

5. **先跑起来再优化**——我们在复杂方案出问题之前无法预判所有边界情况，快速迭代 + 精准回归比一开始就设计完美更实际。
