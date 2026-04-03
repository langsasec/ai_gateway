"""
AI大模型API网关 - API密钥管理接口
创建、查询、修改、删除API密钥
"""
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from config import settings
from database import get_db
from models import APIKey, APIKeyCreate, APIKeyUpdate, APIKeyStatus
from service.auth_service import hash_key, verify_api_key, get_current_admin


# 创建路由器
router = APIRouter(prefix="/api/key", tags=["api_key"])


@router.post("/create", response_model=Dict[str, Any])
async def create_api_key(
    key_data: APIKeyCreate,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """创建新的API密钥"""
    # 生成密钥值
    key_value = f"sk-{uuid.uuid4().hex[:24]}"
    hashed_key = hash_key(key_value)
    
    # 解析过期时间
    expire_time = None
    if key_data.expire_days:
        expire_time = datetime.now() + timedelta(days=key_data.expire_days)
    elif key_data.expire_date:
        expire_time = datetime.fromisoformat(key_data.expire_date)
    
    async with get_db() as conn:
        # 检查用户名是否已存在
        if key_data.user_name:
            existing = await conn.fetchval(
                "SELECT COUNT(*) FROM api_key WHERE user_name = $1",
                key_data.user_name
            )
            if existing > 0:
                raise HTTPException(status_code=400, detail="该用户名已存在")
        
        # 插入新密钥
        key_id = await conn.fetchval(
            """
            INSERT INTO api_key (
                key_value, user_name, llm_ids, rate_limit, 
                daily_limit, monthly_limit, expire_time, ip_whitelist, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING id
            """,
            hashed_key,
            key_data.user_name if key_data.user_name else None,
            key_data.llm_ids if key_data.llm_ids else [],
            key_data.rate_limit if key_data.rate_limit else 10,
            key_data.daily_limit if key_data.daily_limit else 1000,
            key_data.monthly_limit if key_data.monthly_limit else 30000,
            expire_time,
            key_data.ip_whitelist if key_data.ip_whitelist else [],
            key_data.status if key_data.status else 1
        )
    
    # 返回完整的密钥（仅此一次）
    return {
        "id": key_id,
        "key_value": key_value,
        "user_name": key_data.user_name,
        "rate_limit": key_data.rate_limit or 10,
        "daily_limit": key_data.daily_limit or 1000,
        "monthly_limit": key_data.monthly_limit or 30000,
        "expire_time": expire_time.isoformat() if expire_time else None,
        "ip_whitelist": key_data.ip_whitelist or [],
        "llm_ids": key_data.llm_ids or [],
        "status": key_data.status or 1,
        "message": "请妥善保存此密钥，此后不会再显示完整密钥"
    }


@router.get("/list", response_model=Dict[str, Any])
async def list_api_keys(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: Optional[int] = Query(None),
    user_name: Optional[str] = Query(None),
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """查询API密钥列表（支持后端分页+搜索）"""
    offset = (page - 1) * page_size

    where_conditions = []
    params = []
    param_index = 1

    if status is not None:
        where_conditions.append(f"status = ${param_index}")
        params.append(status)
        param_index += 1

    if user_name:
        where_conditions.append(f"user_name ILIKE ${param_index}")
        params.append(f"%{user_name}%")
        param_index += 1

    where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""

    async with get_db() as conn:
        # 查询总数
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM api_key {where_clause}", *params
        )

        # 查询密钥列表
        keys = await conn.fetch(
            f"""
            SELECT
                id, key_value, user_name, llm_ids, rate_limit,
                daily_limit, monthly_limit, expire_time, ip_whitelist,
                status, create_time, last_use_time,
                (SELECT COUNT(*) FROM request_logs r WHERE r.api_key = api_key.key_value) as total_requests
            FROM api_key
            {where_clause}
            ORDER BY create_time DESC
            LIMIT ${param_index} OFFSET ${param_index + 1}
            """,
            *params, page_size, offset
        )

    # 处理结果
    result = []
    for key in keys:
        key_dict = dict(key)
        key_dict["key_value"] = mask_key(key_dict["key_value"])

        llm_names = []
        if key_dict["llm_ids"]:
            async with get_db() as conn:
                models = await conn.fetch(
                    "SELECT llm_name FROM llm_config WHERE id = ANY($1)",
                    key_dict["llm_ids"]
                )
                llm_names = [m["llm_name"] for m in models]

        key_dict["llm_names"] = llm_names
        result.append(key_dict)

    return {
        "items": result,
        "total": total or 0,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, -(-(total or 0) // page_size))
    }


@router.get("/{key_id}", response_model=Dict[str, Any])
async def get_api_key(
    key_id: int,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """获取单个API密钥详情"""
    async with get_db() as conn:
        key = await conn.fetchrow(
            """
            SELECT 
                id, key_value, user_name, llm_ids, rate_limit, 
                daily_limit, monthly_limit, expire_time, ip_whitelist, 
                status, create_time, last_use_time,
                (SELECT COUNT(*) FROM request_logs r WHERE r.api_key = api_key.key_value) as total_requests
            FROM api_key
            WHERE id = $1
            """,
            key_id
        )
    
    if not key:
        raise HTTPException(status_code=404, detail="API密钥不存在")
    
    key_dict = dict(key)
    # 脱敏处理
    key_dict["key_value"] = mask_key(key_dict["key_value"])
    
    # 获取模型名称
    llm_names = []
    if key_dict["llm_ids"]:
        async with get_db() as conn:
            models = await conn.fetch(
                "SELECT llm_name FROM llm_config WHERE id = ANY($1)",
                key_dict["llm_ids"]
            )
            llm_names = [m["llm_name"] for m in models]
    
    key_dict["llm_names"] = llm_names
    
    # 获取使用统计
    async with get_db() as conn:
        today = datetime.now().date()
        today_usage = await conn.fetchval(
            "SELECT COUNT(*) FROM request_logs WHERE api_key = $1 AND DATE(request_time) = $2",
            key_dict["key_value"], today
        )
        
        month_start = datetime.now().replace(day=1).date()
        month_usage = await conn.fetchval(
            "SELECT COUNT(*) FROM request_logs WHERE api_key = $1 AND DATE(request_time) >= $2",
            key_dict["key_value"], month_start
        )
    
    key_dict["today_usage"] = today_usage or 0
    key_dict["month_usage"] = month_usage or 0
    
    return key_dict


@router.put("/{key_id}")
async def update_api_key(
    key_id: int,
    key_data: APIKeyUpdate,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """更新API密钥配置"""
    # 检查密钥是否存在
    async with get_db() as conn:
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM api_key WHERE id = $1",
            key_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail="API密钥不存在")
        
        # 检查用户名是否被其他密钥使用
        if key_data.user_name:
            other_use = await conn.fetchval(
                "SELECT COUNT(*) FROM api_key WHERE id != $1 AND user_name = $2",
                key_id, key_data.user_name
            )
            if other_use > 0:
                raise HTTPException(status_code=400, detail="该用户名已被其他密钥使用")
        
        # 解析过期时间
        expire_time = None
        if key_data.expire_days:
            expire_time = datetime.now() + timedelta(days=key_data.expire_days)
        elif key_data.expire_date:
            expire_time = datetime.fromisoformat(key_data.expire_date)
        
        # 更新密钥
        await conn.execute(
            """
            UPDATE api_key 
            SET 
                user_name = COALESCE($2, user_name),
                llm_ids = COALESCE($3, llm_ids),
                rate_limit = COALESCE($4, rate_limit),
                daily_limit = COALESCE($5, daily_limit),
                monthly_limit = COALESCE($6, monthly_limit),
                expire_time = COALESCE($7, expire_time),
                ip_whitelist = COALESCE($8, ip_whitelist),
                status = COALESCE($9, status)
            WHERE id = $1
            """,
            key_id,
            key_data.user_name,
            key_data.llm_ids,
            key_data.rate_limit,
            key_data.daily_limit,
            key_data.monthly_limit,
            expire_time,
            key_data.ip_whitelist,
            key_data.status
        )
    
    return {"message": "API密钥更新成功"}


@router.put("/{key_id}/status")
async def update_key_status(
    key_id: int,
    status_data: APIKeyStatus,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """更新API密钥状态"""
    async with get_db() as conn:
        # 检查密钥是否存在
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM api_key WHERE id = $1",
            key_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail="API密钥不存在")
        
        # 更新状态
        await conn.execute(
            "UPDATE api_key SET status = $1 WHERE id = $2",
            status_data.status, key_id
        )
    
    status_text = "启用" if status_data.status == 1 else "禁用"
    return {"message": f"API密钥已{status_text}"}


@router.delete("/{key_id}")
async def delete_api_key(
    key_id: int,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """删除API密钥"""
    async with get_db() as conn:
        # 检查密钥是否存在
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM api_key WHERE id = $1",
            key_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail="API密钥不存在")
        
        # 删除密钥
        await conn.execute(
            "DELETE FROM api_key WHERE id = $1",
            key_id
        )
    
    return {"message": "API密钥删除成功"}


@router.get("/stats/{key_id}")
async def get_key_stats(
    key_id: int,
    days: int = Query(30, ge=1, le=365),
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """获取API密钥使用统计"""
    async with get_db() as conn:
        # 获取密钥信息
        key = await conn.fetchrow(
            "SELECT key_value FROM api_key WHERE id = $1",
            key_id
        )
        
        if not key:
            raise HTTPException(status_code=404, detail="API密钥不存在")
        
        key_value = key["key_value"]
        
        # 获取每日使用统计
        daily_stats = []
        for i in range(days - 1, -1, -1):
            date = datetime.now().date() - timedelta(days=i)
            count = await conn.fetchval(
                """
                SELECT COUNT(*) 
                FROM request_logs 
                WHERE api_key = $1 AND DATE(request_time) = $2
                """,
                key_value, date
            )
            
            success_count = await conn.fetchval(
                """
                SELECT COUNT(*) 
                FROM request_logs 
                WHERE api_key = $1 AND DATE(request_time) = $2 AND status = 'success'
                """,
                key_value, date
            )
            
            daily_stats.append({
                "date": date.strftime("%Y-%m-%d"),
                "total_requests": count or 0,
                "success_requests": success_count or 0,
                "success_rate": round(success_count / count * 100, 1) if count else 0
            })
        
        # 获取模型使用分布
        model_distribution = await conn.fetch(
            """
            SELECT llm_name, COUNT(*) as request_count
            FROM request_logs
            WHERE api_key = $1 AND llm_name IS NOT NULL
            GROUP BY llm_name
            ORDER BY request_count DESC
            """,
            key_value
        )
    
    return {
        "key_id": key_id,
        "daily_stats": daily_stats,
        "model_distribution": [dict(row) for row in model_distribution]
    }


def mask_key(key: str) -> str:
    """对密钥进行脱敏处理"""
    if not key or len(key) <= 8:
        return key
    return key[:6] + "****" + key[-4:]


@router.post("/batch-generate")
async def batch_generate_keys(
    count: int = Query(10, ge=1, le=100),
    prefix: str = Query("sk-batch-"),
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """批量生成API密钥"""
    if count > 100:
        raise HTTPException(status_code=400, detail="批量生成数量不能超过100")
    
    generated_keys = []
    async with get_db() as conn:
        for i in range(count):
            key_value = f"{prefix}{uuid.uuid4().hex[:20]}"
            hashed_key = hash_key(key_value)
            
            key_id = await conn.fetchval(
                """
                INSERT INTO api_key (key_value, user_name, status)
                VALUES ($1, $2, $3)
                RETURNING id
                """,
                hashed_key,
                f"batch_user_{i+1}",
                1
            )
            
            generated_keys.append({
                "id": key_id,
                "key_value": key_value,
                "user_name": f"batch_user_{i+1}",
                "status": 1
            })
    
    return {
        "message": f"成功生成 {count} 个API密钥",
        "keys": generated_keys,
        "total": len(generated_keys)
    }


@router.get("/search")
async def search_api_keys(
    query: str = Query(..., min_length=1),
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """搜索API密钥"""
    async with get_db() as conn:
        keys = await conn.fetch(
            """
            SELECT id, key_value, user_name, status, create_time, last_use_time
            FROM api_key
            WHERE 
                user_name ILIKE $1 OR
                key_value ILIKE $1
            ORDER BY create_time DESC
            LIMIT 50
            """,
            f"%{query}%"
        )
    
    result = []
    for key in keys:
        key_dict = dict(key)
        key_dict["key_value"] = mask_key(key_dict["key_value"])
        result.append(key_dict)
    
    return {
        "query": query,
        "results": result,
        "count": len(result)
    }