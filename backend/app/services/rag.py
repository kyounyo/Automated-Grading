from typing import List, Dict, Any
from .embedding import embedding_service


def retrieve_rubric_context(assignment_id: str, student_text: str, top_k: int = 4) -> str:
    """
    Retrieves the most relevant rubric criteria and model answer chunks from ChromaDB for a student's submission text.
    """
    context_chunks = embedding_service.query_reference_context(assignment_id, student_text[:1000], top_k=top_k)
    if not context_chunks:
        return "No specific vector context found. Evaluate strictly against provided rubric rules."
    
    formatted_context = "\n".join([f"- {chunk}" for chunk in context_chunks])
    return f"Retrieved Rubric & Model Answer Reference Context:\n{formatted_context}"
