"""轻量压测脚本：并发打 /agent/chat，统计吞吐、延迟、失败率、429 频率。

零依赖（标准库），用法：
    python scripts/load_test.py --concurrency 3 --requests 12
    python scripts/load_test.py --questions "组织的考勤制度是什么" --concurrency 5 --requests 20

注意：hybrid 类问题会触发 web_report（子进程，单次可达 60s+），并发过高会同时
跑多个子进程并快速消耗 LLM 额度，建议 hybrid 场景并发 <= 2。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.error
import urllib.request

# 吞吐/内部链路（轻量，适合并发压测）
LIGHT_QUESTIONS = [
    "你好",
    "组织的考勤制度是什么",
]
# 全链路（触发 web_report，单次慢，适合低并发测完整链路）
HEAVY_QUESTIONS = [
    "组织的请假制度跟劳动法规定有什么区别",
]


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(len(sorted_values) * pct))
    return sorted_values[index]


def run_request(url: str, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
        status = response.status
        error = ""
    except urllib.error.HTTPError as exc:
        status = exc.code
        error = ""
        try:
            exc.read()
        except Exception:
            pass
    except Exception as exc:
        status = 0
        error = str(exc)[:200]
    elapsed = time.perf_counter() - start
    return {"status": status, "elapsed": elapsed, "error": error}


def run_load(url: str, questions: list[str], concurrency: int, total: int, timeout: float) -> list[dict]:
    results: list[dict] = []
    payloads = [{"message": questions[i % len(questions)]} for i in range(total)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(run_request, url, payload, timeout)
            for payload in payloads
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    return results


def report(results: list[dict]) -> None:
    total = len(results)
    ok = [r for r in results if r["status"] == 200]
    rate_limited = [r for r in results if r["status"] == 429]
    failed = [r for r in results if r["status"] not in (200, 429)]
    elapsed = sorted(r["elapsed"] for r in ok)

    print("=" * 56)
    print("压测报告")
    print("=" * 56)
    print(f"总请求: {total}   成功: {len(ok)}   429限流: {len(rate_limited)}   失败: {len(failed)}")
    if ok:
        print(f"成功率: {len(ok) / total * 100:.1f}%")
        total_sec = max(elapsed) if elapsed else 0
        print(f"总耗时(最慢请求): {total_sec:.1f}s  吞吐(串行等价): {len(ok) / total_sec * 1000:.2f} req/min" if total_sec > 0 else "")
    if elapsed:
        print(f"延迟  P50={_percentile(elapsed, 0.5):.2f}s  P95={_percentile(elapsed, 0.95):.2f}s  "
              f"P99={_percentile(elapsed, 0.99):.2f}s  max={elapsed[-1]:.2f}s")
        print(f"平均延迟: {statistics.mean(elapsed):.2f}s")
    if failed:
        print("失败明细（前 5 条）:")
        for r in failed[:5]:
            print(f"  status={r['status']} {r['elapsed']:.1f}s {r['error'][:80]}")
    print("=" * 56)
    print("明细（status  elapsed）:")
    for r in sorted(results, key=lambda x: x["elapsed"], reverse=True):
        print(f"  {r['status']:<5} {r['elapsed']:7.2f}s  {r['error'][:60]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="agent-service 轻量压测")
    parser.add_argument("--url", default="http://127.0.0.1:8010/agent/chat")
    parser.add_argument("--concurrency", type=int, default=2, help="并发数（hybrid 场景建议 <=2）")
    parser.add_argument("--requests", type=int, default=10, help="总请求数")
    parser.add_argument("--timeout", type=float, default=180, help="单请求超时（秒），web_report 可能 60s+")
    parser.add_argument("--questions", nargs="*", default=None,
                        help="自定义问题（默认用轻量问题测吞吐；传 'heavy' 用 hybrid 全链路问题）")
    args = parser.parse_args()

    if args.questions is None:
        questions = LIGHT_QUESTIONS
    elif args.questions == ["heavy"]:
        questions = HEAVY_QUESTIONS
    else:
        questions = args.questions

    print(f"开始压测: url={args.url} 并发={args.concurrency} 请求数={args.requests}")
    print(f"问题({len(questions)}): {questions}")
    results = run_load(args.url, questions, args.concurrency, args.requests, args.timeout)
    report(results)


if __name__ == "__main__":
    main()
