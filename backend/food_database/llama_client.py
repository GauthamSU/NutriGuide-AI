"""
Re-export LlamaCppClient from nutrition.services.llama_client.
"""

from nutrition.services.llama_client import (
    LlamaCppClient,
    build_system_prompt,
)

__all__ = [
    "LlamaCppClient",
    "build_system_prompt",
]
