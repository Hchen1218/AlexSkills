# 本地引擎与手机记录协议

固定依赖为 `fsrs==6.3.2`。所有命令都用安装该依赖的 Python 运行；若配置文件含 `python_path`，可用 `scripts/run.py` 转交给该环境：

```sh
python scripts/practice.py --data-root /absolute/private/data COMMAND ...
python scripts/run.py COMMAND ...
```

数据根必须是绝对路径，也可由 `SPOKEN_ENGLISH_DATA_ROOT` 或 `~/.config/spoken-english/config.json` 的 `data_root` 提供。没有配置时命令拒绝创建数据，不从当前工作目录猜测。

## 命令

```text
init          --learner ID --profile '{"goal":"work"}'
apply         --learner ID --file local-record.json
report        --learner ID --at 2026-09-16T10:00:00+08:00
export-mobile --learner ID --out /absolute/private/export --at 2026-09-16T10:00:00+08:00
import-mobile --learner ID --file records.json
import-mobile --learner ID --file -
backup        --file /absolute/private/backup.sqlite3
restore       --file /absolute/private/backup.sqlite3
```

`apply` 用于当前电脑直接观察到的记录；`import-mobile` 标成外部报告，并要求 `package_id` 是该学习者真实导出过的包。导入接受一个对象、对象数组，或 Markdown 中多个 `spoken-english-record` JSON 代码块。整个批次事务提交：任一记录无效、同 ID 异内容或日期模糊时全部不写入。相同 ID 且规范化内容完全相同视为重复。

## 固定记录结构

导出生成的 `record-template.json` 是机器模板。手机在保留其头部字段后填三组数组：

```json
{
  "protocol_version": 1,
  "method_version": "spoken-english-v1",
  "learner_id": "demo",
  "package_id": "pkg-from-export",
  "sessions": [
    {
      "id": "session-20260916-a",
      "started_at": "2026-09-16T09:00:00+08:00",
      "status": "partial",
      "method_version": "spoken-english-v1",
      "scheduler_version": "fsrs-6.3.2-default-r0.9-no-fuzz"
    }
  ],
  "new_cards": [
    {
      "id": "phone-demo-001",
      "created_at": "2026-09-16T09:02:00+08:00",
      "expression": "I would rather wait.",
      "meaning": "我宁愿等一等。",
      "function": "表达偏好",
      "context": "讨论两个方案时",
      "personal_example": "I would rather wait until the tests pass.",
      "source": "教师示范后由学习者确认",
      "cue": "What would you prefer to do?"
    }
  ],
  "events": [
    {
      "id": "event-20260916-a1",
      "session_id": "session-20260916-a",
      "card_id": "phone-demo-001",
      "occurred_at": "2026-09-16T09:04:00+08:00",
      "kind": "retrieval",
      "method_version": "spoken-english-v1",
      "task_prompt": "你更愿意怎么做？请用目标表达回答。",
      "key_quote": "I would rather wait.",
      "evidence_source": "手机聊天中学习者原话；给答案后才说出",
      "hint": "answer",
      "input_mode": "transcript",
      "recall": "forgot",
      "accuracy": "correct",
      "transfer": "unknown"
    }
  ]
}
```

枚举不可扩写：

- `status`: `in_progress | partial | complete`
- `kind`: `retrieval | reading | shadowing | immediate_repeat | conversation | correction`
- `hint`: `none | cue | answer | unknown`
- `input_mode`: `text | transcript | audio | unknown`
- `recall`: `forgot | difficult | success | easy | unknown`
- `accuracy`: `correct | incorrect | mixed | unknown`
- `transfer`: `same_day | cross_day_new_context | unknown`

`task_prompt` 是题目原文；题目之后没有追加帮助才记 `hint:none`。`cue` 是不含目标英语答案的追加帮助；展示过完整或部分目标表达为 `answer`。纯朗读、跟读和刚展示后的复述分别用对应 `kind`，不会进入独立回忆调度。忘记或答案提示映射 Again；无追加提示的独立困难映射 Hard；独立成功映射 Good；`easy` 没有 `easy_evidence` 时仍按 Good。准确性和迁移不影响 FSRS 评级。

每次暂停使用新的稳定会话 ID 保存当前阶段；不要用同一个会话 ID 把 `partial` 改写成 `complete`。继续练习可新建会话阶段，并在可读摘要里说明接续关系。未做的题不生成事件。新增手机卡 ID 原样进入电脑，换聊天也不能另取 ID。

表达卡必须保留含义、沟通功能、适用情境、个人例句、来源和不泄露答案的提示；未观察字段写明 `unknown`，不能静默省略。每个会话快照同时保存方法版本和调度版本。

`cross_day_new_context` 还需 `prior_event_id`、`prior_context`、`transfer_context`，且引用同一张卡、更早本地日历日期的不同事件；前后情境也必须不同。事件时间保留明确时区，跨天判断使用记录里写明的本地日历日期，调度仍统一转为 UTC。自我引用、未来引用、同日记录或证据不全自动降为 `unknown`。声音评估字段只有在 `input_mode:audio` 且带 `audio_analysis_evidence` 时可出现。转写不能携带口音、语速、重音、音素或发音分数。

## 更正、重放与版本

历史只追加。要更正事件，新增 `kind:correction`，提供 `supersedes`、`recorded_at`、`replacement_kind`，并填写替代后的其余事件字段；不要编辑旧事件或复用旧 ID。引擎保留两条审计记录，确定性地按 `occurred_at` 和事件 ID 重放有效版本。冲突、更正循环和不兼容卡片拒绝写入。

调度标识为 `fsrs-6.3.2-default-r0.9-no-fuzz`：官方默认权重、`desired_retention=.9`、关闭 fuzz，不拟合个人参数。所有时刻要求明确 ISO 8601 时区，内部转 UTC；“昨天早上”必须待补。

报告分列到期队列、独立回忆事件、延迟回忆事件、准确性计数、本地观察与外部报告的跨天迁移数。外部迁移数仍标记未验证，不能当作能力等级。运行 `report`、导入或本地应用记录时，会在私有数据根更新 `summary-学习者ID.md`。手机导出最多五张到期卡和二十张活跃卡，并生成 `TEACHING.md`、`SUMMARY.md`、`progress.json` 和记录模板。

备份使用 SQLite 在线备份。恢复前检查完整性、schema 和必需表，并自动保留恢复前快照。升级旧 schema 时自动先做迁移前备份；未知更高版本拒绝打开。先在隔离数据根恢复、查看报告，再操作真实数据根。
