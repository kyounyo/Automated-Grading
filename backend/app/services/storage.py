import os
import shutil
from pathlib import Path
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "autograde-submissions")

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class StorageService:
    def __init__(self):
        self.use_s3 = bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY and AWS_S3_BUCKET)
        if self.use_s3:
            try:
                self.s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                    region_name=AWS_REGION
                )
            except Exception as e:
                print(f"[Storage Warning] S3 Initialization failed: {e}. Falling back to local storage.")
                self.use_s3 = False
        else:
            self.s3_client = None

    def upload_file(self, file_path: str, s3_key: str) -> dict:
        """
        Uploads a file to AWS S3 if credentials are available, or stores locally.
        Returns a dict containing file_path and file_s3_url.
        """
        file_path_obj = Path(file_path)
        local_dest = UPLOAD_DIR / s3_key
        local_dest.parent.mkdir(parents=True, exist_ok=True)
        
        if str(file_path_obj.resolve()) != str(local_dest.resolve()):
            shutil.copy2(file_path, local_dest)

        s3_url = None
        if self.use_s3 and self.s3_client:
            try:
                self.s3_client.upload_file(str(local_dest), AWS_S3_BUCKET, s3_key)
                s3_url = f"https://{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
            except Exception as e:
                print(f"[Storage Error] Failed to upload to AWS S3: {e}")

        return {
            "file_path": str(local_dest),
            "file_s3_url": s3_url or f"/static/uploads/{s3_key}"
        }

storage_service = StorageService()
