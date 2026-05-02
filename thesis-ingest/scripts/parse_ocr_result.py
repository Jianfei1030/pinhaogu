#!/usr/bin/env python3
"""
OCR 结果结构化脚本
从 OCR 纯文本中提取题材名和成分股列表
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


def extract_thesis_name(text: str) -> str:
    """提取题材名称"""
    # 尝试匹配 "AI硬件" 或 "Al硬件" (OCR 误差)
    patterns = [
        r'AI\s*硬件',
        r'Al\s*硬件',  # OCR 常见误差：I -> l
        r'A\s*I\s*硬件',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            # 标准化为 "AI硬件"
            return "AI硬件"
    
    # 如果没找到，尝试从第一行提取
    lines = text.strip().split('\n')
    for line in lines[:5]:
        if '硬件' in line or '题材' in line:
            # 清理并返回
            cleaned = re.sub(r'[^A-Za-z\u4e00-\u9fa5]', '', line)
            if cleaned:
                return cleaned
    
    return "未知题材"


def extract_stocks(text: str) -> list[dict]:
    """提取成分股列表"""
    stocks = []
    seen = set()
    
    # 定义分类标记（用于区分分类名和股票名）
    category_markers = {
        'CPO', '光模块', 'LPO', '其他', 'LPU', 'CPU', '供货海外', 'BSS',
        '算力芯片', '芯片', '推理芯片', 'UQD', '液态金属', '冷却液',
        '液冷相关', '设备厂商', '服务器', '交换机', 'PCB设备', 'PCB产品',
        'PCB', '电子布', 'HVLP铜箔', 'PE', 'HVDC', 'TBS', '电源类',
        '机架电源', '数据中心', '铜缆', 'AGP', '自有产品', '股权相关',
        '态态压', '态压',  # OCR 噪声
    }
    
    # 常见非股票词汇（动词、形容词、量词等）
    non_stock_words = {
        # 动词/形容词
        '随着', '快速', '发展', '超过', '需求', '增长', '查看', '更新', '创建',
        '涉及', '仅供', '来自', '增长', '显示', '查看', '更新', '全文',
        # 名词（非股票）
        '硬件', '全球', '算力', '年复', '数据', '网络', '公共', '信息',
        '资讯', '内容', '免责', '声明', '个股', '行情', '小表', '本文',
        # OCR 噪声词
        '大模型的', '大模型', '模型的', '合增长', '算力年', '力年复',
        '算力年复', '快速发展', '的快速', '速发展', '大模',
        # 时间/数量词
        '创建', '更新',
    }
    
    # 已知股票名列表（用于验证提取结果）
    known_stocks = {
        '福晶科技', '腾景科技', '中际旭创', '剑桥科技', '长飞光纤', '汇绿生态',
        '华工科技', '永卓股份', '航锦科技', '罗博特科', '东田微', '致尚科技',
        '青山纸业', '海得控制', '江波龙', '旋极信息', '智微智能', '星宕科技',
        '国光电器', '中国长城', '海光信息', '澜起科技', '龙芯中科', '怡亚通',
        '综艺股份', '宏昌电子', '通富微电', '中电港', '北京君正', '新特电气',
        '泰永长征', '深圳燃气', '佛焕能源', '寒武纪', '国科微', '景嘉微',
        '摩尔线程', '复旦微电', '首都在线', '云天励飞', '工业富联', '英维克',
        '瑞可达', '溯联股份', '回天新材', '东阳光', '新宙邦', '永太科技',
        '统一股份', '巨化股份', '冰轮环境', '润泽科技', '申萎环境', '康盛股份',
        '佳力图', '烽火通信', '川润股份', '浪潮信息', '紫光股份', '中科曙光',
        '中兴通讯', '光迅科技', '光库科技', '英唐智控', '炬光科技', '凌云光',
        '芯动联科', '沪电股份', '共进股份', '锐捷网络', '光华科技', '三孕新科',
        '大族数控', '中钨高新', '日联科技', '深南电路', '金安国纪', '生益电子',
        '科翔股份', '威尔高', '宏和科技', '国际复材', '中国巨石', '菲利华',
        '北自科技', '泰豪科技', '科泰电源', '滩迪重机', '风形股份', '苏美达',
        '神驰机电', '四方股份', '科士达', '圣阳股份', '科华数据', '欧陆通',
        '九洲集团', '航天长峰', '盛弘股份', '英威腾', '环旭电子', '电科数字',
        '朗威股份', '动力源', '中富电路', '新雷能', '中恒电气', '南都电源',
        '江海股份', '麦格米特', '华脉科技', '优刻得', '奥飞数据', '光环新网',
        '顺钠股份', '宁波建工', '铜牛信息', '三变科技', '彩讯股份', '川环科技',
        '广安爱众', '正泰电器', '宝信软件', '明阳智能', '深南电A', '特瑞斯',
        '新亚电子', '宝胜股份', '神宇股份', '云路股份', '并行科技',
    }
    
    lines = text.split('\n')
    
    for line in lines:
        # 跳过明显不是股票的行
        if any(skip in line for skip in ['免责声明', '我说两句', '查看全文', '创建', '更新', 'VPN', 'GRAF']):
            continue
        
        # 提取中文词（2-4个汉字）
        matches = re.findall(r'[\u4e00-\u9fa5]{2,4}', line)
        
        for name in matches:
            # 长度过滤
            if len(name) < 2 or len(name) > 4:
                continue
            # 排除分类名
            if name in category_markers:
                continue
            # 排除非股票词
            if name in non_stock_words:
                continue
            # 额外检查：排除以"的"结尾或包含"发展"、"增长"等的词
            if name.endswith('的') or '发展' in name or '增长' in name or '快速' in name:
                continue
            # 排除纯数字+中文混合
            if re.match(r'^[0-9\-]+$', name):
                continue
            
            # 添加到结果（去重）
            if name not in seen:
                seen.add(name)
                stocks.append({
                    "code": "",  # OCR 不包含代码，后续通过名称查询
                    "name": name,
                    "verified": name in known_stocks  # 标记是否为已知股票
                })
    
    return stocks


def parse_ocr_file(input_path: Path) -> dict:
    """解析 OCR 文件"""
    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()
    
    thesis_name = extract_thesis_name(text)
    stocks = extract_stocks(text)
    
    return {
        "thesis_name": thesis_name,
        "stocks": stocks,
        "source_file": str(input_path.name),
        "parse_time": datetime.now().isoformat()
    }


def main():
    parser = argparse.ArgumentParser(description='OCR 结果结构化脚本')
    parser.add_argument('--ocr-output', required=True, help='OCR 输出文件路径')
    parser.add_argument('--output-dir', default='output', help='输出目录')
    args = parser.parse_args()
    
    input_path = Path(args.ocr_output)
    if not input_path.exists():
        print(f"错误：文件不存在 - {input_path}")
        return 1
    
    # 解析
    result = parse_ocr_file(input_path)
    
    # 输出目录处理：使用输入文件的父目录作为输出目录
    output_dir = input_path.parent
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_file = output_dir / f'ocr_structured_{timestamp}.json'
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"解析完成:")
    print(f"  题材名称: {result['thesis_name']}")
    print(f"  成分股数量: {len(result['stocks'])}")
    print(f"  已验证股票: {sum(1 for s in result['stocks'] if s.get('verified'))}")
    print(f"  输出文件: {output_file}")
    
    # 显示前 10 只股票
    print(f"\n前 10 只成分股:")
    for stock in result['stocks'][:10]:
        status = "✓" if stock.get('verified') else "?"
        print(f"  {status} {stock['name']}")
    
    return 0


if __name__ == '__main__':
    exit(main())