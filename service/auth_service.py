"""
AI大模型API网关 - 认证服务
"""
from datetime import datetime, timedelta
from typing import Optional
import secrets

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import settings
from models import Token, TokenData
from database import db


# 密码加密上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer认证
security = HTTPBearer()




def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)






def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


async def authenticate_admin(username: str, password: str):
    """管理员认证"""
    try:
        # 查询管理员信息
        admin = await db.fetchrow(
            "SELECT id, username, password FROM admin WHERE username = $1",
            username
        )
        
        if not admin:
            return None
        
        # 验证密码
        if not verify_password(password, admin["password"]):
            return None
        
        return {
            "id": admin["id"],
            "username": admin["username"]
        }
    except Exception as e:
        print(f"管理员认证失败: {e}")
        return None


async def authenticate_api_key(api_key: str) -> Optional[dict]:
    """API密钥认证"""
    try:
        # 查询API密钥信息
        key_info = await db.fetchrow(
            """
            SELECT 
                id, key_value, user_name, llm_ids, rate_limit, 
                daily_limit, monthly_limit, expire_time, ip_whitelist,
                status, total_requests, daily_requests, monthly_requests,
                COALESCE(token_limit, 0) as token_limit,
                COALESCE(total_tokens, 0) as total_tokens
            FROM api_key 
            WHERE key_value = $1 AND status = 1
            """,
            api_key
        )
        
        if not key_info:
            # 打印密钥前缀，帮助排查是密钥不存在还是其他原因
            all_keys = await db.fetch("SELECT id, LEFT(key_value, 12) as kv_prefix FROM api_key")
            print(f"[认证失败] 未找到密钥: '{(api_key or '')[:12]}...' 数据库中共有 {len(all_keys)} 个密钥: {[(k['id'], k['kv_prefix']) for k in all_keys]}")
            return None
        
        # 检查密钥是否过期
        if key_info["expire_time"] and key_info["expire_time"] < datetime.now():
            print(f"[认证失败] 密钥已过期: id={key_info['id']} expire_time={key_info['expire_time']}")
            return None
        
        return {
            "id": key_info["id"],
            "key_value": key_info["key_value"],
            "user_name": key_info["user_name"],
            "llm_ids": key_info["llm_ids"],
            "rate_limit": key_info["rate_limit"],
            "daily_limit": key_info["daily_limit"],
            "monthly_limit": key_info["monthly_limit"],
            "expire_time": key_info["expire_time"],
            "ip_whitelist": key_info["ip_whitelist"],
            "total_requests": key_info["total_requests"],
            "daily_requests": key_info["daily_requests"],
            "monthly_requests": key_info["monthly_requests"],
            "token_limit": key_info["token_limit"],
            "total_tokens": key_info["total_tokens"]
        }
    except Exception as e:
        print(f"API密钥认证失败: {e}")
        return None


async def validate_ip_whitelist(api_key_info: dict, client_ip: str) -> bool:
    """验证IP白名单"""
    ip_whitelist = api_key_info.get("ip_whitelist", [])
    
    # 如果没有设置白名单，则允许所有IP
    if not ip_whitelist:
        return True
    
    # 检查客户端IP是否在白名单中
    return client_ip in ip_whitelist


async def check_rate_limit(api_key_info: dict, request_time: datetime) -> bool:
    """检查速率限制"""
    # TODO: 实现更精确的速率限制逻辑
    # 这里使用简单的计数器方法
    rate_limit = api_key_info.get("rate_limit", 10)
    # 实际部署中应该使用Redis等缓存实现
    
    return True  # 临时返回True


async def check_daily_limit(api_key_info: dict) -> bool:
    """检查日调用限制"""
    daily_limit = api_key_info.get("daily_limit") or 1000
    daily_requests = api_key_info.get("daily_requests") or 0
    
    return daily_requests < daily_limit


async def check_monthly_limit(api_key_info: dict) -> bool:
    """检查月调用限制"""
    monthly_limit = api_key_info.get("monthly_limit") or 30000
    monthly_requests = api_key_info.get("monthly_requests") or 0
    
    return monthly_requests < monthly_limit


async def update_api_key_usage(api_key_id: int, prompt_tokens: int = 0, completion_tokens: int = 0):
    """更新API密钥使用统计"""
    try:
        total_new_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        if total_new_tokens > 0:
            await db.execute(
                """
                UPDATE api_key 
                SET 
                    last_use_time = NOW(),
                    total_requests = total_requests + 1,
                    daily_requests = daily_requests + 1,
                    monthly_requests = monthly_requests + 1,
                    total_tokens = total_tokens + $2
                WHERE id = $1
                """,
                api_key_id,
                total_new_tokens
            )
        else:
            await db.execute(
                """
                UPDATE api_key 
                SET 
                    last_use_time = NOW(),
                    total_requests = total_requests + 1,
                    daily_requests = daily_requests + 1,
                    monthly_requests = monthly_requests + 1
                WHERE id = $1
                """,
                api_key_id
            )
    except Exception as e:
        print(f"更新API密钥使用统计失败: {e}")


def generate_api_key() -> str:
    """生成API密钥"""
    # 生成随机字符串作为密钥
    return f"sk-{secrets.token_urlsafe(32)}"


async def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """获取当前管理员"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的认证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    # 验证管理员是否存在
    admin = await db.fetchrow(
        "SELECT id, username FROM admin WHERE username = $1",
        token_data.username
    )
    if admin is None:
        raise credentials_exception
    
    return {
        "id": admin["id"],
        "username": admin["username"]
    }