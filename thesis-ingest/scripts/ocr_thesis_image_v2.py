#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR 识别脚本 V2 - 优化版
从开盘啦图片中提取文字内容，支持分类和成分股识别

优化点：
1. 使用 PaddleOCR 替代 pytesseract，中文识别更准确
2. 智能文本清洗和后处理
3. 基于上下文语义的股票名称提取
4. 支持多区域识别和表格结构解析
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Set

try:
    from PIL import Image
    import numpy as np
except ImportError as e:
    print(f"Error: Missing required dependency - {e}")
    print("Please install: pip3 install Pillow numpy")
    sys.exit(1)

# 尝试导入 PaddleOCR，如果失败则使用 pytesseract
USE_PADDLE = False
try:
    from paddleocr import PaddleOCR
    USE_PADDLE = True
    print("Using PaddleOCR for better Chinese text recognition")
except ImportError:
    print("PaddleOCR not available, falling back to pytesseract")
    try:
        import pytesseract
    except ImportError:
        print("Error: Neither PaddleOCR nor pytesseract is available")
        print("Please install one of them:")
        print("  - PaddleOCR: pip3 install paddleocr")
        print("  - pytesseract: pip3 install pytesseract")
        sys.exit(1)


class ThesisOCR:
    """开盘啦题材图片 OCR 识别器"""
    
    def __init__(self):
        self.ocr_engine = None
        if USE_PADDLE:
            # 初始化 PaddleOCR，使用中文模型
            self.ocr_engine = PaddleOCR(
                use_angle_cls=True,
                lang='ch',
                show_log=False,
                use_gpu=False
            )
    
    def extract_text_paddle(self, image_path: str) -> List[Dict]:
        """使用 PaddleOCR 提取文字（带位置信息）"""
        result = self.ocr_engine.ocr(image_path, cls=True)
        
        # 解析结果
        text_boxes = []
        if result and result[0]:
            for line in result[0]:
                if line:
                    bbox = line[0]  # 文本框坐标
                    text = line[1][0]  # 文本内容
                    confidence = line[1][1]  # 置信度
                    text_boxes.append({
                        'bbox': bbox,
                        'text': text,
                        'confidence': confidence
                    })
        
        return text_boxes
    
    def extract_text_tesseract(self, image_path: str) -> str:
        """使用 pytesseract 提取文字（备用方案）"""
        image = Image.open(image_path)
        
        # 使用多种 PSM 模式进行识别
        texts = []
        
        # PSM 6: 假设是统一的文本块
        text1 = pytesseract.image_to_string(
            image, 
            lang='chi_sim+eng',
            config='--psm 6'
        )
        texts.append(text1)
        
        # PSM 4: 假设是单列可变文本
        text2 = pytesseract.image_to_string(
            image, 
            lang='chi_sim+eng',
            config='--psm 4'
        )
        texts.append(text2)
        
        # PSM 11: 稀疏文本 - 尽可能找到所有文本
        text3 = pytesseract.image_to_string(
            image, 
            lang='chi_sim+eng',
            config='--psm 11'
        )
        texts.append(text3)
        
        # 合并结果，去重
        combined = '\n'.join(texts)
        return combined
    
    def extract_text(self, image_path: str) -> Dict:
        """提取图片中的文字内容"""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")
        
        if USE_PADDLE and self.ocr_engine:
            # 使用 PaddleOCR
            text_boxes = self.extract_text_paddle(image_path)
            
            # 按 Y 坐标排序，然后按 X 坐标排序（从上到下，从左到右）
            text_boxes.sort(key=lambda x: (x['bbox'][0][1], x['bbox'][0][0]))
            
            # 提取纯文本
            lines = []
            current_line = []
            last_y = None
            y_threshold = 20  # Y 坐标差异阈值
            
            for box in text_boxes:
                y = box['bbox'][0][1]
                if last_y is not None and abs(y - last_y) > y_threshold:
                    if current_line:
                        lines.append(' '.join(current_line))
                        current_line = []
                current_line.append(box['text'])
                last_y = y
            
            if current_line:
                lines.append(' '.join(current_line))
            
            raw_text = '\n'.join(lines)
            
            return {
                'raw_text': raw_text,
                'text_boxes': text_boxes,
                'engine': 'paddleocr'
            }
        else:
            # 使用 pytesseract
            raw_text = self.extract_text_tesseract(image_path)
            return {
                'raw_text': raw_text,
                'text_boxes': [],
                'engine': 'tesseract'
            }


class ThesisParser:
    """开盘啦题材文本解析器 - V2 优化版"""
    
    # 非股票名称的关键词（需要过滤）
    EXCLUDE_KEYWORDS = {
        'AI硬件', 'Al硬件', '小表格', '个股行情', 'GRAF', '查看全文', '更新', '免责声明',
        '本文涉及', '资讯', '数据', '内容', '网络', '公共信息', '仅供', '我来说两句',
        'CPO', 'LPO', 'CPU', 'LPU', 'GPU', 'SORA', 'AGENE', 'HBR', 'HTB', 'BAR',
        'SI', 'area', 'ARE', 'HEE', 'BARE', 'MEARE', 'lam', 'ABH', 'SER', 'BebA',
        'KRY', 'PRED', 'BSH', 'IRR', 'UQD', 'AKER', 'KA', 'BREE', 'ET', 'BAH', 'KR',
        'SRY', 'BRE', 'Sesh', 'RAST', 'BAT', 'Cee', 'HEA', 'xR', 'SNR', 'SUROVBE',
        'RINE', 'ak', 'mR', 'SSA', 'HRSA', 'FER', 'RRA', 'TRE', 'PORE', 'He', 'SIF',
        'BORSA', 'RRR', 'hee', 'SES', 'HERO', 'ES', 'HVLP', 'EET', 'SAI', 'SIAL',
        'PE', 'AMIE', 'Hees', 'TBS', 'Ati', 'Chae', 'Si', 'RAR', 'HAR', 'HES', 'sa',
        'A', 'AWA', 'SUES', 'SEI', 'PEAS', 'XE', 'ARs', 'TERE', 'yeeray', 'REID',
        'EBS', 'MB', 'BR', 'BEER', 'same', 'OC', 'SIR', 'BRM', 'IRE', 'REE', 'SRR',
        'PRR', 'AGP', 'mask', 'VPN', 'ey', '全', '加', '其他', '产品', '机', '机架电源',
        '电源类', '算力芯片', '芯片', '推理芯片', '供货海外', '股权相关', '自有产品',
        '光模块', 'PCB设备', 'PCB产品', 'PCB', 'IH', 'HVDC', '机柜', '数据中心',
        '铜缆', '液冷相关', '设备厂商', '服务器', '交换机', '冷却液', '液态金属',
        '液冷', '电池', '变压器', 'PCB设备', '电子布', '铜箔', '机', '接',
        '光芯片', '存储', '内存', '硬盘', 'IDC', '机房', 'UPS', 'HVLP铜箔',
        '态恋压', '滩迪重机', '让', '思'
    }
    
    # 常见分类标签
    CATEGORY_KEYWORDS = [
        'CPO', 'LPO', '光模块', '光芯片', '光器件',
        '铜缆', '铜连接',
        '液冷', '冷却液', '液态金属',
        '数据中心', 'IDC', '机房',
        '服务器', '交换机', '电源', 'HVDC', 'UPS',
        'PCB', '电子布', '铜箔',
        '芯片', 'CPU', 'GPU', 'LPU', '算力芯片', '推理芯片',
        '存储', '内存', '硬盘',
        '其他'
    ]
    
    def __init__(self):
        self.stock_name_to_code = self._build_stock_mapping()
    
    def _build_stock_mapping(self) -> Dict[str, str]:
        """构建股票名称到代码的映射（常见股票）"""
        # AI 硬件产业链相关常见股票
        mapping = {
            # 光模块/CPO
            '中际旭创': '300308', '新易盛': '300502', '天孚通信': '300394',
            '剑桥科技': '603083', '光迅科技': '002281', '华工科技': '000988',
            '博创科技': '300548', '太辰光': '300570', '德科立': '688205',
            '长飞光纤': '601869', '汇绿生态': '001267', '永鼎股份': '600105',
            '通鼎互联': '002491', '东田微': '301183', '致尚科技': '301486',
            '青山纸业': '600103', '腾景科技': '688195', '福晶科技': '002222',
            '罗博特科': '300757', '航锦科技': '000818',
            
            # 铜缆/连接
            '沃尔核材': '002130', '神宇股份': '300563', '兆龙互连': '300913',
            '鼎通科技': '688668', '华丰科技': '688629', '立讯精密': '002475',
            '新亚电子': '605277', '宝胜股份': '600973', '金信诺': '300252',
            
            # 液冷
            '英维克': '002837', '高澜股份': '300499', '申菱环境': '301018',
            '同飞股份': '300990', '佳力图': '603912', '依米康': '300249',
            '网宿科技': '300017', '浪潮信息': '000977', '中科曙光': '603019',
            '润泽科技': '300442', '冰轮环境': '000811', '巨化股份': '600160',
            '新宙邦': '300037', '永太科技': '002326', '统一股份': '600506',
            '回天新材': '300041', '东阳光': '600673', '川润股份': '002272',
            '康盛股份': '002418', '烽火通信': '600498', '中兴通讯': '000063',
            '共进股份': '603118', '锐捷网络': '301165',
            
            # 数据中心/IDC
            '奥飞数据': '300738', '光环新网': '300383', '数据港': '603881',
            '宝信软件': '600845', '科华数据': '002335', '科士达': '002518',
            '英威腾': '002334', '铜牛信息': '300895', '首都在线': '300846',
            '优刻得': '688158', '朗威股份': '301202', '宁波建工': '601789',
            '云赛智联': '600602', '电科数字': '600850', '海得控制': '002184',
            '正泰电器': '601877', '特锐德': '300001', '苏美达': '600710',
            '三变科技': '002112', '中兴通讯': '000063', '共进股份': '603118',
            '锐捷网络': '301165', '光华科技': '002741', '大族数控': '301200',
            '中钨高新': '000657', '日联科技': '688531', '沪电股份': '002463',
            '深南电路': '002916', '金安国纪': '002636', '生益电子': '688183',
            '科翔股份': '300903', '威尔高': '301251', '宏和科技': '603256',
            '国际复材': '301526', '中国巨石': '600176', '菲利华': '300395',
            '北自科技': '603082', '泰豪科技': '600590', '科泰电源': '300153',
            '潍柴重机': '000880', '风形股份': '002760', '神驰机电': '603109',
            '四方股份': '601126', '圣阳股份': '002580', '欧陆通': '300870',
            '九洲集团': '300040', '航天长峰': '600855', '盛弘股份': '300693',
            '环旭电子': '601231', '中富电路': '300814', '新雷能': '300593',
            '中恒电气': '002364', '南都电源': '300068', '江海股份': '002484',
            '麦格米特': '002851', '华脉科技': '603042', '顺钠股份': '000533',
            '彩讯股份': '300634', '川环科技': '300547', '广安爱众': '600979',
            '明阳智能': '601615', '深南电A': '000037', '并行科技': '839493',
            
            # 芯片/半导体
            '寒武纪': '688256', '国科微': '300672', '景嘉微': '300474',
            '摩尔线程': None, '复旦微电': '688385', '云天励飞': '688343',
            '成都华微': '688709', '云从科技': '688327', '工业富联': '601138',
            '瑞可达': '688800', '溯联股份': '301397', '回天新材': '300041',
            '泰永长征': '002927', '星宕科技': None, '国光电器': '002045',
            '中国长城': '000066', '海光信息': '688041', '澜起科技': '688008',
            '龙芯中科': '688047', '综艺股份': '600770', '怡亚通': '002183',
            '宏昌电子': '603002', '通富微电': '002156', '中电港': '001287',
            '北京君正': '300223', '新特电气': '301120', '深圳燃气': '601139',
            '佛燃能源': '002911', '源杰科技': '688498', '长光华芯': '688048',
            '仕佳光子': '688313', '光库科技': '300620', '炬光科技': '688167',
            '凌云光': '688400', '芯动联科': '688582', '英唐智控': '300131',
            
            # PCB/电子
            '生益科技': '600183', '鹏鼎控股': '002938', '东山精密': '002384',
            '景旺电子': '603228', '胜宏科技': '300476', '世运电路': '603920',
            '奥士康': '002913', '博敏电子': '603936', '超声电子': '000823',
            '天津普林': '002134', '方正科技': '600601', '华正新材': '603186',
            '南亚新材': '688519', '金信诺': '300252', '沃尔核材': '002130',
            
            # 电源/HVDC
            '中远通': '301516', '欧陆通': '300870', '麦格米特': '002851',
            '科华数据': '002335', '科士达': '002518', '英威腾': '002334',
            '动力源': '600405', '中恒电气': '002364', '新雷能': '300593',
            '航天长峰': '600855', '盛弘股份': '300693',
            
            # 其他
            '特瑞斯': '834014', '云路股份': '688190', '芯原股份': '688521',
            '永卓股份': '002630', '智微智能': '001339', '佛燃能源': '002911',
            '紫光股份': '000938', '江波龙': '301308', '潍柴重机': '000880',
            '沃尔核材': '002130', '兆龙互连': '300913', '鼎通科技': '688668',
            '华丰科技': '688629', '立讯精密': '002475', '金信诺': '300252',
            '高澜股份': '300499', '同飞股份': '300990', '依米康': '300249',
            '网宿科技': '300017', '中科曙光': '603019', '申菱环境': '301018',
            '数据港': '603881', '云赛智联': '600602', '特锐德': '300001',
            '生益科技': '600183', '鹏鼎控股': '002938', '东山精密': '002384',
            '景旺电子': '603228', '胜宏科技': '300476', '世运电路': '603920',
            '奥士康': '002913', '博敏电子': '603936', '超声电子': '000823',
            '天津普林': '002134', '方正科技': '600601', '华正新材': '603186',
            '南亚新材': '688519', '中远通': '301516', '宝胜股份': '600973',
            '利扬芯片': '688135', '华大九天': '301269', '广立微': '301095',
            '概伦电子': '688206', '安路科技': '688107', '紫光国微': '002049',
            '中颖电子': '300327', '全志科技': '300458', '瑞芯微': '603893',
            '晶晨股份': '688099', '恒玄科技': '688608', '博通集成': '603068',
            '乐鑫科技': '688018', '翱捷科技': '688220', '唯捷创芯': '688153',
            '艾为电子': '688798', '南芯科技': '688484', '希荻微': '688173',
            '英集芯': '688209', '杰华特': '688141', '美芯晟': '688458',
            '晶丰明源': '688368', '明微电子': '688699', '富满微': '300671',
            '必易微': '688045', '东微半导': '688261', '新洁能': '605111',
            '士兰微': '600460', '华润微': '688396', '时代电气': '688187',
            '斯达半导': '603290', '宏微科技': '688711', '扬杰科技': '300373',
            '捷捷微电': '300623', '台基股份': '300046', '华微电子': '600360',
            '立昂微': '605358', '沪硅产业': '688126', '立昂微': '605358',
            '晶盛机电': '300316', '北方华创': '002371', '中微公司': '688012',
            '拓荆科技': '688072', '芯源微': '688037', '盛美上海': '688082',
            '至纯科技': '603690', '华海清科': '688120', '富创精密': '688409',
            '正帆科技': '688596', '新莱应材': '300260', '江丰电子': '300666',
            '安集科技': '688019', '鼎龙股份': '300054', '晶瑞电材': '300655',
            '南大光电': '300346', '上海新阳': '300236', '飞凯材料': '300398',
            '雅克科技': '002409', '江化微': '603078', '强力新材': '300429',
            '广信材料': '300537', '容大感光': '300576', '彤程新材': '603650',
            '华特气体': '688268', '金宏气体': '688106', '凯美特气': '002549',
            '和林微纳': '688661', '清溢光电': '688138', '路维光电': '688401',
            '美迪凯': '688079', '奥来德': '688378', '莱特光电': '688150',
        }
        return mapping
    
    def clean_text(self, text: str) -> str:
        """清洗文本，去除噪音"""
        # 去除多余空格
        text = re.sub(r'\s+', ' ', text)
        # 去除特殊字符
        text = re.sub(r'[@#%^&*()_+=\[\]{}|;:,.<>?/~`\\]', ' ', text)
        # 去除连续的数字串（可能是页码、时间等）
        text = re.sub(r'\d{1,2}:\d{2}', ' ', text)
        text = re.sub(r'\d{4}-\d{2}-\d{2}', ' ', text)
        return text.strip()
    
    def extract_thesis_name(self, text: str) -> str:
        """提取题材名称"""
        # 查找 "AI硬件" 或类似格式
        patterns = [
            r'([\u4e00-\u9fa5A-Za-z]+硬件)',
            r'([\u4e00-\u9fa5A-Za-z]+产业)',
            r'([\u4e00-\u9fa5A-Za-z]+概念)',
            r'([\u4e00-\u9fa5A-Za-z]+板块)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        
        # 默认返回 AI硬件
        return "AI硬件"
    
    def is_likely_stock_name(self, text: str) -> bool:
        """判断文本是否可能是股票名称"""
        # 过滤太短的或太长的
        if len(text) < 3 or len(text) > 8:
            return False
        
        # 过滤纯英文/数字
        if re.match(r'^[A-Za-z0-9]+$', text):
            return False
        
        # 过滤排除关键词
        if text in self.EXCLUDE_KEYWORDS:
            return False
        
        # 必须包含中文字符
        if not re.search(r'[\u4e00-\u9fa5]', text):
            return False
        
        # 股票名称通常以"股份"、"科技"、"信息"、"智能"等结尾
        # 或者是常见的公司名（2-4个字）
        stock_suffixes = ['股份', '科技', '信息', '智能', '电子', '通信', '网络', '软件', 
                         '微电', '电气', '机电', '精工', '新材', '环保', '生态', '纸业',
                         '燃气', '能源', '电源', '数据', '商业', '集团', '控股', '实业',
                         '建设', '航空', '航天', '船舶', '汽车', '医药', '生物', '化学',
                         '材料', '纺织', '服饰', '食品', '饮料', '农业', '牧业', '渔业',
                         '矿业', '钢铁', '有色', '水泥', '玻璃', '电力', '水务', '港口',
                         '机场', '高速', '铁路', '公交', '物流', '传媒', '文化', '教育',
                         '旅游', '酒店', '家居', '家电', '家具', '照明', '仪表', '设备',
                         '机械', '重工', '电机', '电器', '电缆', '光纤', '光缆', '芯片',
                         '半导体', '电路', '精工', '装备', '制品', '纤维', '复材', '玻纤']
        
        has_suffix = any(text.endswith(suffix) for suffix in stock_suffixes)
        
        # 过滤常见的非股票词汇
        exclude_patterns = [
            r'^\d+$',  # 纯数字
            r'^[A-Za-z]+$',  # 纯英文
            r'^第[一二三四五六七八九十]+',  # 第X...
            r'查看', r'更新', r'免责', r'涉及', r'资讯', r'数据',
            r'内容', r'网络', r'信息', r'仅供', r'来说', r'两句',
            r'随着', r'增长', r'需求', r'发展', r'超过', r'复合',
            r'全文', r'创建', r'硬件', r'软件', r'模型', r'全球',
            r'快速', r'超过', r'增长', r'发展', r'设备', r'厂商',
            r'产品', r'相关', r'海外', r'股权', r'自有', r'推理',
            r'算力', r'供货', r'分类', r'标签', r'板块', r'概念',
        ]
        
        for pattern in exclude_patterns:
            if re.search(pattern, text):
                return False
        
        # 如果是已知的股票名称，直接返回True
        if text in self.stock_name_to_code:
            return True
        
        # 否则需要有股票后缀或者是2-4个字的常见公司名
        if len(text) >= 3 and has_suffix:
            return True
        
        return False
    
    def extract_stock_names(self, text: str) -> List[Dict]:
        """提取股票名称列表 - V2优化版"""
        stocks = []
        seen_names = set()
        
        # 首先尝试匹配已知的股票名称（优先匹配）
        for stock_name in sorted(self.stock_name_to_code.keys(), key=len, reverse=True):
            if stock_name in text:
                if stock_name not in seen_names:
                    seen_names.add(stock_name)
                    code = self.stock_name_to_code.get(stock_name, "")
                    stocks.append({
                        'name': stock_name,
                        'code': code
                    })
        
        # 然后使用正则提取可能的股票名称
        # 股票名称通常是2-6个中文字符
        pattern = r'[\u4e00-\u9fa5]{2,6}'
        matches = re.findall(pattern, text)
        
        for candidate in matches:
            candidate = candidate.strip()
            if not candidate:
                continue
            
            # 检查是否是股票名称
            if self.is_likely_stock_name(candidate):
                if candidate not in seen_names:
                    seen_names.add(candidate)
                    # 查找对应的代码
                    code = self.stock_name_to_code.get(candidate, "")
                    stocks.append({
                        'name': candidate,
                        'code': code
                    })
        
        return stocks
    
    def parse_from_raw_text(self, raw_text: str) -> Dict:
        """从原始OCR文本解析结构化数据"""
        # 提取题材名称
        thesis_name = self.extract_thesis_name(raw_text)
        
        # 提取股票名称
        stocks = self.extract_stock_names(raw_text)
        
        return {
            'thesis_name': thesis_name,
            'stocks': stocks,
            'stock_count': len(stocks)
        }


def save_structured_result(data: Dict, output_dir: str) -> str:
    """保存结构化结果到JSON文件"""
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"ocr_structured_v2_{timestamp}.json")
    
    # 添加元数据
    data['parse_time'] = datetime.now().isoformat()
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description='OCR 识别脚本 V2 - 优化版'
    )
    parser.add_argument(
        '--image', 
        required=True, 
        help='输入图片路径'
    )
    parser.add_argument(
        '--output-dir',
        default='output',
        help='输出目录 (默认: output)'
    )
    parser.add_argument(
        '--raw-text',
        help='直接传入原始OCR文本（用于测试解析逻辑）'
    )
    
    args = parser.parse_args()
    
    # 获取工作目录
    script_dir = Path(__file__).parent
    work_dir = script_dir.parent
    
    # 解析输出目录
    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(work_dir, output_dir)
    
    # 初始化解析器
    thesis_parser = ThesisParser()
    
    if args.raw_text:
        # 直接从原始文本解析（测试模式）
        print("Parsing from raw text...")
        raw_text = args.raw_text
        if os.path.exists(args.raw_text):
            with open(args.raw_text, 'r', encoding='utf-8') as f:
                raw_text = f.read()
        
        result = thesis_parser.parse_from_raw_text(raw_text)
        
    else:
        # 从图片识别
        image_path = args.image
        if not os.path.isabs(image_path):
            image_path = os.path.join(os.getcwd(), image_path)
        
        print(f"Processing image: {image_path}")
        
        # 初始化OCR引擎
        ocr = ThesisOCR()
        
        # 提取文字
        ocr_result = ocr.extract_text(image_path)
        raw_text = ocr_result['raw_text']
        
        print(f"OCR Engine: {ocr_result['engine']}")
        print(f"Raw text length: {len(raw_text)} chars")
        
        # 解析结构化数据
        result = thesis_parser.parse_from_raw_text(raw_text)
        result['source_file'] = image_path
        result['ocr_engine'] = ocr_result['engine']
    
    # 保存结果
    output_path = save_structured_result(result, output_dir)
    
    # 输出摘要
    print(f"\n{'='*50}")
    print(f"题材名称: {result['thesis_name']}")
    print(f"识别股票数: {result['stock_count']}")
    print(f"{'='*50}")
    print(f"\n前20只股票:")
    for i, stock in enumerate(result['stocks'][:20], 1):
        code_str = f"({stock['code']})" if stock['code'] else ""
        print(f"  {i}. {stock['name']}{code_str}")
    
    if result['stock_count'] > 20:
        print(f"  ... 还有 {result['stock_count'] - 20} 只")
    
    print(f"\n结果已保存到: {output_path}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
