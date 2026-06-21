from typing import List, Optional

from ..shared.clients.bedrock_client import BedrockClient
from .services.session_chat_history import SessionChatHistory
from .services.message_builder_service import build_messages
from langchain_aws.chat_models import ChatBedrockConverse
from langchain_core.documents import Document
from langchain_core.messages import AIMessageChunk


class ChatOrchestrator:

    def __init__(self, generator_model_id: str,temperature: Optional[float],  provider: str = "anthropic"):
        if temperature is not None:
            if not isinstance(temperature, (int, float)) or not 0 <= temperature <= 1:
                raise ValueError("Temperature must be a float between 0 and 1")
        bedrock = BedrockClient(generator_model_id)
        self.generator_model = ChatBedrockConverse(
            client=bedrock.client,
            model_id=bedrock.model_id,
            provider=provider,
            temperature=temperature,
            max_tokens=2048
        )
        self.chat_history = SessionChatHistory()


    def stream_answer(
        self,
        user_query: str, 
        retrieved_chunks_raw: List[Document],
        max_chunks_to_format: int = 10
    ):
        """
        Stream an answer for the user query from the configured chat model.

        Process flow:
         1 - Build LangChain messages from the user query, retrieved chunks, and chat history
         2 - Stream response chunks from the generator model
         3 - Extract text from each streamed AIMessageChunk and yield it to the caller
         4 - Accumulate yielded text chunks into the full assistant response
         5 - Store the completed user/assistant turn in chat history after streaming finishes
        """
        combined_messages = build_messages(
            user_query=user_query,
            retrieved_chunks_raw=retrieved_chunks_raw,
            chat_history=self.chat_history,
            max_chunks_to_format=max_chunks_to_format
        )
        assistant_response_chunks: List[str] = []

        for stream_chunk in self.generator_model.stream(combined_messages):
            
            text = stream_chunk.text
            
            # Text extraction fallback thru stream_chunk.content if stream_chunk.text is malformed or None
            if not text or not isinstance(text, str):
                text = self._extract_stream_chunk_text(stream_chunk=stream_chunk)

            # If fallback extraction still produces None: skip to next stream_chunk
            if not text:
                continue
            
            assistant_response_chunks.append(text)
            yield text
        
        # Build full assistant response string and append user-query assistant response pair to chat history
        assistant_response_str = "".join(assistant_response_chunks)
        if len(assistant_response_chunks) > 0:
            self.chat_history.add_chat_turn(user_query=user_query, assistant_response=assistant_response_str)            


    def _extract_stream_chunk_text(self, stream_chunk: AIMessageChunk) -> Optional[str]:
        """
        Backup text extraction helper to extract text content from streamed assistant 
        response chunk if chunk.text attribute value is malformed or None.

         - Returns the chunk.content of the chunk as-is if chunk.content is a string
         - If chunj.content is a list, collects all partial chunk blocks inside list
            and concatenates all colllected blocks to build the full chunk text
        """

        stream_chunk_content = stream_chunk.content

        # String format, return as-is
        if isinstance(stream_chunk_content, str):
            return stream_chunk_content
        
        # List format, parse list items (Dict | String) and build full chunk text accordingly
        if isinstance(stream_chunk_content, list):
            partial_chunk_blocks: List = []
            for partial_chunk_block in stream_chunk_content:
                
                # Each item is string: append as-is to list of partial chunk texts
                if isinstance(partial_chunk_block, str):
                    partial_chunk_blocks.append(partial_chunk_block)
                    continue

                # Each item is a dict: extract "text" field if exists and append to list
                if isinstance(partial_chunk_block, dict):
                    partial_chunk_text = partial_chunk_block.get("text")
                    if isinstance(partial_chunk_text, str):
                        partial_chunk_blocks.append(partial_chunk_text)

            # Concatenate to rebuild and return full chunk text 
            full_chunk_text = "".join(partial_chunk_blocks)
            return full_chunk_text
        
        return None
