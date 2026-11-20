"""程序入口：串联"搜索 → 抽取 → 过滤 → 证据 → 报告"完整流程。"""

import argparse
from src import config
from src.query_builder import build_query
from src.tavily_client import search, extract
from src.source_filter import filter_sources
from src.evidence_builder import build_evidence_list
from src.report_generator import generate_report
from src.markdown_writer import create_run_output_dir, write_evidence_list, write_report


def main():
    parser = argparse.ArgumentParser(
        description="Web Report — 基于搜索引擎的调研报告生成工具"
    )
    parser.add_argument(
        "--topic", "-t", required=True,
        help="调研主题，例如：AI Agent 在企业知识管理中的应用"
    )
    parser.add_argument(
        "--report-type", "-r", default="调研报告",
        help="报告类型，例如：综述报告、数据调研、竞品分析"
    )
    parser.add_argument(
        "--time-range", default="",
        help="时间范围，例如：past_day, past_week, past_month, past_year"
    )
    parser.add_argument(
        "--keywords", "-k", default="",
        help="附加关键词，逗号分隔，例如：票房,上映,累计票房"
    )
    args = parser.parse_args()

    # 1. 校验配置
    config.validate()
    output_dir = create_run_output_dir(args.topic)
    print(f"输出目录: {output_dir}")

    # 2. 构造搜索 query
    query = build_query(args.topic, args.report_type, args.keywords)
    print(f"[1/6] 搜索 query: {query}")

    # 3. Tavily 搜索 Top_k 个结果
    print("[2/6] 正在搜索...")
    search_results = search(
        query,
        time_range=args.time_range,
        max_results=config.SEARCH_MAX_RESULTS,
    )
    print(f"  获取到 {len(search_results)} 条搜索结果")

    # 4. Tavily 抽取正文
    urls = [r.url for r in search_results if r.url]
    print(f"[3/6] 正在抽取 {len(urls)} 个 URL 的正文...")
    extract_results = extract(urls, query=query)
    print(f"  成功抽取 {len(extract_results)} 个正文")

    # 5. 过滤来源
    print("[4/6] 正在过滤来源...")
    filtered = filter_sources(search_results, extract_results)
    print(f"  最终保留 {len(filtered)} 条来源")

    # 6. 生成证据列表
    evidence_list = build_evidence_list(filtered)
    print(f"  生成 {len(evidence_list)} 条证据")

    # 7. 写出 evidence_list.md
    evidence_path = write_evidence_list(evidence_list, output_dir)
    print(f"  证据列表已写入: {evidence_path}")

    # 8. LLM 生成报告
    print("[5/6] 正在生成报告...")
    report = generate_report(
        topic=args.topic,
        report_type=args.report_type,
        time_range=args.time_range or "不限",
        evidence_list=evidence_list,
    )

    # 9. 写出 report.md
    report_path = write_report(report, output_dir)
    print(f"[6/6] 报告已写入: {report_path}")
    print("完成!")


if __name__ == "__main__":
    main()
