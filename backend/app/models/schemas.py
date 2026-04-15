"""数据模型定义"""

from typing import List, Optional, Union
from pydantic import BaseModel, Field, field_validator


# ============ 请求模型 ============

class TripRequest(BaseModel):
    """旅行规划请求"""
    city: str = Field(..., description="目的地城市", example="北京")
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD", example="2025-06-01")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD", example="2025-06-03")
    travel_days: int = Field(..., description="旅行天数", ge=1, le=30, example=3)
    transportation: str = Field(..., description="交通方式", example="公共交通")
    accommodation: str = Field(..., description="住宿偏好", example="经济型酒店")
    preferences: List[str] = Field(default=[], description="旅行偏好标签", example=["历史文化", "美食"])
    free_text_input: Optional[str] = Field(default="", description="额外要求", example="希望多安排一些博物馆")
    
    class Config:
        json_schema_extra = {
            "example": {
                "city": "北京",
                "start_date": "2025-06-01",
                "end_date": "2025-06-03",
                "travel_days": 3,
                "transportation": "公共交通",
                "accommodation": "经济型酒店",
                "preferences": ["历史文化", "美食"],
                "free_text_input": "希望多安排一些博物馆"
            }
        }


class POISearchRequest(BaseModel):
    """POI搜索请求"""
    keywords: str = Field(..., description="搜索关键词", example="故宫")
    city: str = Field(..., description="城市", example="北京")
    citylimit: bool = Field(default=True, description="是否限制在城市范围内")


class RouteRequest(BaseModel):
    """路线规划请求"""
    origin_address: str = Field(..., description="起点地址", example="北京市朝阳区阜通东大街6号")
    destination_address: str = Field(..., description="终点地址", example="北京市海淀区上地十街10号")
    origin_city: Optional[str] = Field(default=None, description="起点城市")
    destination_city: Optional[str] = Field(default=None, description="终点城市")
    route_type: str = Field(default="walking", description="路线类型: walking/driving/transit")


class DbStationSearchRequest(BaseModel):
    """德铁站点查询请求"""
    query: str = Field(..., description="站点关键词", example="Berlin Hbf")
    limit: int = Field(default=10, ge=1, le=50, description="返回数量")
    language: str = Field(default="de", description="语言")


class DbTripQueryRequest(BaseModel):
    """德铁车次查询请求（出发地->目的地）"""
    origin: str = Field(..., description="出发地站点关键词", example="Frankfurt Hbf")
    destination: str = Field(..., description="目的地站点关键词", example="Berlin Hbf")
    date: str = Field(..., description="日期 YYMMDD", example="260402")
    hour: str = Field(..., description="小时 HH", example="14")
    language: str = Field(default="de", description="语言")


class TravelPlanRequest(BaseModel):
    """Google Places 旅行规划请求"""
    location: str = Field(..., description="模糊地点/国家/城市", example="法国")
    days: int = Field(default=3, ge=1, le=15, description="旅行天数", example=3)
    preferences: Optional[str] = Field(default="博物馆/美食/预算中等", description="偏好说明", example="博物馆/美食/预算中等")


# ============ 响应模型 ============

class Location(BaseModel):
    """地理位置"""
    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")


class Attraction(BaseModel):
    """景点信息"""
    name: str = Field(..., description="景点名称")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    visit_duration: int = Field(..., description="建议游览时间(分钟)")
    description: str = Field(..., description="景点描述")
    category: Optional[str] = Field(default="景点", description="景点类别")
    rating: Optional[float] = Field(default=None, description="评分")
    photos: Optional[List[str]] = Field(default_factory=list, description="景点图片URL列表")
    poi_id: Optional[str] = Field(default="", description="POI ID")
    mapbox_id: Optional[str] = Field(default="", description="Mapbox feature ID")
    image_url: Optional[str] = Field(default=None, description="图片URL")
    ticket_price: int = Field(default=0, description="门票价格(元)")


class Meal(BaseModel):
    """餐饮信息"""
    type: str = Field(..., description="餐饮类型: breakfast/lunch/dinner/snack")
    name: str = Field(..., description="餐饮名称")
    address: Optional[str] = Field(default=None, description="地址")
    location: Optional[Location] = Field(default=None, description="经纬度坐标")
    description: Optional[str] = Field(default=None, description="描述")
    estimated_cost: int = Field(default=0, description="预估费用(元)")


class Hotel(BaseModel):
    """酒店信息"""
    name: str = Field(..., description="酒店名称")
    address: str = Field(default="", description="酒店地址")
    location: Optional[Location] = Field(default=None, description="酒店位置")
    price_range: str = Field(default="", description="价格范围")
    rating: str = Field(default="", description="评分")
    distance: str = Field(default="", description="距离景点距离")
    type: str = Field(default="", description="酒店类型")
    estimated_cost: int = Field(default=0, description="预估费用(元/晚)")


class DayPlan(BaseModel):
    """单日行程"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_index: int = Field(..., description="第几天(从0开始)")
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    accommodation: str = Field(..., description="住宿")
    hotel: Optional[Hotel] = Field(default=None, description="推荐酒店")
    attractions: List[Attraction] = Field(default=[], description="景点列表")
    meals: List[Meal] = Field(default=[], description="餐饮列表")


class WeatherInfo(BaseModel):
    """天气信息"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_weather: str = Field(default="", description="白天天气")
    night_weather: str = Field(default="", description="夜间天气")
    day_temp: Union[int, str] = Field(default=0, description="白天温度")
    night_temp: Union[int, str] = Field(default=0, description="夜间温度")
    wind_direction: str = Field(default="", description="风向")
    wind_power: str = Field(default="", description="风力")

    @field_validator('day_temp', 'night_temp', mode='before')
    @classmethod
    def parse_temperature(cls, v):
        """解析温度,移除°C等单位"""
        if isinstance(v, str):
            # 移除°C, ℃等单位符号
            v = v.replace('°C', '').replace('℃', '').replace('°', '').strip()
            try:
                return int(v)
            except ValueError:
                return 0
        return v


class Budget(BaseModel):
    """预算信息"""
    total_attractions: int = Field(default=0, description="景点门票总费用")
    total_hotels: int = Field(default=0, description="酒店总费用")
    total_meals: int = Field(default=0, description="餐饮总费用")
    total_transportation: int = Field(default=0, description="交通总费用")
    total: int = Field(default=0, description="总费用")


class TripPlan(BaseModel):
    """旅行计划"""
    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: List[DayPlan] = Field(..., description="每日行程")
    weather_info: List[WeatherInfo] = Field(default=[], description="天气信息")
    overall_suggestions: str = Field(..., description="总体建议")
    budget: Optional[Budget] = Field(default=None, description="预算信息")


class TripPlanResponse(BaseModel):
    """旅行计划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[TripPlan] = Field(default=None, description="旅行计划数据")


class POIInfo(BaseModel):
    """POI信息"""
    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="名称")
    type: str = Field(..., description="类型")
    address: str = Field(..., description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: Optional[str] = Field(default=None, description="电话")
    mapbox_id: Optional[str] = Field(default="", description="Mapbox feature ID")


class POISearchResponse(BaseModel):
    """POI搜索响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[POIInfo] = Field(default=[], description="POI列表")


class RouteInfo(BaseModel):
    """路线信息"""
    distance: float = Field(..., description="距离(米)")
    duration: int = Field(..., description="时间(秒)")
    route_type: str = Field(..., description="路线类型")
    description: str = Field(..., description="路线描述")


class RouteResponse(BaseModel):
    """路线规划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: Optional[RouteInfo] = Field(default=None, description="路线信息")


class WeatherResponse(BaseModel):
    """天气查询响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[WeatherInfo] = Field(default=[], description="天气信息")


class DbStation(BaseModel):
    """德铁站点信息"""
    id: str = Field(default="", description="站点ID")
    name: str = Field(default="", description="站点名")
    type: str = Field(default="", description="类型")
    latitude: Optional[float] = Field(default=None, description="纬度")
    longitude: Optional[float] = Field(default=None, description="经度")
    distance: Optional[int] = Field(default=None, description="距离(米)")


class DbTrip(BaseModel):
    """德铁车次信息（出发地->目的地）"""
    train_name: str = Field(default="", description="车次")
    origin: str = Field(default="", description="出发站")
    destination: str = Field(default="", description="目的站")
    departure_time: str = Field(default="", description="出发时间")
    arrival_time: str = Field(default="", description="到达时间")
    platform: str = Field(default="", description="站台")
    status: str = Field(default="", description="状态")


class DbStationSearchResponse(BaseModel):
    """德铁站点查询响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[DbStation] = Field(default=[], description="站点列表")


class DbTripQueryResponse(BaseModel):
    """德铁车次查询响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: List[DbTrip] = Field(default=[], description="车次列表")


class DbNlqRequest(BaseModel):
    """自然语言查询请求"""
    query: str = Field(..., description="用户自然语言提问", example="帮我查 2026-04-02 14点 Frankfurt Hbf 到 Berlin Hbf 的车次")


class DbNlqResponse(BaseModel):
    """自然语言查询响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    parsed: Optional[DbTripQueryRequest] = Field(default=None, description="解析出的结构化查询")
    data: List[DbTrip] = Field(default=[], description="车次列表")
    policy_version: Optional[str] = Field(default=None, description="服务端策略版本")


class TravelPlanAttraction(BaseModel):
    """旅行规划景点（前端渲染友好）"""
    name: str = Field(..., description="景点名")
    lat: float = Field(..., description="纬度")
    lng: float = Field(..., description="经度")
    route_desc: str = Field(default="", description="路线描述")
    formatted_address: str = Field(default="", description="格式化地址")
    rating: Optional[float] = Field(default=None, description="评分")
    editorial_summary: Optional[str] = Field(default=None, description="编辑摘要")
    place_id: Optional[str] = Field(default=None, description="地点ID")
    ticket_price: float = Field(default=0, description="门票价格")


class TravelPlanMeal(BaseModel):
    """单日餐饮项"""
    type: str = Field(..., description="餐饮类型: breakfast/lunch/dinner/snack")
    name: str = Field(..., description="名称")
    time: str = Field(..., description="时间段")
    description: str = Field(..., description="描述")
    route_desc: str = Field(..., description="交通描述")
    estimated_cost: float = Field(default=0, description="预估费用")
    address: Optional[str] = Field(default=None, description="地址")
    latitude: Optional[float] = Field(default=None, description="纬度")
    longitude: Optional[float] = Field(default=None, description="经度")


class TravelPlanActivity(BaseModel):
    """单日活动项"""
    name: str = Field(..., description="名称")
    time: str = Field(..., description="时间段")
    description: str = Field(..., description="描述")
    route_desc: str = Field(..., description="交通描述")
    estimated_cost: float = Field(..., description="预估费用")
    ticket_price: float = Field(default=0, description="门票价格")
    address: Optional[str] = Field(default=None, description="地址")
    latitude: Optional[float] = Field(default=None, description="纬度")
    longitude: Optional[float] = Field(default=None, description="经度")


class TravelPlanDay(BaseModel):
    """每日行程"""
    day: int = Field(..., description="第几天（从1开始")
    title: str = Field(..., description="当天标题")
    route_summary: str = Field(..., description="当天路线摘要")
    activities: List[TravelPlanActivity] = Field(default_factory=list, description="活动列表")
    meals: List[TravelPlanMeal] = Field(default_factory=list, description="餐饮列表")


class TravelPlanBudget(BaseModel):
    """预算估算"""
    transport: int = Field(..., description="交通预算")
    tickets: int = Field(..., description="门票预算")
    food: int = Field(..., description="餐饮预算")
    total: int = Field(..., description="总预算")
    currency: str = Field(default="EUR", description="货币")


class TravelPlanData(BaseModel):
    """结构化旅行规划结果"""
    location: str
    days: int
    attractions: List[TravelPlanAttraction]
    itinerary: List[TravelPlanDay]
    total_budget: TravelPlanBudget
    tips: List[str]
    warnings: List[str] = Field(default_factory=list)


class TravelPlanResponseV2(BaseModel):
    """Google Places 旅行规划响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="消息")
    data: TravelPlanData


# ============ 错误响应 ============

class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = Field(default=False, description="是否成功")
    message: str = Field(..., description="错误消息")
    error_code: Optional[str] = Field(default=None, description="错误代码")

