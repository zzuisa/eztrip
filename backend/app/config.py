"""配置管理模块"""

import os
from pathlib import Path
from typing import List
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# 加载环境变量
# 优先加载当前 backend/.env，再兼容历史 HelloAgents/.env
backend_env = Path(__file__).resolve().parents[2] / ".env"
if backend_env.exists():
    load_dotenv(backend_env, override=False)
else:
    load_dotenv()

helloagents_env = Path(__file__).parent.parent.parent.parent / "HelloAgents" / ".env"
if helloagents_env.exists():
    load_dotenv(helloagents_env, override=False)


class Settings(BaseSettings):
    """应用配置"""

    # 应用基本配置
    app_name: str
    app_version: str
    debug: bool

    # 服务器配置
    host: str
    port: int

    # CORS配置 - 使用字符串,在代码中分割
    cors_origins: str

    # 地图与空间服务
    map_provider: str
    amap_api_key: str | None
    mapbox_access_token: str | None
    debug_mapbox: bool
    debug_trip_map_only: bool
    debug_attraction_map: bool

    # Unsplash API配置
    unsplash_access_key: str | None
    unsplash_secret_key: str | None

    # Deutsche Bahn API配置
    enable_db_feature: bool
    db_api_base_url: str
    db_api_key: str | None
    db_client_id: str | None
    db_client_secret: str | None
    db_timeout_seconds: int
    db_use_bearer_auth: bool
    enable_db_mcp: bool
    db_mcp_sse_url: str | None
    debug_db: bool

    # 小红书 MCP (HTTP) 配置
    enable_xiaohongshu_mcp: bool
    xiaohongshu_mcp_base_url: str
    xiaohongshu_mcp_timeout_seconds: int
    debug_xiaohongshu: bool

    # Google Places API
    google_places_api_key: str
    google_places_base_url: str
    google_places_timeout_seconds: int
    debug_google_places_full_key: bool = False

    # LLM配置（SiliconFlow）
    siliconflow_api_key: str
    siliconflow_base_url: str
    llm_model_deepseek_v32: str
    llm_model_deepseek_r1: str

    # 日志配置
    log_level: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # 忽略额外的环境变量

    def get_cors_origins_list(self) -> List[str]:
        """获取CORS origins列表"""
        return [origin.strip() for origin in self.cors_origins.split(',') if origin.strip()]


# 创建全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取配置实例"""
    return settings


# 验证必要的配置
def validate_config():
    """验证配置是否完整"""
    errors = []
    warnings = []

    if (settings.map_provider or "amap").lower() == "mapbox":
        if not settings.mapbox_access_token:
            errors.append("MAPBOX_ACCESS_TOKEN未配置 (map_provider=mapbox)")
    else:
        if not settings.amap_api_key:
            errors.append("AMAP_API_KEY未配置")

    if not settings.siliconflow_api_key:
        warnings.append("SILICONFLOW_API_KEY未配置,LLM功能可能无法使用")

    if settings.enable_db_feature:
        if not settings.db_api_base_url:
            errors.append("ENABLE_DB_FEATURE=true 时必须配置 DB_API_BASE_URL")
        if settings.db_use_bearer_auth and not (
            settings.db_api_key or (settings.db_client_id and settings.db_client_secret)
        ):
            errors.append(
                "DB_USE_BEARER_AUTH=true 时必须配置 DB_API_KEY 或 DB_CLIENT_ID/DB_CLIENT_SECRET"
            )
    if settings.enable_db_mcp and not settings.db_mcp_sse_url:
        errors.append("ENABLE_DB_MCP=true 时必须配置 DB_MCP_SSE_URL")

    if errors:
        error_msg = "配置错误:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ValueError(error_msg)

    if warnings:
        print("\n⚠️  配置警告:")
        for w in warnings:
            print(f"  - {w}")

    return True


# 打印配置信息(用于调试)
def print_config():
    """打印当前配置(隐藏敏感信息)"""
    print(f"应用名称: {settings.app_name}")
    print(f"版本: {settings.app_version}")
    print(f"服务器: {settings.host}:{settings.port}")
    print(f"地图提供商: {settings.map_provider}")
    print(f"高德地图API Key: {'已配置' if settings.amap_api_key else '未配置'}")
    print(f"Mapbox Token: {'已配置' if settings.mapbox_access_token else '未配置'}")
    print(f"DEBUG_MAPBOX: {settings.debug_mapbox}")

    # 检查LLM配置
    print(f"LLM API Key: {'已配置' if settings.siliconflow_api_key else '未配置'}")
    print(f"LLM Base URL: {settings.siliconflow_base_url}")
    print(f"LLM Model V3.2: {settings.llm_model_deepseek_v32}")
    print(f"LLM Model R1: {settings.llm_model_deepseek_r1}")
    print(f"DB Feature: {'启用' if settings.enable_db_feature else '未启用'}")
    print(f"DB API Base URL: {settings.db_api_base_url}")
    print(f"DB API Auth: {'已配置' if (settings.db_api_key or settings.db_client_id) else '未配置'}")
    print(f"DB MCP: {'启用' if settings.enable_db_mcp else '未启用'}")
    print(f"DB MCP URL: {settings.db_mcp_sse_url if settings.db_mcp_sse_url else '未配置'}")
    print(f"DB Debug: {'启用' if settings.debug_db else '未启用'}")
    print(f"Google Places Full Key Debug: {'启用' if settings.debug_google_places_full_key else '未启用'}")
    print(f"日志级别: {settings.log_level}")

