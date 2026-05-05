"""
storage.py — Camada de armazenamento de anexos.
Usa Cloudflare R2 (compatível S3) quando R2_ACCOUNT_ID estiver configurado;
caso contrário, faz fallback para o filesystem local (ANEXOS_DIR).
"""

import os

R2_ACCOUNT_ID       = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID    = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME      = os.environ.get("R2_BUCKET_NAME", "")
R2_PUBLIC_URL       = os.environ.get("R2_PUBLIC_URL", "")

DIR_BASE   = os.path.dirname(os.path.abspath(__file__))
ANEXOS_DIR = os.path.join(DIR_BASE, "anexos_laudos")
os.makedirs(ANEXOS_DIR, exist_ok=True)


def _r2_habilitado() -> bool:
    return bool(R2_ACCOUNT_ID)


def _get_client():
    try:
        import boto3
        return boto3.client(
            "s3",
            endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
    except Exception:
        return None


def _path_local(chave: str) -> str:
    nome = chave.replace("/", "_")
    return os.path.join(ANEXOS_DIR, nome)


def upload_arquivo(chave: str, dados_bytes: bytes, tipo_mime: str) -> bool:
    if not _r2_habilitado():
        try:
            with open(_path_local(chave), "wb") as f:
                f.write(dados_bytes)
            return True
        except Exception:
            return False
    try:
        client = _get_client()
        if client is None:
            return False
        client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=chave,
            Body=dados_bytes,
            ContentType=tipo_mime,
            ACL="public-read",
        )
        return True
    except Exception:
        return False


def url_publica(chave: str) -> str:
    if not _r2_habilitado():
        try:
            return _path_local(chave)
        except Exception:
            return None
    try:
        return R2_PUBLIC_URL + "/" + chave
    except Exception:
        return None


def download_arquivo(chave: str) -> bytes:
    if not _r2_habilitado():
        try:
            with open(_path_local(chave), "rb") as f:
                return f.read()
        except Exception:
            return None
    try:
        client = _get_client()
        if client is None:
            return None
        resp = client.get_object(Bucket=R2_BUCKET_NAME, Key=chave)
        return resp["Body"].read()
    except Exception:
        return None


def deletar_arquivo(chave: str) -> bool:
    if not _r2_habilitado():
        try:
            os.unlink(_path_local(chave))
            return True
        except Exception:
            return False
    try:
        client = _get_client()
        if client is None:
            return False
        client.delete_object(Bucket=R2_BUCKET_NAME, Key=chave)
        return True
    except Exception:
        return False
