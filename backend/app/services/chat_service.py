import json
import base64
from typing import List, AsyncGenerator
from sqlalchemy.orm import Session
from langchain_openai import ChatOpenAI
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, PromptTemplate
from langchain_core.messages import HumanMessage, AIMessage
from app.core.config import settings
from app.models.chat import Message
from app.models.user import User
from app.models.knowledge import KnowledgeBase, Document
from langchain.globals import set_verbose, set_debug
from app.services.llm.llm_factory import LLMFactory
from app.services.retrieval_service import ParentContextRetriever, RetrievalConfig
from app.services.rag_trace_service import RagTraceService

set_verbose(True)
set_debug(True)

async def generate_response(
    query: str,
    messages: dict,
    knowledge_base_ids: List[int],
    chat_id: int,
    db: Session,
    current_user: User
) -> AsyncGenerator[str, None]:
    try:
        # Create user message
        user_message = Message(
            content=query,
            role="user",
            chat_id=chat_id
        )
        db.add(user_message)
        db.commit()
        
        # Create bot message placeholder
        bot_message = Message(
            content="",
            role="assistant",
            chat_id=chat_id
        )
        db.add(bot_message)
        db.commit()
        
        # Get knowledge bases and their documents
        knowledge_bases = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.id.in_(knowledge_base_ids))
            .all()
        )
        
        available_kb_ids = []
        for kb in knowledge_bases:
            documents = db.query(Document).filter(Document.knowledge_base_id == kb.id).all()
            if documents:
                available_kb_ids.append(kb.id)

        if not available_kb_ids:
            error_msg = "当前会话没有可用知识库，无法基于知识库回答。"
            yield f"0:{json.dumps(error_msg, ensure_ascii=False)}\n"
            yield 'd:{"finishReason":"stop","usage":{"promptTokens":0,"completionTokens":0}}\n'
            bot_message.content = error_msg
            db.commit()
            return

        # Create QA prompt
        qa_system_prompt = (
            "你是医院知识库问答助手，只能依据给定 Context 回答。"
            "Context 按顺序编号，第一段为 citation 1，第二段为 citation 2。"
            "每个事实句末尾必须使用 [citation:x] 标注依据；多个依据写成 [citation:1][citation:2]。"
            "禁止使用 Context 外的事实、经验或猜测；Context 不足时必须明确说明缺少依据。"
            "回答语言必须与用户问题一致，保持专业、简洁，不超过 1024 tokens。\n\n"
            "Context: {context}\n\n"
            "重要：不要逐字复读原文，要基于引用内容归纳；没有引用的事实句不允许输出。"
        )
        qa_prompt = ChatPromptTemplate.from_messages([
            ("system", qa_system_prompt),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}")
        ])

        # 修改 create_stuff_documents_chain 来自定义 context 格式
        document_prompt = PromptTemplate.from_template("\n\n- {page_content}\n\n")

        # Generate response
        chat_history = []
        trace_history = []
        for message in messages["messages"]:
            if message["role"] == "user":
                chat_history.append(HumanMessage(content=message["content"]))
                trace_history.append({"role": "user", "content": message["content"]})
            elif message["role"] == "assistant":
                # if include __LLM_RESPONSE__, only use the last part
                if "__LLM_RESPONSE__" in message["content"]:
                    message["content"] = message["content"].split("__LLM_RESPONSE__")[-1]
                chat_history.append(AIMessage(content=message["content"]))
                trace_history.append({"role": "assistant", "content": message["content"]})

        full_response = ""
        # 先执行 child 检索与可选 rerank，再按 parent 去重，避免多个 child 重复占用上下文 token。
        retrieval_config = RetrievalConfig.from_settings()
        retriever = ParentContextRetriever(db)
        retrieval_result = retriever.retrieve(
            query=query,
            knowledge_base_ids=available_kb_ids,
            config=retrieval_config,
            user=current_user,
            chat_history=trace_history,
        )
        final_context = retrieval_result.documents

        serializable_context = []
        for context in final_context:
            serializable_doc = {
                "page_content": context.page_content,
                "metadata": {
                    **context.metadata,
                    "retrieval_latency_ms": retrieval_result.latency_ms,
                },
            }
            serializable_context.append(serializable_doc)

        answer_policy = {
            "confidence_score": retrieval_result.confidence_score,
            "confidence_threshold": retrieval_config.confidence_threshold,
            "should_refuse": retrieval_result.should_refuse,
            "refusal_reason": retrieval_result.refusal_reason,
        }
        trace_row = RagTraceService.create_trace(
            db,
            user_id=current_user.id,
            chat_id=chat_id,
            query=query,
            retrieval_result=retrieval_result,
            answer_policy=answer_policy,
        )
        envelope = {
            "version": 2,
            "context": serializable_context,
            "trace": {
                "id": trace_row.id,
                **(retrieval_result.trace or {}),
            },
            "answer_policy": answer_policy,
        }

        # 先把引用上下文和 trace 编码到流首部，前端用它生成 citation 弹层和透明化面板。
        escaped_context = json.dumps(envelope, ensure_ascii=False)
        base64_context = base64.b64encode(escaped_context.encode()).decode()
        separator = "__LLM_RESPONSE__"
        yield f"0:{json.dumps(base64_context + separator, ensure_ascii=False)}\n"
        full_response += base64_context + separator

        if retrieval_result.trace.get("router", {}).get("intent") == "chitchat":
            chitchat_msg = "你好，我可以基于已选择的知识库回答问题，也可以展示检索、重排和引用链路。"
            full_response += chitchat_msg
            yield f"0:{json.dumps(chitchat_msg, ensure_ascii=False)}\n"
            yield 'd:{"finishReason":"stop","usage":{"promptTokens":0,"completionTokens":0}}\n'
            bot_message.content = full_response
            db.commit()
            return

        if retrieval_result.should_refuse:
            refusal_msg = "未在知识库中找到足够可靠的依据，无法基于当前知识库回答该问题。"
            full_response += refusal_msg
            yield f"0:{json.dumps(refusal_msg, ensure_ascii=False)}\n"
            yield 'd:{"finishReason":"stop","usage":{"promptTokens":0,"completionTokens":0}}\n'
            bot_message.content = full_response
            db.commit()
            return

        # Initialize the language model only after refusal gating,避免低置信度问题继续硬答。
        llm = LLMFactory.create()
        question_answer_chain = create_stuff_documents_chain(
            llm,
            qa_prompt,
            document_variable_name="context",
            document_prompt=document_prompt
        )

        async for answer_chunk in question_answer_chain.astream({
            "input": query,
            "chat_history": chat_history,
            "context": final_context
        }):
            full_response += answer_chunk
            yield f"0:{json.dumps(answer_chunk, ensure_ascii=False)}\n"
            
        # Update bot message content
        bot_message.content = full_response
        db.commit()
            
    except Exception as e:
        error_message = f"Error generating response: {str(e)}"
        print(error_message)
        yield '3:{text}\n'.format(text=error_message)
        
        # Update bot message with error
        if 'bot_message' in locals():
            bot_message.content = error_message
            db.commit()
    finally:
        db.close()
