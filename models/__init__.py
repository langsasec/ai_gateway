"""
AI大模型API网关 - 数据模型模块
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator
import uuid


class AdminCreate(BaseModel):
    """管理员创建模型"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)


class AdminLogin(BaseModel):
    """管理员登录模型"""
    username: str
    password: str


class AdminLoginResponse(BaseModel):
    """管理员登录响应模型"""
    access_token: str
    token_type: str = "bearer"
    username: str


class AdminResponse(BaseModel):
    """管理员响应模型"""
    id: int
    username: str
    create_time: datetime


class LLMConfigCreate(BaseModel):
    """大模型配置创建模型"""
    llm_name: str = Field(..., min_length=1, max_length=50)
    api_url: str = Field(..., min_length=1, max_length=255)
    api_key: str = Field(..., min_length=1, max_length=255)
    status: int = Field(default=1, ge=0, le=1)


class LLMConfigResponse(BaseModel):
    """大模型配置响应模型"""
    id: int
    llm_name: str
    api_url: str
    status: int
    create_time: datetime


class APIKeyCreate(BaseModel):
    """API密钥创建模型"""
    user_name: Optional[str] = Field(None, max_length=50)
    llm_ids: List[int] = Field(default_factory=list)
    rate_limit: int = Field(default=10, ge=1, le=1000)
    daily_limit: int = Field(default=1000, ge=1, le=100000)
    monthly_limit: int = Field(default=30000, ge=1, le=1000000)
    token_limit: int = Field(default=0, ge=0, description="Token总量限额，0表示不限制")
    expire_time: Optional[datetime] = None
    ip_whitelist: List[str] = Field(default_factory=list)


class APIKeyResponse(BaseModel):
    """API密钥响应模型"""
    id: int
    key_value: str
    user_name: Optional[str]
    llm_ids: List[int]
    rate_limit: int
    daily_limit: int
    monthly_limit: int
    expire_time: Optional[datetime]
    ip_whitelist: List[str]
    status: int
    create_time: datetime
    last_use_time: Optional[datetime]
    total_requests: int
    daily_requests: int
    monthly_requests: int


class SensitiveWordCreate(BaseModel):
    """敏感词创建模型"""
    word: str = Field(..., min_length=1, max_length=200)
    type: Optional[str] = Field(None, max_length=20)
    is_regex: bool = Field(False, description="True 时 word 作为正则表达式")


class SensitiveWordResponse(BaseModel):
    """敏感词响应模型"""
    id: int
    word: str
    type: Optional[str]
    is_regex: bool = False
    create_time: datetime



class ChatCompletionRequest(BaseModel):
    """聊天补全请求模型（OpenAI兼容格式）"""
    model: str = Field(..., description="模型名称")
    messages: List[Dict[str, Any]] = Field(..., description="消息列表")
    temperature: Optional[float] = Field(default=0.7, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    stream: Optional[bool] = Field(default=False)
    top_p: Optional[float] = Field(default=1.0, ge=0, le=1)
    frequency_penalty: Optional[float] = Field(default=0.0, ge=-2, le=2)
    presence_penalty: Optional[float] = Field(default=0.0, ge=-2, le=2)


class ChatCompletionResponse(BaseModel):
    """聊天补全响应模型（OpenAI兼容格式）"""
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4()}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(datetime.now().timestamp()))
    model: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, Any]  # Any 以兼容嵌套字段（如 completion_tokens_details）


class RequestLogCreate(BaseModel):
    """请求日志创建模型"""
    request_id: str
    api_key: str
    user_name: Optional[str]
    client_ip: str
    llm_name: str
    prompt_content: Optional[str]
    image_content: Optional[str]
    response_content: Optional[str]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    status: str
    sensitive_result: Optional[Any]  # str 或 dict
    error_msg: Optional[str]


class RequestLogResponse(BaseModel):
    """请求日志响应模型"""
    id: int
    request_id: str
    api_key: str
    user_name: Optional[str]
    request_time: datetime
    client_ip: str
    llm_name: str
    prompt_content: Optional[str]
    image_content: Optional[str]
    response_content: Optional[str]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    status: str
    sensitive_result: Optional[Any]  # str 或 dict（解析后的敏感词检测结果）
    error_msg: Optional[str]


class Token(BaseModel):
    """令牌响应模型"""
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """令牌数据模型"""
    username: Optional[str] = None


class DailyTrend(BaseModel):
    date: str
    requests: int


class ModelRank(BaseModel):
    llm_name: str
    request_count: int


class StatusDist(BaseModel):
    status: str
    cnt: int


class DailyToken(BaseModel):
    date: str
    input: int
    output: int


class SensitiveTop(BaseModel):
    sensitive_result: Optional[Any] = None
    cnt: int


class TokenTopKey(BaseModel):
    user_name: Optional[str] = None
    total_tokens: int = 0
    token_limit: int = 0
    total_requests: int = 0


class DashboardStats(BaseModel):
    """仪表板统计数据"""
    today_requests: int = 0
    total_api_keys: int = 0
    success_rate: float = 0
    sensitive_triggers: int = 0
    daily_trend: List[DailyTrend] = []
    top_models: List[ModelRank] = []
    status_dist: List[StatusDist] = []
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    daily_tokens: List[DailyToken] = []
    sensitive_top: List[SensitiveTop] = []
    token_top_keys: List[TokenTopKey] = []
    global_total_tokens: int = 0
    keys_with_token_limit: int = 0


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, description="原密码")
    new_password: str = Field(..., min_length=6, description="新密码（至少6位）")