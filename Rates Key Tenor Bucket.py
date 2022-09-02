import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import datetime
from datetime import timedelta
from xbbg import blp
import glob
import os

def durations_explicit(y, m, n):
    macaulay_duration = ((1+y)/(m*y))*(1 - (1 / (1+y)**n))
#     modified_duration = macaulay_duration / (1 + y)
    return macaulay_duration

class KTB:
    
    def __init__(self, data, account_names, trader_names, asset_type, asset_class, xxy_codes, xxy_fx, auto_open_close, theme_name, trade_name):
        
        self.data = data
        self.account_names = account_names
        self.trader_names = trader_names
        self.asset_type = asset_type
        self.asset_class = asset_class
        self.xxy_codes = xxy_codes
        self.xxy_fx = xxy_fx
        self.auto_open_close = auto_open_close
        self.theme_name = theme_name
        self.trade_name = trade_name
        
        self.filtering()
        self.add_fx(self.xxy_codes, self.xxy_fx)
        self.floating_period()
        
    def filtering(self):
        
        clean_data = self.data[~self.data["Account Name"].isin(self.account_names)]
        clean_data = clean_data[clean_data["Trader Name"].isin(self.trader_names)]
        clean_data = clean_data[clean_data["Asset Type"].isin(self.asset_type)]
        clean_data = clean_data[clean_data["Asset Class"].isin(self.asset_class)]
        clean_data = clean_data[clean_data["Currency Code"].isin(self.xxy_codes)]
        clean_data["Auto Open Close"] = clean_data["Auto Open Close"].astype(str)
        clean_data = clean_data[clean_data["Auto Open Close"].isin(self.auto_open_close)]
        clean_data = clean_data[~clean_data["Theme Name"].isin(self.theme_name)]
        clean_data = clean_data[~clean_data["Trade Name"].str.endswith(self.trade_name)]
        
        self.data = clean_data
        
    '''add fx conversion'''
    def add_fx(self, xxy_codes, xxy_fx):
        
        data = self.data

        for i in range(len(xxy_codes)):
            data.loc[data["Currency Code"] == xxy_codes[i], "fx"] = xxy_fx[i]
        
        self.data = data
        
    def floating_period(self):
        
        data = self.data
        
        #Benchmark 2 
        data['Floating_Period'] = np.where((data["Benchmark 2"].str.contains('COMPOUND')) | (data["Benchmark 2"].str.contains('CMP')), 1,
                   np.where(data["Benchmark 2"].str.contains("7D"), 7,
                   np.where(data["Benchmark 2"].str.contains("3"), 91,
                   np.where(data["Benchmark 2"].str.contains("6"), 182,"NA"))))
            
        self.data = data

    def get_x_y(self, data, asset_type):
        
        if "Interest Rate Swap" in asset_type:
            
            # x (0 if settlement date has passed)
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (data["Settlement Date"] < np.datetime64('today')) & (data["Floating_Period"] == 1), "Settlement Date"] = np.datetime64('today')
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (data["Floating_Period"] == 1), "forw_dur"] = data["Settlement Date"] - np.datetime64('today')
            #x + y (contract duration left)
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (data["Floating_Period"] == 1), "contract_dur"] = data["Maturity Date"] - np.datetime64('today') 
            
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (data["Settlement Date"] > np.datetime64('today')) & (data["Floating_Period"] != 1), "forw_dur"] = data["Settlement Date"] - np.datetime64('today')
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (data["Settlement Date"] > np.datetime64('today')) & (data["Floating_Period"] != 1), "contract_dur"] = data["Maturity Date"] - np.datetime64('today') 
            
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (data["Settlement Date"] < np.datetime64('today')) & (data["Floating_Period"] != 1), "Intervals"] = ((data["Maturity Date"] - np.datetime64('today')).dt.days).floordiv(data["Floating_Period"].astype(int))
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (data["Settlement Date"] < np.datetime64('today')) & (data["Floating_Period"] != 1), "New Fixing Date"] = data["Maturity Date"] - (data["Intervals"] * data["Floating_Period"].astype(int)).map(lambda x: pd.to_timedelta(x, unit='D'))
            
            # x (0 if settlement date has passed)
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (data["Settlement Date"] < np.datetime64('today')) & (data["Floating_Period"] != 1), "forw_dur"] = data["New Fixing Date"] - np.datetime64('today')
            #x + y (contract duration left)
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (data["Settlement Date"] < np.datetime64('today')) & (data["Floating_Period"] != 1), "contract_dur"] = data["Maturity Date"] - data["New Fixing Date"]
          
        if "Futures" in asset_type:
                
            # x (0 if settlement date has passed)
            data.loc[(data["Asset Type"] == "Futures") & (data["Settlement Date"] < np.datetime64('today')), "Settlement Date"] = np.datetime64('today')
            data.loc[data["Asset Type"] == "Futures", "forw_dur"] = data["Settlement Date"] - np.datetime64('today')
            #x + y (contract duration left)
            approx_year = data["Duration"][data["Asset Type"] == "Futures"]*365
            data.loc[data["Asset Type"] == "Futures", "contract_dur"] = data["forw_dur"][data["Asset Type"] == "Futures"] + approx_year.map(lambda x: pd.to_timedelta(x, unit='D'))

        if "Bond" in asset_type:
                
            # x 
            data.loc[data["Asset Type"] == "Bond", "forw_dur"] = "0 days"
            #x + y (contract duration left)
            data.loc[data["Asset Type"] == "Bond", "contract_dur"] = data["Maturity Date"] - np.datetime64('today') 
            
        return data
        
    def get_duration(self, data, asset_type):

        if "Interest Rate Swap" in asset_type:
                
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (((data["Maturity Date"] - data["Settlement Date"]).dt.days/365).astype('int') >= 1), "freq"] = 2
            data.loc[(data["Asset Type"] == "Interest Rate Swap") & (((data["Maturity Date"] - data["Settlement Date"]).dt.days/365).astype('int') < 1), "freq"] = 1
            
            data.loc[data["Asset Type"] == "Interest Rate Swap", "Duration"] = durations_explicit(y=data["Trade Price"]/100/data["freq"], m=data["freq"], n=((data["Maturity Date"] - data["Settlement Date"]).dt.days/365)*data["freq"])
            
        if "Futures" in asset_type:
                
            data.loc[data["Asset Type"] == "Futures", "Duration"] = data.loc[data["Asset Type"] == "Futures", "Duration"]*365
            
        if "Bond" in asset_type:
                
            data.loc[data["Asset Type"] == "Futures", "Duration"] = data.loc[data["Asset Type"] == "Bond", "Duration"]*365
            
        return data
            
            
    def run(self):
        
        data = self.data

        #if maturity has passed, no dv01, drop rows
        data.drop(data[data["Maturity Date"] <= np.datetime64('today')].index, inplace = True)
        
        #if maturity has passed, no dv01, drop rows
        data.drop(data[data["Maturity Date"] <= np.datetime64('today')].index, inplace = True)

        data.loc[data["Asset Type"] == "Futures", "Ticker"] = data["ISIN"] + " COMDTY"
        data.loc[data["Asset Type"] == "Bond", "Ticker"] = data["ISIN"] + " GOVT"

        futures_dur = pd.DataFrame(data.loc[data["Asset Type"] == "Futures", ["TradeID", "Ticker"]])
        futures_dur = futures_dur.reset_index().drop("index", axis = 1)
        fut_list = [blp.bdp(futures_dur["Ticker"][i],"DUR_MID")["dur_mid"][0] for i in range(len(futures_dur))]
        futures_dur['Duration'] = fut_list
        data1 = pd.merge(data, futures_dur, how='left', on='TradeID')

        bond_dur = pd.DataFrame(data.loc[data["Asset Type"] == "Bond", ["TradeID", "Ticker"]])
        bond_dur = bond_dur.reset_index().drop("index", axis = 1)
        bond_list = [blp.bdp(bond_dur["Ticker"][i],"RISK_MID")["risk_mid"][0] for i in range(len(bond_dur))]
        bond_dur['Duration'] = bond_list
        data2 = pd.merge(data, bond_dur, how='left', on='TradeID')

        data = data1.fillna(data1[["TradeID"]].merge(data2, on='TradeID', how='left'))
        
        data = self.get_x_y(data, self.asset_type)

        data = self.get_duration(data, self.asset_type)

        data["dv01"] = -1*data.Duration*data.Notional/10000/data["fx"]
        data["x/(x+y)"] = data.forw_dur/data.contract_dur

        for xxy in data["Currency Code"].unique():
            data_xxy = data[data["Currency Code"] == xxy]

            results = []
            for i in data_xxy.index:

                A = [[1, 1],[data_xxy["x/(x+y)"][i],1]]
                Y = [data_xxy.dv01[i], 0]

                res = np.linalg.inv(A).dot(Y)
                res_dict = {'Days to Maturity': [data_xxy["contract_dur"][i], data_xxy["forw_dur"][i]], 'DV01': res, 'Trade Name': data_xxy["Trade Name"][i]}
                res_df = pd.DataFrame(res_dict)
                results.append(res_df)
                
            df = pd.concat(results)

            combi = []
            for name in df["Trade Name"].unique():
                df_sep = df[df["Trade Name"] == name] 
                df_sep = df_sep.groupby(['Days to Maturity']).sum().reset_index()
                
                df_sep.loc[(df_sep["Days to Maturity"].dt.days <= 7), "Period"] = "1W"
                df_sep.loc[(df_sep["Days to Maturity"].dt.days > 7) & (df_sep["Days to Maturity"].dt.days <= 30), "Period"] = "1M"
                df_sep.loc[(df_sep["Days to Maturity"].dt.days > 30) & (df_sep["Days to Maturity"].dt.days <= 60), "Period"] = "2M"
                df_sep.loc[(df_sep["Days to Maturity"].dt.days > 60) & (df_sep["Days to Maturity"].dt.days <= 91), "Period"] = "3M"
                df_sep.loc[(df_sep["Days to Maturity"].dt.days > 91) & (df_sep["Days to Maturity"].dt.days <= 182), "Period"] = "6M"
                df_sep.loc[(df_sep["Days to Maturity"].dt.days > 182) & (df_sep["Days to Maturity"].dt.days <= 273), "Period"] = "9M"
                df_sep.loc[(df_sep["Days to Maturity"].dt.days > 273) & (df_sep["Days to Maturity"].dt.days <= 365), "Period"] = "1Y"
                df_sep.loc[df_sep["Days to Maturity"].dt.days/365 >= 1, "Period"] = round(df_sep["Days to Maturity"].dt.days/365).astype(int).astype(str) + "Y"
                df_sep["Trade Name"] = name
            
                combi.append(df_sep)
                
            dataf = pd.concat(combi)
            dataf.sort_values("Days to Maturity", inplace = True)

            fig = px.bar(dataf, x='Period', y='DV01', color="Trade Name", category_orders={'Period': dataf["Period"]},
                          barmode='relative', template="plotly_white", opacity=0.6)
            
            datafline = dataf.groupby(['Period']).sum().reset_index()
            datafline.loc[datafline["Period"] == "1W", "index"] = 1
            datafline.loc[datafline["Period"] == "1M", "index"] = 2
            datafline.loc[datafline["Period"] == "2M", "index"] = 3
            datafline.loc[datafline["Period"] == "3M", "index"] = 4
            datafline.loc[datafline["Period"] == "6M", "index"] = 5
            datafline.loc[datafline["Period"] == "9M", "index"] = 6
            datafline.loc[datafline["Period"].str.endswith(tuple('Y')), "index"] = datafline["Period"][datafline["Period"].str.endswith(tuple('Y'))].str.strip().str[:-1].astype(int) + 6

            datafline.sort_values("index", inplace = True)
            datafline.loc[datafline["DV01"]<0, "Color"] = 'darkred'
            datafline.loc[datafline["DV01"]>=0, "Color"] = 'darkgreen'
            
            fig.add_hline(y=0, line_width=1, line_dash="dash")
            fig.add_trace(go.Scatter(x=datafline["Period"], y=datafline["DV01"], mode="lines+markers+text", name=xxy, 
                                      text = datafline["DV01"], textposition="top center", textfont=dict(color=datafline["Color"]), 
                                      texttemplate='<b>%{text:.2s}</b>', marker= dict(size=9, symbol = 'diamond', color="black"), line=dict(color="black")))
            
            fig.update_xaxes(type='category')
            fig.update_layout(title_text=xxy, title_x=0.5, yaxis=(dict(showgrid=False)), plot_bgcolor="rgba(0,0,0,0)")
            
            with open(r"Z:\Business\Personnel\Ling Yin\key tenor bucketing\Charts/KTB_" + str(today) + ".html", 'a') as f:
                f.write(fig.to_html(full_html=False, include_plotlyjs='cdn'))
                
            # with open(r"Z:\Business\Personnel\Ling Yin\key tenor bucketing/plot_" + str(today) + ".html", 'a') as f:
            #     f.write(fig.to_html(full_html=False, include_plotlyjs='cdn'))
        
        
if __name__ == "__main__":
    
    today = datetime.date.today()
    
    path = r"Z:\Business\trades"
    files = glob.glob(path + r'\*xlsx')
    latest_file = max(files, key=os.path.getctime)
    if "~$" in latest_file:
        latest_file = latest_file.split("~$")[0] + latest_file.split("~$")[-1]
    data = pd.read_excel(latest_file, engine='openpyxl')
    
    #filter account name not in 
    account_names = ["Account1", "Account2"]
    #filter trader name
    trader_names = ["bob", "tom", "terry"] 
    #filter asset type
    asset_type = ["Interest Rate Swap", "Futures", "Bond"]
    #filter asset type
    asset_class = ["Rates"]
    #filter currency codes
    xxy_codes = ["USD", "KRW", "TWD", "INR", "EUR", "AUD", "NZD", "HKD", "THB", "SGD", "JPY", "MYR", "CNY"] 
    xxy_fx = [1, blp.bdh("USDKRW Curncy","PX_LAST").iloc[0, :][0], blp.bdh("USDTWD Curncy","PX_LAST").iloc[0, :][0], 
              blp.bdh("USDINR Curncy","PX_LAST").iloc[0, :][0], blp.bdh("USDEUR Curncy","PX_LAST").iloc[0, :][0], 
              blp.bdh("USDAUD Curncy","PX_LAST").iloc[0, :][0], blp.bdh("USDNZD Curncy","PX_LAST").iloc[0, :][0], 
              blp.bdh("USDHKD Curncy","PX_LAST").iloc[0, :][0], blp.bdh("USDTHB Curncy","PX_LAST").iloc[0, :][0], 
              blp.bdh("USDSGD Curncy","PX_LAST").iloc[0, :][0], blp.bdh("USDJPY Curncy","PX_LAST").iloc[0, :][0], 
              blp.bdh("USDMYR Curncy","PX_LAST").iloc[0, :][0], blp.bdh("USDCNY Curncy","PX_LAST").iloc[0, :][0]]
    #filter auto open close
    auto_open_close = ["True"]
    #filter themes not equals to 
    theme_name = ["Asia Weather", "Politics"]
    #filter trade name dont end with 
    trade_name = ("Dup")
    
    obj = KTB(data, account_names, trader_names, asset_type, asset_class, xxy_codes, xxy_fx, auto_open_close, theme_name, trade_name)
    obj.run()
        
        