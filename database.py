"""
AI大模型API网关 - 数据库模块
"""
import asyncio
from typing import Optional
from datetime import datetime

import asyncpg
from asyncpg.pool import Pool
from fastapi import HTTPException

from config import settings


class Database:
    """数据库连接池管理"""
    
    def __init__(self):
        self.pool: Optional[Pool] = None
    
    async def connect(self):
        """连接到数据库"""
        try:
            self.pool = await asyncpg.create_pool(
                dsn=settings.DATABASE_URL,
                min_size=5,
                max_size=20,
                command_timeout=60
            )
            print(f"成功连接到数据库: {settings.DATABASE_URL}")
            
            # 初始化数据库表
            await self.init_tables()
            
        except Exception as e:
            print(f"数据库连接失败: {e}")
            raise
    
    async def disconnect(self):
        """断开数据库连接"""
        if self.pool:
            await self.pool.close()
    
    async def init_tables(self):
        """初始化数据库表"""
        try:
            async with self.pool.acquire() as conn:
                # 创建管理员表
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS admin (
                        id SERIAL PRIMARY KEY,
                        username VARCHAR(50) NOT NULL UNIQUE,
                        password VARCHAR(255) NOT NULL,
                        create_time TIMESTAMP DEFAULT NOW()
                    )
                ''')
                
                # 创建大模型配置表
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS llm_config (
                        id SERIAL PRIMARY KEY,
                        llm_name VARCHAR(50) NOT NULL,
                        api_url VARCHAR(255) NOT NULL,
                        api_key VARCHAR(255) NOT NULL,
                        status INT DEFAULT 1,
                        create_time TIMESTAMP DEFAULT NOW()
                    )
                ''')
                
                # 创建API密钥表
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS api_key (
                        id SERIAL PRIMARY KEY,
                        key_value VARCHAR(100) NOT NULL UNIQUE,
                        user_name VARCHAR(50),
                        llm_ids INT[],
                        rate_limit INT DEFAULT 10,
                        daily_limit INT DEFAULT 1000,
                        monthly_limit INT DEFAULT 30000,
                        expire_time TIMESTAMP,
                        ip_whitelist TEXT[],
                        status INT DEFAULT 1,
                        create_time TIMESTAMP DEFAULT NOW(),
                        last_use_time TIMESTAMP,
                        total_requests INT DEFAULT 0,
                        daily_requests INT DEFAULT 0,
                        monthly_requests INT DEFAULT 0
                    )
                ''')
                
                # 创建敏感词表
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS sensitive_words (
                        id SERIAL PRIMARY KEY,
                        word VARCHAR(100) NOT NULL UNIQUE,
                        type VARCHAR(20),
                        create_time TIMESTAMP DEFAULT NOW()
                    )
                ''')
                
                # 创建请求日志表
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS request_logs (
                        id SERIAL PRIMARY KEY,
                        request_id UUID NOT NULL UNIQUE,
                        api_key VARCHAR(100) NOT NULL,
                        user_name VARCHAR(50),
                        request_time TIMESTAMP DEFAULT NOW(),
                        client_ip VARCHAR(50),
                        llm_name VARCHAR(50),
                        prompt_content TEXT,
                        image_content TEXT,
                        response_content TEXT,
                        prompt_tokens INT,
                        completion_tokens INT,
                        status VARCHAR(20),
                        sensitive_result TEXT,
                        error_msg TEXT
                    )
                ''')
                
                # 创建请求日志索引
                await conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_request_logs_time 
                    ON request_logs(request_time DESC)
                ''')
                await conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_request_logs_api_key 
                    ON request_logs(api_key)
                ''')
                await conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_request_logs_status 
                    ON request_logs(status)
                ''')
                
                print("数据库表初始化完成")
                
        except Exception as e:
            print(f"数据库表初始化失败: {e}")
            raise
    
    async def execute(self, query: str, *args):
        """执行SQL查询"""
        async with self.pool.acquire() as conn:
            return await conn.execute(query, *args)
    
    async def fetch(self, query: str, *args):
        """执行SQL查询并返回结果"""
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)
    
    async def fetchrow(self, query: str, *args):
        """执行SQL查询并返回单行结果"""
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    async def fetchval(self, query: str, *args):
        """执行SQL查询并返回单个值"""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)


# 创建全局数据库实例
db = Database()