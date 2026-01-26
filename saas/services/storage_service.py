import os
import time
import uuid
import json
from urllib import request as urllib_request
from typing import Dict

def _safe_filename(name: str) -> str:
    name = (name or "upload.bin").strip().replace("\\", "/").split("/")[-1]
    # 简单去除危险字符
    return "".join(c for c in name if c.isalnum() or c in (".", "-", "_")) or "upload.bin"

def upload_file_stream(user_id: str, filename: str, data: bytes, content_type: str) -> Dict[str, str]:
    """
    统一的对象存储上传入口：
    - 环境变量 STORAGE_DRIVER=COS 时，使用腾讯云 COS
    - 否则走本地目录 STORAGE_LOCAL_DIR（默认 /tmp/saas_uploads）
    返回:
      - key: 对象键（路径）
      - url: 可访问的URL（COS为公网，LOCAL需自行映射静态目录或开发使用）
    """
    driver = (os.getenv("STORAGE_DRIVER") or "LOCAL").upper()
    ts = int(time.time())
    fid = uuid.uuid4().hex[:12]
    fname = _safe_filename(filename)
    key = f"uploads/{user_id}/{ts}-{fid}-{fname}"

    if driver == "COS":
        # 期望环境变量：
        # COS_BUCKET, COS_REGION
        # 可选：COS_SECRET_ID, COS_SECRET_KEY (若不填则尝试获取微信云托管临时密钥)
        # 可选：COS_BASE_URL (自定义CDN域名)
        bucket = os.getenv("COS_BUCKET")
        region = os.getenv("COS_REGION")
        base_url = os.getenv("COS_BASE_URL")
        
        secret_id = os.getenv("COS_SECRET_ID")
        secret_key = os.getenv("COS_SECRET_KEY")
        token = None

        # 如果没有配置永久密钥，尝试获取微信云托管临时密钥
        if not (secret_id and secret_key):
            try:
                # 微信云托管内部鉴权接口
                resp = urllib_request.urlopen("http://api.weixin.qq.com/_/cos/getauth", timeout=3)
                if resp.status == 200:
                    auth_data = json.loads(resp.read().decode('utf-8'))
                    secret_id = auth_data.get("TmpSecretId")
                    secret_key = auth_data.get("TmpSecretKey")
                    token = auth_data.get("Token")
            except Exception:
                # 忽略错误，后续检查会处理缺失情况
                pass

        if not all([secret_id, secret_key, bucket, region]):
            raise RuntimeError("COS config missing: COS_BUCKET|COS_REGION is required. COS_SECRET_ID|COS_SECRET_KEY is required unless in WXCloud environment.")

        try:
            # 仅在启用 COS 时尝试导入，避免未安装时报错
            from qcloud_cos import CosConfig, CosS3Client
        except Exception:
            raise RuntimeError("Missing dependency: cos-python-sdk-v5. Please `pip install cos-python-sdk-v5`")

        config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)
        client = CosS3Client(config)
        client.put_object(
            Bucket=bucket,
            Body=data,
            Key=key,
            ContentType=content_type or "application/octet-stream",
        )
        if base_url:
            url = f"{base_url.rstrip('/')}/{key}"
        else:
            url = f"https://{bucket}.cos.{region}.myqcloud.com/{key}"
        
        # 构造 file_id (云托管环境)
        # 格式通常为: cloud://<ENV_ID>.<BUCKET>-<APPID>/<KEY>
        # 但 bucket 名字通常已经是 <name>-<appid>
        # 如果能获取到 WX_CLOUD_ENV_ID，则尝试构造
        env_id = os.getenv("WX_CLOUD_ENV_ID")
        file_id = None
        if env_id:
            # 假设 COS_BUCKET 已经是完整名 (name-appid)
            # 云托管的 fileID 格式有点 trick，这里尝试最通用的 cloud://<ENV_ID>.<BUCKET>/<KEY>
            # 注意：如果 bucket 不是该环境默认的 bucket，这个 file_id 可能无效
            file_id = f"cloud://{env_id}.{bucket}/{key}"
        
        # 生成一个短期有效的签名 URL，确保即使 Bucket 是私有的，前端上传后也能立即回显
        signed_url = client.get_presigned_url(
            Method='GET',
            Bucket=bucket,
            Key=file_id,
            Expired=3600
        )

        return {"key": key, "url": url, "file_id": file_id, "signed_url": signed_url}

    # LOCAL 存储：开发联调用。生产请使用 COS。

    base_dir = os.getenv("STORAGE_LOCAL_DIR") or "/tmp/saas_uploads"
    full_path = os.path.join(base_dir, key)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "wb") as f:
        f.write(data)
    # 本地没有公网URL，这里返回一个相对路径提示；若需要前端展示，请配置静态映射
    # 例如：将 base_dir 映射到 /static/uploads，从而形成 /static/...
    static_prefix = os.getenv("STORAGE_LOCAL_STATIC_PREFIX") or "/static"
    url = f"{static_prefix}/{key.split('uploads/',1)[-1]}"
    return {"key": key, "url": url, "file_id": None, "signed_url": url}


def get_presigned_url(key: str) -> str:
    """
    获取文件的临时访问链接 (用于 COS 私有读)
    如果不是 COS 驱动，返回 None 或 静态链接
    """
    driver = (os.getenv("STORAGE_DRIVER") or "LOCAL").upper()
    if driver != "COS":
        # Local storage, just return static url logic
        # 这里简单复用 upload 的逻辑
        static_prefix = os.getenv("STORAGE_LOCAL_STATIC_PREFIX") or "/static"
        return f"{static_prefix}/{key.split('uploads/',1)[-1]}"

    try:
        from qcloud_cos import CosConfig, CosS3Client
        secret_id = os.getenv("COS_SECRET_ID")
        secret_key = os.getenv("COS_SECRET_KEY")
        bucket = os.getenv("COS_BUCKET")
        region = os.getenv("COS_REGION")
        token = None

        if not (secret_id and secret_key):
             try:
                resp = urllib_request.urlopen("http://api.weixin.qq.com/_/cos/getauth", timeout=3)
                if resp.status == 200:
                    auth_data = json.loads(resp.read().decode('utf-8'))
                    secret_id = auth_data.get("TmpSecretId")
                    secret_key = auth_data.get("TmpSecretKey")
                    token = auth_data.get("Token")
             except:
                 pass
        
        if not all([secret_id, secret_key, bucket, region]):
            return ""

        config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key, Token=token)
        client = CosS3Client(config)
        # 生成预签名 URL (1小时有效)
        url = client.get_presigned_url(
            Method='GET',
            Bucket=bucket,
            Key=key,
            Expired=3600
        )
        return url
    except Exception:
        return ""
