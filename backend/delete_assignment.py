import sys
import os
import argparse

# Path setup
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models import Assignment, Submission, EvaluationLog, AuditLog

try:
    from app.services.embedding import embedding_service
except Exception:
    embedding_service = None


def list_assignments():
    """Lists all current assignments in database."""
    db = SessionLocal()
    try:
        assignments = db.query(Assignment).all()
        if not assignments:
            print("\n📁 No assignments found in database.")
            return []
        print("\n=== 📁 Existing Assignments in Local Database ===")
        for idx, a in enumerate(assignments, 1):
            sub_count = len(a.submissions)
            print(f"  [{idx}] ID: {a.id} | Course: {a.course_code} | Title: {a.title} | Submissions: {sub_count}")
        print("==================================================")
        return assignments
    finally:
        db.close()


def delete_assignment_by_id(assignment_id: str):
    """Deletes an assignment by its ID and cascades to submissions and ChromaDB."""
    db = SessionLocal()
    try:
        assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if not assignment:
            print(f"❌ Error: Assignment with ID '{assignment_id}' not found.")
            return False

        title = assignment.title
        course = assignment.course_code
        sub_count = len(assignment.submissions)

        # ChromaDB cleanup
        try:
            if hasattr(embedding_service, "chroma_client") and embedding_service.chroma_client:
                coll_name = f"rubric_{assignment_id.replace('-', '_')}"
                try:
                    embedding_service.chroma_client.delete_collection(coll_name)
                    print(f"🧹 Cleaned ChromaDB collection: {coll_name}")
                except Exception:
                    pass
        except Exception:
            pass

        db.delete(assignment)
        db.commit()
        print(f"✅ Successfully deleted assignment '{title}' ({course}, ID: {assignment_id}) and all {sub_count} associated submissions.")
        print("🔒 All other assignments and submissions remain untouched.")
        return True
    except Exception as e:
        db.rollback()
        print(f"❌ Error deleting assignment: {e}")
        return False
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Safely delete a specific assignment from local database.")
    parser.add_argument("--id", type=str, default=None, help="Assignment ID to delete (e.g. assign-cf746f)")
    parser.add_argument("--list", action="store_true", help="List all assignments")
    args = parser.parse_args()

    if args.list:
        list_assignments()
        return

    if args.id:
        delete_assignment_by_id(args.id)
        return

    # Interactive mode
    assignments = list_assignments()
    if not assignments:
        return

    user_input = input("\nEnter the Assignment ID or number [1-" + str(len(assignments)) + "] to delete (or press Enter to cancel): ").strip()
    if not user_input:
        print("Canceled. No changes made.")
        return

    target_id = None
    if user_input.isdigit():
        idx = int(user_input) - 1
        if 0 <= idx < len(assignments):
            target_id = assignments[idx].id
    else:
        target_id = user_input

    if not target_id:
        print("Invalid selection.")
        return

    confirm = input(f"Are you sure you want to permanently delete assignment '{target_id}'? (y/N): ").strip().lower()
    if confirm in ["y", "yes"]:
        delete_assignment_by_id(target_id)
    else:
        print("Deletion canceled.")


if __name__ == "__main__":
    main()
