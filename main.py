from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import json
import os
import random
import datetime
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any

@register("fun_utilities", "AstrBot_User", "包含群聊签到、每日运势、随机决策等功能的实用工具集", "1.0.0")
class FunUtilities(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.data_dir = Path("data")
        self.data_file = self.data_dir / "plugin_data.json"
        self.data: Dict[str, Any] = {
            "signin": {},
            "fortune": {}
        }
        self.lock = asyncio.Lock()
        
    async def initialize(self):
        """插件初始化，加载数据"""
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
        
        if self.data_file.exists():
            try:
                async with self.lock:
                    # 使用 run_in_executor 避免阻塞主线程
                    loop = asyncio.get_running_loop()
                    content = await loop.run_in_executor(None, self.data_file.read_text, "utf-8")
                    self.data = json.loads(content)
            except Exception as e:
                logger.error(f"加载数据失败: {e}")
                # 如果加载失败，保持默认空数据
        else:
            await self._save_data()
            
    async def _save_data(self):
        """保存数据到文件"""
        try:
            async with self.lock:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: self.data_file.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"))
        except Exception as e:
            logger.error(f"保存数据失败: {e}")

    # ==================== 签到功能 ====================
    
    @filter.command("签到")
    async def signin(self, event: AstrMessageEvent):
        """每日签到，获取积分"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        today = datetime.date.today().isoformat()
        
        signin_data = self.data.get("signin", {})
        user_data = signin_data.get(user_id, {
            "total_days": 0,
            "continuous_days": 0,
            "last_signin_date": "",
            "points": 0,
            "name": user_name
        })
        
        # 检查是否已签到
        if user_data["last_signin_date"] == today:
            yield event.plain_result(f"📅 {user_name}，你今天已经签到过了哦！明天再来吧~")
            return

        # 计算连续签到
        last_date_str = user_data["last_signin_date"]
        if last_date_str:
            last_date = datetime.date.fromisoformat(last_date_str)
            if (datetime.date.today() - last_date).days == 1:
                user_data["continuous_days"] += 1
            else:
                user_data["continuous_days"] = 1
        else:
            user_data["continuous_days"] = 1
            
        # 计算积分
        base_points = 10
        bonus_points = min(user_data["continuous_days"], 10) # 连续签到奖励上限10分
        total_points_gained = base_points + bonus_points
        
        # 更新数据
        user_data["total_days"] += 1
        user_data["last_signin_date"] = today
        user_data["points"] += total_points_gained
        user_data["name"] = user_name # 更新昵称
        
        signin_data[user_id] = user_data
        self.data["signin"] = signin_data
        await self._save_data()
        
        yield event.plain_result(
            f"✅ 签到成功！\n"
            f"👤 用户：{user_name}\n"
            f"📅 连续签到：{user_data['continuous_days']} 天\n"
            f"💰 获得积分：{total_points_gained} (基础{base_points} + 连签{bonus_points})\n"
            f"💎 当前总积分：{user_data['points']}"
        )

    @filter.command("签到排行")
    async def signin_rank(self, event: AstrMessageEvent):
        """查看签到排行榜"""
        signin_data = self.data.get("signin", {})
        if not signin_data:
            yield event.plain_result("📊 暂时还没有人签到哦，快来抢沙发吧！")
            return
            
        # 按积分排序
        sorted_users = sorted(signin_data.items(), key=lambda x: x[1]["points"], reverse=True)
        top_10 = sorted_users[:10]
        
        msg = ["🏆 签到积分排行榜 TOP 10 🏆", ""]
        for idx, (uid, data) in enumerate(top_10, 1):
            icon = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            msg.append(f"{icon} {data['name']}: {data['points']} 分 (连签 {data['continuous_days']} 天)")
            
        yield event.plain_result("\n".join(msg))

    # ==================== 运势功能 ====================

    @filter.command("运势")
    async def fortune(self, event: AstrMessageEvent):
        """查看今日运势，支持 @他人"""
        target_user_id = event.get_sender_id()
        target_user_name = event.get_sender_name()
        
        # 检查是否有 @mention
        message_chain = event.get_messages()
        for msg in message_chain:
            # 尝试检测 At 组件
            # 注意：这里依赖 AstrBot 的具体实现，通常 At 组件会有 qq 或 user_id 属性
            if type(msg).__name__ == "At": 
                if hasattr(msg, 'qq'):
                    target_user_id = str(msg.qq)
                    target_user_name = f"用户({target_user_id})" # 暂时无法获取对方昵称，使用ID代替
                elif hasattr(msg, 'user_id'):
                    target_user_id = str(msg.user_id)
                    target_user_name = f"用户({target_user_id})"
                break

        today = datetime.date.today().isoformat()
        fortune_data = self.data.get("fortune", {})
        
        # 检查该用户今日是否已生成运势
        user_fortune = fortune_data.get(target_user_id)
        
        if not user_fortune or user_fortune["date"] != today:
            # 生成新运势
            # 使用 日期 + 用户ID 作为随机种子，保证同一天同一人结果一致
            seed_str = f"{today}-{target_user_id}"
            r = random.Random(seed_str)
            
            love = r.randint(0, 100)
            wealth = r.randint(0, 100)
            career = r.randint(0, 100)
            lucky_index = int((love + wealth + career) / 3)
            
            quotes = [
                "今天是充满希望的一天！",
                "宜：代码，忌：摸鱼。",
                "好运正在向你奔来。",
                "相信自己，你就是最棒的！",
                "今天的努力是明天的铺垫。",
                "保持微笑，运气不会差。",
                "记得喝水，保持健康。",
                "代码一次过，Bug 远离我。",
                "出门可能会遇到小惊喜哦。",
                "适合学习新知识的一天。"
            ]
            quote = r.choice(quotes)
            
            user_fortune = {
                "date": today,
                "love": love,
                "wealth": wealth,
                "career": career,
                "lucky_index": lucky_index,
                "quote": quote
            }
            
            # 保存数据
            fortune_data[target_user_id] = user_fortune
            self.data["fortune"] = fortune_data
            await self._save_data()
        
        # 格式化输出
        msg = [
            f"🔮 {target_user_name} 的今日运势 🔮",
            f"📅 日期：{today}",
            "",
            f"❤️ 爱情运：{self._render_bar(user_fortune['love'])} {user_fortune['love']}",
            f"💰 财运：　{self._render_bar(user_fortune['wealth'])} {user_fortune['wealth']}",
            f"💼 事业运：{self._render_bar(user_fortune['career'])} {user_fortune['career']}",
            "",
            f"🍀 综合幸运指数：{user_fortune['lucky_index']}",
            f"📝 今日寄语：{user_fortune['quote']}"
        ]
        
        yield event.plain_result("\n".join(msg))

    def _render_bar(self, value: int, length: int = 10) -> str:
        """生成进度条"""
        filled = int(value / 100 * length)
        return "█" * filled + "░" * (length - filled)

    # ==================== 随机决策功能 ====================

    @filter.command("选择")
    async def choose(self, event: AstrMessageEvent):
        """帮我选：/选择 选项1 选项2 ..."""
        msg_str = event.message_str.replace("/选择", "").strip()
        if not msg_str:
            yield event.plain_result("❓ 请输入选项，用空格分隔。例如：/选择 吃饭 睡觉 打豆豆")
            return
            
        # 支持空格或逗号分隔
        options = [opt.strip() for opt in msg_str.replace(",", " ").split() if opt.strip()]
        
        if len(options) < 2:
            yield event.plain_result("❓ 至少需要两个选项才能帮你做决定哦！")
            return
            
        choice = random.choice(options)
        yield event.plain_result(f"🤔 经过深思熟虑，我建议你选择：\n✨ {choice} ✨")

    @filter.command("抽签")
    async def draw_lots(self, event: AstrMessageEvent):
        """随机抽签"""
        lots = [
            {"result": "大吉", "desc": "万事皆宜，心想事成！"},
            {"result": "中吉", "desc": "运势不错，继续努力。"},
            {"result": "小吉", "desc": "小有收获，知足常乐。"},
            {"result": "吉", "desc": "平平安安，顺顺利利。"},
            {"result": "末吉", "desc": "否极泰来，静待花开。"},
            {"result": "凶", "desc": "诸事不宜，谨慎行事。"},
            {"result": "大凶", "desc": "今日不宜出门，在家躺平。"},
        ]
        # 加权随机，大凶概率低一点
        weights = [10, 20, 25, 25, 10, 8, 2]
        lot = random.choices(lots, weights=weights, k=1)[0]
        
        user_name = event.get_sender_name()
        yield event.plain_result(f"🏷️ {user_name} 的抽签结果：\n\n【{lot['result']}】\n{lot['desc']}")

    @filter.command("roll")
    async def roll_dice(self, event: AstrMessageEvent):
        """掷骰子：/roll [最大值]"""
        msg_str = event.message_str.replace("/roll", "").strip()
        max_val = 100
        
        if msg_str.isdigit():
            max_val = int(msg_str)
            if max_val <= 0:
                yield event.plain_result("❓ 最大值必须大于 0")
                return
        
        result = random.randint(1, max_val)
        yield event.plain_result(f"🎲 掷骰子 (1-{max_val}) 结果：\n\n👉 {result}")

    async def terminate(self):
        """插件卸载时保存数据"""
        await self._save_data()
