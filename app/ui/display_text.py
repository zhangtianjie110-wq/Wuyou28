from __future__ import annotations

import re


STATUS_TEXT = {
    "RUNNING": "运行中",
    "STOPPED": "已停止",
    "ONLINE": "在线",
    "OFFLINE": "离线",
    "PASS": "正常",
    "FAIL": "异常",
    "WARNING": "警告",
    "PENDING": "等待处理",
    "HASH_OK": "校验正常",
    "HASH_FAIL": "校验异常",
    "HASH_MISMATCH": "校验不一致",
    "FRESH": "数据最新",
    "STALE": "数据已过期",
    "UNAVAILABLE": "暂不可用",
    "NOT_FOUND": "未找到",
    "COMPLETE": "完整",
    "PARTIAL": "不完整",
    "MISSING": "缺失",
    "INVALID_SAMPLE": "无效样本",
    "INSUFFICIENT_SAMPLE": "样本不足",
    "SAMPLE_LOW": "样本偏少",
    "SAMPLE_MEDIUM": "样本一般",
    "RESEARCH_ONLY": "研究中",
    "CANDIDATE": "候选策略",
    "FORWARD_TEST": "前向验证",
    "VERIFIED": "已验证",
    "REJECTED": "已淘汰",
    "LOCAL_V2": "本地V2",
    "FROZEN_VERIFIED": "已冻结验证",
    "MATCH": "一致",
    "MISMATCH": "不一致",
    "YES": "是",
    "NO": "否",
    "ERROR": "错误",
    "HEALTHY": "正常",
    "WAITING_DRAW": "等待开奖",
    "DRAWN": "已开奖",
    "SETTLED": "已结算",
    "INGESTED": "已导入",
    "MISSING_OUTCOME": "缺少开奖结果",
    "DATA_GAP": "数据缺口",
    "NOT_REQUIRED": "无需依赖",
    "HIT": "命中",
    "MISS": "未命中",
    "NONE": "无",
    "TRAIN": "训练",
    "VALIDATION": "验证",
    "TEST": "测试",
    "READY": "已生成",
    "NOT_TRIGGERED": "未触发",
    "WAITING_DATA": "等待当期数据",
    "INVALID_INPUT": "数据无效",
    "MISSED_FORWARD": "错过前向预测",
    "FORWARD": "正式前向",
    "RECONSTRUCTED": "历史重建",
    "VIP100_LOCAL_V2": "正式前向",
    "DYNAMIC_COLLAPSE_WARNING": "动态选择退化警告",
    "SKIP_AFFECTED_TIE": "受影响并列时跳过",
    "FIXED_COMBINATION_ORDER": "固定组合顺序",
    "R1_R2": "最低两项",
    "R3_R4": "最高两项",
    "R1_R3": "最低项 + 第三项",
    "R1_R4": "最低项 + 最高项",
    "R2_R3": "第二项 + 第三项",
    "R2_R4": "第二项 + 最高项",
    "EUCLIDEAN": "欧氏距离",
    "MANHATTAN": "曼哈顿距离",
    "RAW_DISTRIBUTION": "原始四组比例",
    "RANK_DISTRIBUTION": "排名结构比例",
    "EQUAL": "历史样本等权",
    "RECENCY_DECAY": "相似度与时间衰减",
    "OBSERVATION": "观察中",
    "SIMILAR": "相似状态",
    "REPLAY": "历史回放",
    "HISTORICALLY_SIMILAR": "存在历史相似状态",
    "INSUFFICIENT_HISTORICAL_SIMILARITY": "当前状态历史相似样本不足",
    "RECENT_STRENGTHENING": "近期增强",
    "BASICALLY_STABLE": "基本稳定",
    "RECENT_WEAKENING": "近期减弱",
    "STRONG": "较强",
    "MODERATE": "一般",
    "WEAK": "较弱",
    "LOW": "较低",
    "HIGH": "较高",
    "NORMAL": "普通",
    "RECENT_100": "最近100期分层",
    "RECENT_200": "最近200期分层",
    "RECENT_500": "最近500期分层",
    "WILSON_LOWER": "置信下界分层",
    "ACCURACY_STABILITY": "命中率与稳定性分层",
    "MULTI_WINDOW_CONSISTENCY": "多窗口一致性分层",
    "TRAIN_AGREEMENT_NORMALIZED": "训练期群组归一化",
    "HIGHEST_TWO": "最高两组",
    "LOWEST_TWO": "最低两组",
    "HIGHEST_LOWEST": "最高组与最低组",
    "FINAL_CANDIDATE": "最终候选",
    "TESTED": "已完成测试",
}


DISPLAY_NAMES = {
    "StrategyResearchEngine": "策略研究引擎",
    "Strategy Engine": "策略研究引擎",
    "Strategy DB": "策略数据库",
    "YU28 producer": "YU28 数据生产服务",
    "VIP100 production": "VIP100 生产服务",
    "VIP100 validation": "VIP100 校验服务",
    "8787 UI": "8787 界面服务",
    "HASH异常": "算法校验异常",
    "Strategy DB读取状态": "策略数据库读取状态",
}


def display_status(value: object, default: str = "—") -> str:
    if value is None or value == "":
        return default
    text = str(value)
    return STATUS_TEXT.get(text, text)


def display_name(value: object, default: str = "—") -> str:
    if value is None or value == "":
        return default
    text = str(value)
    return DISPLAY_NAMES.get(text, display_status(text, default))


def display_message(value: object, default: str = "—") -> str:
    if value is None or value == "":
        return default
    text = str(value)
    for source, target in sorted(DISPLAY_NAMES.items(), key=lambda item: -len(item[0])):
        text = text.replace(source, target)
    for source, target in sorted(STATUS_TEXT.items(), key=lambda item: -len(item[0])):
        text = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])",
            target,
            text,
        )
    return text
