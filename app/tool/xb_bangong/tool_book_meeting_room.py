import asyncio
import json
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

from httpx import AsyncClient
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langgraph.types import interrupt
from langgraph.prebuilt import ToolRuntime
from ...core.config import settings
from ...core.logger import app_logger as logger
from ...context.chat_context import ChatContext
from ..abstract_tool import AbstractTool
from ...db_connection_pool.zb_node_prompt_util import _default_cache
from ..util.interrupt_message import InterruptMessage
from ..util.resume_message import ResumeMessage

# Mock 数据开关（生产环境设为 False）
USE_MOCK_DATA = True
MOCK_DATA_PATH = Path(__file__).parent.parent.parent.parent / "tests" / "mock_meeting_room_data.json"

def load_mock_data():
    """加载 mock 数据"""
    if MOCK_DATA_PATH.exists():
        with open(MOCK_DATA_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


# ========== 参数 Schema ==========

class BookMeetingRoomArgs(BaseModel):
    """预订会议室的参数"""
    meeting_room_name: str = Field(title="会议室名称", description="预订的会议室名称（从 get_meeting_room_available_time_periods 返回的 name 字段获取）")
    begintime: str = Field(title="开始时间", description="预订开始时间，格式为 %Y-%m-%d %H:%M:%S")
    endtime: str = Field(title="结束时间", description="预订结束时间，格式为 %Y-%m-%d %H:%M:%S")


class GetMeetingRoomAvailableTimePeriodsArgs(BaseModel):
    """查询会议室可用时间段的参数"""
    begintime: str = Field(default=None, title="查询开始时间", description="查询开始时间，格式为 %Y-%m-%d %H:%M:%S")
    endtime: str = Field(default=None, title="查询结束时间", description="查询结束时间，格式为 %Y-%m-%d %H:%M:%S")


# ========== 工具函数 ==========

@tool(args_schema=BookMeetingRoomArgs, description="预订指定的会议室（需人工确认）", return_direct=True)
async def book_meeting_room(
    meeting_room_name: str,
    begintime: str,
    endtime: str,
    run_time: ToolRuntime[ChatContext],
) -> str:
    """预订会议室 — 需人工确认，工具内部自行 interrupt"""
    # 从 run_time 获取 ChatContext
    context: ChatContext = run_time.context
    user_name = context.user_name if context and context.user_name else "未知用户"

    # 会议室主题
    meetingtitle = f"{user_name}预订的会议室"

    logger.info(f"[会议室预订] 预订会议室: {meeting_room_name} 预订人:{user_name}")

    # 校验5001会议室不可预订
    if "5001" in meeting_room_name:
        logger.warning(f"[会议室预订] {meeting_room_name}会议室不可预订，预订人: {user_name}")
        return f"预订失败：{meeting_room_name}不开放预订，请选择其他会议室。"

    # 校验预订时间
    try:
        begin_dt = datetime.strptime(begintime, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(endtime, "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        logger.error(f"[会议室预订] 时间格式解析错误: {e}")
        return f"预订失败：时间格式错误，请使用正确的格式（%Y-%m-%d %H:%M:%S）。"

    # 校验开始和结束时间不能早于当前时间
    china_tz = timezone(timedelta(hours=8))
    now_dt = datetime.now(china_tz)
    # 为解析的时间添加时区信息
    begin_dt = begin_dt.replace(tzinfo=china_tz)
    end_dt = end_dt.replace(tzinfo=china_tz)

    if begin_dt < now_dt:
        logger.warning(f"[会议室预订] 开始时间早于当前时间，会议室: {meeting_room_name}，开始时间: {begintime}，当前时间: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        return f"预订失败：开始时间不能早于当前时间。"
    if end_dt < now_dt:
        logger.warning(f"[会议室预订] 结束时间早于当前时间，会议室: {meeting_room_name}，结束时间: {endtime}，当前时间: {now_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        return f"预订失败：结束时间不能早于当前时间。"

    # 校验开始时间和结束时间必须在同一天
    if begin_dt.date() != end_dt.date():
        logger.warning(f"[会议室预订] 预订时间跨天，会议室: {meeting_room_name}，开始日期: {begin_dt.date()}，结束日期: {end_dt.date()}")
        return f"预订失败：预订时间必须在同一天内，不能跨天预订。"

    # 校验预订时长不能超过1小时
    duration_minutes = (end_dt - begin_dt).total_seconds() / 60
    if duration_minutes > 60:
        logger.warning(f"[会议室预订] 预订时长超过1小时，会议室: {meeting_room_name}，时长: {duration_minutes}分钟")
        return f"预订失败：预订时长不能超过1小时，当前时长为{int(duration_minutes)}分钟。"

    interrupt_msg = f"以下是您要预定的会议室信息：\n- 会议室：{meeting_room_name}\n- 开始时间：{begintime}\n- 结束时间：{endtime}\n- 预订人：{user_name}\n\n确认要预定吗？"
    interrupt_message = InterruptMessage(
        interrupt_bisiness_type="book_meeting_room",
        interrupt_message=interrupt_msg,
        extra_info={}
    )
    resume_value = interrupt(interrupt_message.to_json_str())
    logger.info(f"[会议室预订] interrupt 中断信息 interrupt_message: {interrupt_message}")

    # 使用 ResumeMessage 解析用户恢复输入
    resume_message: ResumeMessage = ResumeMessage.from_json_str(resume_value)
    if not resume_message.resume_business_type:
        resume_message.resume_business_type = interrupt_message.interrupt_bisiness_type
    logger.info(f"[会议室预订] resume 恢复信息 resume_message: {resume_message}")

    # 检查用户是否确认
    if resume_message.resume_message != '确认':
        logger.info(f"[会议室预订] 用户取消预订，会议室: {meeting_room_name}，预订人: {user_name}，回复: {resume_message.resume_message}")
        return f"用户 {user_name} 取消预定。"

    # 用户确认后，调用API预订
    # 开始时间加1秒，跳过历史数据中已被预定的时刻
    begintime_adjusted = add_one_second(begintime)
    # 截止时间减1秒，避免与下一时段的会议室重叠
    endtime_adjusted = subtract_one_second(endtime)
    logger.info(f"[会议室预订] 时间调整 | 原开始时间={begintime}, 调整后={begintime_adjusted}, 原结束时间={endtime}, 调整后={endtime_adjusted}")
    param = {
        "meetingroom": meeting_room_name,
        "meetingtitle": meetingtitle,
        "begintime": begintime_adjusted,
        "endtime": endtime_adjusted,
        "username": user_name
    }

    # 使用 Mock 数据
    if USE_MOCK_DATA:
        mock_data = load_mock_data()
        if mock_data and "reserve_success" in mock_data:
            logger.info(f"[会议室预订] 使用 Mock 数据，会议室: {meeting_room_name}")
            return f"已成功预订会议室（会议室名称: {meeting_room_name}）。"

    final_msg = ""
    try:
        async with AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f'http://{settings.AIGC_WQ_DOMAIN}/aigc-wq/api/reserveMeetingRoom',
                json=param
            )
            if response.status_code != 200:
                logger.error(f"[会议室预订] HTTP请求失败，状态码: {response.status_code}，会议室: {meeting_room_name}")
                return f"预订会议室失败（会议室名称: {meeting_room_name}），接口返回异常。"

            resp_data = json.loads(response.text)
            code = resp_data.get("code", "")

            if code == "10000":
                logger.info(f"[会议室预订] 预订成功，会议室: {meeting_room_name}，预订人:{user_name}，会议主题:{meetingtitle}")
                return f"已成功预订会议室（会议室名称: {meeting_room_name}）。"
            else:
                result = resp_data.get("msg", "未知错误")
                logger.error(f"[会议室预订] 预订失败，原因:{result}，会议室: {meeting_room_name}，预订人:{user_name}，会议主题:{meetingtitle}")
                return f"预订会议室失败（会议室名称: {meeting_room_name}），失败原因:{result}。"
    except Exception as e:
        logger.error(f"[会议室预订] 调用接口异常，原因:{str(e)}，会议室: {meeting_room_name}，预订人:{user_name}，会议主题:{meetingtitle}")
        return f"调用预订会议室接口异常：{str(e)}"
    finally:
        context.set_business_state_completed()

@tool(args_schema=GetMeetingRoomAvailableTimePeriodsArgs, description="查询指定时间段内会议室的可用（空闲）时间段，便于用户选择合适的预订时间")
async def get_meeting_room_available_time_periods(
    begintime: str = None,
    endtime: str = None,
    run_time: ToolRuntime[ChatContext] = None,
) -> str:
    """查询会议室可用时间段 — 安全操作，直接执行"""

    # 使用 Mock 数据
    if USE_MOCK_DATA:
        mock_data = load_mock_data()
        if mock_data and "query_result" in mock_data:
            logger.info("[会议室查询] 使用 Mock 数据")
            query_result = mock_data["query_result"]
            # mock 数据已经包含处理好的 rooms 和 availableTimePeriod
            result_json = json.dumps([query_result], ensure_ascii=False)
            return f"查询时间段：{query_result['timePeriod']}\n会议室可用时间段：{result_json}"

    async def query_single_day(client: AsyncClient, day_begin: str, day_end: str) -> tuple:
        """查询单日会议室预订数据（原始数据，后续会计算可用时间段）"""
        # 去除首尾空格
        day_begin = day_begin.strip()
        day_end = day_end.strip()
        logger.info(f"[会议室查询] 正在查询API，时间范围: {day_begin} 至 {day_end}")
        param = {"begintime": day_begin, "endtime": day_end}
        response = await client.post(
            f'http://{settings.AIGC_WQ_DOMAIN}/aigc-wq/api/queryMeetingRoom',
            json=param
        )
        if response.status_code != 200:
            logger.error(f"[会议室查询] HTTP请求失败，状态码: {response.status_code}，时间范围: {day_begin} 至 {day_end}")
            return day_begin, day_end, []
        resp_data = json.loads(response.text)
        logger.info(f"[会议室查询] API返回成功，时间范围: {day_begin} 至 {day_end}，返回数据条数: {len(resp_data.get('result', []))}")
        return day_begin, day_end, resp_data.get("result", [])

    def calculate_available_periods(query_begin: str, query_end: str, booked_periods: list) -> list:
        """
        根据查询时间范围和已预订时间段，计算可用时间段

        Args:
            query_begin: 查询开始时间
            query_end: 查询结束时间
            booked_periods: 已预订时间段列表，每个元素包含 begintime 和 endtime

        Returns:
            可用时间段列表，每个元素为 {"begintime": str, "endtime": str}
        """
        try:
            query_begin_dt = datetime.strptime(query_begin, "%Y-%m-%d %H:%M:%S")
            query_end_dt = datetime.strptime(query_end, "%Y-%m-%d %H:%M:%S")
        except ValueError as e:
            logger.error(f"[会议室查询] 时间格式解析错误: {e}")
            return []

        # 解析并排序已预订时间段
        booked = []
        for p in booked_periods:
            try:
                begin_str = normalize_time(p.get("begintime", ""))
                end_str = normalize_time(p.get("endtime", ""))
                begin = datetime.strptime(begin_str, "%Y-%m-%d %H:%M:%S")
                end = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")
                booked.append((begin, end))
            except (ValueError, AttributeError) as e:
                logger.warning(f"[会议室查询] 跳过无效的预订时间段: {p}, 错误: {e}")
                continue
        booked.sort(key=lambda x: x[0])

        # 计算可用时间段
        available = []
        current = query_begin_dt

        for book_begin, book_end in booked:
            # 跳过不在查询范围内或已结束的预订
            if book_end <= current or book_begin >= query_end_dt:
                continue

            # 如果预订开始时间在当前时间之后，则中间有空档
            if book_begin > current:
                available.append({
                    "begintime": current.strftime("%H:%M:%S"),
                    "endtime": book_begin.strftime("%H:%M:%S")
                })

            # 更新当前时间为预订结束时间
            current = max(current, book_end)

        # 检查最后是否有空档
        if current < query_end_dt:
            available.append({
                "begintime": current.strftime("%H:%M:%S"),
                "endtime": query_end_dt.strftime("%H:%M:%S")
            })

        return available

    # 调用查询会议室API接口
    try:
        # 获取当前时间
        now = get_current_time()
        now_dt = datetime.strptime(now, "%Y-%m-%d %H:%M:%S")
        logger.info(f"[会议室查询] 用户查询可用会议室，入参时间范围: {begintime} 至 {endtime}")

        if not begintime and not endtime:
            # 无时间参数时的默认查询范围
            if now_dt.hour >= 20:
                # 当前时间已过20点，查明天、后天（共2天）
                tomorrow = now_dt.date() + timedelta(days=1)
                begintime = tomorrow.strftime("%Y-%m-%d 08:00:00")
                endtime = (tomorrow + timedelta(days=1)).strftime("%Y-%m-%d 20:00:00")
            else:
                # 查今天、明天、后天（共3天）
                begintime = now
                endtime = add_days(now, 2)  # 获取后天日期
                endtime = endtime.split(" ")[0] + " 20:00:00"  # 设置为后天20:00

        begin_dt = datetime.strptime(begintime, "%Y-%m-%d %H:%M:%S")
        end_dt = datetime.strptime(endtime, "%Y-%m-%d %H:%M:%S")

        logger.info(f"[会议室查询] 用户查询可用会议室，处理后时间范围: {begintime} 至 {endtime}")

        # 判断查询结束时间是否早于当前时间
        if end_dt <= now_dt:
            return "错误：查询的时间段不能早于当前时间。"

        if end_dt <= begin_dt:
            return "错误：结束时间必须晚于开始时间。"

        # 校验：跨日期查询最多10天
        days_diff = (end_dt.date() - begin_dt.date()).days + 1
        if days_diff > 10:
            return "错误：查询日期跨度不能超过10天，请缩小查询范围。"

        # 按天拆分并发查询（单日时循环一次）
        queries = []
        current_date = begin_dt.date()
        end_date = end_dt.date()

        async with AsyncClient(timeout=30.0) as client:
            while current_date <= end_date:
                if current_date == begin_dt.date():
                    # 第一天：从begintime到当天20:00（或endtime）
                    day_begin = begintime
                    day_end = current_date.strftime("%Y-%m-%d 20:00:00")
                    # 如果是单日查询，使用实际的endtime
                    if current_date == end_date:
                        day_end = endtime
                elif current_date == end_date:
                    # 最后一天：从08:00到endtime
                    day_begin = current_date.strftime("%Y-%m-%d 08:00:00")
                    day_end = endtime
                else:
                    # 中间天：08:00-20:00
                    day_begin = current_date.strftime("%Y-%m-%d 08:00:00")
                    day_end = current_date.strftime("%Y-%m-%d 20:00:00")

                queries.append(query_single_day(client, day_begin, day_end))
                current_date += timedelta(days=1)

            # 并发执行所有查询
            results = await asyncio.gather(*queries)

        # 按天列出结果，并计算每个会议室的可用时间段
        all_results = []
        for day_begin, day_end, room_list in results:
            processed_rooms = []
            for room in room_list:
                # 复制会议室信息（保留原始数据）
                room_info = dict(room)
                # 计算可用时间段
                booked_periods = room.get("bookedTimePeriod", [])
                available_periods = calculate_available_periods(day_begin, day_end, booked_periods)
                room_info["availableTimePeriod"] = available_periods
                processed_rooms.append(room_info)

            day_result = {
                "timePeriod": f"{day_begin} 至 {day_end}",
                "rooms": processed_rooms
            }
            all_results.append(day_result)

        # 按日期升序排序
        all_results.sort(key=lambda x: x["timePeriod"].split(" 至 ")[0])

        # 返回查询结果（统一返回按天分组的数组格式）
        result_json = json.dumps(all_results, ensure_ascii=False)
        logger.info(f"[会议室查询] 查询结果，时间范围: {begintime} 至 {endtime}，返回数据: {result_json}")
        return f"查询时间段：{begintime} 至 {endtime}\n会议室可用时间段：{result_json}"

    except Exception as e:
        logger.error(f"[会议室查询] 执行查询会议室工具出现错误: {traceback.format_exc()}")
        return f"执行查询会议室工具出现错误：{e}"


class ToolBookMeetingRoom(AbstractTool):
    def __init__(self):
        """初始化基本属性，设置node_id"""
        super().__init__(node_id="tool_meeting_room")

    async def _initialize_tool(self, context: ChatContext = None) -> None:
        """初始化工具，设置 prompt_tool_call 和工具列表"""
        logger.info(f"[会议室预订工具] 初始化工具，当前用户: {context.user_id}")
        self.tool = [get_meeting_room_available_time_periods, book_meeting_room]
        self.use_checkpointer = True
        self.user_parallel_tool_call = False
         # 系统提示词 - 新版 create_agent 通过 bind_tools() 将工具信息传递给模型
        # 不需要在提示词中包含 {tools} 占位符
        #获取提示词
        result = await _default_cache.format_prompt("tool_meeting_room", "prompt_tool_call",
                                                    {"node_name": self.node.node_name, "user_name": context.user_name, "current_time": get_current_time()})


        self.prompt_tool_call = result


    async def _get_prompt_friendly_response(self, context: ChatContext = None) -> str:
        """获取友好回应提示词"""
        logger.info(f"[会议室预订工具] 获取友好回应提示词，当前用户: {context.user_id}")
        #获取友好回应提示词
        prompt_content = await _default_cache.format_prompt("tool_meeting_room", "prompt_friendly_response",
                                                    {"node_name": self.node.node_name})
        return prompt_content

    async def _build_intent_analysis_prompt(self, context: ChatContext = None) -> str:
        """构建意图分析的 system prompt（针对会议室预订场景定制）"""
        logger.info(f"[会议室预订工具] 构建意图分析提示词，当前用户: {context.user_id}")
        # 获取意图识别提示词
        prompt_content = await _default_cache.format_prompt("tool_meeting_room", "prompt_intent_analysis",
                                                            {"INTENT_CONTINUE_BUSINESS": self.INTENT_CONTINUE_BUSINESS,"INTENT_FRIENDLY_RESPONSE":self.INTENT_FRIENDLY_RESPONSE,"INTENT_END_BUSINESS":self.INTENT_END_BUSINESS,"INTENT_CHANGE_TOPIC":self.INTENT_CHANGE_TOPIC})
        return prompt_content


def normalize_time(time_str: str) -> str:
    """规范化时间字符串：去空格，补全秒数"""
    if not time_str:
        return ""
    time_str = time_str.strip()
    # 如果格式为 "YYYY-MM-DD HH:MM"，补全秒数为 ":00"
    if len(time_str) == 16:  # "2026-04-15 16:00" 长度为16
        time_str += ":00"
    return time_str

def get_current_time():
    """获取当前时间，给模型注入时间用"""
    china_tz = timezone(timedelta(hours=8))
    current_time = datetime.now(china_tz).strftime('%Y-%m-%d %H:%M:%S')
    return current_time

def add_days(time_str: str, days: int = 1) -> str:
    """对日期时间字符串加N天"""
    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    dt_new = dt + timedelta(days=days)
    return dt_new.strftime("%Y-%m-%d %H:%M:%S")

def get_morning_time(time_str: str) -> str:
    """获取当天 08:00:00"""
    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d 08:00:00")

def get_evening_time(time_str: str) -> str:
    """获取当天 20:00:00"""
    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d 20:00:00")

def subtract_one_second(time_str: str) -> str:
    """
    将时间字符串减1秒，但20:00:00不减

    Args:
        time_str: 格式为 'YYYY-MM-DD %H:%M:%S' 的字符串

    Returns:
        减1秒后的时间字符串，格式为 'YYYY-MM-DD %H:%M:%S'
        如果结束时间是20:00:00，则保持不变
    """
    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    # 20:00:00 不需要减1秒
    if dt.hour == 20 and dt.minute == 0 and dt.second == 0:
        return time_str
    dt_new = dt - timedelta(seconds=0)
    return dt_new.strftime("%Y-%m-%d %H:%M:%S")

def add_one_second(time_str: str) -> str:
    """
    将时间字符串加1秒，但8:00:00不加（工作日开始时间）

    Args:
        time_str: 格式为 'YYYY-MM-DD %H:%M:%S' 的字符串

    Returns:
        加1秒后的时间字符串，格式为 'YYYY-MM-DD %H:%M:%S'
        如果开始时间是8:00:00，则保持不变
    """
    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    # 8:00:00 不需要加1秒（工作日开始时间）
    if dt.hour == 8 and dt.minute == 0 and dt.second == 0:
        return time_str
    dt_new = dt + timedelta(seconds=0)
    return dt_new.strftime("%Y-%m-%d %H:%M:%S")