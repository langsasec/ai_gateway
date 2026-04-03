"""
AI大模型API网关 - 大模型服务
"""
import asyncio
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, AsyncGenerator
import aiohttp
from fastapi import HTTPException, status

from config import settings
from database import db
from models import ChatCompletionRequest, ChatCompletionResponse
from service.sensitive_service import sensitive_detector
from service.auth_service import authenticate_api_key, validate_ip_whitelist, check_rate_limit, check_daily_limit, check_monthly_limit, update_api_key_usage


class LLMService:
    """大模型服务"""
    
    def __init__(self):
        self.llm_configs = {}
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def initialize(self):
        """初始化服务"""
        try:
            # 加载大模型配置
            await self.load_llm_configs()
            
            # 创建HTTP会话
            self.session = aiohttp.ClientSession()
            
            print("大模型服务初始化完成")
            
        except Exception as e:
            print(f"大模型服务初始化失败: {e}")
            raise
    
    async def load_llm_configs(self):
        """加载大模型配置"""
        try:
            configs = await db.fetch(
                "SELECT id, llm_name, api_url, api_key, status FROM llm_config WHERE status = 1"
            )
            
            self.llm_configs = {}
            for config in configs:
                self.llm_configs[config["llm_name"]] = {
                    "id": config["id"],
                    "api_url": config["api_url"],
                    "api_key": config["api_key"],
                    "status": config["status"]
                }
            
            print(f"加载了 {len(self.llm_configs)} 个大模型配置")
            
        except Exception as e:
            print(f"加载大模型配置失败: {e}")
    
    async def get_llm_config(self, model_name: str) -> Optional[Dict[str, Any]]:
        """获取大模型配置"""
        return self.llm_configs.get(model_name)
    
    async def validate_request(self, 
                              api_key: str, 
                              model_name: str, 
                              client_ip: str,
                              request_time: datetime) -> Dict[str, Any]:
        """验证请求"""
        # 1. 认证API密钥
        api_key_info = await authenticate_api_key(api_key)
        if not api_key_info:
            print(f"[认证失败] key='{(api_key or '')[:12]}...' 在数据库中未找到或已禁用")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的API密钥"
            )
        
        # 2. 验证IP白名单
        if not await validate_ip_whitelist(api_key_info, client_ip):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="IP地址不在白名单中"
            )
        
        # 3. 检查密钥是否允许调用该模型
        llm_ids = api_key_info.get("llm_ids") or []
        llm_config = await self.get_llm_config(model_name)
        
        if not llm_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不支持的大模型"
            )
        
        # 过滤 llm_ids 中已不存在的模型 ID（防止删除模型后数据不一致）
        if llm_ids:
            valid_llm_ids = [lid for lid in llm_ids if lid in {c["id"] for c in self.llm_configs.values()}]
            if valid_llm_ids != llm_ids:
                print(f"[警告] 密钥 id={api_key_info['id']} 的 llm_ids={llm_ids} 包含已删除的模型，已自动过滤为 {valid_llm_ids}")
                llm_ids = valid_llm_ids
        
        # 如果llm_ids为空，表示允许调用所有模型
        if llm_ids and llm_config["id"] not in llm_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="该密钥不允许调用此大模型"
            )
        
        # 4. 检查调用限制
        if not await check_daily_limit(api_key_info):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="日调用次数已达到上限"
            )
        
        if not await check_monthly_limit(api_key_info):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="月调用次数已达到上限"
            )
        
        # 5. 检查Token用量限额
        token_limit = api_key_info.get("token_limit", 0)
        total_tokens = api_key_info.get("total_tokens", 0)
        if token_limit > 0 and total_tokens >= token_limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Token用量已达上限（{total_tokens}/{token_limit}）"
            )
        
        # 6. 检查速率限制
        if settings.RATE_LIMIT_ENABLED and not await check_rate_limit(api_key_info, request_time):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="请求过于频繁，请稍后再试"
            )
        
        return {
            "api_key_info": api_key_info,
            "llm_config": llm_config
        }
    
    async def chat_completion(self, 
                             request: ChatCompletionRequest, 
                             api_key: str,
                             client_ip: str,
                             request_id: Optional[str] = None) -> ChatCompletionResponse:
        """聊天补全请求"""
        if not request_id:
            request_id = str(uuid.uuid4())
        
        request_time = datetime.now()
        
        try:
            # 1. 验证请求
            validation_result = await self.validate_request(
                api_key, request.model, client_ip, request_time
            )
            
            api_key_info = validation_result["api_key_info"]
            llm_config = validation_result["llm_config"]
            
            # 2. 提取提示词内容用于敏感词检测
            prompt_content = self.extract_prompt_content(request.messages)
            
            # 3. 敏感词检测
            sensitive_result = None
            if settings.SENSITIVE_CHECK_ENABLED and prompt_content:
                passed, check_result = await sensitive_detector.check_and_log_sensitive(
                    content=prompt_content,
                    request_id=request_id,
                    api_key=api_key,
                    client_ip=client_ip,
                    content_type="prompt"
                )
                
                if not passed:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="内容包含敏感信息，请求被拦截"
                    )
                
                # 审计模式下 check_result 不为 None 表示有命中
                if check_result:
                    sensitive_result = check_result
            
            # 4. 转发请求到大模型API
            response_data = await self.forward_to_llm(request, llm_config)
            
            # 5. 提取响应内容用于敏感词检测
            response_content = self.extract_response_content(response_data)
            
            # 6. 响应内容敏感词检测
            if settings.SENSITIVE_CHECK_ENABLED and response_content:
                passed, response_sensitive_result = await sensitive_detector.check_and_log_sensitive(
                    content=response_content,
                    request_id=request_id,
                    api_key=api_key,
                    client_ip=client_ip,
                    content_type="response"
                )
                
                # 即使响应包含敏感词，也返回结果，但记录审计日志
                if response_sensitive_result:
                    if sensitive_result:
                        # 合并敏感词检测结果：将响应的命中追加到请求结果中
                        merged = dict(sensitive_result)
                        merged["response_detection"] = response_sensitive_result
                        sensitive_result = merged
                    else:
                        sensitive_result = response_sensitive_result
            
            # 7. 更新API密钥使用统计（含Token累计）
            prompt_tok = response_data.get("usage", {}).get("prompt_tokens", 0)
            completion_tok = response_data.get("usage", {}).get("completion_tokens", 0)
            await update_api_key_usage(api_key_info["id"], prompt_tokens=prompt_tok, completion_tokens=completion_tok)
            
            # 8. 异步记录请求日志
            # 序列化敏感词检测结果
            sensitive_result_str = json.dumps(sensitive_result, ensure_ascii=False) if sensitive_result else None
            asyncio.create_task(self.log_request(
                request_id=request_id,
                api_key=api_key,
                user_name=api_key_info.get("user_name"),
                client_ip=client_ip,
                llm_name=request.model,
                prompt_content=prompt_content,
                response_content=response_content,
                prompt_tokens=prompt_tok,
                completion_tokens=completion_tok,
                status="success",
                sensitive_result=sensitive_result_str,
                error_msg=None
            ))
            
            # 9. 返回响应
            return ChatCompletionResponse(
                model=request.model,
                choices=response_data.get("choices", []),
                usage=response_data.get("usage", {})
            )
            
        except HTTPException:
            raise
        except Exception as e:
            # 记录错误日志
            error_msg = str(e)
            asyncio.create_task(self.log_request(
                request_id=request_id,
                api_key=api_key,
                user_name=None,
                client_ip=client_ip,
                llm_name=request.model if hasattr(request, 'model') else "unknown",
                prompt_content=None,
                response_content=None,
                prompt_tokens=None,
                completion_tokens=None,
                status="failed",
                sensitive_result=None,
                error_msg=error_msg
            ))
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"请求处理失败: {error_msg}"
            )
    
    async def chat_completion_stream(self, 
                                    request: ChatCompletionRequest, 
                                    api_key: str,
                                    client_ip: str,
                                    request_id: Optional[str] = None) -> AsyncGenerator[bytes, None]:
        """流式聊天补全请求"""
        if not request_id:
            request_id = str(uuid.uuid4())
        
        request_time = datetime.now()
        
        # 用于在 finally 中记录日志的上下文变量
        log_context = {
            "request_id": request_id,
            "api_key": api_key,
            "user_name": None,
            "client_ip": client_ip,
            "llm_name": request.model,
            "prompt_content": None,
            "response_content": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "status": "failed",
            "sensitive_result": None,
            "error_msg": None,
            "api_key_info": None,
            "full_response_content": [],
            "sensitive_result_dict": None,
        }
        
        try:
            # 1. 验证请求
            validation_result = await self.validate_request(
                api_key, request.model, client_ip, request_time
            )
            
            api_key_info = validation_result["api_key_info"]
            llm_config = validation_result["llm_config"]
            
            log_context["api_key_info"] = api_key_info
            log_context["user_name"] = api_key_info.get("user_name")
            
            # 2. 提取提示词内容用于敏感词检测
            prompt_content = self.extract_prompt_content(request.messages)
            log_context["prompt_content"] = prompt_content
            
            # 3. 敏感词检测（请求）
            sensitive_result = None
            if settings.SENSITIVE_CHECK_ENABLED and prompt_content:
                passed, check_result = await sensitive_detector.check_and_log_sensitive(
                    content=prompt_content,
                    request_id=request_id,
                    api_key=api_key,
                    client_ip=client_ip,
                    content_type="prompt"
                )
                
                if not passed:
                    log_context["status"] = "blocked"
                    log_context["error_msg"] = "内容包含敏感信息，请求被拦截"
                    error_data = {"error": {"message": "内容包含敏感信息，请求被拦截", "type": "sensitive_content"}}
                    yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n".encode("utf-8")
                    yield b"data: [DONE]\n\n"
                    return
                
                if check_result:
                    sensitive_result = check_result
                    # 立即保存到 log_context，防止 generator 被 cancel 时丢失
                    log_context["sensitive_result_dict"] = check_result
            
            # 4. 流式转发到大模型API
            request.stream = True
            full_response_content = log_context["full_response_content"]
            
            # 构建请求头
            headers = {
                "Authorization": f"Bearer {llm_config['api_key']}",
                "Content-Type": "application/json"
            }
            
            # 构建请求体
            request_data = request.dict(exclude_none=True)
            
            # 请求上游在流式响应末尾返回 usage 信息
            # OpenAI / qwen 等多数模型支持 stream_options.include_usage
            if request_data.get("stream") and isinstance(request_data.get("stream_options"), dict):
                request_data["stream_options"]["include_usage"] = True
            elif request_data.get("stream"):
                request_data["stream_options"] = {"include_usage": True}
            
            # 构建请求URL
            base_url = llm_config["api_url"].rstrip("/")
            if not base_url.endswith("/chat/completions"):
                forward_url = base_url + "/chat/completions"
            else:
                forward_url = base_url
            
            timeout = aiohttp.ClientTimeout(total=300)
            
            async with self.session.post(
                forward_url,
                headers=headers,
                json=request_data,
                timeout=timeout
            ) as upstream_response:
                if upstream_response.status != 200:
                    error_text = await upstream_response.text()
                    log_context["status"] = "failed"
                    log_context["error_msg"] = f"大模型API错误: {upstream_response.status} - {error_text}"
                    error_data = {"error": {"message": f"大模型API错误: {upstream_response.status} - {error_text}", "type": "upstream_error"}}
                    yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n".encode("utf-8")
                    yield b"data: [DONE]\n\n"
                    return
                
                # 逐行转发 SSE 数据
                # 使用 iter_any() + 手动 buffer，按 \n 切割确保每次 yield 完整的 SSE 行
                buffer = b""
                received_done = False  # 标记是否已收到上游的 [DONE]

                async for raw_chunk in upstream_response.content.iter_any():
                    buffer += raw_chunk
                    
                    while b"\n" in buffer:
                        newline_idx = buffer.index(b"\n")
                        line = buffer[:newline_idx]
                        buffer = buffer[newline_idx + 1:]
                        
                        # 跳过空行（SSE 事件之间的分隔符 \n\n 会产生空行）
                        if not line:
                            continue
                        
                        decoded_line = line.decode("utf-8", errors="replace").rstrip("\r")
                        
                        # 检测上游的 [DONE] — 记录但先不转发（统一在最后发送）
                        if decoded_line.strip() == "data: [DONE]":
                            received_done = True
                            continue
                        
                        # 解析 data 行，提取内容用于日志和敏感词检测
                        if decoded_line.startswith("data: "):
                            try:
                                chunk_data = json.loads(decoded_line[6:].strip())
                                choices = chunk_data.get("choices") or []
                                first_choice = choices[0] if choices else None
                                if isinstance(first_choice, dict):
                                    delta = first_choice.get("delta") or {}
                                    if isinstance(delta, dict) and delta.get("content"):
                                        full_response_content.append(delta["content"])
                                # 尝试提取 usage 信息（部分模型在最后一个 chunk 里带 usage）
                                usage = chunk_data.get("usage")
                                if isinstance(usage, dict):
                                    log_context["prompt_tokens"] = usage.get("prompt_tokens")
                                    log_context["completion_tokens"] = usage.get("completion_tokens")
                            except Exception:
                                pass
                        
                        # 按 SSE 标准格式转发：每行以 \n\n 结尾（一行一个事件）
                        yield line + b"\n\n"
                
                # buffer 尾部残留（上游最后一段不以 \n 结尾时）
                if buffer.strip():
                    decoded_tail = buffer.decode("utf-8", errors="replace").rstrip("\r\n")
                    if decoded_tail and decoded_tail.strip() != "data: [DONE]":
                        if decoded_tail.startswith("data: "):
                            try:
                                chunk_data = json.loads(decoded_tail[6:].strip())
                                choices = chunk_data.get("choices") or []
                                first_choice = choices[0] if choices else None
                                if isinstance(first_choice, dict):
                                    delta = first_choice.get("delta") or {}
                                    if isinstance(delta, dict) and delta.get("content"):
                                        full_response_content.append(delta["content"])
                                usage = chunk_data.get("usage")
                                if isinstance(usage, dict):
                                    log_context["prompt_tokens"] = usage.get("prompt_tokens")
                                    log_context["completion_tokens"] = usage.get("completion_tokens")
                            except Exception:
                                pass
                        yield buffer.rstrip(b"\r\n") + b"\n\n"
                    elif decoded_tail.strip() == "data: [DONE]":
                        received_done = True
                
                # 5. 合并完整响应内容
                response_content = "".join(full_response_content)
                log_context["response_content"] = response_content if response_content else None
                log_context["status"] = "success"
            
            # ---- 以下后处理在 async with 之外执行，不阻塞上游连接释放 ----
            
            # 6. 响应内容敏感词检测
            if settings.SENSITIVE_CHECK_ENABLED and response_content:
                try:
                    passed, response_sensitive_result = await sensitive_detector.check_and_log_sensitive(
                        content=response_content,
                        request_id=request_id,
                        api_key=api_key,
                        client_ip=client_ip,
                        content_type="response"
                    )
                    
                    if response_sensitive_result:
                        if sensitive_result:
                            merged = dict(sensitive_result)
                            merged["response_detection"] = response_sensitive_result
                            sensitive_result = merged
                        else:
                            sensitive_result = response_sensitive_result
                except Exception as det_err:
                    print(f"[流式] 响应敏感词检测失败: {det_err}")
            
            # 7. 序列化敏感词检测结果（必须在 yield [DONE] 之前写入 log_context）
            log_context["sensitive_result"] = json.dumps(sensitive_result, ensure_ascii=False) if sensitive_result else None
            
            # 8. 更新API密钥使用统计（含Token累计）
            try:
                pt = log_context["prompt_tokens"] or 0
                ct = log_context["completion_tokens"] or 0
                # 兜底估算：如果上游未返回 usage，基于字符数粗略估算
                # 中文约 1.5 字/token，英文约 4 字符/token，取中间值 ~2 字符/token
                if pt == 0 and ct == 0:
                    _prompt_text = log_context.get("prompt_content") or ""
                    _resp_text = log_context.get("response_content") or ""
                    pt = max(1, len(_prompt_text) // 2) if _prompt_text else 0
                    ct = max(1, len(_resp_text) // 2) if _resp_text else 0
                    log_context["prompt_tokens"] = pt
                    log_context["completion_tokens"] = ct
                await update_api_key_usage(api_key_info["id"], prompt_tokens=pt, completion_tokens=ct)
            except Exception as usage_err:
                print(f"[流式] 更新使用统计失败: {usage_err}")
            
            # 最后 yield [DONE]
            yield b"data: [DONE]\n\n"
        
        except HTTPException as e:
            # HTTPException（如密钥无效、权限不足等）直接透传，保留原始 detail
            error_msg = e.detail
            log_context["status"] = "failed"
            log_context["error_msg"] = error_msg
            print(f"[流式请求失败] key='{(api_key or '')[:12]}...' model='{request.model}' error={error_msg} code={e.status_code}")
            error_data = {"error": {"message": error_msg, "type": "auth_error", "code": e.status_code}}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"
        except Exception as e:
            error_msg = str(e)
            log_context["status"] = "failed"
            log_context["error_msg"] = error_msg
            error_data = {"error": {"message": f"请求处理失败: {error_msg}", "type": "server_error"}}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"
        
        finally:
            # 确保日志始终被记录（即使 generator 被 cancel）
            try:
                # 如果还有未合并的响应内容（generator 被 cancel 时 yield 后的代码可能没执行）
                if log_context["response_content"] is None and log_context["full_response_content"]:
                    log_context["response_content"] = "".join(log_context["full_response_content"]) or None
            except Exception:
                pass
            
            # 兜底：如果 sensitive_result 还没被设置（正常路径在 async with 内已设置），
            # 但 prompt 阶段已经检测到敏感词，用 prompt 阶段的结果
            if log_context["sensitive_result"] is None and log_context.get("sensitive_result_dict"):
                log_context["sensitive_result"] = json.dumps(
                    log_context["sensitive_result_dict"], ensure_ascii=False
                )
            
            # 用 fire-and-forget 方式写日志，不阻塞 generator 关闭
            async def _log_and_update():
                try:
                    await self.log_request(
                        request_id=log_context["request_id"],
                        api_key=log_context["api_key"],
                        user_name=log_context["user_name"],
                        client_ip=log_context["client_ip"],
                        llm_name=log_context["llm_name"],
                        prompt_content=log_context["prompt_content"],
                        response_content=log_context["response_content"],
                        prompt_tokens=log_context["prompt_tokens"],
                        completion_tokens=log_context["completion_tokens"],
                        status=log_context["status"],
                        sensitive_result=log_context["sensitive_result"],
                        error_msg=log_context["error_msg"]
                    )
                except Exception as log_err:
                    print(f"流式请求日志记录失败: {log_err}")
            
            try:
                # shield 防止 task 被取消
                task = asyncio.ensure_future(asyncio.shield(_log_and_update()))
                # 不 await task，让它后台运行
            except RuntimeError:
                # event loop 已关闭时忽略
                pass
    
    async def forward_to_llm(self, 
                            request: ChatCompletionRequest, 
                            llm_config: Dict[str, Any]) -> Dict[str, Any]:
        """转发请求到大模型API"""
        if not self.session:
            raise Exception("HTTP会话未初始化")
        
        try:
            # 构建请求头
            headers = {
                "Authorization": f"Bearer {llm_config['api_key']}",
                "Content-Type": "application/json"
            }
            
            # 构建请求体
            request_data = request.dict(exclude_none=True)
            
            # 构建完整的请求URL（自动拼接 /chat/completions）
            base_url = llm_config["api_url"].rstrip("/")
            if not base_url.endswith("/chat/completions"):
                forward_url = base_url + "/chat/completions"
            else:
                forward_url = base_url
            
            # 发送请求
            timeout = aiohttp.ClientTimeout(total=300)  # 5分钟超时
            async with self.session.post(
                forward_url,
                headers=headers,
                json=request_data,
                timeout=timeout
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"大模型API错误: {response.status} - {error_text}")
                
                response_data = await response.json()
                return response_data
                
        except asyncio.TimeoutError:
            raise Exception("大模型API请求超时")
        except Exception as e:
            raise Exception(f"转发请求失败: {e}")
    
    def extract_prompt_content(self, messages: List[Dict[str, Any]]) -> str:
        """
        从消息中提取提示词内容
        支持 OpenAI 标准格式：
        - 简单字符串: {"role": "user", "content": "你好"}
        - 多模态数组: {"role": "user", "content": [{"type": "text", "text": "你好"}, {"type": "image_url", ...}]}
        - null/空值: {"role": "assistant", "content": null} → 跳过
        """
        if not messages:
            return ""
        
        content_parts = []
        for message in messages:
            content = message.get("content")
            if not content:
                continue
            
            if isinstance(content, str):
                # 普通字符串
                if content.strip():
                    content_parts.append(content)
            elif isinstance(content, list):
                # 多模态格式: [{"type": "text", "text": "..."}, ...]
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text = part.get("text", "")
                            if text and text.strip():
                                content_parts.append(text)
                        # image_url 等非文本类型跳过
                    elif isinstance(part, str):
                        if part.strip():
                            content_parts.append(part)
            else:
                # 其他类型，尝试转字符串
                text = str(content)
                if text.strip():
                    content_parts.append(text)
        
        return "\n".join(content_parts)
    
    def extract_response_content(self, response_data: Dict[str, Any]) -> str:
        """从响应中提取内容"""
        if not response_data or "choices" not in response_data:
            return ""
        
        choices = response_data["choices"]
        if not choices:
            return ""
        
        content_parts = []
        for choice in choices:
            if "message" in choice and "content" in choice["message"]:
                content = choice["message"]["content"]
                if content:
                    content_parts.append(str(content))
        
        return "\n".join(content_parts)
    
    async def log_request(self,
                         request_id: str,
                         api_key: str,
                         user_name: Optional[str],
                         client_ip: str,
                         llm_name: str,
                         prompt_content: Optional[str],
                         response_content: Optional[str],
                         prompt_tokens: Optional[int],
                         completion_tokens: Optional[int],
                         status: str,
                         sensitive_result: Optional[str],
                         error_msg: Optional[str]):
        """记录请求日志"""
        try:
            # 截断过长的内容
            if prompt_content and len(prompt_content) > 10000:
                prompt_content = prompt_content[:10000] + "...[截断]"
            
            if response_content and len(response_content) > 10000:
                response_content = response_content[:10000] + "...[截断]"
            
            await db.execute(
                """
                INSERT INTO request_logs 
                (request_id, api_key, user_name, client_ip, llm_name, 
                 prompt_content, image_content, response_content, 
                 prompt_tokens, completion_tokens, status, sensitive_result, error_msg)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                """,
                request_id,
                api_key,
                user_name,
                client_ip,
                llm_name,
                prompt_content,
                None,  # image_content 暂时为None
                response_content,
                prompt_tokens,
                completion_tokens,
                status,
                sensitive_result,
                error_msg
            )
            
        except Exception as e:
            print(f"记录请求日志失败: {e}")
    
    async def close(self):
        """关闭服务"""
        if self.session:
            await self.session.close()


# 创建全局大模型服务实例
llm_service = LLMService()