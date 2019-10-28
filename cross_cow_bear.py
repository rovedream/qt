# editor by linbirg@2019-09-19
# 先改为py3版本，再考虑实盘优化，包括代码模块化、仓位控制、风险控制、止损、择时等

# 克隆自聚宽文章：https://www.joinquant.com/post/13382
# 标题：穿越牛熊基业长青的价值精选策略
# 作者：拉姆达投资


'''
投资程序：
霍华．罗斯曼强调其投资风格在于为投资大众建立均衡、且以成长为导向的投资组合。选股方式偏好大型股，
管理良好且为领导产业趋势，以及产生实际报酬率的公司；不仅重视公司产生现金的能力，也强调有稳定成长能力的重要。
总市值大于等于50亿美元。
良好的财务结构。
较高的股东权益报酬。
拥有良好且持续的自由现金流量。
稳定持续的营收成长率。
优于比较指数的盈余报酬率。
'''

import pandas as pd
import numpy as np
import datetime as dt
# import jqdata


# from jqdata import get_trade_days

def log_time(f):
    import time
    def decorater(*args,**kw):
        now = time.time() * 1000
        ret = f(*args,**kw)
        delta = time.time() * 1000 - now
        log.info('函数[%s]用时[%d]'%(f.__name__,delta))
        return ret
    
    return decorater
    

class DateHelper:
    @classmethod
    def to_date(cls,one):
        '''
        ### 将日期转换为Date类型。
        ### para:
        - one: 某一天，可以是Date、Datetime或者```%Y-%m-%d```格式的字符串
        '''
        import datetime
        if isinstance(one,str):
            one_date = datetime.datetime.strptime(one, "%Y-%m-%d")
            return one_date.date()
        
        if isinstance(one,datetime.datetime):
            return one.date()
        
        if isinstance(one,datetime.date):
            return one
        
        raise RuntimeError('不支持的日期格式')

    @classmethod
    def add_ndays(cls,one,ndays):
        import datetime
        one_date = cls.to_date(one)
        one_date = one_date + datetime.timedelta(ndays)
        return one_date 
    
    @classmethod
    def date_is_after(cls, one, other):
        one_date = cls.to_date(one)
        other_date = cls.to_date(other)
        
        is_after = one_date > other_date
        return is_after

    @classmethod
    def days_between(cls, one,other):
        one_date = cls.to_date(one)
        other_date = cls.to_date(other)
        
        interval = one_date - other_date
        return interval.days

class BzUtil():
    # 去极值
    @staticmethod
    def fun_winsorize(rs, type, num):
        # rs为Series化的数据
        rs = rs.dropna().copy()
        low_line, up_line = 0, 0
        if type == 1:   # 标准差去极值
            mean = rs.mean()
            #取极值
            mad = num*rs.std()
            up_line  = mean + mad
            low_line = mean - mad
        elif type == 2: #中位值去极值
            rs = rs.replace([-np.inf, np.inf], np.nan)
            median = rs.median()
            md = abs(rs - median).median()
            mad = md * num * 1.4826
            up_line = median + mad
            low_line = median - mad
        elif type == 3: # Boxplot 去极值
            if len(rs) < 2:
                return rs
            mc = sm.stats.stattools.medcouple(rs)
            rs.sort()
            q1 = rs[int(0.25*len(rs))]
            q3 = rs[int(0.75*len(rs))]
            iqr = q3-q1        
            if mc >= 0:
                    low_line = q1-1.5*np.exp(-3.5*mc)*iqr
                    up_line = q3+1.5*np.exp(4*mc)*iqr        
            else:
                    low_line = q1-1.5*np.exp(-4*mc)*iqr
                    up_line = q3+1.5*np.exp(3.5*mc)*iqr

        rs[rs < low_line] = low_line
        rs[rs > up_line] = up_line
        
        return rs
    
    #标准化
    @staticmethod
    def fun_standardize(s,type):
        '''
        s为Series数据
        type为标准化类型:1 MinMax,2 Standard,3 maxabs 
        '''
        data=s.dropna().copy()
        if int(type)==1:
            rs = (data - data.min())/(data.max() - data.min())
        elif type==2:
            rs = (data - data.mean())/data.std()
        elif type==3:
            rs = data/10**np.ceil(np.log10(data.abs().max()))
        return rs

    #中性化
    @staticmethod
    def fun_neutralize(s, df, module='pe_ratio', industry_type=None, level=2, statsDate=None):
        '''
        参数：
        s为stock代码 如'000002.XSHE' 可为list,可为str
        moduel:中性化的指标 默认为PE
        industry_type:行业类型(可选), 如果行业不指定，全市场中性化
        返回：
        中性化后的Series index为股票代码 value为中性化后的值
        '''
        s = df[df.code.isin(list(s))]
        s = s.reset_index(drop = True)
        s = pd.Series(s[module].values, index=s['code'])
        s = BzUtil.fun_winsorize(s,1,3)

        if industry_type:
            stocks = BzUtil.fun_get_industry_stocks(industry=industry_type, level=level, statsDate=statsDate)
        else:
            stocks = list(get_all_securities(['stock'], date=statsDate).index)

        df = df[df.code.isin(stocks)]
        df = df.reset_index(drop = True)
        df = pd.Series(df[module].values, index=df['code'])
        df = BzUtil.fun_winsorize(df,1, 3)
        rs = (s - df.mean())/df.std()

        return rs
    
    @classmethod
    def filter_paused(cls, stocks, end_date, day=1, x=1):
        '''
        @deprecated
        ### para:
        - stocks:股票池     
        - end_date:查询日期
        - day : 过滤最近多少天(包括今天)停牌过的股票,默认只过滤今天
        - x : 过滤最近day日停牌数>=x日的股票,默认1次

        ### 返回 :过滤后的股票池 
        '''
        if len(stocks) == 0:
            return stocks

        s = get_price(stocks, end_date=end_date, count =day, fields='paused').paused.sum()
        return s[s < x].index.tolist()

    @classmethod
    def filter_st(cls, stocks, end_date):
        if len(stocks) == 0:
            return stocks

        datas = get_extras('is_st', stocks, end_date = end_date , count=1).T
        return  datas[~datas.iloc[:,0]].index.tolist()

    @staticmethod
    def remove_limit_up(stock_list):
        h = history(1, '1m', 'close', stock_list, df=False, skip_paused=False, fq='pre')
        h2 = history(1, '1m', 'high_limit', stock_list, df=False, skip_paused=False, fq='pre')
        tmpList = []
        for stock in stock_list:
            if h[stock][0] < h2[stock][0]:
                tmpList.append(stock)

        return tmpList

    # 剔除上市时间较短的产品
    @staticmethod
    def fun_delNewShare(current_dt, equity, deltaday):
        deltaDate = DateHelper.to_date(current_dt) - dt.timedelta(deltaday)
    
        tmpList = []
        for stock in equity:
            if get_security_info(stock).start_date < deltaDate:
                tmpList.append(stock)
    
        return tmpList
    
    @classmethod
    def remove_paused(cls, stock_list):
        current_data = get_current_data()
        tmpList = []
        for stock in stock_list:
            if not current_data[stock].paused:
                tmpList.append(stock)
        return tmpList
    
    # 行业列表
    @staticmethod
    def fun_get_industry(cycle=None):
        # cycle 的参数：None取所有行业，True取周期性行业，False取非周期性行业
        industry_dict = {
            'A01':False,# 农业 	1993-09-17
            'A02':False,# 林业 	1996-12-06
            'A03':False,# 畜牧业 	1997-06-11
            'A04':False,# 渔业 	1993-05-07
            'A05':False,# 农、林、牧、渔服务业 	1997-05-30
            'B06':True, # 煤炭开采和洗选业 	1994-01-06
            'B07':True, # 石油和天然气开采业 	1996-06-28
            'B08':True, # 黑色金属矿采选业 	1997-07-08
            'B09':True, # 有色金属矿采选业 	1996-03-20
            'B11':True, # 开采辅助活动 	2002-02-05
            'C13':False, #	农副食品加工业 	1993-12-15
            'C14':False,# 食品制造业 	1994-08-18
            'C15':False,# 酒、饮料和精制茶制造业 	1992-10-12
            'C17':True,# 纺织业 	1992-06-16
            'C18':True,# 纺织服装、服饰业 	1993-12-31
            'C19':True,# 皮革、毛皮、羽毛及其制品和制鞋业 	1994-04-04
            'C20':False,# 木材加工及木、竹、藤、棕、草制品业 	2005-05-10
            'C21':False,# 家具制造业 	1996-04-25
            'C22':False,# 造纸及纸制品业 	1993-03-12
            'C23':False,# 印刷和记录媒介复制业 	1994-02-24
            'C24':False,# 文教、工美、体育和娱乐用品制造业 	2007-01-10
            'C25':True, # 石油加工、炼焦及核燃料加工业 	1993-10-25
            'C26':True, # 化学原料及化学制品制造业 	1990-12-19
            'C27':False,# 医药制造业 	1993-06-29
            'C28':True, # 化学纤维制造业 	1993-07-28
            'C29':True, # 橡胶和塑料制品业 	1992-08-28
            'C30':True, # 非金属矿物制品业 	1992-02-28
            'C31':True, # 黑色金属冶炼及压延加工业 	1994-01-06
            'C32':True, # 有色金属冶炼和压延加工业 	1996-02-15
            'C33':True, # 金属制品业 	1993-11-30
            'C34':True, # 通用设备制造业 	1992-03-27
            'C35':True, # 专用设备制造业 	1992-07-01
            'C36':True, # 汽车制造业 	1992-07-24
            'C37':True, # 铁路、船舶、航空航天和其它运输设备制造业 	1992-03-31
            'C38':True, # 电气机械及器材制造业 	1990-12-19
            'C39':False,# 计算机、通信和其他电子设备制造业 	1990-12-19
            'C40':False,# 仪器仪表制造业 	1993-09-17
            'C41':True, # 其他制造业 	1992-08-14
            'C42':False,# 废弃资源综合利用业 	2012-10-26
            'D44':True, # 电力、热力生产和供应业 	1993-04-16
            'D45':False,# 燃气生产和供应业 	2000-12-11
            'D46':False,# 水的生产和供应业 	1994-02-24
            'E47':True, # 房屋建筑业 	1993-04-29
            'E48':True, # 土木工程建筑业 	1994-01-28
            'E50':True, # 建筑装饰和其他建筑业 	1997-05-22
            'F51':False,# 批发业 	1992-05-06
            'F52':False,# 零售业 	1992-09-02
            'G53':True, # 铁路运输业 	1998-05-11
            'G54':True, # 道路运输业 	1991-01-14
            'G55':True, # 水上运输业 	1993-11-19
            'G56':True, # 航空运输业 	1997-11-05
            'G58':True, # 装卸搬运和运输代理业 	1993-05-05
            'G59':False,# 仓储业 	1996-06-14
            'H61':False,# 住宿业 	1993-11-18
            'H62':False,# 餐饮业 	1997-04-30
            'I63':False,# 电信、广播电视和卫星传输服务 	1992-12-02
            'I64':False,# 互联网和相关服务 	1992-05-07
            'I65':False,# 软件和信息技术服务业 	1992-08-20
            'J66':True, # 货币金融服务 	1991-04-03
            'J67':True, # 资本市场服务 	1994-01-10
            'J68':True, # 保险业 	2007-01-09
            'J69':True, # 其他金融业 	2012-10-26
            'K70':True, # 房地产业 	1992-01-13
            'L71':False,# 租赁业 	1997-01-30
            'L72':False,# 商务服务业 	1996-08-29
            'M73':False,# 研究和试验发展 	2012-10-26
            'M74':True, # 专业技术服务业 	2007-02-15
            'N77':False,# 生态保护和环境治理业 	2012-10-26
            'N78':False,# 公共设施管理业 	1992-08-07
            'P82':False,# 教育 	2012-10-26
            'Q83':False,# 卫生 	2007-02-05
            'R85':False,# 新闻和出版业 	1992-12-08
            'R86':False,# 广播、电视、电影和影视录音制作业 	1994-02-24
            'R87':False,# 文化艺术业 	2012-10-26
            'S90':False,# 综合 	1990-12-10
            }

        industry_list = []
        if cycle == True:
            for industry in list(industry_dict.keys()):
                if industry_dict[industry] == True:
                    industry_list.append(industry)
        elif cycle == False:
            for industry in list(industry_dict.keys()):
                if industry_dict[industry] == False:
                    industry_list.append(industry)
        else:
            industry_list = list(industry_dict.keys())

        return industry_list

    # 一级行业列表
    @staticmethod
    def fun_get_industry_levelI(industry=None):
        industry_dict = {
            'A':['A01', 'A02', 'A03', 'A04', 'A05'] #农、林、牧、渔业
            ,'B':['B06', 'B07', 'B08', 'B09', 'B11'] #采矿业
            ,'C':['C13', 'C14', 'C15', 'C17', 'C18', 'C19', 'C20', 'C21', 'C22', 'C23', 'C24', 'C25', 'C26', 'C27', 'C28', 'C29', 'C30', 'C31', 'C32',\
                'C33', 'C34', 'C35', 'C36', 'C37', 'C38', 'C39', 'C40', 'C41', 'C42'] #制造业
            ,'D':['D44', 'D45', 'D46'] #电力、热力、燃气及水生产和供应业
            ,'E':['E47', 'E48', 'E50'] #建筑业
            ,'F':['F51', 'F52'] #批发和零售业
            ,'G':['G53', 'G54', 'G55', 'G56', 'G58', 'G59']	#交通运输、仓储和邮政业
            ,'H':['H61', 'H62'] #住宿和餐饮业
            ,'I':['I63', 'I64', 'I65']	#信息传输、软件和信息技术服务业
            ,'J':['J66', 'J67', 'J68', 'J69']	#金融业
            ,'K':['K70']	#房地产业
            ,'L':['L71', 'L72']	#租赁和商务服务业
            ,'M':['M73', 'M74']	#科学研究和技术服务业
            ,'N':['N78']	#水利、环境和公共设施管理业
            #,'O':[] #居民服务、修理和其他服务业
            ,'P':['P82']	#教育
            ,'Q':['Q83']	#卫生和社会工作
            ,'R':['R85', 'R86', 'R87'] #文化、体育和娱乐业
            ,'S':['S90']	#综合
            }
        if industry:
            return industry_dict[industry]
        
        return industry_dict
    
    # 根据行业取股票列表
    @staticmethod
    def fun_get_industry_stocks(industry, level=2, statsDate=None):
        if level == 2:
            stock_list = get_industry_stocks(industry, statsDate)
        elif level == 1:
            industry_list = BzUtil.fun_get_industry_levelI(industry)
            stock_list = []
            for industry_code in industry_list:
                tmpList = get_industry_stocks(industry_code, statsDate)
                stock_list = stock_list + tmpList
            stock_list = list(set(stock_list))
        else:
            stock_list = []

        return stock_list

    @classmethod
    def fun_get_factor(cls, df, factor_name, industry, level, statsDate):
        stock_list = BzUtil.fun_get_industry_stocks(industry, level, statsDate)
        rs = BzUtil.fun_neutralize(stock_list, df, module=factor_name, industry_type=industry, level=level, statsDate=statsDate)
        rs = BzUtil.fun_standardize(rs, 2)

        return rs

    
    @staticmethod
    def filter_without(stocks, bad_stocks):
        tmpList = []
        for stock in stocks:
            if stock not in bad_stocks:
                tmpList.append(stock)
        return tmpList

    @staticmethod
    def filter_intersection(stocks,others):
        ret = list(set(stocks) & set(others))
        return ret
    
    @classmethod
    def financial_data_filter_bigger(cls, stocks, factor=indicator.gross_profit_margin,val=40,startDate=None):
        q = query(indicator.code, factor).filter(factor>val,indicator.code.in_(stocks))
        df = get_fundamentals(q,date=startDate)
        
        return list(df['code'])
    
    @classmethod
    def filter_financial_data_area(cls, security_list, factor=valuation.pe_ratio, area=(5,35),startDate=None):
        q = query(indicator.code, factor).filter(factor>area[0],factor<area[1],indicator.code.in_(security_list))
        df = get_fundamentals(q,date=startDate)
        
        return list(df['code'])
    
    @classmethod
    def get_all_stocks(cls,startDate=None):
        q = query(valuation.code)
        df = get_fundamentals(q, date=startDate)
        return list(df['code'])

    @classmethod
    def print_with_name(cls, stocks):
        for s in stocks:
            info = get_security_info(s)
            log.info(info.code,info.display_name)


class ValueLib:
    '''
    1.总市值≧市场平均值*1.0。
    2.最近一季流动比率≧市场平均值（流动资产合计/流动负债合计）。
    3.近四季股东权益报酬率（roe）≧市场平均值。
    4.近五年自由现金流量均为正值。（cash_flow.net_operate_cash_flow - cash_flow.net_invest_cash_flow）
    5.近四季营收成长率介于6%至30%（）。    'IRYOY':indicator.inc_revenue_year_on_year, # 营业收入同比增长率(%)
    6.近四季盈余成长率介于8%至50%。(eps比值)
    '''
    @classmethod
    def filter_by_mkt_cap_bigger_mean(cls, stocks, panel):
        '''
        ### 总市值≧市场平均值*1.0。
        ### para:
        - stocks:待过滤股票列表
        - panel:取好的财务数据

        ### return:
            过滤后的股票列表
        '''
        df_mkt = panel.loc[['circulating_market_cap'], 3, :]
        log.info('市场流通市值均值[%f]'%(df_mkt['circulating_market_cap'].mean()))
        df_mkt = df_mkt[df_mkt['circulating_market_cap']
                        > df_mkt['circulating_market_cap'].mean()*0.5]

        stocks_cap_bigger_mean = set(df_mkt.index)
        log.info('总市值≧市场平均值:%d'%(len(stocks_cap_bigger_mean)))

        return [s for s in stocks if s in stocks_cap_bigger_mean]
    
    @classmethod
    def filter_by_last_quart_cr_bigger_mean(cls, stocks, panel):
        '''
        ### 最近一季流动比率≧市场平均值（流动资产合计/流动负债合计）。
        '''
        df_cr = panel.loc[['total_current_assets',
                        'total_current_liability'], 3, :]
        # 替换零的数值
        df_cr = df_cr[df_cr['total_current_liability'] != 0]
        df_cr['cr'] = df_cr['total_current_assets'] / df_cr['total_current_liability']
        df_cr_temp = df_cr[df_cr['cr'] > df_cr['cr'].mean()*0.8]
        stocks_cr_bigger_mean = set(df_cr_temp.index)
        log.info('最近一季流动比率≧市场平均值(0.8):%d'%(len(stocks_cr_bigger_mean)))
        return [s for s in stocks if s in stocks_cr_bigger_mean]
    
    @classmethod
    def filter_by_4quart_roe_bigger_mean(cls, stocks, panel):
        '''
        ### 近四季股东权益报酬率（roe）≧市场平均值。
        '''
        l3 = set()
        for i in range(4):
            roe_mean = panel.loc['roe', i, :].mean()
            log.info('roe_mean:%f'%(roe_mean))
            df_3 = panel.iloc[:, i, :]
            df_temp_3 = df_3[df_3['roe'] > roe_mean]
            if i == 0:
                l3 = set(df_temp_3.index)

            if i > 0:
                l_temp = df_temp_3.index
                l3 = l3 & set(l_temp)
        stocks_4roe_bigger_mean = set(l3)
        log.info('近四季股东权益报酬率（roe）≧市场平均值:%d'%(len(stocks_4roe_bigger_mean)))
        return [s for s in stocks if s in stocks_4roe_bigger_mean]

    @classmethod
    def filter_by_5year_cf_neg(cls, stocks, current_dt):
        '''
        ### 近五年自由现金流量均为正值。
        ```cash_flow.net_operate_cash_flow - cash_flow.net_invest_cash_flow```
        '''
        y = DateHelper.to_date(current_dt).year 
        l4 = set()
        for i in range(1, 6):
            df = get_fundamentals(query(cash_flow.code, cash_flow.statDate, cash_flow.net_operate_cash_flow,
                                        cash_flow.net_invest_cash_flow), statDate=str(y-i))
            if len(df) == 0:
                continue

            df['FCF'] = df['net_operate_cash_flow']-df['net_invest_cash_flow']
            df = df[df['FCF'] > 0]
            l_temp = df['code'].values
            if len(l4) == 0:
                l4 = l_temp
                continue

            l4 = set(l4) & set(l_temp)
            
        stocks_neg_5year_cach_flow = set(l4)
        log.info('近五年自由现金流量均为正值:%d'%(len(stocks_neg_5year_cach_flow)))
        return [s for s in stocks if s in stocks_neg_5year_cach_flow]
    
    @classmethod
    def filter_by_4q_inc_revenue_between(cls, stocks, panel, area=(6,60)):
        '''
        ### 近四季营收成长率介于6%至30%.   
          ```'IRYOY':indicator.inc_revenue_year_on_year # 营业收入同比增长率(%)```
        '''
        l5 = set()
        for i in range(4):
            df_5 = panel.iloc[:, i, :]
            df_temp_5 = df_5[(df_5['inc_revenue_year_on_year'] > area[0])
                            & (df_5['inc_revenue_year_on_year'] < area[1])]
            if i == 0:
                l5 = set(df_temp_5.index)

            if i > 0:
                l_temp = df_temp_5.index
                l5 = l5 & set(l_temp)
        stocks_4q_inc_revenue_between = set(l5)
        log.info('近四季营收成长率介于%d至%d:%d'%(area[0], area[1], len(stocks_4q_inc_revenue_between)))
        return [s for s in stocks if s in stocks_4q_inc_revenue_between]

    @classmethod
    @log_time
    def filter_by_4q_eps_between(cls, stocks, panel, area=(0.08,0.8)):
        '''
        ### 近四季盈余成长率介于8%至50%。(eps比值)
        '''
        l6 = set()
        for i in range(4):
            df_6 = panel.iloc[:, i, :]
            df_temp = df_6[(df_6['eps'] > area[0]) & (df_6['eps'] < area[1])]
            log.info('季盈余成长率(eps)均值：%.2f', df_6['eps'].mean()) 
            if i == 0:
                l6 = set(df_temp.index)

            if i > 0:
                l_temp = df_temp.index
                l6 = l6 & set(l_temp)
        stocks_4q_eps_bt = set(l6)
        log.info("近四季盈余成长率介于%d至%d:%d"%(area[0]*100, area[1]*100, len(stocks_4q_eps_bt)))
        return [s for s in stocks if s in stocks_4q_eps_bt]

    @classmethod
    @log_time
    def get_quarter_fundamentals(cls, stocks, num):
        '''
        ### 获取多期财务数据内容
        '''
        def get_curr_quarter(str_date):
            '''
            ### para:
            - str_date: 字符串格式的日期
            ```
            eg: '2019-03-31'
            ```
            '''
            quarter = str_date[:4]+'q'+str(int(str_date[5:7])//3) # //为整除
            return quarter


        def get_pre_quarter(quarter):
            '''
            ### 上一季
            ### para:
            - quarter:当前季 ```eg:2019q1```

            ### return: 上一季
            '''
            if quarter[-1] == '1':
                return str(int(quarter[:4])-1) + 'q4'
                
            if not quarter[-1] == '1':
                return quarter[:-1] + str(int(quarter[-1])-1)   

        q = query(valuation.code, income.statDate,
                income.pubDate).filter(valuation.code.in_(stocks))
        df = get_fundamentals(q)
        df.index = df.code
        stat_dates = set(df.statDate)
        stat_date_stocks = {sd: [
            stock for stock in df.index if df['statDate'][stock] == sd] for sd in stat_dates}

        q = query(valuation.code, valuation.code, valuation.circulating_market_cap, balance.total_current_assets, balance.total_current_liability,
                indicator.roe, cash_flow.net_operate_cash_flow, cash_flow.net_invest_cash_flow, indicator.inc_revenue_year_on_year, indicator.eps,
                indicator.gross_profit_margin
                )

        stat_date_panels = {sd: None for sd in stat_dates}

        for sd in stat_dates:
            quarters = [get_curr_quarter(sd)]
            for i in range(num-1):
                quarters.append(get_pre_quarter(quarters[-1]))
            nq = q.filter(valuation.code.in_(stat_date_stocks[sd]))

            pre_panel = {quarter: get_fundamentals(
                nq, statDate=quarter) for quarter in quarters}

            for quart in pre_panel:
                pre_panel[quart].index = pre_panel[quart].code.values

            panel = pd.Panel(pre_panel)
            panel.items = range(len(quarters))

            stat_date_panels[sd] = panel.transpose(2, 0, 1)

        final_panel = pd.concat(stat_date_panels.values(), axis=2, sort=False)

        return final_panel.dropna(axis=2)

    @classmethod
    @log_time
    def get_sorted_ps(cls,startDate):
        df = get_fundamentals(
            query(valuation.code, valuation.ps_ratio),
            date = startDate
        )

        # 根据 sp 去极值、中性化、标准化后，跨行业选最佳的标的
        industry_list = BzUtil.fun_get_industry(cycle=None)

        df = df.fillna(value = 0)
        sp_ratio = {}
        df['SP'] = 1.0/df['ps_ratio']

        df = df.drop(['ps_ratio'], axis=1)

        for industry in industry_list:
            tmpDict = BzUtil.fun_get_factor(df, 'SP', industry, 2, startDate).to_dict()
            for stock in tmpDict:
                if stock in sp_ratio:
                    sp_ratio[stock] = max(sp_ratio[stock],tmpDict[stock])
                else:
                    sp_ratio[stock] = tmpDict[stock]

        dict_score = sorted(list(sp_ratio.items()), key=lambda d:d[1], reverse=True)
        stock_list = []

        for idx in dict_score:
            stock = idx[0]
            stock_list.append(stock)

        return stock_list 

    @classmethod
    def fun_get_low_ps(cls, startDate=None):
        stock_list = cls.get_sorted_ps(startDate=startDate)
        return stock_list[:int(len(stock_list)*0.45)]
    
    @classmethod
    def fun_get_high_ps(cls,startDate=None):
        stock_list = cls.get_sorted_ps(startDate=startDate)
        return stock_list[int(len(stock_list)*0.85):]

    @classmethod
    def filter_by_ps_not_in_high(cls,stocks):
        high_stocks = cls.fun_get_high_ps()
        
        filterd_stocks = [s for s in stocks if s not in high_stocks]
        log.info('持仓不再高ps区：')
        BzUtil.print_with_name(filterd_stocks)
        return filterd_stocks
    
    @classmethod
    def filter_by_in_low_ps(cls,stocks):
        low_stocks = cls.fun_get_low_ps()
        
        return [s for s in stocks if s in low_stocks]

    @classmethod
    @log_time
    def filter_by_gross_profit_margin_bigger(cls,stocks,panel):
        '''
        近四季销售毛利率(%)(毛利/营业收入)≧median
        '''
        # gross_margin_stocks = BzUtil.financial_data_filter_bigger(stocks,indicator.gross_profit_margin,val)
        # log.info('销售毛利率(%)≧40:'+str(len(gross_margin_stocks)))
        # return BzUtil.filter_intersection(stocks, gross_margin_stocks)
        # df_gross = panel.loc['gross_profit_margin', 3, :]
        # log.info('销售毛利率中位数:%.2f'%(df_gross['gross_profit_margin'].median()))
        # df_gross_bigger_median = df_gross[df_gross['gross_profit_margin']>df_gross['gross_profit_margin'].median()]
        l7 = set()
        for i in range(4):
            median = panel.loc['gross_profit_margin',i,:].median()
            df_7 = panel.iloc[:, i, :]
            print('销售毛利率中位数:%.2f'%(median))
            df_temp = df_7[df_7['gross_profit_margin'] > 0.8*median]
            
            if i == 0:
                l7 = set(df_temp.index)

            if i > 0:
                l_temp = df_temp.index
                l7 = l7 & set(l_temp)
        stocks_gross_big_median_stocks = set(l7)
        print("近四季销售毛利率大于中位数(0.8):%d"%(len(stocks_gross_big_median_stocks)))
        return [s for s in stocks if s in stocks_gross_big_median_stocks]

    @classmethod
    @log_time
    def filter_stocks_for_buy(cls, current_dt):
        all_stocks = BzUtil.get_all_stocks()
        # panel_data = cls.get_quarter_fundamentals(all_stocks, 4)
        # g.panel = panel_data
        if not hasattr(g,'panel') or g.panel is None:
            g.panel = cls.get_quarter_fundamentals(all_stocks, 4)

        panel_data = g.panel

        filter_stocks = cls.filter_by_4q_eps_between(all_stocks,panel_data)
        filter_stocks = cls.filter_by_4q_inc_revenue_between(filter_stocks,panel_data)
        filter_stocks = cls.filter_by_4quart_roe_bigger_mean(filter_stocks,panel_data)
        filter_stocks = cls.filter_by_5year_cf_neg(filter_stocks, current_dt)
        filter_stocks = cls.filter_by_last_quart_cr_bigger_mean(filter_stocks,panel_data)
        log.info('eps,revenue,roe,cf,cr选出以下股票：')
        BzUtil.print_with_name(filter_stocks)
        filter_stocks = BzUtil.filter_st(filter_stocks, current_dt)
        filter_stocks = BzUtil.remove_paused(filter_stocks)
        filter_stocks = BzUtil.filter_financial_data_area(filter_stocks,factor=valuation.pe_ratio, area=(5,40))
        filter_stocks = cls.filter_by_mkt_cap_bigger_mean(filter_stocks,panel_data)
        log.info('考虑市值与pe<35选出以下股票：')
        BzUtil.print_with_name(filter_stocks)
        # 增加高增长选股的毛利选股
        # filter_stocks = cls.filter_by_gross_profit_margin_bigger(filter_stocks, panel_data)
        # log.info('考虑毛利率，不考虑ps低过滤选出以下股票：')
        # BzUtil.print_with_name(filter_stocks)
        # ps
        filter_stocks = cls.filter_by_in_low_ps(filter_stocks)

        return filter_stocks
    
    @classmethod
    @log_time
    def filter_for_sell(cls, stocks, current_dt):
        all_stocks = BzUtil.get_all_stocks()
        if not hasattr(g,'panel') or g.panel is None:
            g.panel = cls.get_quarter_fundamentals(all_stocks, 4)
        
        panel_data = g.panel

        filter_stocks = cls.filter_by_4q_eps_between(all_stocks,panel_data)
        filter_stocks = cls.filter_by_4q_inc_revenue_between(filter_stocks,panel_data)
        filter_stocks = cls.filter_by_4quart_roe_bigger_mean(filter_stocks,panel_data)
        filter_stocks = cls.filter_by_5year_cf_neg(filter_stocks, current_dt)
        filter_stocks = cls.filter_by_last_quart_cr_bigger_mean(filter_stocks,panel_data)
        filter_stocks = cls.filter_by_mkt_cap_bigger_mean(filter_stocks,panel_data)
        filter_stocks = BzUtil.filter_st(filter_stocks, current_dt)
        # 增加高增长选股的毛利选股
        # filter_stocks = cls.filter_by_gross_profit_margin_bigger(filter_stocks,panel_data)

        filter_stocks = BzUtil.filter_financial_data_area(filter_stocks,factor=valuation.pe_ratio, area=(5,60))
        
        can_hold = [s for s in stocks if s in filter_stocks]
        
        can_hold = cls.filter_by_ps_not_in_high(can_hold)

        return can_hold




class StopManager():
    # 1 是否止损 
    # 2 止损记录
    # 3 一段时间内不再购买
    # 4 按先后排序
    def __init__(self):
        self.stop_ratio = 0.1 # 跌10%止损
        self.stop_ndays = 20
        self.blacks = {}
        self.sorted_blacks = []

    def check_stop(self,context):
        self.context = context

        for s in context.portfolio.positions:
            p = context.portfolio.positions[s]
            self.try_close(p)
    
    def try_close(self, p):
        # p:Position对象
        if self.is_stop(p,self.stop_ratio):
            log.info('股票[%s]发生止损[%f,%f,%f]。'%(p.security,p.price,p.avg_cost,(p.price-p.avg_cost)*p.total_amount))
            order_target(p.security, 0)
            self.record(p.security)
    
    def is_stop(self, position,ratio=0.08):
        # position:Position对象
        return position.price <= (1-ratio) * position.avg_cost
    
    def is_lost(self, position):
        return self.is_stop(position,0)
    
    def record(self,sec):
        # 记录sec,date
        self.blacks[sec] = self.context.current_dt
        if sec in self.sorted_blacks:
            self.sorted_blacks.remove(sec)
        
        self.sorted_blacks.append(sec)
    
    def beyond_last_stop(self,stock,current_dt):
        import datetime
        stop_day = self.blacks[stock]

        beyond_day = stop_day + datetime.timedelta(self.stop_ndays)

        log.info('当前日期：'+str(current_dt)+' 逾期日：'+str(beyond_day))
        
        return current_dt > beyond_day
    
    def sort_by_stop_time(self,stocks):
        sorted_stocks = []

        tmp_stocks = stocks[::]

        if len(tmp_stocks) == 0:
            return sorted_stocks

        for s in self.sorted_blacks:
            if s in tmp_stocks:
                sorted_stocks.append(s)
                tmp_stocks.remove(s)
            
            if len(tmp_stocks) == 0:
                break

        return sorted_stocks

    def filter_and_sort(self,stocks,current_dt):
        filted_stocks = []
        need_sort = []
        for s in stocks:
            if s not in self.blacks:
                filted_stocks.append(s)

            if s in self.blacks:
                log.info('股票[%s]发生过止损[%s]。'%(s,str(self.blacks[s])))
                if self.beyond_last_stop(s,current_dt):
                    need_sort.append(s)
                
        sorted_stocks = self.sort_by_stop_time(need_sort)

        return filted_stocks + sorted_stocks

    def get_latest_stopped_stocks(self, current_dt, max_days=20):
        latest_stoped = []
        for s in self.blacks:
            if self.calc_stock_stopped_days(s, current_dt) <= max_days:
                latest_stoped.append(s)

        return latest_stoped
    
    def calc_stock_stopped_days(self,stock,current_dt):
        return DateHelper.days_between(current_dt, self.blacks[stock])



class QuantileWraper:
    def __init__(self):
        self.pe_pb_df = None
        self.quantile = None
        self.index_code = '000300.XSHG'

    def pretty_print(self,ndays=2):
        if self.quantile is None:
            log.info('没有指数PE分位数据。')
            return
        
        import prettytable as pt

        tb = pt.PrettyTable(["日期", "pe", "pb", "近" + str(g.quantile_long) + "年pe百分位高度"])
        for i in range(1, ndays+1):
            tb.add_row([str(self.pe_pb_df.index[-i]), 
                        str(round(self.pe_pb_df['pe'].iat[-i],3)),
                        str(round(self.pe_pb_df['pb'].iat[-i],3)), 
                        str( round(self.quantile['quantile'].iat[-i],3))])
        index_name = get_security_info(self.index_code).display_name
        log.info('每日报告，' + index_name + '近'+ str(ndays)+'个交易日估值信息：\n' + str(tb))

    def get_one_day_index_pe_pb_media(self,index_code, date):
        stocks = get_index_stocks(index_code, date)
        q = query(valuation.pe_ratio, 
                valuation.pb_ratio
                ).filter(valuation.pe_ratio != None,
                        valuation.pb_ratio != None,
                        valuation.code.in_(stocks))
        df = get_fundamentals(q, date)
        quantile = df.quantile([0.1, 0.9])
        df_pe = df.pe_ratio[(df.pe_ratio > quantile.pe_ratio.values[0]) & (df.pe_ratio < quantile.pe_ratio.values[1])]
        df_pb = df.pb_ratio[(df.pb_ratio > quantile.pb_ratio.values[0]) & (df.pb_ratio < quantile.pb_ratio.values[1])]
        return date, df_pe.median(), df_pb.median()
    
    # 定义一个函数，计算每天的成份股的平均pe/pb
    def iter_pe_pb(self, index_code, start_date, end_date):
        from jqdata import get_trade_days
        # 一个获取PE/PB的生成器
        trade_date = get_trade_days(start_date=start_date, end_date=end_date)   
        for date in trade_date:
            yield self.get_one_day_index_pe_pb_media(index_code, date)

    @log_time    
    def get_pe_pb(self, index_code, end_date, old_pe_pb=None):
        if old_pe_pb is not None:
            start_date = old_pe_pb.index[-1]
        else:
            info = get_security_info(index_code)
            start_date = info.start_date

        dict_result = [{'date': value[0], 'pe': value[1], 'pb':value[2]} for value in self.iter_pe_pb(index_code, start_date, end_date)]

        df_result = pd.DataFrame(dict_result)
        df_result.set_index('date', inplace=True)

        if old_pe_pb is None:
            old_pe_pb = df_result
        else:
            old_pe_pb = pd.concat([old_pe_pb, df_result],sort=True)

        return old_pe_pb

    ## pe近7年百分位位置计算
    @log_time
    def get_quantile(self, pe_pb_data, p='pe', n=7.5):
        """pe百分位计算。
        Args:
            p: 可以是 pe，也可以是 pb。
            n: 指用于计算指数估值百分位的区间，如果是5指近5年数据。
            pe_pb_data: 包含有 pe/pb 的 DataFrame。
        Returns:
            计算后的DataFrame。
        """
        _df = pe_pb_data.copy()
        windows = self._year_to_days(n)  # 将时间取整数

        _df['quantile'] = _df[p].rolling(windows).apply(lambda x: pd.Series(x).rank().iloc[-1] / 
                                                    pd.Series(x).shape[0], raw=True)
        _df.dropna(inplace=True)
        return _df
    
    def _year_to_days(self, years):
        # 这里的计算按一年244个交易日计算
        return int(years * 244)
    
    def init_last_years(self, current_dt, years=7.5, index_code='000300.XSHG'):
        start_date = DateHelper.add_ndays(current_dt,-self._year_to_days(years))
        self.pe_pb_df = self.get_pe_pb(index_code,current_dt)
        self.quantile = self.get_quantile(self.pe_pb_df,'pe',years)
        self.index_code = index_code
        return self.quantile
    
    @log_time
    def try_get_today_quantile(self, current_dt, years=7.5, index_code='000300.XSHG'):
        if self.quantile is None:
            self.quantile = self.init_last_years(DateHelper.add_ndays(current_dt,-1),years,index_code)

        last_day = self.quantile.index[-1]

        if DateHelper.date_is_after(current_dt, last_day):
            self.pe_pb_df = self.get_pe_pb(index_code=self.index_code,end_date=current_dt, old_pe_pb=self.pe_pb_df)
            self.quantile = self.get_quantile(self.pe_pb_df,'pe',years)

        return self.quantile['quantile'].iat[-1]

class RiskLib:
    @staticmethod
    def __get_daily_returns(stock_or_list, freq, lag):
        hStocks = history(lag, freq, 'close', stock_or_list, df=True)
        dailyReturns = hStocks.resample('D').last().pct_change().fillna(value=0, method=None, axis=0).values
    
        return dailyReturns
    
    @staticmethod
    def __level_to_probability(confidencelevel):
        # 正太分布标准差的倍数对应的分布概率
        a = (1 - 0.95)
        if confidencelevel == 1.96:
            a = (1 - 0.95)
        elif confidencelevel == 2.06:
            a = (1 - 0.96)
        elif confidencelevel == 2.18:
            a = (1 - 0.97)
        elif confidencelevel == 2.34:
            a = (1 - 0.98)
        elif confidencelevel == 2.58:
            a = (1 - 0.99)
        elif confidencelevel == 5:
            a = (1 - 0.99999)
        
        return a
    
    @staticmethod
    def calc_stock_ES(stock, a=0.05, freq='1d', lag=120):
        ES = 0
        fac = lag * a
        
        dailyReturns = RiskLib.__get_daily_returns(stock, freq, lag)
        dailyReturns_sort =  sorted(dailyReturns)
        
        count = 0
        sum_value = 0
        for i in range(len(dailyReturns_sort)):
            if i < fac:
                sum_value += dailyReturns_sort[i]
                count += 1
                
        if count > 0:
            ES = -(sum_value / fac)
            
        return ES[0]
    
    @staticmethod
    def calc_stock_VaR(stock,confidentLevel=1.96,freq='1d',lag=120):
        __portfolio_VaR = 0
    
        dailyReturns = RiskLib.__get_daily_returns(stock, freq, lag)
        __portfolio_VaR = 1 * confidentLevel * np.std(dailyReturns)
    
        return __portfolio_VaR
    
    @staticmethod
    def get_portfilo_ratio_ES(stocks,confidentLevel=1.96):
        es_stocks = []
        a = RiskLib.__level_to_probability(confidentLevel)
        for s in stocks:
            es = RiskLib.calc_stock_ES(s,a=a, freq='1d', lag=120)
            es_stocks.append(es)
        
        max_es = max(es_stocks)
        pos_stocks = list(max_es/np.array(es_stocks))
        
        total_positions = sum(pos_stocks)
        __ratio = {}
        
        for i in range(len(stocks)):
            stock = stocks[i]
            if stock not in __ratio:
                __ratio[stock] = 0
                
            ratio =  pos_stocks[i]/total_positions
            __ratio[stock] += ratio
        
        return __ratio
    
    @staticmethod
    def get_portfilo_ratio_Var(stocks,confidentLevel=1.96):
        var_stocks = []
        for s in stocks:
            vaR = RiskLib.calc_stock_VaR(s,confidentLevel=confidentLevel,freq='1d',lag=120)   
            var_stocks.append(vaR)
        
        max_var = max(var_stocks)
        pos_stocks = list(max_var/np.array(var_stocks))
        
        total_positions = sum(pos_stocks)
        __ratio = {}
        
        for i in range(len(stocks)):
            stock = stocks[i]
            if stock not in __ratio:
                __ratio[stock] = 0
                
            ratio =  pos_stocks[i]/total_positions
            __ratio[stock] += ratio
        
        return __ratio
    
    @staticmethod
    def get_portfilo_es(portfolio_ratios,confidentLevel=1.96):
        hStocks = history(1, '1d', 'close', list(portfolio_ratios.keys()), df=False)
        __portfolio_es = 0
        a = RiskLib.__level_to_probability(confidentLevel)
        for stock in portfolio_ratios:
            s_es = RiskLib.calc_stock_ES(stock, a=0.05, freq='1d', lag=120)  # 盈亏比率
            currVaR = hStocks[stock] * s_es # 每股盈亏 = 价格 × 比率
            perAmount = 1 * portfolio_ratios[stock] / hStocks[stock] # 每份钱按比例投到该股能买的股票数量
            __portfolio_es += perAmount * currVaR
        
        return __portfolio_es
    
    @staticmethod
    def get_portfilo_VaR(portfolio_ratios,confidentLevel=1.96):
        hStocks = history(1, '1d', 'close', list(portfolio_ratios.keys()), df=False)
        __portfolio_VaR = 0
        for stock in portfolio_ratios:
            s_vaR = RiskLib.calc_stock_VaR(stock,confidentLevel=confidentLevel,freq='1d',lag=120)  # 盈亏比率
            currVaR = hStocks[stock] * s_vaR # 每股盈亏 = 价格 × 比率
            perAmount = 1 * portfolio_ratios[stock] / hStocks[stock] # 每份前按比例投到该股能买的股票数量
            __portfolio_VaR += perAmount * currVaR
        
        return __portfolio_VaR
    
    @staticmethod
    def calc_portfilo_es_value_by_risk_money(risk_money,portfolio_ratios,confidentLevel=1.96):
        portfolio_es = RiskLib.get_portfilo_es(portfolio_ratios=portfolio_ratios,confidentLevel=confidentLevel)
        return risk_money/portfolio_es
    
    @staticmethod
    def calc_portfilo_var_value_by_risk_money(risk_money,portfolio_ratios,confidentLevel=1.96):
        portfolio_vaR = RiskLib.get_portfilo_VaR(portfolio_ratios=portfolio_ratios,confidentLevel=confidentLevel)
        return risk_money/portfolio_vaR

    @classmethod
    def formula_risk(cls, quantile, rmax=0.08, rmin=0.005):
        # risk 以0为顶点，开口向下的抛物线，quantile>0.85后，取最小值
        q_mid = 0
        q_min = -0.85
        q_max = q_mid + q_mid - q_min
    
        if quantile > q_max:
            return rmin
    
        b = (rmax-rmin)/(q_max*q_max)
    
        return abs(rmax - b*quantile*quantile)
    
    @classmethod
    def ajust_risk(cls, context):
        # 根据当前PE的分位、当前盈亏，调整risk。
        quantile = g.quantile.try_get_today_quantile(context.current_dt)

        risk = cls.formula_risk(quantile,rmax=g.max_risk,rmin=g.min_risk)
        log.info('quantile[%f] rmax[%f] rmin[%f] new risk[%f]'%(quantile, g.max_risk,g.min_risk,risk))
        return risk
    
    @classmethod
    def risk_formula_by_stop(cls, nday, max_days=20):
        def formula(nday,max_days):
            a,b = 1,1
            if nday == 0:
                a = 2/3
                b = 1

            if nday > 0 and nday < max_days:
                a = 1
                b = 1.025

            if nday > max_days:
                a = 1
                b = 1

            ry = a * b
            # print('(a,b,ry)',(a,b,ry))
            return ry

        rate = formula(0, max_days)
        for i in range(1,nday+1):
            rate = rate * formula(i,max_days)
            
        print('第[%d]天rate[%.3f]'%(nday,rate))   
        return rate

    @classmethod
    def ajust_by_stop(cls,stopper,current_dt,risk,rmax=0.04,rmin=0.01, max_days=20):
        # 幂等性
        stop_stocks = stopper.get_latest_stopped_stocks(current_dt)
        rate = 1
        for s in stop_stocks:
            ndays = stopper.calc_stock_stopped_days(s,current_dt)
            rate = rate * cls.risk_formula_by_stop(ndays, max_days=max_days)
        
        risk = risk * rate
        if risk > rmax:
            risk = rmax
        
        if risk < rmin:
            risk = rmin

        print('new risk:%.3f'%(risk))
        return risk


class Trader():
    def __init__(self, context):
        self.context = context
    
    def positions_num(self):
        return len(list(self.context.portfolio.positions.keys()))
    
    @classmethod
    def print_holdings(cls, context):
        if len(list(context.portfolio.positions.keys())) <= 0:
            log.info('没有持仓。')
            return
        
        import prettytable as pt

        tb = pt.PrettyTable(["名称","时间", "数量", "价值","盈亏"])
        total_balance = 0
        for p in context.portfolio.positions:
            pos_obj = context.portfolio.positions[p]
            p_balance = (pos_obj.price-pos_obj.avg_cost) * pos_obj.total_amount
            total_balance += p_balance
            tb.add_row([get_security_info(p).display_name + "(" + p + ")", 
                str(DateHelper.to_date(pos_obj.init_time)), 
                pos_obj.total_amount,
                round(pos_obj.value,2),
                round(p_balance,2)])
        
        log.info(str(tb))
        log.info('总权益：', round(context.portfolio.total_value, 2),' 总持仓：',round(context.portfolio.positions_value,2),' 总盈亏:',round(total_balance,2))
            

    def market_open(self):
        self.check_for_sell()

        if self.positions_num() >= g.stock_num:
            log.info('持仓数量大于限仓数量，只调仓不开仓。')
            buys = list(self.context.portfolio.positions.keys())
            self.trade_with_risk_ctrl(buys)
            return
        
        if DateHelper.to_date(self.context.current_dt).day >= 25:
            log.info('社区神定律，每月25号之后不交易')
            return
        
        self.check_for_buy()

    
    def check_for_sell(self):
        if len(list(self.context.portfolio.positions.keys())) <= 0:
            log.info("没有持仓，无需平仓。")
            return

        # 检查止损
        g.stopper.check_stop(self.context)
        holds = list(self.context.portfolio.positions.keys())

        can_hold_stocks = ValueLib.filter_for_sell(holds, self.context.current_dt)

        log.info('can hold stocks:')
        BzUtil.print_with_name(can_hold_stocks)
        
        bad_holds = [s for s in holds if s not in can_hold_stocks]
        log.info('bad_holds:')
        BzUtil.print_with_name(bad_holds)

        if len(bad_holds) > 0:
            log.info('下列股票在不好的股票里面，将清空。')
            BzUtil.print_with_name(bad_holds)
            for s in bad_holds:
                order_target(s, 0)
    
    def choose_buy_stocks(self, context):
        buys = []

        hold_stock = list(context.portfolio.positions.keys())
        
        for s in hold_stock:
            buys.append(s)  # 大盘有利，持有的仓位继续持有

        log.info('目前持有股票数量[%d],还需再选[%d]。'%(len(buys), g.stock_num-len(buys)))

        for s in g.stocks:
            if len(buys) >= g.stock_num:
                break

            if s in hold_stock:
                continue
            buys.append(s)
            log.info('额外选出股票[%s]'%(s))
            BzUtil.print_with_name([s])
            
        return buys
    
    
    # 策部略选股买卖分    
    def check_for_buy(self):
        if self.positions_num() >= g.stock_num:
            log.info('持仓数量大于等于最大允许持仓数量，不新增仓位。')
            return

        # 买入股票
        buys = self.choose_buy_stocks(self.context)
        log.info('总共选出%s只股票'%len(buys))

        if len(buys) <= 0:
            return
        
        # self.trade_equal(buys)
        self.trade_with_risk_ctrl(buys)
    
    def trade_equal(self,buys):
        # 等权买入
        if len(buys) == 0:
            return

        total = self.context.portfolio.total_value

        cost = total/len(buys)
        for s in buys:
            order_target_value(s, cost)

    def ajust_hold_positions(self,portfilo_ratio,will_spend):
        need_sells = {}
        need_buys = {}

        for s in self.context.portfolio.positions:
            if s not in portfilo_ratio:
                log.info('持仓[%s]不再组合中，全部清空。'%(s))
                order_target(s,0)
                continue

            ratio = portfilo_ratio[s]
            cost = will_spend * ratio
            p = self.context.portfolio.positions[s]
            if p.value > cost + p.price * 100:
                need_sells[s] = cost
            elif p.value < cost - p.price * 100:
                need_buys[s] = cost
            else:
                log.info('持仓[%s]变动很小，不需要调整。'%(s))
        
        # 先处理卖
        for s in need_sells:
            order_target_value(s,need_sells[s])
        
        for s in need_buys:
            order_target_value(s,need_buys[s])
    
    def buy_stocks_by_ratio(self,buy_stocks,portfilo_ratio,total_cost):
        for s in buy_stocks:
            ratio = portfilo_ratio[s]
            cost = total_cost * ratio
            order_target_value(s,cost)


    def trade_with_risk_ctrl(self,buys):
        portfilo_ratio = RiskLib.get_portfilo_ratio_ES(buys, g.confidentLevel)
        portfilo_VaR = RiskLib.get_portfilo_VaR(portfolio_ratios=portfilo_ratio,confidentLevel=g.confidentLevel)
        portfilo_es = RiskLib.get_portfilo_es(portfolio_ratios=portfilo_ratio,confidentLevel=g.confidentLevel)

        risk_money = self.context.portfolio.total_value * g.risk

        vaR_value = RiskLib.calc_portfilo_var_value_by_risk_money(risk_money,portfilo_ratio,confidentLevel=g.confidentLevel)
        es_value = RiskLib.calc_portfilo_es_value_by_risk_money(risk_money*1.5,portfilo_ratio,confidentLevel=g.confidentLevel)
        risk_value = min(vaR_value,es_value)

        buy_value = min(risk_value,self.context.portfolio.total_value)

        log.info('portfilo_ratio:',portfilo_ratio,' buy_value:', buy_value,' g.risk:', g.risk)
        
        self.ajust_hold_positions(portfilo_ratio,buy_value)

        need_buys = BzUtil.filter_without(list(portfilo_ratio.keys()),list(self.context.portfolio.positions.keys()))

        self.buy_stocks_by_ratio(need_buys,portfilo_ratio,buy_value)




def initialize(context):
    # 设定沪深300作为基准
    set_benchmark('000300.XSHG')
    # 开启动态复权模式(真实价格)
    set_option('use_real_price', True)
    # 输出内容到日志 log.info()
    log.info('初始函数开始运行且全局只运行一次')
    # 过滤掉order系列API产生的比error级别低的log
    log.set_level('order', 'error')
    # 策略参数设置
    # 操作的股票列表
    
    ### 股票相关设定 ###
    # 股票类每笔交易时的手续费是：买入时佣金万分之三，卖出时佣金万分之三加千分之一印花税, 每笔交易佣金最低扣5块钱
    set_order_cost(OrderCost(close_tax=0.001, open_commission=0.0003,
                             close_commission=0.0003, min_commission=5), type='stock')

    # 每月第5个交易日进行操作
    # 开盘前运行

    run_monthly(adjust_risk_before_market_open, 5, time='before_open',
                reference_security='000300.XSHG')
    # # 开盘时运行
    # run_monthly(market_open, 5, time='open', reference_security='000300.XSHG')
    
    run_daily(before_market_open,time='9:00', reference_security='000300.XSHG')
    run_daily(market_open, time='9:30', reference_security='000300.XSHG')

    run_daily(check_stop_at_noon, time='14:30', reference_security='000300.XSHG')

    # run_daily(before_market_open, time='before_open', reference_security='000300.XSHG') 
      # 开盘时运行
    # run_daily(check_sell_when_market_open, time='9:30', reference_security='000300.XSHG')

    run_daily(after_market_close, time='after_close', reference_security='000300.XSHG')

# 开盘前运行函数


@log_time
def after_code_changed(context):
    g.stock_num = 5
    
 
    g.stocks = None
    
    g.stopper = StopManager()
    g.stopper.stop_ratio = 0.08 # 跌8%止损
    g.stopper.stop_ndays = 20

    # 风险敞口的最大最小值
    g.risk = 0.03 # 风险敞口
    g.max_risk, g.min_risk = 0.04,0.01
    g.confidentLevel = 1.96

    g.quantile_long = 7.5 # 检查的pe分位的年数

    g.quantile = None
    

    
def get_check_stocks_sort(context, check_out_lists):
    df = get_fundamentals(query(valuation.circulating_cap, valuation.pe_ratio, valuation.code).filter(
        valuation.code.in_(check_out_lists)), date=context.previous_date)
    # asc值为0，从大到小
    df = df.sort_values('circulating_cap', ascending=True)
    out_lists = list(df['code'].values)
    return out_lists

def before_market_open(context):
    # 获取要操作的股票列表
    # temp_list = filter_stocks_for_buy(context)

    # 获取满足条件的股票列表
    temp_list = ValueLib.filter_stocks_for_buy(context.current_dt)
    log.info('满足条件的股票有%s只' % len(temp_list))
    # 按市值进行排序
    g.stocks = get_check_stocks_sort(context, temp_list)
    g.stocks = g.stopper.filter_and_sort(g.stocks, context.current_dt)
    # g.stocks = BzUtil.filter_without(g.buy_list,['600276.XSHG']) # 去掉恒瑞

    g.risk = RiskLib.ajust_by_stop(g.stopper,context.current_dt,g.risk,rmax=g.max_risk, rmin=g.min_risk,max_days=g.stopper.stop_ndays)

# 开盘时运行函数


def market_open(context):
    log.info('函数运行时间(market_open):'+str(context.current_dt.time()))
    trader = Trader(context)
    trader.market_open()


def after_market_close(context):
    Trader.print_holdings(context)
    g.panel = None

    if hasattr(g,'quantile') and g.quantile is not None:
        g.quantile.pretty_print()


def adjust_risk_before_market_open(context):
    if not hasattr(g,'quantile') or g.quantile is None:
        g.quantile = QuantileWraper()
    
    g.quantile.init_last_years(context.current_dt, years=g.quantile_long)

    g.risk = RiskLib.ajust_risk(context)
    

def check_stop_at_noon(context):
    g.stopper.check_stop(context)


