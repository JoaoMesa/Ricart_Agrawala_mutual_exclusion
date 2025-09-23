# message.py
from enum import Enum
from typing import Optional

class MessageType(Enum):
    REQUEST = "request"  # Request to access resource
    REPLY = "reply"      # Reply to a request (OK or DENY)

class Message:
    """Message class for Ricart-Agrawala mutual exclusion algorithm."""
    
    def __init__(self, msg_type: MessageType, sender: str, logical_time: int,
                 resource_name: Optional[str] = None, request_id: Optional[str] = None,
                 granted: Optional[bool] = None):
        """
        Initialize a message for Ricart-Agrawala algorithm.
        
        Args:
            msg_type: Type of message (REQUEST or REPLY)
            sender: Process identifier/number
            logical_time: Current logical time when message was created
            resource_name: Name of the resource being requested (for REQUEST messages)
            request_id: ID of the original request (for REPLY messages)
            granted: True for OK, False for DENY (for REPLY messages)
        """
        self.msg_id = f"{sender}_{logical_time}_{msg_type.value}"
        self.msg_type = msg_type
        self.sender = sender  # This serves as the process number
        self.logical_time = logical_time
        self.resource_name = resource_name
        self.request_id = request_id  # For REPLY messages, references the original REQUEST
        self.granted = granted  # For REPLY messages: True=OK, False=DENY
        
    @property
    def process_number(self):
        """Get the process number (same as sender)."""
        return self.sender
    
    def to_dict(self):
        """Convert message to dictionary for JSON serialization."""
        return {
            'msg_id': self.msg_id,
            'msg_type': self.msg_type.value,
            'sender': self.sender,
            'logical_time': self.logical_time,
            'resource_name': self.resource_name,
            'request_id': self.request_id,
            'granted': self.granted
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create message from dictionary."""
        message = cls(
            msg_type=MessageType(data['msg_type']),
            sender=data['sender'],
            logical_time=data['logical_time'],
            resource_name=data.get('resource_name'),
            request_id=data.get('request_id'),
            granted=data.get('granted')
        )
        # Maintain the original msg_id from dictionary
        message.msg_id = data['msg_id']
        return message
    
    @classmethod
    def create_request(cls, sender: str, logical_time: int, resource_name: str):
        """Factory method to create a REQUEST message."""
        return cls(
            msg_type=MessageType.REQUEST,
            sender=sender,
            logical_time=logical_time,
            resource_name=resource_name
        )
    
    @classmethod
    def create_reply(cls, sender: str, logical_time: int, request_id: str, granted: bool = True):
        """Factory method to create a REPLY message."""
        return cls(
            msg_type=MessageType.REPLY,
            sender=sender,
            logical_time=logical_time,
            request_id=request_id,
            granted=granted
        )
    
    def __repr__(self):
        if self.msg_type == MessageType.REQUEST:
            return f"Message(id={self.msg_id}, type={self.msg_type.value}, sender={self.sender}, time={self.logical_time}, resource='{self.resource_name}')"
        else:
            grant_str = "OK" if self.granted else "DENY" if self.granted is not None else "UNKNOWN"
            return f"Message(id={self.msg_id}, type={self.msg_type.value}, sender={self.sender}, time={self.logical_time}, request_id='{self.request_id}', granted={grant_str})"