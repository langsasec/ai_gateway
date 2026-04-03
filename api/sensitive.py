"""
AI大模型API网关 - 敏感词管理接口
敏感词的增删改查、检测策略配置等
"""
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from database import get_db
from service.auth_service import get_current_admin


# 创建路由器
router = APIRouter(prefix="/api/sensitive", tags=["sensitive"])


class SensitiveWordCreate(BaseModel):
    word: str
    type: Optional[str] = None  # 敏感词类型：violence, pornography, terrorism, fraud, drugs, gambling, political, general
    is_regex: bool = False       # True 时 word 作为正则表达式匹配


class SensitiveWordUpdate(BaseModel):
    word: Optional[str] = None
    type: Optional[str] = None
    is_regex: Optional[bool] = None


class DetectionConfig(BaseModel):
    mode: str = "audit"  # audit: 审计模式, block: 拦截模式
    check_request: bool = True  # 是否检查请求内容
    check_response: bool = True  # 是否检查响应内容
    enable_pii_detection: bool = True  # 是否启用个人信息检测


@router.post("/create", response_model=Dict[str, Any])
async def create_sensitive_word(
    word_data: SensitiveWordCreate,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """添加敏感词（支持正则）"""
    import re as _re
    # 验证敏感词类型
    valid_types = ["violence", "pornography", "terrorism", "fraud", "drugs", "gambling", "political", "general"]
    if word_data.type and word_data.type not in valid_types:
        raise HTTPException(status_code=400, detail=f"无效的敏感词类型，可选值: {', '.join(valid_types)}")

    # 如果是正则，先验证合法性
    if word_data.is_regex:
        try:
            _re.compile(word_data.word)
        except _re.error as exc:
            raise HTTPException(status_code=400, detail=f"正则表达式无效: {exc}")

    async with get_db() as conn:
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM sensitive_words WHERE word = $1",
            word_data.word
        )
        if existing > 0:
            raise HTTPException(status_code=400, detail="该敏感词已存在")

        word_id = await conn.fetchval(
            "INSERT INTO sensitive_words (word, type, is_regex) VALUES ($1, $2, $3) RETURNING id",
            word_data.word, word_data.type, word_data.is_regex
        )

    # 通知检测器重新加载
    from service.sensitive_service import sensitive_detector
    import asyncio
    asyncio.create_task(sensitive_detector.initialize())

    return {
        "id": word_id,
        "word": word_data.word,
        "type": word_data.type,
        "is_regex": word_data.is_regex,
        "message": "敏感词添加成功"
    }


@router.get("/list", response_model=List[Dict[str, Any]])
async def list_sensitive_words(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    word_type: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """查询敏感词列表"""
    offset = (page - 1) * page_size
    
    where_conditions = []
    params = []
    param_index = 1
    
    if word_type:
        where_conditions.append(f"type = ${param_index}")
        params.append(word_type)
        param_index += 1
    
    if keyword:
        where_conditions.append(f"word ILIKE ${param_index}")
        params.append(f"%{keyword}%")
        param_index += 1
    
    where_clause = "WHERE " + " AND ".join(where_conditions) if where_conditions else ""
    
    async with get_db() as conn:
        # 查询敏感词列表
        words = await conn.fetch(
            f"""
            SELECT id, word, type, COALESCE(is_regex, FALSE) AS is_regex,
                   COALESCE(is_preset, FALSE) AS is_preset, create_time
            FROM sensitive_words
            {where_clause}
            ORDER BY create_time DESC
            LIMIT ${param_index} OFFSET ${param_index + 1}
            """,
            *params, page_size, offset
        )
        
        # 查询总数
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM sensitive_words {where_clause}",
            *params
        )
    
    return {
        "words": [dict(word) for word in words],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0
    }


@router.get("/types")
async def get_sensitive_word_types(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    """获取敏感词类型统计"""
    async with get_db() as conn:
        type_stats = await conn.fetch(
            """
            SELECT 
                type,
                COUNT(*) as count
            FROM sensitive_words
            WHERE type IS NOT NULL
            GROUP BY type
            ORDER BY count DESC
            """
        )
        
        # 按类型分类的敏感词
        words_by_type = {}
        for type_stat in type_stats:
            type_name = type_stat["type"]
            words = await conn.fetch(
                "SELECT word FROM sensitive_words WHERE type = $1 ORDER BY word LIMIT 10",
                type_name
            )
            words_by_type[type_name] = [w["word"] for w in words]
    
    return {
        "type_stats": [dict(stat) for stat in type_stats],
        "words_by_type": words_by_type
    }


@router.put("/{word_id}")
async def update_sensitive_word(
    word_id: int,
    word_data: SensitiveWordUpdate,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """更新敏感词"""
    async with get_db() as conn:
        # 检查敏感词是否存在
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM sensitive_words WHERE id = $1",
            word_id
        )
        if not existing:
            raise HTTPException(status_code=404, detail="敏感词不存在")
        
        # 如果更新word，检查是否与现有冲突
        if word_data.word:
            other_word = await conn.fetchval(
                "SELECT COUNT(*) FROM sensitive_words WHERE word = $1 AND id != $2",
                word_data.word, word_id
            )
            if other_word > 0:
                raise HTTPException(status_code=400, detail="该敏感词已存在")
        
        # 更新敏感词
        update_fields = []
        params = []
        param_index = 1
        
        if word_data.word is not None:
            update_fields.append(f"word = ${param_index}")
            params.append(word_data.word)
            param_index += 1
        
        if word_data.type is not None:
            update_fields.append(f"type = ${param_index}")
            params.append(word_data.type)
            param_index += 1
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="没有提供更新字段")
        
        params.append(word_id)
        query = f"UPDATE sensitive_words SET {', '.join(update_fields)} WHERE id = ${param_index}"
        
        await conn.execute(query, *params)
    
    return {"message": "敏感词更新成功"}


@router.delete("/{word_id}")
async def delete_sensitive_word(
    word_id: int,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """删除敏感词（预置规则不可删除）"""
    async with get_db() as conn:
        # 检查敏感词是否存在及是否为预置规则
        word = await conn.fetchrow(
            "SELECT id, word, COALESCE(is_preset, FALSE) AS is_preset FROM sensitive_words WHERE id = $1",
            word_id
        )
        if not word:
            raise HTTPException(status_code=404, detail="敏感词不存在")
        if word["is_preset"]:
            raise HTTPException(status_code=403, detail="预置规则不可删除")
        
        # 删除敏感词
        await conn.execute(
            "DELETE FROM sensitive_words WHERE id = $1",
            word_id
        )
    
    return {"message": "敏感词删除成功"}


@router.post("/batch-create")
async def batch_create_sensitive_words(
    words: List[str],
    word_type: Optional[str] = None,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """批量添加敏感词"""
    if len(words) > 100:
        raise HTTPException(status_code=400, detail="批量添加数量不能超过100")
    
    success_count = 0
    failed_count = 0
    failed_words = []
    
    async with get_db() as conn:
        for word in words:
            word = word.strip()
            if not word:
                continue
            
            try:
                # 检查是否已存在
                existing = await conn.fetchval(
                    "SELECT COUNT(*) FROM sensitive_words WHERE word = $1",
                    word
                )
                
                if existing == 0:
                    await conn.execute(
                        "INSERT INTO sensitive_words (word, type) VALUES ($1, $2)",
                        word, word_type
                    )
                    success_count += 1
                else:
                    failed_count += 1
                    failed_words.append(f"{word} (已存在)")
            except Exception as e:
                failed_count += 1
                failed_words.append(f"{word} (错误: {str(e)})")
    
    return {
        "message": f"批量添加完成，成功 {success_count} 个，失败 {failed_count} 个",
        "success_count": success_count,
        "failed_count": failed_count,
        "failed_words": failed_words
    }


@router.get("/config")
async def get_detection_config(current_admin: Dict[str, Any] = Depends(get_current_admin)):
    """获取检测配置"""
    # 从数据库或配置文件中读取配置
    async with get_db() as conn:
        config = await conn.fetchrow(
            """
            SELECT 
                mode, check_request, check_response, enable_pii_detection
            FROM sensitive_config
            LIMIT 1
            """
        )
    
    if not config:
        # 默认配置
        config = {
            "mode": "audit",
            "check_request": True,
            "check_response": True,
            "enable_pii_detection": True
        }
    
    return dict(config)


@router.put("/config")
async def update_detection_config(
    config_data: DetectionConfig,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """更新检测配置"""
    if config_data.mode not in ["audit", "block"]:
        raise HTTPException(status_code=400, detail="检测模式必须是 'audit' 或 'block'")
    
    async with get_db() as conn:
        # 检查配置是否存在
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM sensitive_config"
        )
        
        if existing > 0:
            # 更新配置
            await conn.execute(
                """
                UPDATE sensitive_config 
                SET mode = $1, check_request = $2, check_response = $3, enable_pii_detection = $4
                """,
                config_data.mode, config_data.check_request, 
                config_data.check_response, config_data.enable_pii_detection
            )
        else:
            # 插入新配置
            await conn.execute(
                """
                INSERT INTO sensitive_config (mode, check_request, check_response, enable_pii_detection)
                VALUES ($1, $2, $3, $4)
                """,
                config_data.mode, config_data.check_request, 
                config_data.check_response, config_data.enable_pii_detection
            )
    
    return {
        "message": "检测配置更新成功",
        "config": config_data.dict()
    }


@router.get("/stats")
async def get_sensitive_stats(
    days: int = Query(30, ge=1, le=365),
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """获取敏感词检测统计"""
    async with get_db() as conn:
        # 总触发次数
        total_triggers = await conn.fetchval(
            "SELECT COUNT(*) FROM request_logs WHERE sensitive_result IS NOT NULL"
        )
        
        # 按类型统计触发次数
        type_triggers = await conn.fetch(
            """
            SELECT 
                (sensitive_result->>'type') as trigger_type,
                COUNT(*) as count
            FROM request_logs 
            WHERE sensitive_result IS NOT NULL 
            AND sensitive_result->>'type' IS NOT NULL
            GROUP BY sensitive_result->>'type'
            ORDER BY count DESC
            """
        )
        
        # 每日触发趋势
        daily_trend = []
        from datetime import datetime, timedelta
        for i in range(days - 1, -1, -1):
            date = datetime.now().date() - timedelta(days=i)
            count = await conn.fetchval(
                """
                SELECT COUNT(*) 
                FROM request_logs 
                WHERE sensitive_result IS NOT NULL AND DATE(request_time) = $1
                """,
                date
            )
            
            daily_trend.append({
                "date": date.strftime("%Y-%m-%d"),
                "triggers": count or 0
            })
        
        # 触发最多的关键词
        top_words = await conn.fetch(
            """
            SELECT 
                (sensitive_result->>'word') as word,
                COUNT(*) as count
            FROM request_logs 
            WHERE sensitive_result IS NOT NULL 
            AND sensitive_result->>'word' IS NOT NULL
            GROUP BY sensitive_result->>'word'
            ORDER BY count DESC
            LIMIT 10
            """
        )
    
    return {
        "total_triggers": total_triggers or 0,
        "type_triggers": [dict(stat) for stat in type_triggers],
        "daily_trend": daily_trend,
        "top_words": [dict(word) for word in top_words]
    }


@router.post("/test")
async def test_sensitive_detection(
    text: str,
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """测试敏感词检测（支持正则）"""
    from service.sensitive_service import sensitive_detector

    # 确保已初始化
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
        "blocked": False  # test 接口不做实际拦截
    }


@router.get("/export")
async def export_sensitive_words(
    format: str = Query("json", regex="^(json|csv)$"),
    current_admin: Dict[str, Any] = Depends(get_current_admin)
):
    """导出敏感词列表"""
    async with get_db() as conn:
        words = await conn.fetch(
            "SELECT id, word, type, create_time FROM sensitive_words ORDER BY word"
        )
    
    words_list = [dict(word) for word in words]
    
    if format == "csv":
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # 写入表头
        writer.writerow(["ID", "敏感词", "类型", "创建时间"])
        
        # 写入数据
        for word in words_list:
            writer.writerow([
                word["id"],
                word["word"],
                word["type"] or "",
                word["create_time"].isoformat() if word["create_time"] else ""
            ])
        
        return {
            "format": "csv",
            "data": output.getvalue(),
            "filename": f"sensitive_words_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    else:
        return {
            "format": "json",
            "data": words_list,
            "total": len(words_list)
        }