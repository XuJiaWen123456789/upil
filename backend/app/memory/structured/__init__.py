"""结构化长期记忆公共入口。"""

from backend.app.memory.structured.contracts import MemoryScope, StoredStructuredMemory
from backend.app.memory.structured.admission import is_explicit_memory_request
from backend.app.memory.structured.models import StructuredMemoryRecord
from backend.app.memory.structured.service import StructuredMemoryService

__all__ = [
    "MemoryScope",
    "StoredStructuredMemory",
    "StructuredMemoryRecord",
    "StructuredMemoryService",
    "is_explicit_memory_request",
]
