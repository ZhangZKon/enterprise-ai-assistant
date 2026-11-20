from minio import Minio
from botocore.exceptions import ClientError
from config.config import APP_CONFIG
import logging

logger = logging.getLogger(__name__)

class MinioClient:
    def __init__(self):
        self.minio_config = APP_CONFIG.minio
        self.s3_client = self._init_s3_client()

    def _init_s3_client(self) -> Minio:
        return Minio(
            endpoint=self.minio_config.endpoint,
            access_key=self.minio_config.access_key,
            secret_key=self.minio_config.secret_key,
            secure=False  # 是否启用 HTTPS
        )
    def put_object(self,  bucket_name, object_name,file_content):
        try:
            self.s3_client.put_object(bucket_name, object_name, file_content,length=len(file_content))
            logger.info(f"File '{object_name}' uploaded to '{bucket_name}/{object_name}'")
            return True
        except ClientError as e:
            logger.error(f"Error uploading file: {e}")
            return False

    def get_object(self, bucket_name: str, object_name: str):
        """实现get_object方法，返回文件对象"""
        return self.s3_client.get_object(bucket_name, object_name)


s3_client = MinioClient()
