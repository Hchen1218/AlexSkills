#!/usr/bin/env python3
"""Deterministically grade the paired scripted replays; this measures behavior, not learning."""
from __future__ import annotations

import json
import re
import argparse
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2] / "spoken-english-workspace"

CHECKS = {
    "eval-1-foundation": [
        ("一次只给一个小任务", r"一次只做|只做一个小任务|先说一句|一句就好"),
        ("照读不算独立回忆", r"照着[\s\S]{0,80}(?:不算|不能记成|还不能算)[\s\S]{0,30}独立"),
        ("次日先提取再显示答案", r"先不看(?:英文)?答案|先不看昨天"),
        ("文字转写不评价口音", r"(?:只有.*转写[\s\S]{0,80}(?:无法|不能)|(?:无法|不能)[\s\S]{0,40}根据.*转写)[\s\S]{0,40}(?:评价)?[\s\S]{0,20}(?:口音|发音)"),
        ("未把同内容回忆冒充跨情境迁移", r"(?:不能据此|不能.*记为)[\s\S]{0,60}(?:跨天新情境|迁移)"),
    ],
    "eval-2-complex": [
        ("等待表达完成后反馈", r"说完之前.*不|说完后.*(?:点评|纠正)|我等你说完"),
        ("反馈聚焦一个组织重点", r"最值得改的一点|主要问题|先抓一个.*重点"),
        ("让学习者重试而非代写长稿", r"不给.*(?:长稿|完整稿|成句)|请自己|你自己的话"),
        ("提供未预演条件追问", r"(?:没|没有)预演过|未预演"),
        ("报告区分延迟回忆和跨天迁移", r"(?:不是|没有).*跨天[\s\S]{0,100}(?:延迟回忆|迁移)|不能证明.*迁移"),
        ("文字输入不评价声音", r"(?:文字输入|只有文字|没有原始音频)[\s\S]{0,80}(?:不评价|不能评价|无法评价)[\s\S]{0,30}(?:口音|发音|语速)"),
    ],
    "eval-3-mobile": [
        ("明确无法访问电脑且手机不运行脚本", r"(?=[\s\S]*(?:不需要运行 Python|不需要运行Python))(?=[\s\S]*(?:不会直接访问你的电脑|不能.*访问你的电脑|无法.*访问你的电脑))"),
        ("无正式模板时不自创可导入格式", r"(?:缺少|没有).*模板[\s\S]{0,160}(?:不能自创|不生成自创|只能.*(?:可读暂存|中间记录))"),
        ("保留首次失败和提示后复述", r"保留[\s\S]{0,80}(?:忘记|失败)[\s\S]{0,100}(?:答案|提示)"),
        ("未做项目不算失败", r"(?:没做|未做)[\s\S]{0,50}(?:不算失败|不产生失败|不记.*失败)"),
        ("同ID异内容整批冲突", r"同.*ID[\s\S]{0,120}(?:整个批次.*拒绝|整批拒绝)"),
        ("乱序按真实时间重放", r"按实际发生时间[\s\S]{0,30}(?:重放|排序)|排序时看事件时间"),
        ("旧快照不覆盖历史", r"(?:不能|不要|不建议).*旧包[\s\S]{0,30}覆盖|旧包不能覆盖"),
        ("模糊时间不猜测", r"不能随便补|不能.*补成精确|不适合伪造精确时间"),
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration", default="iteration-1")
    args = parser.parse_args()
    root = WORKSPACE / args.iteration
    runs = []
    for eval_dir, checks in CHECKS.items():
        eval_id = int(eval_dir.split("-")[1])
        for config in ("with_skill", "without_skill"):
            run = root / eval_dir / config
            output = (run / "outputs" / "transcript.md").read_text(encoding="utf-8")
            expectations = []
            for label, pattern in checks:
                match = re.search(pattern, output, re.I)
                expectations.append({
                    "text": label,
                    "passed": bool(match),
                    "evidence": match.group(0)[:260] if match else "未找到满足该断言的文本证据。",
                })
            passed = sum(item["passed"] for item in expectations)
            timing_path = run / "timing.json"
            timing = json.loads(timing_path.read_text()) if timing_path.exists() else {"total_tokens": None, "duration_ms": None, "note": "执行接口未提供可持久化的真实耗时或 token；未估算。"}
            grading = {
                "expectations": expectations,
                "summary": {"passed": passed, "failed": len(checks) - passed, "total": len(checks), "pass_rate": passed / len(checks)},
                "timing": timing,
                "user_notes_summary": {"uncertainties": ["脚本化回放只验证响应行为，不证明学习效果。"], "needs_review": ["请在官方查看页审阅自然度与教学负担。"], "workarounds": []},
            }
            (run / "grading.json").write_text(json.dumps(grading, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if not timing_path.exists() and not (run / "outputs" / "timing.json").exists():
                timing_path.write_text(json.dumps(grading["timing"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            # The official viewer intentionally hides transcript.md; response.md exposes the same replay.
            (run / "outputs" / "response.md").write_text(output, encoding="utf-8")
            runs.append({
                "eval_id": eval_id,
                "eval_name": eval_dir.split("-", 2)[2],
                "configuration": config,
                "run_number": 1,
                "result": {"pass_rate": passed / len(checks), "passed": passed, "failed": len(checks) - passed, "total": len(checks), "time_seconds": None, "tokens": None, "tool_calls": None, "errors": 0},
                "expectations": expectations,
                "notes": ["执行接口未提供可持久化的真实耗时或 token；未填充估算值。"],
            })
    grouped = {}
    for config in ("with_skill", "without_skill"):
        values = [r["result"]["pass_rate"] for r in runs if r["configuration"] == config]
        mean = sum(values) / len(values)
        grouped[config] = {"pass_rate": {"mean": mean, "stddev": (sum((x - mean) ** 2 for x in values) / len(values)) ** .5, "min": min(values), "max": max(values)}, "time_seconds": {"mean": None, "stddev": None}, "tokens": {"mean": None, "stddev": None}}
    grouped["delta"] = {"pass_rate": grouped["with_skill"]["pass_rate"]["mean"] - grouped["without_skill"]["pass_rate"]["mean"], "time_seconds": None, "tokens": None}
    benchmark = {
        "metadata": {"skill_name": "spoken-english", "skill_path": str(Path(__file__).resolve().parents[1]), "executor_model": "Codex paired agents", "analyzer_model": "deterministic regex grader", "timestamp": "2026-09-16", "evals_run": [1, 2, 3], "runs_per_configuration": 1},
        "runs": runs,
        "run_summary": grouped,
        "notes": ["差异主要来自结构化报告与手机协议；基础教学行为的基线已较强。", "单次脚本化样本不估计方差，也不证明学习效果。", "执行代理返回时触发用量限制，真实耗时与 token 记为 null。"],
    }
    (root / "benchmark.json").write_text(json.dumps(benchmark, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
