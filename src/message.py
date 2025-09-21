# message.py
from enum import Enum
from typing import Optional

class MessageType(Enum):
    MULTICAST = "multicast"
    ACK = "ack"

class Message:
    """Message class for totally ordered multicast."""
    
    def __init__(self, msg_type: MessageType, sender: str, timestamp: int, 
                 content: Optional[str] = None, original_msg_id: Optional[str] = None):
        self.msg_id = f"{sender}_{timestamp}"
        self.msg_type = msg_type
        self.sender = sender
        self.timestamp = timestamp
        self.content = content
        self.original_msg_id = original_msg_id  # For ACK messages
    
    def to_dict(self):
        """Convert message to dictionary for JSON serialization."""
        return {
            'msg_id': self.msg_id,
            'msg_type': self.msg_type.value,
            'sender': self.sender,
            'timestamp': self.timestamp,
            'content': self.content,
            'original_msg_id': self.original_msg_id
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create message from dictionary."""
        message = cls(
            msg_type=MessageType(data['msg_type']),
            sender=data['sender'],
            timestamp=data['timestamp'],
            content=data.get('content'),
            original_msg_id=data.get('original_msg_id')
        )
        # Mantém o msg_id original do dicionário
        message.msg_id = data['msg_id']
        return message
    
    def __repr__(self):
        return f"Message(id={self.msg_id}, type={self.msg_type.value}, sender={self.sender}, ts={self.timestamp}, content='{self.content}')"