# 新增：LLM 调用逻辑（提示词+模型+输出处理）
from typing import List, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
import logging
import asyncio
from langchain_core.documents import Document

from config.config import APP_CONFIG
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

class LLMService:
    def __init__(self):
        """初始化 LLM 服务（单例模式，避免重复创建）"""
        self._ready = False
        try:
            self.llm = self._init_llm()
            self.promt_template = self._init_promt_template()
            self.summary_template = self._init_summary_template()
            self.rewrite_template = self._init_rewrite_template()

            self.summary_chain = (
                    self._init_summary_template()
                    | self.llm.bind(temperature=0, max_tokens=200)
                    | StrOutputParser()
            )
            self.rewrite_chain = (
                self._init_rewrite_template()
                | self.llm.bind(temperature=0, max_tokens=200)
                | StrOutputParser()
            )
            self.rag_chain = self.promt_template | self.llm | StrOutputParser()
            self.rag_chain_raw = self.promt_template | self.llm
            self._ready = True
        except Exception:
            logger.warning("LLM 服务初始化失败（API Key 未配置？），RAG 分支将不可用", exc_info=True)

    def _init_llm(self) -> ChatOpenAI:
        """初始化智谱 LLM 模型"""
        try:
            llm = ChatOpenAI(
                base_url=APP_CONFIG.llm.base_url,
                model_name=APP_CONFIG.llm.model_id,
                api_key=APP_CONFIG.llm.api_key,
                temperature=0,
                max_tokens=2048
            )

            logger.info(f"LLM 模型初始化成功：{APP_CONFIG.llm.model_id}")
            return llm
        except Exception as e:
            logger.error(f"LLM模型初始化失败：{e}",exc_info=True)
            raise

    def _init_promt_template(self) -> ChatPromptTemplate:
        """初始化RAG提示模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是专业的问答助手，仅基于参考文档回答用户问题。
                            规则：
                            1. 严格按照参考文档内容回答，不编造信息；
                            2. 无相关信息时，明确说明「未找到相关信息」；
                            3. 回答简洁准确，必要时分点说明；
                            4. 绝对不提及「参考文档」「上下文」等词汇。
                            5. 绝对不要提及根据文档等信息
                            6. 若最近对话历史和较早对话摘要中包含用户目标、身体状况、限制条件或偏好，
                                 回答当前问题时必须优先结合这些信息给出个性化建议。
                            7. 对话历史中助手的回答仅用于理解话题，不作为事实依据。
                            参考文档：
                            {context}
                            较早对话摘要：
                            {conversation_summary}
                            最近对话历史：
                            {conversation_context}
                        """),
            ("user", "{query}")
        ])

    def _build_context(self,documents: List[Document])-> str:
        """将重排序后的文档拼接为LLM 的上下文"""
        if not documents:
            return "无参考文档"
        return "\n\n".join([
            f"文档{i+1}(来源：{doc.metadata.get('source','未知')}):{doc.page_content}"
            for i,doc in enumerate(documents)
        ])

    def _init_summary_template(self) -> ChatPromptTemplate:
        """初始化压缩摘要提示模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是专业的总结摘要助手，根据已有摘要和较早的对话，输出简洁、事实性的中文摘要。
                          规则：
                            1. 只保留：
                            - 用户目标、身份、限制条件、偏好；
                            - 已确认的结论、决定、计划；
                            - 当前后续对话仍可能需要的关键上下文。
                            2. 不要编造，不要保留寒暄、重复内容、无关细节。
                            3. 若没有应保留的信息，输出空字符串。"""),
            ("user", """已有摘要：
            {existing_summary}
            需要合并的较早对话：
            {turns}""",
                    ),
        ])

    def _init_rewrite_template(self) -> ChatPromptTemplate:
        """初始化查询重写提示模板（严格约束，仅输出检索查询）"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是知识库检索查询改写器。
            任务：将用户当前问题改写为更适合知识库检索的查询短语。
            输出必须用于检索，不用于回答。
            规则：
            - 保留用户原始意图，不添加未知事实。
            - 如果有对话历史，只补全当前问题中省略的对象、主题、限制条件。
            - 将口语化疑问句改写为“核心主题 + 关键字段 + 常见同义词”的检索表达。
            - 不要输出“查询、了解、相关信息、怎么办”等空泛词；保留具体字段词。
            - 遇到“几点到几点、多久、多少、电话、流程”等问题，保留对应字段，如“上班时间 下班时间”“时长 天数”“电话 联系方式”“流程 步骤”。
            - 不输出解释，不输出答案，不输出标点列表。
            - 输出一行，建议 8 到 40 个汉字；最多 80 个汉字。
            - 如果原问题已经是清晰关键词，原样输出或轻微补充同义词。
            示例：公司标准工作时间是几点到几点？ -> 公司标准工作时间 上班时间 下班时间 标准工时 考勤"""),
                        ("user", """已有摘要：
            {summary}
            最近用户问题：
            {recent_user_turns}
            当前问题：
            {query}""",
             ),
        ])

    async def generate_answer(self, query: str, documents: List[Document],
                              usage: Optional[dict] = None) -> str:
        """核心方法： 生成基于检索结果的回答

        Args:
            query: 用户查询
            documents: 重排后的文档
            usage: 若传入，则把 token 用量写入该字典，键为
                   'prompt_tokens' / 'completion_tokens' / 'total_tokens'。
                   不传则行为完全不变（仅用于基线埋点）。
        """
        context = self._build_context(documents)
        logger.info(f"拼接上下文长度：{len(documents)}字符")

        #  # 异步调用 LLM（适配同步的 invoke 方法）
        try:
            if usage is not None:
                # 用原始链拿到 AIMessage，从中提取 token 用量
                msg = await asyncio.to_thread(
                    self.rag_chain_raw.invoke,
                    {"context": context, "conversation_summary": "无",
                     "conversation_context": "No prior conversation.", "query": query}
                )
                meta = getattr(msg, "usage_metadata", None) or {}
                usage["prompt_tokens"] = meta.get("input_tokens", 0)
                usage["completion_tokens"] = meta.get("output_tokens", 0)
                usage["total_tokens"] = meta.get("total_tokens", 0)
                return msg.content
            else:
                answer = await asyncio.to_thread(
                    self.rag_chain.invoke,
                    {
                    "context": context,
                    "conversation_summary": "无",
                    "conversation_context": "无历史对话。",
                    "query": query
                    }
                )
                return answer
        except Exception as e:
            logger.error(f"LLM生成回答失败{e}", exc_info=True)
            raise

    @staticmethod
    def _format_recent_turns(turns: List[dict]) -> str:
        if not turns:
            return "无历史对话。"

        return "\n\n".join(
            f"用户：{turn.get('user', '')}\n助手：{turn.get('assistant', '')}"
            for turn in turns
        )

    @staticmethod
    def _format_recent_user_turns(turns: List[dict]) -> str:
        """仅提取用户原话，不包含助手回答，供重写器使用。"""
        user_turns = [turn.get("user", "").strip() for turn in turns]
        user_turns = [text for text in user_turns if text]
        return "\n".join(f"- {text}" for text in user_turns) or "无"

    async def summarize_turns(
            self,
            existing_summary: str,
            turns: list[dict],
    ) -> str:
        return (
            await self.summary_chain.ainvoke(
                {
                    "existing_summary": existing_summary or "无",
                    "turns": self._format_recent_turns(turns),
                }
            )
        ).strip()

    async def rewrite_query(
            self,
            summary: str,
            recent_turns: list[dict],
            query: str,
    ) -> str:
        rewritten = await self.rewrite_chain.ainvoke(
            {
                "summary": summary or "无",
                "recent_user_turns": self._format_recent_user_turns(recent_turns),
                "query": query,
            }
        )
        rewritten = rewritten.strip().replace("\n", " ")
        if not rewritten or len(rewritten) > 80:
            logger.warning(
                "Invalid rewritten query (len=%d); fallback to raw query",
                len(rewritten),
            )
            return query
        return rewritten

    async def generate_answer_stream(
            self,
            query: str,
            documents: List[Document],
            summary: str = "",
            recent_turns: Optional[List[dict]] = None,
            ) -> AsyncIterator[str]:
        """核心方法： 改用流式生成基于检索结果的回答

        Args:
            query: 用户查询
            documents: 重排后的文档
        """
        context = self._build_context(documents)
        logger.info(f"拼接上下文长度：{len(documents)}字符")

        try:

            conversation_context = self._format_recent_turns(recent_turns or [])
            async for chunk in self.rag_chain.astream(
                    {
                    "context" : context,
                    "conversation_summary": summary or "无",
                    "conversation_context": conversation_context,
                    "query" : query
                     }
            ):
                if chunk:
                    yield chunk

        except Exception as e:
            logger.exception("LLM流式生成失败")
            raise

# 全局单例实例（避免重复初始化）
llm_service = LLMService()


