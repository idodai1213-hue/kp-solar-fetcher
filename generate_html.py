import pandas as pd
import json
import os
import math

# ---------------------------------------------------------
# 単価・基本料金設定 (中部電力 eライフプラン)
# ---------------------------------------------------------
BASIC_CHARGE_PER_MONTH = 2551.40  # 基本料金 [円/月]
SELL_PRICE_PER_KWH = 16.0          # 売電単価 [円/kWh]

# eライフプラン 買電単価 [円/kWh]
PRICE_DAYTIME = 32.19     # デイタイム
PRICE_HOMETIME = 24.13    # @ホームタイム
PRICE_NIGHTTIME = 14.24   # ナイトタイム

LATITUDE = 35.333   # 多治見市の緯度
LONGITUDE = 137.033 # 多治見市の経度

PANEL_TILT_DEG = 25.0       # 屋根の傾斜角 [度]
PANEL_AZIMUTH_DEG = 142.0   # パネルの方位角 [度] (10:30ピーク)

# ---------------------------------------------------------
# 地形（山影）考慮パラメータ (日照強度の補正用)
# ---------------------------------------------------------
# 太陽高度がこの角度以下の時間帯は、山影による影響（アメダスデータの1時間積算ラグ）を考慮するしきい値
MOUNTAIN_ELEVATION_THRESHOLD_DEG = 3.0

# ---------------------------------------------------------
# eライフプラン 時間帯＆買電単価判定関数
# ---------------------------------------------------------
def get_e_life_price(dt):
    month = dt.month
    day = dt.day
    weekday = dt.weekday() # 0:月, 1:火, ... 5:土, 6:日
    
    is_weekend_or_holiday = False
    
    # 土日判定
    if weekday in [5, 6]:
        is_weekend_or_holiday = True
    # 年末年始判定 (1/1~1/3, 12/29~12/31)
    elif (month == 1 and day <= 3) or (month == 12 and day >= 29):
        is_weekend_or_holiday = True
    # 固定祝日等
    elif (month, day) in [
        (1, 1), (1, 12), (2, 11), (2, 23), (3, 20), (3, 21), 
        (4, 29), (5, 3), (5, 4), (5, 5), (7, 20), (8, 11), 
        (9, 15), (9, 22), (9, 23), (10, 13), (11, 3), (11, 23)
    ]:
        is_weekend_or_holiday = True

    hour = dt.hour

    # ナイトタイム: 毎日 23:00 〜 8:00
    if hour >= 23 or hour < 8:
        return PRICE_NIGHTTIME
    
    # 休日・祝日の 8:00 〜 23:00 はすべて @ホームタイム
    if is_weekend_or_holiday:
        return PRICE_HOMETIME
    
    # 平日の 8:00 〜 23:00 の内訳
    if 10 <= hour < 17:
        return PRICE_DAYTIME    # デイタイム (10:00 〜 17:00)
    else:
        return PRICE_HOMETIME   # @ホームタイム (8:00〜10:00, 17:00〜23:00)


# ---------------------------------------------------------
# 太陽位置およびパネル受光強度計算関数
# ---------------------------------------------------------
def get_solar_elevation(dt, lat=LATITUDE, lon=LONGITUDE):
    """指定日時の太陽高度（度）を返す"""
    day_of_year = dt.timetuple().tm_yday
    
    declination_deg = 23.45 * math.sin(math.radians(360 / 365.0 * (284 + day_of_year)))
    declination_rad = math.radians(declination_deg)
    
    b = math.radians((360 / 365.0) * (day_of_year - 81))
    eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    
    lstm = 135.0  # JST
    time_offset = 4.0 * (lon - lstm) + eot
    time_hours = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    solar_time_hours = time_hours + time_offset / 60.0
    
    hour_angle_deg = (solar_time_hours - 12.0) * 15.0
    hour_angle_rad = math.radians(hour_angle_deg)
    
    lat_rad = math.radians(lat)
    
    sin_elevation = (math.sin(lat_rad) * math.sin(declination_rad) +
                     math.cos(lat_rad) * math.cos(declination_rad) * math.cos(hour_angle_rad))
    sin_elevation = max(-1.0, min(1.0, sin_elevation))
    return math.degrees(math.asin(sin_elevation))


def get_raw_cos_incidence(dt, lat=LATITUDE, lon=LONGITUDE, tilt=PANEL_TILT_DEG, panel_azimuth=PANEL_AZIMUTH_DEG):
    """パネルへの入射角の余弦 (0.0 〜 1.0) を返す（受光強度は山影でカットせず純粋な太陽位置で計算）"""
    elevation_deg = get_solar_elevation(dt, lat, lon)
    
    # 太陽高度が地平線以下の場合は受光なし
    if elevation_deg <= 0:
        return 0.0
    else:
        day_of_year = dt.timetuple().tm_yday
        declination_deg = 23.45 * math.sin(math.radians(360 / 365.0 * (284 + day_of_year)))
        declination_rad = math.radians(declination_deg)
        
        b = math.radians((360 / 365.0) * (day_of_year - 81))
        eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
        lstm = 135.0
        time_offset = 4.0 * (lon - lstm) + eot
        time_hours = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
        solar_time_hours = time_hours + time_offset / 60.0
        hour_angle_deg = (solar_time_hours - 12.0) * 15.0
        hour_angle_rad = math.radians(hour_angle_deg)
        lat_rad = math.radians(lat)

        cos_azimuth = (math.sin(declination_rad) * math.cos(lat_rad) - 
                       math.cos(declination_rad) * math.sin(lat_rad) * math.cos(hour_angle_rad)) / math.cos(math.radians(elevation_deg))
        cos_azimuth = max(-1.0, min(1.0, cos_azimuth))
        
        azimuth_rad = math.acos(cos_azimuth)
        if hour_angle_deg > 0:
            azimuth_rad = 2 * math.pi - azimuth_rad
        
        tilt_rad = math.radians(tilt)
        panel_azimuth_rad = math.radians(panel_azimuth)
        
        cos_incidence = (math.sin(math.radians(elevation_deg)) * math.cos(tilt_rad) + 
                         math.cos(math.radians(elevation_deg)) * math.sin(tilt_rad) * math.cos(azimuth_rad - panel_azimuth_rad))
                         
        return max(0.0, cos_incidence)


# 1. パワコンデータの読み込み
csv_path = os.environ.get('CSV_FILENAME', 'パワコン_2026.csv')
if not os.path.exists(csv_path):
    print(f"Error: {csv_path} が見つかりません。")
    exit(1)

try:
    df = pd.read_csv(csv_path, encoding='utf-8')
except:
    df = pd.read_csv(csv_path, encoding='shift_jis')

df['日時'] = pd.to_datetime(df['年月日'] + ' ' + df['時刻'])

# ---------------------------------------------------------
# アメダスデータの読み込みと前処理
# ---------------------------------------------------------
amedas_path = os.environ.get('AMEDAS_FILENAME', 'アメダス_2026.csv')
if os.path.exists(amedas_path):
    try:
        header_row = 0
        with open(amedas_path, 'r', encoding='cp932', errors='ignore') as f:
            for idx, line in enumerate(f):
                if '年月日時' in line or '日時' in line or '年月日' in line:
                    header_row = idx
                    break
        
        df_amedas = pd.read_csv(amedas_path, encoding='cp932', skiprows=header_row)
    except Exception:
        df_amedas = pd.read_csv(amedas_path, encoding='utf-8', skiprows=5)

    df_amedas.columns = [str(c).strip() for c in df_amedas.columns]

    date_col = next((c for c in df_amedas.columns if '日時' in c or '年月' in c or '時間' in c), df_amedas.columns[0])
    sun_col = next((c for c in df_amedas.columns if '日照' in c), None)

    if sun_col:
        df_amedas['日時'] = pd.to_datetime(df_amedas[date_col], errors='coerce')
        df_amedas = df_amedas.dropna(subset=['日時']).copy()
        df_amedas[sun_col] = pd.to_numeric(df_amedas[sun_col], errors='coerce').fillna(0)

        # アメダス日照強度（0〜100%）の算出
        max_val = df_amedas[sun_col].max()
        scale_base = max_val if max_val > 0 else 1.0
        df_amedas['raw_日照強度'] = (df_amedas[sun_col] / scale_base * 100.0).clip(0, 100)

        # 1時間遅れ補正
        df_amedas['日時_shifted'] = df_amedas['日時'] - pd.Timedelta(hours=1)

        # 30分データへのマッチング
        df = df.sort_values('日時')
        df_amedas = df_amedas.sort_values('日時_shifted')

        df = pd.merge_asof(
            df,
            df_amedas[['日時_shifted', 'raw_日照強度']],
            left_on='日時',
            right_on='日時_shifted',
            direction='nearest',
            tolerance=pd.Timedelta('1hour')
        )
        df['raw_日照強度'] = df['raw_日照強度'].fillna(0.0)
    else:
        df['raw_日照強度'] = 0.0
else:
    df['raw_日照強度'] = 0.0

# ---------------------------------------------------------
# 2. 受光強度および日照強度の第1軸スケール (0.0 〜 3.0 kWh) 換算
# ---------------------------------------------------------
# 生の受光係数 (0.0 〜 1.0)
df['raw_受光係数'] = df['日時'].apply(get_raw_cos_incidence)

# 朝方の山影によるアメダス積算ラグを補正するロジック
# 太陽高度がしきい値以下（山影内）の時間帯であっても、実際のパネルが受光している場合は
# アメダス側の過小評価（積算遅れ）を軽減するため、受光係数をベースにした下限フロアまたは補正を適用
def apply_mountain_sunshine_correction(row):
    raw_sun = row['raw_日照強度']
    dt = row['日時']
    elevation = get_solar_elevation(dt)
    
    # 朝方かつ太陽高度がしきい値以下（山影考慮帯）のとき、アメダスが0であっても
    # 受光係数が立ち上がっていれば、山影による時間積算の遅れとみなして補正をかける
    if elevation <= MOUNTAIN_ELEVATION_THRESHOLD_DEG and elevation > 0:
        # 受光係数の割合に応じて日照強度の下限を持ち上げる（過小評価の緩和）
        effective_sun = max(raw_sun, row['raw_受光係数'] * 100.0 * 0.8)
        return effective_sun
    return raw_sun

if 'raw_日照強度' in df.columns:
    df['補正日照強度_%'] = df.apply(apply_mountain_sunshine_correction, axis=1)
else:
    df['補正日照強度_%'] = 0.0

# 実質日照強度 (0 〜 100%)
df['実質日照強度_%'] = df['補正日照強度_%'] * df['raw_受光係数']

# 第1軸 (0.0 〜 3.0) スケールへの換算
df['日照強度_軸1'] = (df['実質日照強度_%'] / 100.0) * 3.0
df['受光強度_軸1'] = df['raw_受光係数'] * 3.0

df['日照強度_%'] = df['実質日照強度_%'].round(1)
df['受光強度_%'] = (df['raw_受光係数'] * 100.0).round(1)

df['日付'] = df['日時'].dt.strftime('%Y-%m-%d')
df['時刻_str'] = df['日時'].dt.strftime('%H:%M')
df['年月'] = df['日時'].dt.strftime('%Y-%m')
df['日時_str'] = df['日時'].dt.strftime('%Y-%m-%d %H:%M')

# 30分ごとの買電単価・コスト計算
df['買電単価'] = df['日時'].apply(get_e_life_price)
df['買電コスト'] = df['買電電力量[kWh]'] * df['買電単価']


# ---------------------------------------------------------
# JSONデータの作成
# ---------------------------------------------------------

# 24時間分（00:00 〜 23:30、48コマ）の固定タイムスロット作成
full_day_time_slots = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]

# (A) 日次データ
dates = sorted(list(df['日付'].unique()), reverse=True)
daily_data = {}
for date_str in dates:
    sub_df = df[df['日付'] == date_str].copy()
    
    # 24時間固定の全枠にマージする（当日でデータが途中で終わっていても24時間枠を保持）
    full_day_df = pd.DataFrame({'時刻_str': full_day_time_slots})
    
    # 受光強度はデータ有無に関わらず天文学的計算で24時間分求めておく
    date_dt = pd.to_datetime(date_str)
    full_day_df['dt'] = full_day_df['時刻_str'].apply(lambda t: pd.to_datetime(f"{date_str} {t}"))
    full_day_df['calc_受光係数'] = full_day_df['dt'].apply(get_raw_cos_incidence)
    full_day_df['calc_受光強度_軸1'] = (full_day_df['calc_受光係数'] * 3.0).round(3)
    full_day_df['calc_受光強度_%'] = (full_day_df['calc_受光係数'] * 100.0).round(1)
    
    merged_df = pd.merge(full_day_df, sub_df, on='時刻_str', how='left')
    
    gen_sum = sub_df['発電電力量[kWh]'].sum()
    buy_sum = sub_df['買電電力量[kWh]'].sum()
    sell_sum = sub_df['売電電力量[kWh]'].sum()
    cons_sum = sub_df['消費電力量[kWh]'].sum()
    
    self_sufficiency = ((cons_sum - buy_sum) / cons_sum * 100) if cons_sum > 0 else 0
    buy_cost = sub_df['買電コスト'].sum()
    sell_income = sell_sum * SELL_PRICE_PER_KWH
    
    # JSで扱いやすいよう、NaNは None に置換
    def to_js_list(series):
        return [None if pd.isna(x) else x for x in series]

    # 受光強度（理論値）はデータ未到達時刻も途切れないように計算値を優先補完
    elevation_list = []
    elevation_pct_list = []
    for idx, row in merged_df.iterrows():
        if pd.notna(row['受光強度_軸1']):
            elevation_list.append(row['受光強度_軸1'])
            elevation_pct_list.append(row['受光強度_%'])
        else:
            elevation_list.append(row['calc_受光強度_軸1'])
            elevation_pct_list.append(row['calc_受光強度_%'])

    daily_data[date_str] = {
        'time': merged_df['時刻_str'].tolist(),
        'generation': to_js_list(merged_df['発電電力量[kWh]']),
        'buy': to_js_list(merged_df['買電電力量[kWh]']),
        'discharging': to_js_list(merged_df['放電電力量[kWh]']),
        'consumption': to_js_list(-merged_df['消費電力量[kWh]']),
        'sell': to_js_list(-merged_df['売電電力量[kWh]']),
        'charging': to_js_list(-merged_df['充電電力量[kWh]']),
        'soc': to_js_list(merged_df['蓄電残量(SOC)[%]']),
        'elevation': elevation_list,
        'elevation_pct': elevation_pct_list,
        'sunshine': to_js_list(merged_df['日照強度_軸1'].round(3)),
        'sunshine_pct': to_js_list(merged_df['日照強度_%']),
        'summary': {
            'gen': round(gen_sum, 2),
            'buy': round(buy_sum, 2),
            'sell': round(sell_sum, 2),
            'cons': round(cons_sum, 2),
            'net_power': round(sell_sum - buy_sum, 2),
            'self_ratio': round(max(0, min(100, self_sufficiency)), 1),
            'buy_cost': round(buy_cost),
            'sell_income': round(sell_income),
            'net_cost': round(sell_income - buy_cost),
            'is_monthly': False
        }
    }

# (B) 月次データ
months = sorted(list(df['年月'].unique()), reverse=True)
monthly_data = {}
for month_str in months:
    sub_df = df[df['年月'] == month_str]
    
    gen_sum = sub_df['発電電力量[kWh]'].sum()
    buy_sum = sub_df['買電電力量[kWh]'].sum()
    sell_sum = sub_df['売電電力量[kWh]'].sum()
    cons_sum = sub_df['消費電力量[kWh]'].sum()
    
    self_sufficiency = ((cons_sum - buy_sum) / cons_sum * 100) if cons_sum > 0 else 0
    buy_cost_usage = sub_df['買電コスト'].sum()
    total_buy_cost = buy_cost_usage + BASIC_CHARGE_PER_MONTH
    sell_income = sell_sum * SELL_PRICE_PER_KWH
    
    monthly_data[month_str] = {
        'datetime': sub_df['日時_str'].tolist(),
        'generation': sub_df['発電電力量[kWh]'].tolist(),
        'buy': sub_df['買電電力量[kWh]'].tolist(),
        'discharging': sub_df['放電電力量[kWh]'].tolist(),
        'consumption': (-sub_df['消費電力量[kWh]']).tolist(),
        'sell': (-sub_df['売電電力量[kWh]']).tolist(),
        'charging': (-sub_df['充電電力量[kWh]']).tolist(),
        'soc': sub_df['蓄電残量(SOC)[%]'].tolist(),
        'elevation': sub_df['受光強度_軸1'].round(3).tolist(),
        'elevation_pct': sub_df['受光強度_%'].tolist(),
        'sunshine': sub_df['日照強度_軸1'].round(3).tolist(),
        'sunshine_pct': sub_df['日照強度_%'].tolist(),
        'summary': {
            'gen': round(gen_sum, 1),
            'buy': round(buy_sum, 1),
            'sell': round(sell_sum, 1),
            'cons': round(cons_sum, 1),
            'net_power': round(sell_sum - buy_sum, 1),
            'self_ratio': round(max(0, min(100, self_sufficiency)), 1),
            'buy_cost': round(total_buy_cost),
            'basic_charge': round(BASIC_CHARGE_PER_MONTH, 2),
            'sell_income': round(sell_income),
            'net_cost': round(sell_income - total_buy_cost),
            'is_monthly': True
        }
    }

json_daily_data = json.dumps(daily_data, ensure_ascii=False)
json_dates = json.dumps(dates, ensure_ascii=False)
json_monthly_data = json.dumps(monthly_data, ensure_ascii=False)
json_months = json.dumps(months, ensure_ascii=False)

# ---------------------------------------------------------
# 3. HTMLテンプレートの作成
# ---------------------------------------------------------
html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>太陽光発電 収支モニタリング</title>
    <link rel="apple-touch-icon" href="solar_dashboard_icon_light.png">
    <link rel="icon" type="image/png" href="solar_dashboard_icon_light.png">
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 10px;
            background-color: #f4f7f9;
            color: #333;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        .card {{
            background: #fff;
            padding: 15px 8px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            margin-bottom: 20px;
        }}
        h1 {{
            font-size: 1.4rem;
            margin-top: 0;
            color: #2c3e50;
            text-align: center;
        }}
        .tabs {{
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-bottom: 15px;
        }}
        .tab-btn {{
            padding: 10px 18px;
            font-size: 0.95rem;
            font-weight: bold;
            border: none;
            border-radius: 8px;
            background-color: #e0e6ed;
            color: #555;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .tab-btn.active {{
            background-color: #3498db;
            color: #fff;
            box-shadow: 0 2px 6px rgba(52, 152, 219, 0.4);
        }}
        .controls {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            margin-bottom: 12px;
        }}
        select {{
            padding: 8px 16px;
            font-size: 1rem;
            border-radius: 8px;
            border: 1px solid #ccc;
            background-color: #fff;
        }}

        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
            margin-bottom: 15px;
            padding: 10px;
            background: #f8fafc;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
        }}
        .summary-card {{
            background: #ffffff;
            padding: 8px 6px;
            border-radius: 6px;
            text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }}
        
        .summary-card .label {{
            font-size: 0.75rem;
            color: #64748b;
            font-weight: bold;
            margin-bottom: 2px;
            white-space: nowrap;
        }}
        .summary-card .val {{
            font-size: 1.05rem;
            font-weight: bold;
            color: #1e293b;
        }}
        .summary-card .sub-val {{
            font-size: 0.72rem;
            font-weight: bold;
        }}
        .summary-card .sub-val.cost {{ color: #e74c3c; }}
        .summary-card .sub-val.income {{ color: #2ecc71; }}
        .summary-card .note {{
            font-size: 0.65rem;
            color: #94a3b8;
            margin-top: 1px;
        }}

        .custom-legend {{
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 10px;
            margin-bottom: 15px;
            padding: 10px;
            background: #f8fafc;
            border-radius: 8px;
            font-size: 0.8rem;
            font-weight: bold;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 4px;
        }}
        .legend-color {{
            width: 12px;
            height: 12px;
            border-radius: 3px;
        }}

        .chart-layout-wrapper {{
            display: flex;
            width: 100%;
            position: relative;
            background: #fff;
        }}
        .yaxis-fixed-
