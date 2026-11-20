"""web_report Redis 缓存测试：验证归一化键与近似主题命中。

用法：
    python scripts/test_cache.py              # 只测归一化键（不需要 Redis/服务）
    python scripts/test_cache.py --live       # 真实调用：第一次生成报告写缓存，第二次近似主题验证命中

注意：--live 会真实运行 web-report-skill（约 1 分钟），且要求 Redis(6379) 在跑。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 允许从任意目录运行：把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools.web_report_tool import (
    _cache_key,
    _normalize_topic,
    _redis_client,
    run,
)


def test_normalization() -> None:
    """归一化键：近似主题应同 key，不同主题不撞。"""
    pairs = [
        ("劳动法关于请假制度的规定", "劳动法请假制度规定"),      # 虚词差异 → 同
        ("欧洲劳动法关于上下班时间及工时的规定", "欧洲劳动法上下班时间工时规定"),  # 同
        ("华为招聘流程", "华为招聘流程介绍"),                    # 语气词差异 → 同
    ]
    for a, b in pairs:
        ka = _cache_key(a, "综述报告", "past_month", "")
        kb = _cache_key(b, "综述报告", "past_month", "")
        assert ka == kb, f"应同 key: {a!r} vs {b!r} -> {ka} != {kb}"
        print("OK 近似同key: %r ~ %r" % (a, b))

    # 不同主题不应撞
    ka = _cache_key("劳动法请假制度", "综述报告", "past_month", "")
    kb = _cache_key("华为招聘流程", "综述报告", "past_month", "")
    assert ka != kb
    print("OK 不同主题不同key")
    print("归一化示例: %r -> %r" % ("劳动法关于请假制度的规定", _normalize_topic("劳动法关于请假制度的规定")))


def test_live() -> None:
    client = _redis_client()
    if client is None:
        print("Redis 不可用（127.0.0.1:6379），无法 --live。先启动 rag-redis（docker compose up -d rag-redis）。")
        return
    try:
        client.ping()
    except Exception as exc:
        print("Redis 连接失败:", exc)
        return

    topic_a = "劳动法关于请假制度的规定"
    topic_b = "劳动法请假制度规定"  # 近似主题

    print("第一次调用（应真实生成报告并写缓存，约 1 分钟）...")
    t0 = time.perf_counter()
    r1 = run(topic=topic_a, report_type="综述报告", time_range="past_month")
    t1 = time.perf_counter() - t0
    print("  耗时=%.1fs cache_hit=%s success=%s" % (t1, r1.get("data", {}).get("cache_hit"), r1.get("success")))
    assert r1.get("success") is True, r1.get("error")
    assert r1.get("data", {}).get("cache_hit") is False

    print("第二次调用（近似主题，应命中缓存，秒回）...")
    t0 = time.perf_counter()
    r2 = run(topic=topic_b, report_type="综述报告", time_range="past_month")
    t2 = time.perf_counter() - t0
    print("  耗时=%.2fs cache_hit=%s success=%s" % (t2, r2.get("data", {}).get("cache_hit"), r2.get("success")))
    assert r2.get("success") is True
    assert r2.get("data", {}).get("cache_hit") is True, "近似主题未命中缓存"

    print("\n结果: 第一次 %.1fs（真实生成） -> 第二次 %.2fs（缓存命中），提速 %.1fx" % (t1, t2, t1 / t2))


def main() -> None:
    parser = argparse.ArgumentParser(description="web_report 缓存测试")
    parser.add_argument("--live", action="store_true", help="真实调用验证（需 Redis + 约 1 分钟）")
    args = parser.parse_args()

    test_normalization()
    if args.live:
        test_live()
    else:
        print("\n提示: 加 --live 跑真实命中验证（需 Redis 在跑，约 1 分钟）")


if __name__ == "__main__":
    main()
