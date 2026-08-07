import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings

CHROMA_DB_DIR = Path(__file__).resolve().parent.parent.parent / "chroma_db"
CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)


class EmbeddingService:
    def _get_client(self):
        """Always returns a fresh, persistent ChromaDB client instance."""
        try:
            return chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
        except Exception as e:
            print(f"[ChromaDB Warning] PersistentClient init error: {e}. Fallback to ephemeral client.")
            return chromadb.Client()

    def get_assignment_collection(self, assignment_id: str):
        """Fetches existing ChromaDB collection for an assignment if it exists."""
        collection_name = f"assignment_{assignment_id}".replace("-", "_")
        try:
            client = self._get_client()
            return client.get_collection(name=collection_name)
        except Exception as e:
            print(f"[ChromaDB Error] get_assignment_collection error for {collection_name}: {e}")
            return None

    def index_assignment_reference(self, assignment_id: str, rubric_data: List[Dict[str, Any]], model_answer: str = ""):
        """
        Indexes complete Question Prompts, Question IDs, Max Marks, and Reference Answers
        into ChromaDB vector collection with rich metadata for RAG retrieval during AI grading.
        """
        collection_name = f"assignment_{assignment_id}".replace("-", "_")
        try:
            client = self._get_client()

            # Delete existing collection if re-indexing
            try:
                client.delete_collection(collection_name)
            except Exception:
                pass

            collection = client.get_or_create_collection(name=collection_name)
            
            documents = []
            metadatas = []
            ids = []

            # Index Per-Question Vector Context (Question ID + Prompt + Reference Answer)
            if rubric_data:
                for idx, item in enumerate(rubric_data):
                    q_num = item.get("question_number", f"Q{idx + 1}")
                    q_num_clean = q_num.lower().replace(" ", "")
                    q_id = item.get("question_id") or f"{assignment_id}-{q_num_clean}"
                    max_score = float(item.get("max_score", 10.0))
                    prompt = item.get("prompt") or item.get("text") or ""
                    m_answer = item.get("model_answer") or ""

                    # Construct rich RAG reference document combining Prompt & Reference Answer
                    doc_parts = [
                        f"Question Number: {q_num}",
                        f"Question ID: {q_id}",
                        f"Maximum Marks: {max_score}",
                        f"Question Prompt:\n{prompt}"
                    ]
                    
                    if m_answer:
                        doc_parts.append(f"Reference Answer & Marking Criteria:\n{m_answer}")
                    
                    doc_text = "\n\n".join(doc_parts)
                    
                    documents.append(doc_text)
                    metadatas.append({
                        "assignment_id": assignment_id,
                        "question_id": q_id,
                        "question_number": q_num,
                        "max_score": max_score,
                        "type": "question_rubric_vector"
                    })
                    ids.append(q_id)

            if documents:
                collection.add(
                    documents=documents,
                    metadatas=metadatas,
                    ids=ids
                )
            print(f"[ChromaDB] Successfully indexed {len(documents)} complete Question Vector(s) for assignment {assignment_id}")
        except Exception as e:
            print(f"[ChromaDB Error] Failed to index reference documents: {e}")

    def query_relevant_rubric(self, assignment_id: str, student_submission_text: str, top_k: int = 3) -> List[str]:
        """
        Retrieves top-k relevant rubric context for student submission text using similarity search.
        """
        collection_name = f"assignment_{assignment_id}".replace("-", "_")
        try:
            client = self._get_client()
            collection = client.get_collection(name=collection_name)
            results = collection.query(
                query_texts=[student_submission_text],
                n_results=min(top_k, collection.count())
            )
            docs = results.get("documents", [[]])[0]
            return docs
        except Exception as e:
            print(f"[ChromaDB Warning] Query failed for collection {collection_name}: {e}")
            return []

    def query_reference_context(self, assignment_id: str, student_submission_text: str, top_k: int = 3) -> List[str]:
        """Alias for query_relevant_rubric to maintain backward compatibility."""
        return self.query_relevant_rubric(assignment_id, student_submission_text, top_k=top_k)


# Global instance
embedding_service = EmbeddingService()

