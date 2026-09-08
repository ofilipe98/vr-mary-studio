"""Qt presentation domains and service adapters."""

def __getattr__(name):
    if name == "ChatBridge":
        from ..chat import ChatBridge
        return ChatBridge
    raise AttributeError(name)
