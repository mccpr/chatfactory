import json
from typing import Optional, Dict, List, Tuple, Any
from chatfactory.llm.utils import LLM_REGISTRY
from chatfactory.tool.utils import TOOL_REGISTRY
from chatfactory.log import logger

ARXIV_SYSTEM_PROMPT = "你擅长给用户推荐学术论文。"

ARXIV_SEARCH_PROMPT = """任务
根据用户问题提取关键信息，用于论文搜索。

输入
用户问题或陈述（字符串）。

输出
JSON格式，包含以下字段：
{
    "research_field": ["<topic1>", "<topic2>"],
    "authors": ["<author1>", "<author2>"],
    "search_order": "<sort type>"
}

字段说明
research_field：英文研究主题（必须为英文），可以为空。
authors：英文论文作者（必须为英文），可以为空。
search_order：检索方法，值为 "Latest"（按最新排序）或 "Relevance"（按相关度排序）。
"""

ARXIV_CHAT_TEMPLATE = """请根据arXiv论文候选集来回答问题，不要编造，若arXiv论文候选集为空，提醒我检查arXiv服务是否可用。

arXiv论文候选集：

{content}

问题：

{message}
"""

PAPER_CARD_TEMPLATE = """
### [{index}. {title}]({pdf_url})

**Authors:** {authors}

**Abstract:** {abstract}

"""

PAPER_CARD_MARKDOWN = """
<div style="flex: 1; overflow-y: auto;">
{content}
</div>
"""


class ArxivChatBot:
    def __init__(self, llm_config: Optional[dict] = None) -> None:
        llm_engine, model, model_config = self.parse_llm_config(llm_config)
        self.setup_model(llm_engine, model, model_config)
        self.tool = TOOL_REGISTRY["arxiv"]()

    def parse_llm_config(
        self, llm_config: Optional[dict] = None
    ) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
        if llm_config is None:
            llm_config = {}
        llm_engine = llm_config.get("engine", None)
        model = llm_config.get("model", None)
        model_config = llm_config.get("model_config", None)
        return llm_engine, model, model_config

    def setup_model(
        self,
        llm_engine: Optional[str] = None,
        model: Optional[str] = None,
        model_config: Optional[dict] = None,
    ) -> None:
        logger.info("Setting up LLM...")
        if llm_engine is None:
            llm_engine = "openai"
        llm_cls = LLM_REGISTRY[llm_engine]
        self.llm = llm_cls(model, model_config)
        logger.info(f"LLM Engine: {llm_engine}")
        logger.info(f"Model ID/Path: {self.llm.model}")
        logger.info(f"Model Config: {model_config}")
        logger.info("LLM has been initialized.")

    def _search_from_arxiv(
        self,
        message: str,
        history: List[Tuple[str, str]],
        generation_config: Optional[Dict] = None,
        max_results: int = 5,
    ) -> Tuple[str, str]:
        response = self._chat(
            message=message,
            history=history,
            system_prompt=ARXIV_SEARCH_PROMPT,
            generation_config=generation_config,
            stream=False,
        )
        papers = self.tool.call(response, max_results=max_results)
        return papers, response

    def _chat(
        self,
        message: str,
        history: List[Tuple[str, str]],
        system_prompt: Optional[str] = None,
        generation_config: Optional[Dict] = None,
        stream: bool = True,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if len(history) > 0:
            for query, response in history:
                messages.append({"role": "user", "content": query})
                messages.append({"role": "assistant", "content": response})
        messages.append({"role": "user", "content": message})
        if stream:
            response = self.llm.invoke_stream(messages, generation_config)
        else:
            response = self.llm.invoke(messages, generation_config)
        return response

    def chat(
        self,
        message: str,
        history_chat: List[Tuple[str, str]],
        history_search: List[Tuple[str, str]],
        generation_config: Optional[Dict] = None,
        max_results: int = 5,
        stream: bool = True,
    ) -> Tuple[str, str, str]:
        papers, paper_search_query = self._search_from_arxiv(
            message, history_search, generation_config, max_results
        )
        paper_cards = self._generate_paper_cards(papers)
        messaeg_for_llm = self._prepare_message_for_llm(message, papers)
        response = self._chat(
            message=messaeg_for_llm,
            history=history_chat,
            system_prompt=ARXIV_SYSTEM_PROMPT,
            generation_config=generation_config,
            stream=stream,
        )
        return response, paper_cards, paper_search_query

    def _generate_paper_cards(self, papers: Any) -> str:
        if not papers:
            return ""
        papers = json.loads(papers)
        paper_cards = ""
        for index, paper in enumerate(papers):
            paper_cards += PAPER_CARD_TEMPLATE.format(
                index=index + 1,
                title=paper["title"],
                authors=", ".join(paper["authors"]),
                abstract=paper["summary"],
                pdf_url=paper["pdf_url"],
            )
        paper_cards = PAPER_CARD_MARKDOWN.format(content=paper_cards)
        return paper_cards

    def _prepare_message_for_llm(self, message: str, papers: Any) -> str:
        if not papers:
            return message
        papers = json.loads(papers)
        content = ""
        for paper in papers:
            content += "题目：{title}\n".format(title=paper["title"])
            content += "作者：{authors}\n".format(authors=", ".join(paper["authors"]))
            content += "摘要：{abstract}\n\n".format(abstract=paper["summary"])

        message = ARXIV_CHAT_TEMPLATE.format(content=content, message=message)
        return message