import scrapy
import os
import re

class ArxivSpider(scrapy.Spider):
    name = "arxiv"
    allowed_domains = ["arxiv.org"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = os.environ.get("CATEGORIES", "astro-ph.GA, astro-ph.CO")
        categories = categories.split(",")
        self.target_categories = set(map(str.strip, categories))
        
        # ==============================================================================
        # 【自定义修改】在这里定义你的筛选关键词
        # 爬虫会检查文章【标题】或【摘要】是否包含以下任意一个词（不区分大小写）
        # ==============================================================================
        self.my_keywords = [
            "strong lens", "strong gravitational lens", "strong lensing" # 强透镜
            "lens model", "lensing",                    # 透镜建模
            "dark matter", "DM halo",                   # 暗物质
            "ALMA", "SKA" ,"interferometer"             # ALMA,SKA
            "Dust", "dusty",                            # 尘埃
            "DSFGs", "submillimeter",                   # DSFGs/亚毫米
            "high-redshift", "z >", "z>",               # 高红移
            "polarization", "polarized", "polarised",   #偏振
            "gas", "molecular", "molecular gas",        #气体/分子气体
            "SPT", "Herschel", "JWST", "Euclid", "CSST" #望远镜
        ]
        
        self.start_urls = [
            f"https://arxiv.org/list/{cat}/new" for cat in self.target_categories
        ]

    def parse(self, response):
        # 1. 提取锚点辅助定位
        anchors = []
        for li in response.css("div[id=dlpage] ul li"):
            href = li.css("a::attr(href)").get()
            if href and "item" in href:
                anchors.append(int(href.split("item")[-1]))

        # 2. 遍历列表条目
        for paper_dt in response.css("dl dt"):
            
            # --- 基本信息提取 ---
            paper_anchor = paper_dt.css("a[name^='item']::attr(name)").get()
            if not paper_anchor:
                continue
            
            paper_id = int(paper_anchor.split("item")[-1])
            if anchors and paper_id >= anchors[-1]:
                continue

            abstract_link = paper_dt.css("a[title='Abstract']::attr(href)").get()
            if not abstract_link:
                continue
            
            arxiv_id = abstract_link.split("/")[-1]
            
            paper_dd = paper_dt.xpath("following-sibling::dd[1]")
            if not paper_dd:
                continue

            # --- 提取分类 ---
            # (这部分逻辑保持原样，用于构建最终返回的数据结构)
            categories = []
            subjects_text = paper_dd.css(".list-subjects .primary-subject::text").get()
            if not subjects_text:
                subjects_text = paper_dd.css(".list-subjects::text").get()
            
            if subjects_text:
                categories_in_paper = re.findall(r'\(([^)]+)\)', subjects_text)
                categories = list(set(categories_in_paper))
            
            # 构建要返回的 Item 对象
            item_data = {
                "id": arxiv_id,
                "categories": categories,
            }
            
            # 检查分类是否匹配目标（初步筛选）
            paper_categories_set = set(categories)
            if not paper_categories_set.intersection(self.target_categories) and subjects_text:
                # 分类完全不沾边，直接跳过，不需要浪费资源检查摘要
                self.logger.debug(f"Skipped paper {arxiv_id} (category mismatch)")
                continue

            # ==========================================================================
            # 【筛选逻辑升级】
            # 策略：
            # 1. 先检查【标题】。如果标题命中关键词 -> 直接 Yield (无需请求摘要页，节省资源)
            # 2. 如果标题未命中 -> 发起请求抓取【摘要】页，在回调中检查摘要。
            # ==========================================================================
            
            title_text = paper_dd.css(".list-title").xpath("string()").get()
            clean_title = ""
            if title_text:
                clean_title = title_text.replace("Title:", "").strip().lower()
            
            # 1. 检查标题
            is_title_interested = False
            for kw in self.my_keywords:
                if kw.lower() in clean_title:
                    is_title_interested = True
                    break
            
            if is_title_interested:
                self.logger.info(f"Found INTERESTING paper (by Title) {arxiv_id}: {clean_title[:50]}...")
                yield item_data
            else:
                # 2. 标题没中，请求详情页检查摘要
                # 注意：这会增加爬取时间，但在 Scrapy 异步框架下通常可以接受
                # urljoin 确保链接完整
                abs_url = response.urljoin(abstract_link)
                yield scrapy.Request(
                    url=abs_url,
                    callback=self.parse_abstract_page,
                    meta={
                        'item_data': item_data,
                        'title_prefix': clean_title[:30]
                    }
                )

    def parse_abstract_page(self, response):
        """
        回调函数：处理详情页，提取摘要并进行关键词匹配
        """
        item_data = response.meta['item_data']
        title_prefix = response.meta['title_prefix']
        
        # 提取摘要文本
        # arXiv 详情页摘要通常在 blockquote.abstract 中
        # 格式通常是 <blockquote class="abstract mathjax"><span class="descriptor">Abstract:</span> The actual text...</blockquote>
        abstract_text = response.css("blockquote.abstract").xpath("string()").get()
        
        if abstract_text:
            # 去掉 "Abstract:" 前缀并转小写
            clean_abstract = abstract_text.replace("Abstract:", "").strip().lower()
            
            # 检查摘要是否包含关键词
            is_abstract_interested = False
            for kw in self.my_keywords:
                if kw.lower() in clean_abstract:
                    is_abstract_interested = True
                    break
            
            if is_abstract_interested:
                self.logger.info(f"Found INTERESTING paper (by Abstract) {item_data['id']}: {title_prefix}...")
                yield item_data
            else:
                self.logger.info(f"Skipped paper {item_data['id']}: Keywords not found in Title or Abstract")
        else:
            self.logger.warning(f"Could not extract abstract for {item_data['id']}")
