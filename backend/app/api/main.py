"""FastAPI主应用"""

import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ..config import get_settings, validate_config, print_config
from ..tools.debug_trace import set_debug_trace
from .routes import poi, map as map_routes, transport, xiaohongshu, travel_plan

# Ensure UTF-8 output on Windows so hello_agents debug logs (emoji) won't crash.
# This needs to run before any MCPTool initialization or emoji printing.
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    # If sys.stdout doesn't support reconfigure, we'll just continue.
    pass

# 获取配置
settings = get_settings()
set_debug_trace(getattr(settings, "debug_mapbox", False) or os.getenv("DEBUG_TRACE", "").lower() in ("1", "true", "yes"))

# 创建FastAPI应用（Swagger/OpenAPI）
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    summary="智能旅行规划 + 地图检索 + 德铁查询 + 小红书内容增强",
    description=(
        "基于 HelloAgents 的智能旅行规划后端。\n\n"
        "## 调试建议\n"
        "- 优先通过 `/api/travel-plan` 验证端到端旅行规划链路\n"
        "- 使用 `/map/*` 验证 POI 搜索与路径规划\n"
        "- 使用 `/transport/db/nlq` 验证自然语言德铁查询\n"
        "- 当前版本支持通过配置接入第三方小红书 MCP 服务，增强景点候选召回\n\n"
        "## 响应约定\n"
        "- 业务成功通常返回 `success=true`\n"
        "- 服务异常返回 HTTP 5xx，并在 `detail` 中携带错误信息"
    ),
    contact={"name": "HelloAgents Trip Planner"},
    license_info={"name": "MIT"},
    openapi_tags=[
        {"name": "旅行规划", "description": "核心行程规划入口"},
        {"name": "地图服务", "description": "POI 搜索、天气查询（Amap模式）与路线规划"},
        {"name": "交通服务", "description": "德铁自然语言查询与健康检查"},
        {"name": "POI", "description": "POI 详情、关键词搜索、景点图片查询"},
        {"name": "小红书", "description": "小红书 MCP 代理接口（search_feeds / get_feed_detail）"},
    ],
    docs_url="/docs",
    redoc_url="/redoc",
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(poi.router, prefix="/api")
app.include_router(map_routes.router, prefix="/api")
app.include_router(transport.router, prefix="/api")
app.include_router(xiaohongshu.router, prefix="/api")
app.include_router(travel_plan.router, prefix="/api")


@app.on_event("startup")
async def startup_event():
    """应用启动事件"""
    print("\n" + "="*60)
    print(f"🚀 {settings.app_name} v{settings.app_version}")
    print("="*60)
    
    # 打印配置信息
    print_config()
    
    # 验证配置
    try:
        validate_config()
        print("\n✅ 配置验证通过")
    except ValueError as e:
        print(f"\n❌ 配置验证失败:\n{e}")
        print("\n请检查.env文件并确保所有必要的配置项都已设置")
        raise
    
    print("\n" + "="*60)
    print("📚 API文档: http://localhost:8000/docs")
    print("📖 ReDoc文档: http://localhost:8000/redoc")
    print("="*60 + "\n")


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭事件"""
    print("\n" + "="*60)
    print("👋 应用正在关闭...")
    print("="*60 + "\n")


@app.get(
    "/",
    summary="服务根信息",
    description="返回服务名称、版本以及文档入口地址。",
)
async def root():
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get(
    "/health",
    summary="全局健康检查",
    description="用于探活与部署后的可用性检查。",
)
async def health():
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=True
    )

