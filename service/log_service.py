"""
AI大模型API网关 - 日志服务
"""
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import asyncio

from database import db
from models import RequestLogResponse


class LogService:
    """日志服务"""
    
    async def get_logs(self, 
                      page: int = 1, 
                      page_size: int = 10,
                      start_time: Optional[datetime] = None,
                      end_time: Optional[datetime] = None,
                      api_key: Optional[str] = None,
                      status: Optional[str] = None,
                      llm_name: Optional[str] = None,
                      client_ip: Optional[str] = None,
                      sensitive_only: bool = False) -> Dict[str, Any]:
        """获取请求日志列表"""
        try:
            # 构建查询条件
            conditions = []
            params = []
            param_index = 1
            
            if start_time:
                conditions.append(f"request_time >= ${param_index}")
                params.append(start_time)
                param_index += 1
            
            if end_time:
                conditions.append(f"request_time <= ${param_index}")
                params.append(end_time)
                param_index += 1
            
            if api_key:
                conditions.append(f"api_key = ${param_index}")
                params.append(api_key)
                param_index += 1
            
            if status:
                conditions.append(f"status = ${param_index}")
                params.append(status)
                param_index += 1
            
            if llm_name:
                conditions.append(f"llm_name = ${param_index}")
                params.append(llm_name)
                param_index += 1
            
            if client_ip:
                conditions.append(f"client_ip ILIKE ${param_index}")
                params.append(f"%{client_ip}%")
                param_index += 1
            
            if sensitive_only:
                conditions.append(f"sensitive_result IS NOT NULL")
            
            # 构建WHERE子句
            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)
            
            # 查询总记录数
            count_query = f"SELECT COUNT(*) FROM request_logs {where_clause}"
            total_count = await db.fetchval(count_query, *params)
            
            # 查询分页数据
            offset = (page - 1) * page_size
            query = f"""
                SELECT 
                    id, request_id, api_key, user_name, request_time,
                    client_ip, llm_name, prompt_content, image_content,
                    response_content, prompt_tokens, completion_tokens,
                    status, sensitive_result, error_msg
                FROM request_logs
                {where_clause}
                ORDER BY request_time DESC
                LIMIT ${param_index} OFFSET ${param_index + 1}
            """
            
            params.append(page_size)
            params.append(offset)
            
            logs = await db.fetch(query, *params)
            
            # 转换为响应模型
            log_list = []
            for log in logs:
                # 脱敏API密钥
                masked_api_key = self.mask_api_key(log["api_key"])
                
                log_dict = dict(log)
                log_dict["api_key"] = masked_api_key
                
                # 解析敏感词检测结果
                if log_dict["sensitive_result"]:
                    try:
                        import json
                        log_dict["sensitive_result"] = json.loads(log_dict["sensitive_result"])
                    except:
                        pass
                
                log_list.append(RequestLogResponse(**log_dict))
            
            return {
                "total": total_count,
                "page": page,
                "page_size": page_size,
                "logs": log_list
            }
            
        except Exception as e:
            print(f"获取日志列表失败: {e}")
            raise
    
    async def get_log_by_id(self, log_id: int) -> Optional[Dict[str, Any]]:
        """根据ID获取日志详情"""
        try:
            log = await db.fetchrow(
                """
                SELECT 
                    id, request_id, api_key, user_name, request_time,
                    client_ip, llm_name, prompt_content, image_content,
                    response_content, prompt_tokens, completion_tokens,
                    status, sensitive_result, error_msg
                FROM request_logs
                WHERE id = $1
                """,
                log_id
            )
            
            if not log:
                return None
            
            # 脱敏API密钥
            masked_api_key = self.mask_api_key(log["api_key"])
            
            log_dict = dict(log)
            log_dict["api_key"] = masked_api_key
            
            # 解析敏感词检测结果
            if log_dict["sensitive_result"]:
                try:
                    import json
                    log_dict["sensitive_result"] = json.loads(log_dict["sensitive_result"])
                except:
                    pass
            
            return log_dict
            
        except Exception as e:
            print(f"获取日志详情失败: {e}")
            raise
    
    async def get_dashboard_stats(self, days: int = 7) -> Dict[str, Any]:
        """获取仪表板统计信息"""
        try:
            # 计算时间范围
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            
            # 查询今日统计
            today_start = datetime(end_date.year, end_date.month, end_date.day)
            
            stats = {
                "total_requests": 0,
                "today_requests": 0,
                "success_rate": 0,
                "average_response_time": 0,
                "top_models": [],
                "daily_trend": [],
                "sensitive_triggers": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "daily_tokens": [],
                "status_dist": [],
                "sensitive_top": [],
                "total_api_keys": 0,
            }
            
            # 总请求数
            total_count = await db.fetchval(
                "SELECT COUNT(*) FROM request_logs WHERE request_time >= $1",
                start_date
            )
            stats["total_requests"] = total_count or 0
            
            # 今日请求数
            today_count = await db.fetchval(
                "SELECT COUNT(*) FROM request_logs WHERE request_time >= $1",
                today_start
            )
            stats["today_requests"] = today_count or 0
            
            # 成功率
            success_count = await db.fetchval(
                "SELECT COUNT(*) FROM request_logs WHERE request_time >= $1 AND status = 'success'",
                start_date
            )
            if total_count > 0:
                stats["success_rate"] = round((success_count or 0) / total_count * 100, 2)
            
            # 敏感词触发次数
            sensitive_count = await db.fetchval(
                "SELECT COUNT(*) FROM request_logs WHERE request_time >= $1 AND sensitive_result IS NOT NULL",
                start_date
            )
            stats["sensitive_triggers"] = sensitive_count or 0
            
            # Token 统计（近N天）
            token_stats = await db.fetchrow(
                """
                SELECT 
                    COALESCE(SUM(prompt_tokens), 0) as total_input,
                    COALESCE(SUM(completion_tokens), 0) as total_output
                FROM request_logs WHERE request_time >= $1
                """,
                start_date
            )
            stats["total_input_tokens"] = token_stats["total_input"] if token_stats else 0
            stats["total_output_tokens"] = token_stats["total_output"] if token_stats else 0

            # 状态分布（近N天）
            status_rows = await db.fetch(
                """
                SELECT status, COUNT(*) as cnt
                FROM request_logs WHERE request_time >= $1
                GROUP BY status
                """,
                start_date
            )
            stats["status_dist"] = [dict(r) for r in status_rows]

            # 每日Token趋势
            daily_tokens = []
            for i in range(days - 1, -1, -1):
                date = end_date - timedelta(days=i)
                row = await db.fetchrow(
                    """
                    SELECT COALESCE(SUM(prompt_tokens),0) as inp, COALESCE(SUM(completion_tokens),0) as outp
                    FROM request_logs WHERE DATE(request_time) = $1
                    """,
                    date
                )
                daily_tokens.append({
                    "date": date.strftime("%m-%d"),
                    "input": row["inp"] or 0,
                    "output": row["outp"] or 0
                })
            stats["daily_tokens"] = daily_tokens

            # 敏感词触发 Top5 —— 按敏感词类型排行（近N天）
            import json as _json
            sensitive_rows = await db.fetch(
                """
                SELECT sensitive_result
                FROM request_logs
                WHERE sensitive_result IS NOT NULL AND request_time >= $1
                """,
                start_date
            )
            type_counter: dict = {}
            for row in sensitive_rows:
                raw = row["sensitive_result"]
                try:
                    obj = _json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    continue
                # 1) 从 sensitive_words.types 提取（check_and_log_sensitive 格式）
                sw = obj.get("sensitive_words")
                if isinstance(sw, dict):
                    for t in (sw.get("types") or []):
                        if isinstance(t, str) and t:
                            type_counter[t] = type_counter.get(t, 0) + 1
                # 2) 从 personal_info 提取（id_card=True 等）
                pi = obj.get("personal_info")
                if isinstance(pi, dict):
                    for k, v in pi.items():
                        if k != "has_personal_info" and v is True:
                            type_counter[k] = type_counter.get(k, 0) + 1
                # 3) 兼容旧格式：顶层 types / categories 列表
                if not sw and not pi:
                    types = obj.get("types") or obj.get("categories") or []
                    if isinstance(types, str):
                        types = [types]
                    if isinstance(types, (list, tuple)):
                        for t in types:
                            if isinstance(t, str) and t:
                                type_counter[t] = type_counter.get(t, 0) + 1
                # 4) 兼容 response_detection 合并格式
                rd = obj.get("response_detection")
                if isinstance(rd, dict):
                    rsw = rd.get("sensitive_words")
                    if isinstance(rsw, dict):
                        for t in (rsw.get("types") or []):
                            if isinstance(t, str) and t:
                                type_counter[t] = type_counter.get(t, 0) + 1
                    rpi = rd.get("personal_info")
                    if isinstance(rpi, dict):
                        for k, v in rpi.items():
                            if k != "has_personal_info" and v is True:
                                type_counter[k] = type_counter.get(k, 0) + 1
            # 取 Top 5
            sensitive_top = sorted(type_counter.items(), key=lambda x: x[1], reverse=True)[:5]
            stats["sensitive_top"] = [{"type": t, "cnt": c} for t, c in sensitive_top]
            
            # 热门模型
            top_models = await db.fetch(
                """
                SELECT llm_name, COUNT(*) as request_count
                FROM request_logs
                WHERE request_time >= $1
                GROUP BY llm_name
                ORDER BY request_count DESC
                LIMIT 10
                """,
                start_date
            )
            stats["top_models"] = [dict(model) for model in top_models]
            
            # 每日趋势
            daily_trend = await db.fetch(
                """
                SELECT 
                    DATE(request_time) as date,
                    COUNT(*) as request_count,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN sensitive_result IS NOT NULL THEN 1 ELSE 0 END) as sensitive_count
                FROM request_logs
                WHERE request_time >= $1
                GROUP BY DATE(request_time)
                ORDER BY date
                """,
                start_date
            )
            
            # 格式化每日趋势数据 - 生成完整的N天数据（含0值天）
            trend_data = []
            trend_map = {str(t["date"]): t for t in daily_trend}
            for i in range(days - 1, -1, -1):
                date = end_date - timedelta(days=i)
                date_str = str(date.date())
                if date_str in trend_map:
                    t = trend_map[date_str]
                    trend_data.append({
                        "date": t["date"].strftime("%m-%d"),
                        "requests": t["request_count"],
                        "success": t["success_count"],
                        "sensitive": t["sensitive_count"]
                    })
                else:
                    trend_data.append({
                        "date": date.strftime("%m-%d"),
                        "requests": 0,
                        "success": 0,
                        "sensitive": 0
                    })
            
            stats["daily_trend"] = trend_data
            
            # API密钥统计
            api_key_stats = await db.fetch(
                """
                SELECT 
                    COUNT(DISTINCT api_key) as total_keys,
                    SUM(total_requests) as total_calls
                FROM api_key
                WHERE status = 1
                """
            )
            
            if api_key_stats and len(api_key_stats) > 0:
                stats["total_api_keys"] = api_key_stats[0]["total_keys"] or 0
                stats["total_calls"] = api_key_stats[0]["total_calls"] or 0
            
            return stats
            
        except Exception as e:
            print(f"获取仪表板统计失败: {e}")
            raise
    
    async def export_logs(self, 
                         start_time: Optional[datetime] = None,
                         end_time: Optional[datetime] = None,
                         format: str = "json") -> str:
        """导出日志数据"""
        try:
            # 构建查询条件
            conditions = []
            params = []
            param_index = 1
            
            if start_time:
                conditions.append(f"request_time >= ${param_index}")
                params.append(start_time)
                param_index += 1
            
            if end_time:
                conditions.append(f"request_time <= ${param_index}")
                params.append(end_time)
                param_index += 1
            
            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)
            
            # 查询日志数据
            query = f"""
                SELECT 
                    request_id, api_key, user_name, request_time,
                    client_ip, llm_name, status, 
                    prompt_tokens, completion_tokens,
                    sensitive_result, error_msg
                FROM request_logs
                {where_clause}
                ORDER BY request_time DESC
                LIMIT 10000  -- 限制导出数量
            """
            
            logs = await db.fetch(query, *params)
            
            # 格式化导出数据
            export_data = []
            for log in logs:
                # 脱敏API密钥
                masked_api_key = self.mask_api_key(log["api_key"])
                
                log_dict = dict(log)
                log_dict["api_key"] = masked_api_key
                
                # 简化敏感词检测结果
                if log_dict["sensitive_result"]:
                    try:
                        import json
                        sensitive_data = json.loads(log_dict["sensitive_result"])
                        log_dict["has_sensitive"] = sensitive_data.get("sensitive_words", {}).get("found", False)
                        log_dict["sensitive_types"] = sensitive_data.get("sensitive_words", {}).get("types", [])
                    except:
                        log_dict["has_sensitive"] = False
                        log_dict["sensitive_types"] = []
                
                export_data.append(log_dict)
            
            # 根据格式返回数据
            if format == "json":
                import json
                return json.dumps(export_data, default=str, ensure_ascii=False)
            elif format == "csv":
                import csv
                import io
                
                if not export_data:
                    return ""
                
                # 获取所有字段
                fieldnames = list(export_data[0].keys())
                
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(export_data)
                
                return output.getvalue()
            else:
                raise ValueError(f"不支持的导出格式: {format}")
            
        except Exception as e:
            print(f"导出日志失败: {e}")
            raise
    
    def mask_api_key(self, api_key: str) -> str:
        """脱敏API密钥"""
        if not api_key or len(api_key) <= 8:
            return api_key
        
        # 显示前4位和后4位，中间用*代替
        prefix = api_key[:4]
        suffix = api_key[-4:]
        masked_part = "*" * (len(api_key) - 8)
        
        return f"{prefix}{masked_part}{suffix}"
    
    async def cleanup_old_logs(self, days_to_keep: int = 30):
        """清理过期日志"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            
            deleted_count = await db.execute(
                "DELETE FROM request_logs WHERE request_time < $1",
                cutoff_date
            )
            
            print(f"清理了 {deleted_count} 条过期日志")
            return deleted_count
            
        except Exception as e:
            print(f"清理过期日志失败: {e}")
            raise


# 创建全局日志服务实例
log_service = LogService()