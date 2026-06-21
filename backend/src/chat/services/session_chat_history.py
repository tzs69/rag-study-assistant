from dataclasses import dataclass
from typing import List
from langchain_core.messages import AIMessage, HumanMessage


@dataclass
class ChatTurn:
    user: str
    assistant: str


class SessionChatHistory:
    """
    In-memory chat history store for a single chat session.

    Stores completed user/assistant turns as ChatTurn objects, converts them into
    LangChain HumanMessage/AIMessage pairs for prompt construction, and truncates the
    earliest turns when the configured in-memory chat history char limit is exceeded.
        - Moderate generator model input token usage
    """
    
    def __init__(self, max_chat_history_chars: int = 4096):
        self.chat_history: List[ChatTurn] = []
        self.curr_chat_history_chars: int = 0
        self.max_chat_history_chars: int = max_chat_history_chars


    def format_as_messages(self) -> List[HumanMessage | AIMessage]:
        """
        Convert stored chat turns into LangChain chat messages.

        Process flow:
         1 - Iterate through stored ChatTurn objects in sequential order
         2 - Convert each user query into a HumanMessage
         3 - Convert each assistant response into an AIMessage
         4 - Return the flattened message list for prompt construction
        """
        
        messages_list: List = []
        for chat_turn in self.chat_history:
            user_query = chat_turn.user
            assistant_response = chat_turn.assistant

            messages_list.append(HumanMessage(content=user_query))
            messages_list.append(AIMessage(content=assistant_response))

        return messages_list
    

    def add_chat_turn(self, user_query: str, assistant_response: str) -> None:
        """
        Append a completed user/assistant turn and enforce the chat history char limit rule.

        Note: 
        To be invoked only after answer streaming completed successfully so 
        failed partial responses do not get persisted.
        """
        latest_turn_len = len(user_query) + len(assistant_response)
        latest_turn = ChatTurn(user=user_query, assistant=assistant_response)

        # Update buffer first, then trim from the earliest turns if char limit exceeded
        self.chat_history.append(latest_turn)
        self.curr_chat_history_chars += latest_turn_len
        self._truncate_history_recurse()


    def _truncate_history_recurse(self) -> None:
        """
        Helper function to recursively remove earliest chat turns until 
        in-memory session chat history adheres to char limit rule.

        Each removed turn decrements the tracked character count by the combined
        user query and assistant response length for that turn.
        """
        # Base case: if current chat history length within bounds, return
        if self.curr_chat_history_chars <= self.max_chat_history_chars:
            return
        else:
            # Drop earliest context first so the most recent conversation remains available.
            earliest_turn: ChatTurn = self.chat_history.pop(0)
            earliest_turn_len: int = len(earliest_turn.user) + len(earliest_turn.assistant)

            self.curr_chat_history_chars -= earliest_turn_len
            self._truncate_history_recurse()   

