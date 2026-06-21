from typing import List
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from .session_chat_history import SessionChatHistory

SYSTEM_PROMPT="""
You are a context-aware answer generator for a RAG study assistant.

Your job is to answer the user's latest query using the retrieved context as the
primary source of truth. Use the chat history only to understand follow-up
questions, maintain continuity, and respect the user's stated preferences.

Rules:
1. Ground the answer in the retrieved context. Do not invent facts that are not
supported by the retrieved context.
2. The retrieved context may contain irrelevant, weakly related, or redundant chunks.
Select only the context that directly supports the answer. Ignore context that
does not help answer the user's query.
3. Do not force every retrieved chunk into the answer. Use the passages that best
answer the user's query, even if they appear later in the retrieved context. Ranking
scores are hints, not absolute truth.
4. If the retrieved context is insufficient, say that the uploaded documents do
not contain enough information to answer confidently.
5. If chat history conflicts with retrieved context, prefer the retrieved context.
6. If the user asks a follow-up question, resolve references such as "that",
"this", "the previous one", or "the second point" using chat history when
possible.
7. Keep the answer concise but complete. Use bullets or numbered steps when that
makes the explanation easier to study.
8. Do not mention internal implementation details such as BM25, semantic rank,
rerank score, chunk IDs, or retrieval pipelines unless the user explicitly
asks about them.
9. When citing evidence, refer to the provided Document ID only if it is useful
to the user.
"""

    
def build_messages(
    user_query: str, 
    retrieved_chunks_raw: List[Document],
    chat_history: SessionChatHistory,
    max_chunks_to_format: int = 6
) -> List[HumanMessage | AIMessage | SystemMessage]:
    """
    Builds the ordered LangChain message list as input for assistant answer generation.

    Process flow:
        1 - Create the SystemMessage containing stable answer-generation rules.
        2 - Load prior chat turns as HumanMessage/AIMessage pairs and append them.
        3 - Format reranked retrieval chunks into a compact context string.
        4 - Create the latest HumanMessage containing the user query and retrieved context.
        5 - Return the full message list in the order expected by ChatBedrockConverse.
    """

    messages_out: List[HumanMessage | AIMessage | SystemMessage] = []

    # Create system prompt and add to start of message list for output
    messages_out.append(SystemMessage(content=SYSTEM_PROMPT))

    # Build chat history list and if non-empty, extend messages list with it
    chat_history: List[HumanMessage | AIMessage] = chat_history.format_as_messages()
    messages_out.extend(chat_history)

    # Add latest user query and top retrieved chunks for the query (context) as a HumanMessage
    retrieved_context_formatted = _format_context_as_string(
        retrieved_chunks_raw=retrieved_chunks_raw,
        max_chunks_to_format=max_chunks_to_format
    )
    latest_user_message = f"""
    USER QUERY:
    {user_query}

    RETRIEVED CONTEXT:
    {retrieved_context_formatted}
    """
    messages_out.append(HumanMessage(content=latest_user_message))

    return messages_out


def _format_context_as_string(
        retrieved_chunks_raw: List[Document],
        max_chunks_to_format: int = 6
    ) -> str:
        """
        Convert reranked retrieval results into a prompt-ready context block.

        The input is the raw list of LangChain Document objects returned after
        retrieval/RRF/reranking. This method keeps only chunks that have non-empty
        text and a valid ``metadata["doc_id"]`` beginning with ``"raws/"``. It then
        renders a compact text representation for the answer-generation prompt.

        Args:
            retrieved_chunks_raw: Reranked chunk Documents. Expected fields are:
                - ``id``: internal chunk identifier.
                - ``page_content``: chunk text.
                - ``metadata["doc_id"]``: source document S3 key, e.g. ``raws/notes.pdf``.
                - optional ``metadata["rerank_score"]``.
                - optional ``metadata["keyword_retrieval_rank"]``.
                - optional ``metadata["semantic_retrieval_rank"]``.
            max_chunks_to_format: Hard cap on how many top-ranked chunks are rendered.

        Returns:
            A newline-delimited context string suitable for inclusion in the LLM prompt.

        Example:
            Before:
                [
                    Document(
                        id="testing_123-a099-77c670a8053b_chunk_0038",
                        page_content="bla bla bla...",
                        metadata={
                            "doc_id": "raws/testing_123.pdf",
                            "keyword_retrieval_rank": 1,
                            "semantic_retrieval_rank": 3,
                            "rerank_score": 0.87,
                        },
                    )
                ]

            After:
                [Chunk 1]
                Document ID: testing_123.pdf
                Rerank score: 0.87
                Keyword ranking: 1
                Semantic ranking: 3
                Content: bla bla bla...
        """
        
        retrieved_context_list: List = []
        for chunk_rank, retrieved_chunk in enumerate(retrieved_chunks_raw):

            if chunk_rank + 1 > max_chunks_to_format:
                break

            chunk_text = retrieved_chunk.page_content
            keyword_retrieval_rank = retrieved_chunk.metadata.get("keyword_retrieval_rank")
            semantic_retrieval_rank = retrieved_chunk.metadata.get("semantic_retrieval_rank")
            rerank_score = retrieved_chunk.metadata.get("rerank_score")
            
            chunk_document_id = retrieved_chunk.metadata.get("doc_id")

            # First layer check: skip chunk completely if contents are empty
            if not chunk_text:
                continue

            # Verify valid doc_id related to the chunk
            # Must not be null and must be a string
            if chunk_document_id and isinstance(chunk_document_id, str):
                # Must start with "raws/"
                if len(chunk_document_id) > 5 and chunk_document_id[:5] == "raws/":
                    retrieved_context_list.append(f"[Chunk {chunk_rank + 1}]")
                    retrieved_context_list.append(f"Document ID: {chunk_document_id[5:]}") 
                else:
                    continue
            else:
                continue

            # Add rerank score if exists
            if rerank_score and isinstance(rerank_score, float):
                retrieved_context_list.append(f"Rerank score: {rerank_score}")

            # Add keyword and/or semantic retrieval rankings  
            if keyword_retrieval_rank and isinstance(keyword_retrieval_rank, int):
                retrieved_context_list.append(f"Keyword ranking: {keyword_retrieval_rank}")

            if semantic_retrieval_rank and isinstance(semantic_retrieval_rank, int):
                retrieved_context_list.append(f"Semantic ranking: {semantic_retrieval_rank}")

            retrieved_context_list.append(f"Content: {chunk_text}\n")

        retrieved_context_str = "\n".join(retrieved_context_list)
        
        return retrieved_context_str