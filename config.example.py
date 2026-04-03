"""
AI大模型API网关 - 配置示例文件
请复制此文件为 config.py，并根据实际情况修改配置
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "AI大模型API网关"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # 数据库配置
    DATABASE_URL: str = "postgresql://username:password@localhost:5432/ai_gateway"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    # JWT配置
    SECRET_KEY: str = "your-secret-key-change-in-production"  # 必须修改！
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24小时
    
    # 管理员密码加密
    PASSWORD_HASH_ALGORITHM: str = "bcrypt"
    
    # 代理配置
    PROXY_TIMEOUT: int = 300  # 代理请求超时时间（秒）
    MAX_REQUEST_SIZE: int = 10 * 1024 * 1024  # 10MB
    MAX_RESPONSE_SIZE: int = 10 * 1024 * 1024  # 10MB
    
    # 速率限制
    RATE_LIMIT_ENABLED: bool = True
    DEFAULT_RATE_LIMIT: int = 10  # 默认QPS
    RATE_LIMIT_WINDOW: int = 60  # 时间窗口（秒）
    
    # 敏感词检测
    SENSITIVE_CHECK_ENABLED: bool = True
    SENSITIVE_CHECK_MODE: str = "audit"  # audit: 审计模式, block: 拦截模式
    PII_DETECTION_ENABLED: bool = True  # 个人信息检测
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_RETENTION_DAYS: int = 90  # 日志保留天数
    
    # CORS配置
    CORS_ORIGINS: list = ["*"]
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: list = ["*"]
    CORS_HEADERS: list = ["*"]
    
    # Redis配置（可选，用于缓存和速率限制）
    REDIS_URL: Optional[str] = None
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    
    # 静态文件配置
    STATIC_FILES_DIR: str = "static"
    STATIC_URL: str = "/static"
    
    @property
    def database_config(self):
        """获取数据库配置字典"""
        return {
            "dsn": self.DATABASE_URL,
            "min_size": 5,
            "max_size": self.DATABASE_POOL_SIZE,
            "max_queries": 50000,
            "max_inactive_connection_lifetime": 300.0,
        }
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 创建全局配置实例
settings = Settings()

# 如果存在.env文件，则从环境变量加载
if os.path.exists(".env"):
    settings = Settings(_env_file=".env")