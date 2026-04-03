"""
AI大模型API网关 - 主应用入口
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, status, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from database import db
from service.llm_service import llm_service
from service.sensitive_service import sensitive_detector
from service.auth_service import authenticate_admin, create_access_token, get_current_admin, security, verify_password, get_password_hash
from models import (
    AdminCreate, AdminLogin, AdminResponse, Token,
    LLMConfigCreate, LLMConfigResponse, APIKeyCreate, APIKeyResponse,
    SensitiveWordCreate, SensitiveWordResponse, ChatCompletionRequest, ChatCompletionResponse,
    ChangePasswordRequest
)
from service.log_service import log_service
from service.auth_service import generate_api_key


# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def auto_cleanup_logs():
    """后台定时清理过期日志任务"""
    try:
        while True:
            await asyncio.sleep(3600)  # 每小时检查一次
            try:
                retention_days = await db.fetchval(
                    "SELECT config_value FROM system_config WHERE config_key = 'log_retention_days'"
                )
                days = int(retention_days) if retention_days else settings.LOG_RETENTION_DAYS
                deleted = await db.fetchval("SELECT cleanup_expired_logs($1)", days)
                if deleted and deleted > 0:
                    logger.info(f"自动清理过期日志: 删除 {deleted} 条 (保留 {days} 天)")
            except Exception as e:
                logger.error(f"自动清理日志任务出错: {e}")
    except asyncio.CancelledError:
        pass  # 服务关闭时正常退出


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("启动AI大模型API网关服务...")
    
    # 连接数据库
    await db.connect()
    
    # 初始化大模型服务
    await llm_service.initialize()
    
    # 初始化敏感词检测器
    await sensitive_detector.initialize()
    
    # 创建默认管理员账号（如果不存在）
    await create_default_admin()
    
    # 创建默认敏感词（如果不存在）
    await create_default_sensitive_words()
    
    # 启动定时日志清理任务
    cleanup_task = asyncio.create_task(auto_cleanup_logs())
    
    logger.info("服务启动完成，准备接收请求")
    
    yield
    
    # 关闭时
    logger.info("关闭AI大模型API网关服务...")
    
    # 取消定时清理任务
    cleanup_task.cancel()
    
    # 关闭大模型服务
    await llm_service.close()
    
    # 断开数据库连接
    await db.disconnect()
    
    logger.info("服务关闭完成")


async def create_default_admin():
    """创建默认管理员账号"""
    try:
        from service.auth_service import get_password_hash
        
        # 检查是否已存在管理员
        existing_admin = await db.fetchval(
            "SELECT COUNT(*) FROM admin WHERE username = $1",
            settings.DEFAULT_ADMIN_USERNAME
        )
        
        if existing_admin == 0:
            hashed_password = get_password_hash(settings.DEFAULT_ADMIN_PASSWORD)
            await db.execute(
                "INSERT INTO admin (username, password) VALUES ($1, $2)",
                settings.DEFAULT_ADMIN_USERNAME,
                hashed_password
            )
            logger.info(f"创建默认管理员账号: {settings.DEFAULT_ADMIN_USERNAME}")
    except Exception as e:
        logger.error(f"创建默认管理员失败: {e}")


async def create_default_sensitive_words():
    """创建默认敏感词"""
    try:
        # 默认敏感词
        default_words = [
            {"word": "暴力", "type": "violence"},
            {"word": "色情", "type": "pornography"},
            {"word": "恐怖", "type": "terrorism"},
            {"word": "诈骗", "type": "fraud"},
            {"word": "毒品", "type": "drugs"},
            {"word": "赌博", "type": "gambling"},
            {"word": "政治", "type": "political"},
            {"word": "敏感词", "type": "general"}
        ]
        
        for word_info in default_words:
            await db.execute(
                "INSERT INTO sensitive_words (word, type) VALUES ($1, $2) ON CONFLICT (word) DO NOTHING",
                word_info["word"],
                word_info["type"]
            )
        
        logger.info(f"创建了 {len(default_words)} 个默认敏感词")
    except Exception as e:
        logger.error(f"创建默认敏感词失败: {e}")


# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI大模型API网关 - 统一代理、密钥管控、安全审计",
    lifespan=lifespan
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def read_root():
    """首页"""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ==================== 代理接口 ====================

@app.post("/v1/chat/completions")
async def chat_completion(
    request: ChatCompletionRequest,
    api_request: Request
):
    """
    AI聊天补全接口（兼容OpenAI格式）
    
    客户端通过网关密钥调用，网关代理转发到实际的大模型API
    支持流式(stream=True)和非流式响应
    """
    # 提取API密钥
    auth_header = api_request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少有效的Authorization头"
        )
    
    api_key = auth_header.split("Bearer ")[1].strip()
    
    # 获取客户端IP
    client_ip = api_request.client.host
    
    # 根据是否流式请求分流
    if request.stream:
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            llm_service.chat_completion_stream(request, api_key, client_ip),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        return await llm_service.chat_completion(request, api_key, client_ip)


# ==================== 管理员接口 ====================

@app.post("/api/admin/login", response_model=Token)
async def admin_login(form_data: AdminLogin):
    """管理员登录"""
    admin = await authenticate_admin(form_data.username, form_data.password)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": admin["username"]})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/api/admin/me", response_model=AdminResponse)
async def get_admin_info(current_admin: dict = Depends(get_current_admin)):
    """获取当前管理员信息"""
    return current_admin


@app.post("/api/admin/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_admin: dict = Depends(get_current_admin)
):
    """修改管理员密码"""
    try:
        admin = await db.fetchrow(
            "SELECT password FROM admin WHERE id = $1",
            current_admin["id"]
        )
        if not admin:
            raise HTTPException(status_code=404, detail="管理员不存在")
        if not verify_password(body.old_password, admin["password"]):
            raise HTTPException(status_code=400, detail="原密码错误")
        hashed_password = get_password_hash(body.new_password)
        await db.execute(
            "UPDATE admin SET password = $1 WHERE id = $2",
            hashed_password, current_admin["id"]
        )
        return {"message": "密码修改成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修改密码失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"修改密码失败: {str(e)}")


# ==================== 大模型配置接口 ====================

@app.get("/api/llm/list")
async def get_llm_list(
    current_admin: dict = Depends(get_current_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    keyword: Optional[str] = Query(None),
    status_filter: Optional[int] = Query(None, alias="status")
):
    """获取大模型配置列表（支持分页+搜索）"""
    try:
        where_parts = []
        params = []
        idx = 1

        if keyword:
            where_parts.append(f"(llm_name ILIKE ${idx} OR api_url ILIKE ${idx})")
            params.append(f"%{keyword}%")
            idx += 1
        if status_filter is not None:
            where_parts.append(f"status = ${idx}")
            params.append(status_filter)
            idx += 1

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        offset = (page - 1) * page_size

        total = await db.fetchval(
            f"SELECT COUNT(*) FROM llm_config {where_clause}", *params
        )
        configs = await db.fetch(
            f"""SELECT id, llm_name, api_url, status, create_time
                FROM llm_config {where_clause}
                ORDER BY id DESC
                LIMIT ${idx} OFFSET ${idx + 1}""",
            *params, page_size, offset
        )
        return {
            "items": [dict(c) for c in configs],
            "total": total or 0,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-( total or 0) // page_size))
        }
    except Exception as e:
        logger.error(f"获取大模型配置列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取配置列表失败"
        )


@app.post("/api/llm/create", response_model=LLMConfigResponse)
async def create_llm_config(
    config: LLMConfigCreate,
    current_admin: dict = Depends(get_current_admin)
):
    """创建大模型配置"""
    try:
        # 检查名称是否已存在
        existing = await db.fetchval(
            "SELECT id FROM llm_config WHERE llm_name = $1",
            config.llm_name
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="大模型名称已存在"
            )
        
        # 创建配置
        result = await db.fetchrow(
            """
            INSERT INTO llm_config (llm_name, api_url, api_key, status)
            VALUES ($1, $2, $3, $4)
            RETURNING id, llm_name, api_url, status, create_time
            """,
            config.llm_name,
            config.api_url,
            config.api_key,
            config.status
        )
        
        # 重新加载大模型配置
        await llm_service.load_llm_configs()
        
        return dict(result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建大模型配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建配置失败"
        )


@app.put("/api/llm/{config_id}")
async def update_llm_config(
    config_id: int,
    config: LLMConfigCreate,
    current_admin: dict = Depends(get_current_admin)
):
    """更新大模型配置"""
    try:
        # 检查配置是否存在
        existing = await db.fetchval(
            "SELECT id FROM llm_config WHERE id = $1",
            config_id
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="大模型配置不存在"
            )
        
        # 检查名称是否与其他配置冲突
        name_conflict = await db.fetchval(
            "SELECT id FROM llm_config WHERE llm_name = $1 AND id != $2",
            config.llm_name,
            config_id
        )
        if name_conflict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="大模型名称已存在"
            )
        
        # 更新配置
        await db.execute(
            """
            UPDATE llm_config 
            SET llm_name = $1, api_url = $2, api_key = $3, status = $4
            WHERE id = $5
            """,
            config.llm_name,
            config.api_url,
            config.api_key,
            config.status,
            config_id
        )
        
        # 重新加载大模型配置
        await llm_service.load_llm_configs()
        
        return {"message": "更新成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新大模型配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新配置失败"
        )


@app.delete("/api/llm/{config_id}")
async def delete_llm_config(
    config_id: int,
    current_admin: dict = Depends(get_current_admin)
):
    """删除大模型配置"""
    try:
        # 检查配置是否存在
        existing = await db.fetchval(
            "SELECT id FROM llm_config WHERE id = $1",
            config_id
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="大模型配置不存在"
            )
        
        # 删除配置
        await db.execute("DELETE FROM llm_config WHERE id = $1", config_id)
        
        # 级联清理：将所有密钥 llm_ids 中的该模型 ID 移除
        # PostgreSQL array_remove 不能直接在 WHERE 里过滤，这里用子查询方式
        await db.execute(
            """
            UPDATE api_key 
            SET llm_ids = array_remove(llm_ids, $1)
            WHERE $1 = ANY(llm_ids)
            """,
            config_id
        )
        
        # 重新加载大模型配置
        await llm_service.load_llm_configs()
        
        return {"message": "删除成功"}
        
    except Exception as e:
        logger.error(f"删除大模型配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除配置失败"
        )


# ==================== API密钥管理接口 ====================

@app.get("/api/key/list")
async def get_api_key_list(
    current_admin: dict = Depends(get_current_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status_filter: Optional[int] = Query(None, alias="status"),
    user_name: Optional[str] = Query(None)
):
    """获取API密钥列表（后端分页+搜索）"""
    try:
        where_parts = []
        params = []
        idx = 1

        if status_filter is not None:
            where_parts.append(f"status = ${idx}")
            params.append(status_filter)
            idx += 1
        if user_name:
            where_parts.append(f"user_name ILIKE ${idx}")
            params.append(f"%{user_name}%")
            idx += 1

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        offset = (page - 1) * page_size

        total = await db.fetchval(
            f"SELECT COUNT(*) FROM api_key {where_clause}", *params
        )
        keys = await db.fetch(
            f"""SELECT id, key_value, user_name, llm_ids, rate_limit,
                    daily_limit, monthly_limit, expire_time, ip_whitelist,
                    status, create_time, last_use_time, total_requests,
                    COALESCE(token_limit, 0) as token_limit,
                    COALESCE(total_tokens, 0) as total_tokens
                FROM api_key {where_clause}
                ORDER BY create_time DESC
                LIMIT ${idx} OFFSET ${idx + 1}""",
            *params, page_size, offset
        )

        def mask_key(k):
            if not k or len(k) <= 8: return k
            return k[:6] + "****" + k[-4:]

        result = []
        for key in keys:
            kd = dict(key)
            kd["key_value"] = mask_key(kd["key_value"])
            result.append(kd)

        return {
            "items": result,
            "total": total or 0,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-(total or 0) // page_size))
        }
    except Exception as e:
        logger.error(f"获取API密钥列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取密钥列表失败"
        )


@app.post("/api/key/create", response_model=APIKeyResponse)
async def create_api_key(
    key_data: APIKeyCreate,
    current_admin: dict = Depends(get_current_admin)
):
    """创建API密钥"""
    try:
        # 生成API密钥
        key_value = generate_api_key()
        
        # 创建密钥
        result = await db.fetchrow(
            """
            INSERT INTO api_key 
            (key_value, user_name, llm_ids, rate_limit, daily_limit, monthly_limit, 
             expire_time, ip_whitelist, status, token_limit)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 1, $9)
            RETURNING 
                id, key_value, user_name, llm_ids, rate_limit, 
                daily_limit, monthly_limit, expire_time, ip_whitelist,
                status, create_time, last_use_time,
                total_requests, daily_requests, monthly_requests,
                COALESCE(token_limit, 0) as token_limit,
                COALESCE(total_tokens, 0) as total_tokens
            """,
            key_value,
            key_data.user_name,
            key_data.llm_ids,
            key_data.rate_limit,
            key_data.daily_limit,
            key_data.monthly_limit,
            key_data.expire_time,
            key_data.ip_whitelist,
            key_data.token_limit
        )
        
        return dict(result)
        
    except Exception as e:
        logger.error(f"创建API密钥失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建密钥失败"
        )


@app.put("/api/key/{key_id}")
async def update_api_key(
    key_id: int,
    key_data: APIKeyCreate,
    current_admin: dict = Depends(get_current_admin)
):
    """更新API密钥配置"""
    try:
        # 检查密钥是否存在
        existing = await db.fetchval(
            "SELECT id FROM api_key WHERE id = $1",
            key_id
        )
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="API密钥不存在"
            )
        
        # 更新密钥配置
        await db.execute(
            """
            UPDATE api_key 
            SET 
                user_name = $1, llm_ids = $2, rate_limit = $3, 
                daily_limit = $4, monthly_limit = $5, 
                expire_time = $6, ip_whitelist = $7,
                token_limit = $8
            WHERE id = $9
            """,
            key_data.user_name,
            key_data.llm_ids,
            key_data.rate_limit,
            key_data.daily_limit,
            key_data.monthly_limit,
            key_data.expire_time,
            key_data.ip_whitelist,
            key_data.token_limit,
            key_id
        )
        
        return {"message": "更新成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新API密钥失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新密钥失败"
        )


@app.put("/api/key/{key_id}/status")
async def update_api_key_status(
    key_id: int,
    status_data: dict,
    current_admin: dict = Depends(get_current_admin)
):
    """更新API密钥状态"""
    try:
        status_value = status_data.get("status")
        if status_value not in [0, 1]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="状态值必须是0或1"
            )
        
        await db.execute(
            "UPDATE api_key SET status = $1 WHERE id = $2",
            status_value,
            key_id
        )
        
        return {"message": "状态更新成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新API密钥状态失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="更新状态失败"
        )


@app.delete("/api/key/{key_id}")
async def delete_api_key(
    key_id: int,
    current_admin: dict = Depends(get_current_admin)
):
    """删除API密钥"""
    try:
        await db.execute("DELETE FROM api_key WHERE id = $1", key_id)
        return {"message": "删除成功"}
        
    except Exception as e:
        logger.error(f"删除API密钥失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除密钥失败"
        )


# ==================== 敏感词管理接口 ====================

@app.get("/api/sensitive/list")
async def get_sensitive_words(
    current_admin: dict = Depends(get_current_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=200),
    word_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None)
):
    """获取敏感词列表（后端分页+搜索）"""
    try:
        where_parts = []
        params = []
        idx = 1

        if word_type:
            where_parts.append(f"type = ${idx}")
            params.append(word_type)
            idx += 1
        if keyword:
            where_parts.append(f"word ILIKE ${idx}")
            params.append(f"%{keyword}%")
            idx += 1

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
        offset = (page - 1) * page_size

        total = await db.fetchval(
            f"SELECT COUNT(*) FROM sensitive_words {where_clause}", *params
        )
        words = await db.fetch(
            f"""SELECT id, word, type, COALESCE(is_regex, FALSE) AS is_regex, create_time
                FROM sensitive_words {where_clause}
                ORDER BY create_time DESC
                LIMIT ${idx} OFFSET ${idx + 1}""",
            *params, page_size, offset
        )
        return {
            "words": [dict(w) for w in words],
            "total": total or 0,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-(total or 0) // page_size))
        }
    except Exception as e:
        logger.error(f"获取敏感词列表失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取敏感词列表失败"
        )


@app.post("/api/sensitive/create")
async def create_sensitive_word(
    word_data: SensitiveWordCreate,
    current_admin: dict = Depends(get_current_admin)
):
    """创建敏感词（支持正则）"""
    import re as _re
    try:
        # 如果是正则，先验证合法性
        is_regex = getattr(word_data, 'is_regex', False)
        if is_regex:
            try:
                _re.compile(word_data.word)
            except _re.error as exc:
                raise HTTPException(status_code=400, detail=f"正则表达式无效: {exc}")

        # 检查敏感词是否已存在
        existing = await db.fetchval(
            "SELECT id FROM sensitive_words WHERE word = $1",
            word_data.word
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="敏感词已存在"
            )

        # 创建敏感词
        result = await db.fetchrow(
            """
            INSERT INTO sensitive_words (word, type, is_regex)
            VALUES ($1, $2, $3)
            RETURNING id, word, type, COALESCE(is_regex, FALSE) AS is_regex, create_time
            """,
            word_data.word,
            word_data.type,
            is_regex
        )

        # 重新初始化敏感词检测器
        await sensitive_detector.initialize()

        return dict(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建敏感词失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建敏感词失败"
        )





@app.post("/api/sensitive/test")
async def test_sensitive_word(
    text: str = Query(...),
    current_admin: dict = Depends(get_current_admin)
):
    """测试敏感词检测（支持正则）"""
    if not sensitive_detector.initialized:
        await sensitive_detector.initialize()
    found, word_result = sensitive_detector.detect_sensitive_content(text)
    pii_result = sensitive_detector.detect_personal_info(text)
    return {
        "text": text,
        "detection_result": {
            "found": found,
            "sensitive_words": word_result,
            "personal_info": pii_result
        },
        "matched_words": word_result.get("words", []),
        "blocked": False
    }


@app.delete("/api/sensitive/{word_id}")
async def delete_sensitive_word(
    word_id: int,
    current_admin: dict = Depends(get_current_admin)
):
    """删除敏感词"""
    try:
        # 获取敏感词
        word = await db.fetchrow(
            "SELECT word FROM sensitive_words WHERE id = $1",
            word_id
        )
        if not word:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="敏感词不存在"
            )
        
        # 删除敏感词
        await db.execute("DELETE FROM sensitive_words WHERE id = $1", word_id)
        
        # 重新初始化敏感词检测器
        await sensitive_detector.initialize()
        
        return {"message": "删除成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除敏感词失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="删除敏感词失败"
        )


# ==================== 日志查询接口 ====================

@app.get("/api/logs/list")
async def get_request_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None),
    log_status: Optional[str] = Query(None),
    llm_name: Optional[str] = Query(None),
    client_ip: Optional[str] = Query(None, description="客户端IP筛选"),
    sensitive_only: bool = False,
    current_admin: dict = Depends(get_current_admin)
):
    """获取请求日志列表（支持IP、模型等筛选）"""
    try:
        from datetime import datetime
        import dateutil.parser
        
        start_datetime = None
        end_datetime = None
        
        if start_time:
            try:
                start_datetime = dateutil.parser.parse(start_time)
            except:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="开始时间格式错误"
                )
        
        if end_time:
            try:
                end_datetime = dateutil.parser.parse(end_time)
            except:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="结束时间格式错误"
                )
        
        # 获取日志
        logs_data = await log_service.get_logs(
            page=page,
            page_size=page_size,
            start_time=start_datetime,
            end_time=end_datetime,
            api_key=api_key,
            status=log_status,
            llm_name=llm_name,
            client_ip=client_ip,
            sensitive_only=sensitive_only
        )
        
        return logs_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取请求日志失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取日志失败"
        )



@app.get("/api/dashboard/stats")
async def get_dashboard_stats(
    days: int = 7,
    current_admin: dict = Depends(get_current_admin)
):
    """获取仪表板统计数据"""
    try:
        stats = await log_service.get_dashboard_stats(days=days)

        # 添加全局Token统计 —— 从 request_logs 精确汇总
        global_token_row = await db.fetchrow(
            "SELECT COALESCE(SUM(prompt_tokens),0) + COALESCE(SUM(completion_tokens),0) as global_total_tokens FROM request_logs"
        )
        stats["global_total_tokens"] = global_token_row["global_total_tokens"] if global_token_row else 0
        keys_with_limit = await db.fetchval(
            "SELECT COUNT(*) FROM api_key WHERE COALESCE(token_limit, 0) > 0"
        )
        stats["keys_with_token_limit"] = keys_with_limit or 0

        # Token用量 Top5 密钥 —— 从 request_logs 精确汇总
        token_top_keys = await db.fetch(
            """SELECT k.user_name, k.key_value, k.total_tokens as key_tokens,
                      COALESCE(k.token_limit, 0) as token_limit, k.total_requests,
                      COALESCE(lg.log_tokens, 0) as log_tokens
               FROM api_key k
               LEFT JOIN (
                   SELECT api_key,
                          SUM(prompt_tokens) + SUM(completion_tokens) as log_tokens
                   FROM request_logs GROUP BY api_key
               ) lg ON k.key_value = lg.api_key
               WHERE k.status = 1 AND COALESCE(lg.log_tokens, 0) > 0
               ORDER BY COALESCE(lg.log_tokens, 0) DESC LIMIT 5"""
        )
        def _mask(k):
            if not k or len(k) <= 8: return k
            return k[:6] + "****" + k[-4:]
        stats["token_top_keys"] = [
            {"user_name": r["user_name"] or "-", "key_value": _mask(r["key_value"]),
             "total_tokens": r["log_tokens"], "token_limit": r["token_limit"],
             "total_requests": r["total_requests"]}
            for r in token_top_keys
        ]

        return stats

    except Exception as e:
        logger.error(f"获取仪表板统计失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取统计信息失败"
        )


# ==================== 日志管理接口 ====================
# 注意：固定路径路由必须在 /{log_id} 参数路由之前定义

@app.get("/api/logs/retention")
async def get_log_retention(current_admin: dict = Depends(get_current_admin)):
    """获取日志保留策略"""
    try:
        retention_days = await db.fetchval(
            "SELECT config_value FROM system_config WHERE config_key = 'log_retention_days'"
        )
        # 查询各时间段的日志数量
        total = await db.fetchval("SELECT COUNT(*) FROM request_logs")
        old_count = await db.fetchval(
            "SELECT COUNT(*) FROM request_logs WHERE request_time < NOW() - ($1 || ' days')::INTERVAL",
            retention_days or 90
        )
        return {
            "retention_days": int(retention_days) if retention_days else 90,
            "total_logs": total or 0,
            "expired_logs": old_count or 0
        }
    except Exception as e:
        logger.error(f"获取日志保留策略失败: {e}")
        raise HTTPException(status_code=500, detail="获取保留策略失败")


@app.put("/api/logs/retention")
async def set_log_retention(
    days: int = Query(..., ge=1, le=3650, description="保留天数"),
    current_admin: dict = Depends(get_current_admin)
):
    """设置日志保留天数"""
    try:
        await db.execute(
            """INSERT INTO system_config (config_key, config_value, description, updated_time)
               VALUES ('log_retention_days', $1, '日志保留天数', NOW())
               ON CONFLICT (config_key) DO UPDATE SET config_value = $1, updated_time = NOW()""",
            str(days)
        )
        # 同步更新 config.py 中的运行时配置
        settings.LOG_RETENTION_DAYS = days
        logger.info(f"日志保留天数已更新为 {days} 天，操作人: {current_admin.get('username')}")
        return {"message": f"日志保留天数已设置为 {days} 天"}
    except Exception as e:
        logger.error(f"设置日志保留策略失败: {e}")
        raise HTTPException(status_code=500, detail="设置保留策略失败")


@app.delete("/api/logs/cleanup")
async def cleanup_expired_logs_endpoint(current_admin: dict = Depends(get_current_admin)):
    """清理过期日志（根据保留策略自动清理）"""
    try:
        retention_days = await db.fetchval(
            "SELECT config_value FROM system_config WHERE config_key = 'log_retention_days'"
        )
        days = int(retention_days) if retention_days else 90

        # 使用已有的数据库函数
        deleted_count = await db.fetchval(
            "SELECT cleanup_expired_logs($1)", days
        )

        logger.info(f"清理过期日志完成: 删除了 {deleted_count} 条，保留天数: {days}，操作人: {current_admin.get('username')}")
        return {"message": f"清理完成，删除了 {deleted_count} 条过期日志", "deleted_count": deleted_count, "retention_days": days}
    except Exception as e:
        logger.error(f"清理过期日志失败: {e}")
        raise HTTPException(status_code=500, detail="清理过期日志失败")


@app.delete("/api/logs/batch")
async def batch_delete_logs(
    start_time: Optional[str] = Query(None, description="删除此时间之前的日志"),
    end_time: Optional[str] = Query(None, description="删除此时间之后的日志"),
    log_status: Optional[str] = Query(None, description="只删除指定状态的日志"),
    current_admin: dict = Depends(get_current_admin)
):
    """按条件批量删除日志"""
    try:
        import dateutil.parser

        conditions = []
        params = []
        idx = 1

        if start_time:
            try:
                start_dt = dateutil.parser.parse(start_time)
                conditions.append(f"request_time < ${idx}")
                params.append(start_dt)
                idx += 1
            except:
                raise HTTPException(status_code=400, detail="开始时间格式错误")

        if end_time:
            try:
                end_dt = dateutil.parser.parse(end_time)
                conditions.append(f"request_time > ${idx}")
                params.append(end_dt)
                idx += 1
            except:
                raise HTTPException(status_code=400, detail="结束时间格式错误")

        if log_status:
            conditions.append(f"status = ${idx}")
            params.append(log_status)
            idx += 1

        if not conditions:
            raise HTTPException(status_code=400, detail="请至少提供一个删除条件")

        where_clause = "WHERE " + " AND ".join(conditions)

        # 先查询将要删除的数量
        count_query = f"SELECT COUNT(*) FROM request_logs {where_clause}"
        delete_count = await db.fetchval(count_query, *params)

        if delete_count == 0:
            return {"message": "没有匹配的日志需要删除", "deleted_count": 0}

        # 执行删除
        delete_query = f"DELETE FROM request_logs {where_clause}"
        await db.execute(delete_query, *params)

        logger.info(f"批量删除日志: 条件={conditions}, 删除数量={delete_count}, 操作人={current_admin.get('username')}")
        return {"message": f"已删除 {delete_count} 条日志", "deleted_count": delete_count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量删除日志失败: {e}")
        raise HTTPException(status_code=500, detail="批量删除日志失败")


@app.delete("/api/logs/{log_id}")
async def delete_single_log(
    log_id: int,
    current_admin: dict = Depends(get_current_admin)
):
    """删除单条日志"""
    try:
        await db.execute(
            "DELETE FROM request_logs WHERE id = $1", log_id
        )
        logger.info(f"删除单条日志: id={log_id}, 操作人={current_admin.get('username')}")
        return {"message": "日志已删除"}
    except Exception as e:
        logger.error(f"删除日志失败: {e}")
        raise HTTPException(status_code=500, detail="删除日志失败")


@app.get("/api/logs/export")
async def export_logs(
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    format: Optional[str] = Query("json"),
    current_admin: dict = Depends(get_current_admin)
):
    """导出日志数据"""
    try:
        # 解析时间参数
        from datetime import datetime
        import dateutil.parser
        
        start_datetime = None
        end_datetime = None
        
        if start_time:
            try:
                start_datetime = dateutil.parser.parse(start_time)
            except:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="开始时间格式错误"
                )
        
        if end_time:
            try:
                end_datetime = dateutil.parser.parse(end_time)
            except:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="结束时间格式错误"
                )
        
        # 导出日志
        export_data = await log_service.export_logs(
            start_time=start_datetime,
            end_time=end_datetime,
            format=format
        )
        
        # 设置响应头
        if format == "json":
            media_type = "application/json"
            filename = f"logs_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        elif format == "csv":
            media_type = "text/csv"
            filename = f"logs_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不支持的导出格式"
            )
        
        from fastapi.responses import Response
        return Response(
            content=export_data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出日志失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="导出日志失败"
        )


# GET /{log_id} 必须放在所有固定路径路由之后
@app.get("/api/logs/{log_id}")
async def get_request_log_detail(
    log_id: int,
    current_admin: dict = Depends(get_current_admin)
):
    """获取请求日志详情"""
    try:
        log_detail = await log_service.get_log_by_id(log_id)
        if not log_detail:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="日志不存在"
            )

        return log_detail

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取日志详情失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取日志详情失败"
        )


# ==================== 健康检查接口 ====================

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=settings.WORKERS
    )