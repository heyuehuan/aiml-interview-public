"""
LLM Handlers for UniLLM
"""

from unillm.llm.vertex_ai import VertexAIHandler, vertex_ai_handler
# KMS/CMEK handler needs the heavy `vertexai` SDK and is unused in this deployment
# (master-key model, no CMEK). Optional import keeps the plain Vertex path dependency-light.
try:
    from unillm.llm.vertex_ai_kms import VertexAIKMSHandler, vertex_ai_kms_handler
except ImportError:  # pragma: no cover
    VertexAIKMSHandler = None
    vertex_ai_kms_handler = None

__all__ = [
    "VertexAIHandler",
    "vertex_ai_handler",
    "VertexAIKMSHandler",
    "vertex_ai_kms_handler",
]
