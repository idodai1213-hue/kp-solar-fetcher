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
def calculate_panel_irradiance_score(dt, lat=LATITUDE, lon=LONGITUDE, tilt=PANEL_TILT_DEG, panel_azimuth=PANEL_AZIMUTH_DEG):
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
    elevation_deg = math.degrees(math.asin(sin_elevation))
    
    if elevation_deg <= 0:
        raw_score = 0.0
    else:
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
                         
        if cos_incidence < 0:
            cos_incidence = 0.0
            
        raw_score = cos_incidence * 100.0

    adjusted_score = 50.0 + (raw_score * 0.5)
    return round(adjusted_score, 2)


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
# アメダスデータの読み込みと堅牢な前処理
# ---------------------------------------------------------
amedas_path = os.environ.get('AMEDAS_FILENAME', 'アメダス_2026.csv')
if os.path.exists(amedas_path):
    # エンコーディングの判定と読み込み
    try:
        # 気象庁のデータは通常 Shift_JIS (cp932)
        # 1行目が「ダウンロードした時刻：...」等のメタデータになっているため skiprows 等で適切に読み込みます
        df_amedas = pd.read_csv(
            amedas_path,
            encoding='cp932',
            skiprows=5,  # データ行の開始位置（またはヘッダーの開始行に合わせて調整）
            header=None
        )
    except Exception as e:
        # 万が一 UTF-8 で保存されていた場合のフォールバック
        df_amedas = pd.read_csv(
            amedas_path,
            encoding='utf-8',
            skiprows=5,
            header=None
        )

    # 列名のクリーニング
    df_amedas.columns = [str(c).strip() for c in df_amedas.columns]

    # 日時カラム・日照カラムの自動探索
    date_col = next((c for c in df_amedas.columns if '日時' in c or '年月日時' in c or '時間' in c or '年月' in c), df_amedas.columns[0])
    sun_col = next((c for c in df_amedas.columns if '日照' in c), None)

    # 日時変換 (変換不能な文字は NaT にして除外)
    df_amedas['日時'] = pd.to_datetime(df_amedas[date_col], errors='coerce')
    df_amedas = df_amedas.dropna(subset=['日時']).copy()

    if sun_col:
        df_amedas[sun_col] = pd.to_numeric(df_amedas[sun_col], errors='coerce').fillna(0)
        max_val = df_amedas[sun_col].max()
        df_amedas['日照強度'] = (df_amedas[sun_col] / max_val * 100.0) if max_val > 0 else 0.0
        df = pd.merge_asof(df.sort_values('日時'), df_amedas[['日時', '日照強度']].sort_values('日時'), on='日時', direction='nearest')
    else:
        df['日照強度'] = 0.0
else:
    df['日照強度'] = 0.0

df['日付'] = df['日時'].dt.strftime('%Y-%m-%d')
df['時刻_str'] = df['日時'].dt.strftime('%H:%M')
df['年月'] = df['日時'].dt.strftime('%Y-%m')
df['日時_str'] = df['日時'].dt.strftime('%Y-%m-%d %H:%M')

# 30分ごとの買電単価・コスト計算
df['買電単価'] = df['日時'].apply(get_e_life_price)
df['買電コスト'] = df['買電電力量[kWh]'] * df['買電単価']

# パネル受光強度の計算
df['仰角'] = df['日時'].apply(calculate_panel_irradiance_score)


# 2. JSONデータの作成

# (A) 日次データ
dates = sorted(list(df['日付'].unique()), reverse=True)
daily_data = {}
for date_str in dates:
    sub_df = df[df['日付'] == date_str]
    
    gen_sum = sub_df['発電電力量[kWh]'].sum()
    buy_sum = sub_df['買電電力量[kWh]'].sum()
    sell_sum = sub_df['売電電力量[kWh]'].sum()
    cons_sum = sub_df['消費電力量[kWh]'].sum()
    
    self_sufficiency = ((cons_sum - buy_sum) / cons_sum * 100) if cons_sum > 0 else 0
    buy_cost = sub_df['買電コスト'].sum()
    sell_income = sell_sum * SELL_PRICE_PER_KWH
    
    daily_data[date_str] = {
        'time': sub_df['時刻_str'].tolist(),
        'generation': sub_df['発電電力量[kWh]'].tolist(),
        'buy': sub_df['買電電力量[kWh]'].tolist(),
        'discharging': sub_df['放電電力量[kWh]'].tolist(),
        'consumption': (-sub_df['消費電力量[kWh]']).tolist(),
        'sell': (-sub_df['売電電力量[kWh]']).tolist(),
        'charging': (-sub_df['充電電力量[kWh]']).tolist(),
        'soc': sub_df['蓄電残量(SOC)[%]'].tolist(),
        'elevation': sub_df['仰角'].tolist(),
        'sunshine': sub_df['日照強度'].round(1).tolist(),
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
        'elevation': sub_df['仰角'].tolist(),
        'sunshine': sub_df['日照強度'].round(1).tolist(),
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

# 3. HTMLテンプレートの作成
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
        .yaxis-fixed-left {{
            width: 55px;
            flex-shrink: 0;
            z-index: 10;
            background: #fff;
        }}
        .yaxis-fixed-right {{
            width: 55px;
            flex-shrink: 0;
            z-index: 10;
            background: #fff;
        }}
        .chart-scroll-center {{
            flex-grow: 1;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            touch-action: pan-x pan-y;
        }}
        .chart-inner-content {{
            min-width: 100%;
        }}

        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}

        @media (max-width: 600px) {{
            body {{ padding: 5px; }}
            .card {{ padding: 10px 4px; }}
            .yaxis-fixed-left, .yaxis-fixed-right {{ width: 48px; }}
            .summary-grid {{ gap: 5px; padding: 5px; }}
            .summary-card .val {{ font-size: 0.90rem; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>☀️ 太陽光発電 収支ダッシュボード</h1>
            
            <div class="tabs">
                <button class="tab-btn active" onclick="switchTab('daily')">日次 (24時間)</button>
                <button class="tab-btn" onclick="switchTab('monthly')">月次 (31日間・30分刻み)</button>
            </div>

            <div class="custom-legend" id="sharedLegend">
                <div class="legend-item"><div class="legend-color" style="background: rgba(255, 223, 0, 0.6); border: 1px solid #f1c40f;"></div>日照強度 (アメダス)</div>
                <div class="legend-item"><div class="legend-color" style="background: #2ecc71;"></div>発電(+)</div>
                <div class="legend-item"><div class="legend-color" style="background: #1e8449;"></div>放電(+)</div>
                <div class="legend-item"><div class="legend-color" style="background: #e74c3c;"></div>買電(+)</div>
                <div class="legend-item"><div class="legend-color" style="background: #e67e22;"></div>消費(-)</div>
                <div class="legend-item"><div class="legend-color" style="background: #3498db;"></div>充電(-)</div>
                <div class="legend-item"><div class="legend-color" style="background: #8e44ad;"></div>売電(-)</div>
                <div class="legend-item"><div class="legend-color" style="background: #2c3e50;"></div>蓄電SOC[%]</div>
                <div class="legend-item"><div class="legend-color" style="background: #f39c12;"></div>受光強度(10:30ピーク/25°)</div>
            </div>

            <!-- 日次コンテンツ -->
            <div id="dailyTab" class="tab-content active">
                <div class="controls">
                    <label for="dateSelect"><strong>日付選択:</strong></label>
                    <select id="dateSelect" onchange="updateDailyChart()"></select>
                </div>
                
                <div class="summary-grid" id="dailySummary"></div>

                <div class="chart-layout-wrapper">
                    <div id="dailyYLeft" class="yaxis-fixed-left"></div>
                    <div class="chart-scroll-center">
                        <div id="dailyChartCenter" style="width: 100%; height: 460px;"></div>
                    </div>
                    <div id="dailyYRight" class="yaxis-fixed-right"></div>
                </div>
            </div>

            <!-- 月次コンテンツ -->
            <div id="monthlyTab" class="tab-content">
                <div class="controls">
                    <label for="monthSelect"><strong>年月選択:</strong></label>
                    <select id="monthSelect" onchange="updateMonthlyChart()"></select>
                </div>

                <div class="summary-grid" id="monthlySummary"></div>

                <div class="chart-layout-wrapper">
                    <div id="monthlyYLeft" class="yaxis-fixed-left"></div>
                    <div class="chart-scroll-center">
                        <div id="monthlyChartInner" class="chart-inner-content">
                            <div id="monthlyChartCenter" style="height: 460px;"></div>
                        </div>
                    </div>
                    <div id="monthlyYRight" class="yaxis-fixed-right"></div>
                </div>
            </div>

        </div>
    </div>

    <script>
        const rawDailyData = {json_daily_data};
        const dates = {json_dates};
        const rawMonthlyData = {json_monthly_data};
        const months = {json_months};

        const colors = {{
            gen: '#2ecc71',
            discharge: '#1e8449',
            buy: '#e74c3c',
            cons: '#e67e22',
            charge: '#3498db',
            sell: '#8e44ad',
            soc: '#2c3e50',
            elevation: '#f39c12',
            sunshineFill: 'rgba(255, 223, 0, 0.25)',
            sunshineLine: 'rgba(241, 196, 15, 0.6)'
        }};

        const dateSelect = document.getElementById('dateSelect');
        dates.forEach(d => {{
            const opt = document.createElement('option');
            opt.value = d;
            opt.textContent = d;
            dateSelect.appendChild(opt);
        }});

        const monthSelect = document.getElementById('monthSelect');
        months.forEach(m => {{
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            monthSelect.appendChild(opt);
        }});

        function switchTab(tabName) {{
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

            if (tabName === 'daily') {{
                document.querySelectorAll('.tab-btn')[0].classList.add('active');
                document.getElementById('dailyTab').classList.add('active');
                updateDailyChart();
            }} else {{
                document.querySelectorAll('.tab-btn')[1].classList.add('active');
                document.getElementById('monthlyTab').classList.add('active');
                updateMonthlyChart();
            }}
        }}

        function renderSummary(containerId, summary) {{
            const el = document.getElementById(containerId);
            
            const netPowerSign = summary.net_power > 0 ? '+' : '';
            const netCostSign = summary.net_cost > 0 ? '+' : '';
            const netCostClass = summary.net_cost >= 0 ? 'income' : 'cost';

            const buyNote = summary.is_monthly ? `<div class="note">(基本料 ¥${{summary.basic_charge.toLocaleString()}}込)</div>` : `<div class="note">(eライフ従量計算)</div>`;
            const netNote = summary.is_monthly ? `<div class="note">(基本料考慮後)</div>` : ``;

            el.innerHTML = `
                <div class="summary-card">
                    <div class="label">総発電量</div>
                    <div class="val" style="color: #2ecc71;">${{summary.gen.toLocaleString()}} <span style="font-size:0.7rem;">kWh</span></div>
                </div>
                <div class="summary-card">
                    <div class="label">総買電量</div>
                    <div class="val" style="color: #e74c3c;">${{summary.buy.toLocaleString()}} <span style="font-size:0.7rem;">kWh</span></div>
                    <div class="sub-val cost">¥${{summary.buy_cost.toLocaleString()}}</div>
                    ${{buyNote}}
                </div>
                <div class="summary-card">
                    <div class="label">電力自給率</div>
                    <div class="val" style="color: #27ae60;">${{summary.self_ratio}}%</div>
                </div>
                <div class="summary-card">
                    <div class="label">総消費量</div>
                    <div class="val" style="color: #e67e22;">${{summary.cons.toLocaleString()}} <span style="font-size:0.7rem;">kWh</span></div>
                </div>
                <div class="summary-card">
                    <div class="label">総売電量</div>
                    <div class="val" style="color: #8e44ad;">${{summary.sell.toLocaleString()}} <span style="font-size:0.7rem;">kWh</span></div>
                    <div class="sub-val income">¥${{summary.sell_income.toLocaleString()}}</div>
                </div>
                <div class="summary-card">
                    <div class="label">電力収支 (売-買)</div>
                    <div class="val" style="color: #2c3e50;">${{netPowerSign}}${{summary.net_power.toLocaleString()}} <span style="font-size:0.7rem;">kWh</span></div>
                    <div class="sub-val ${{netCostClass}}">${{netCostSign}}¥${{summary.net_cost.toLocaleString()}}</div>
                    ${{netNote}}
                </div>
            `;
        }}

        function getPowerRange(data) {{
            let maxPos = 0;
            let maxNeg = 0;
            for (let i = 0; i < data.time.length; i++) {{
                let posSum = (data.generation[i] || 0) + (data.discharging[i] || 0) + (data.buy[i] || 0);
                let negSum = Math.abs((data.consumption[i] || 0) + (data.charging[i] || 0) + (data.sell[i] || 0));
                if (posSum > maxPos) maxPos = posSum;
                if (negSum > maxNeg) maxNeg = negSum;
            }}
            let limit = Math.ceil(Math.max(maxPos, maxNeg, 1.5) * 1.1 * 10) / 10;
            return [-limit, limit];
        }}

        function getPowerRangeMonthly(data) {{
            let maxPos = 0;
            let maxNeg = 0;
            for (let i = 0; i < data.datetime.length; i++) {{
                let posSum = (data.generation[i] || 0) + (data.discharging[i] || 0) + (data.buy[i] || 0);
                let negSum = Math.abs((data.consumption[i] || 0) + (data.charging[i] || 0) + (data.sell[i] || 0));
                if (posSum > maxPos) maxPos = posSum;
                if (negSum > maxNeg) maxNeg = negSum;
            }}
            let limit = Math.ceil(Math.max(maxPos, maxNeg, 1.5) * 1.1 * 10) / 10;
            return [-limit, limit];
        }}

        function updateDailyChart() {{
            const selectedDate = dateSelect.value;
            const data = rawDailyData[selectedDate];
            if (!data) return;

            renderSummary('dailySummary', data.summary);

            const yRange = getPowerRange(data);

            Plotly.newPlot('dailyYLeft', [], {{
                margin: {{ t: 40, r: 0, l: 45, b: 80 }},
                height: 460,
                yaxis: {{ title: '電力量 [kWh]', range: yRange, fixedrange: true, zeroline: true, zerolinewidth: 2, zerolinecolor: '#333' }},
                xaxis: {{ visible: false, fixedrange: true }}
            }}, {{ displayModeBar: false }});

            Plotly.newPlot('dailyYRight', [], {{
                margin: {{ t: 40, r: 45, l: 0, b: 80 }},
                height: 460,
                yaxis: {{ title: 'SOC / 受光強度 [%]', range: [0, 100], side: 'right', fixedrange: true, showgrid: false }},
                xaxis: {{ visible: false, fixedrange: true }}
            }}, {{ displayModeBar: false }});

            const traces = [
                {{
                    x: data.time,
                    y: data.sunshine,
                    name: '日照強度 (サニーイエロー)',
                    type: 'scatter',
                    mode: 'lines',
                    fill: 'tozeroy',
                    fillcolor: colors.sunshineFill,
                    line: {{ color: colors.sunshineLine, width: 1 }},
                    yaxis: 'y2',
                    hovertemplate: '%{{x}}<br>日照強度: %{{y}}%<extra></extra>'
                }},
                {{ x: data.time, y: data.generation, name: '発電(+)', type: 'bar', marker: {{ color: colors.gen }} }},
                {{ x: data.time, y: data.discharging, name: '放電(+)', type: 'bar', marker: {{ color: colors.discharge }} }},
                {{ x: data.time, y: data.buy, name: '買電(+)', type: 'bar', marker: {{ color: colors.buy }} }},
                {{ x: data.time, y: data.consumption, name: '消費(-)', type: 'bar', marker: {{ color: colors.cons }} }},
                {{ x: data.time, y: data.charging, name: '充電(-)', type: 'bar', marker: {{ color: colors.charge }} }},
                {{ x: data.time, y: data.sell, name: '売電(-)', type: 'bar', marker: {{ color: colors.sell }} }},
                {{ x: data.time, y: data.soc, name: '蓄電SOC[%]', type: 'scatter', mode: 'lines+markers', yaxis: 'y2', line: {{ color: colors.soc, width: 2 }}, marker: {{ size: 4 }} }},
                {{ 
                    x: data.time, 
                    y: data.elevation, 
                    name: '受光強度', 
                    type: 'scatter', 
                    mode: 'lines', 
                    yaxis: 'y2', 
                    line: {{ color: colors.elevation, width: 2, dash: 'dot' }},
                    hovertemplate: '%{{x}}<br>受光強度: %{{y}}%<extra></extra>'
                }}
            ];

            const layout = {{
                title: selectedDate + ' (30分粒度)',
                margin: {{ t: 40, r: 10, l: 10, b: 80 }},
                height: 460,
                showlegend: false,
                dragmode: false,
                xaxis: {{ title: '時刻', tickangle: -45, nticks: 24, fixedrange: true }},
                yaxis: {{ range: yRange, showticklabels: false, zeroline: true, zerolinewidth: 2, zerolinecolor: '#333', fixedrange: true }},
                yaxis2: {{ range: [0, 100], side: 'right', overlaying: 'y', showticklabels: false, showgrid: false, fixedrange: true }},
                barmode: 'relative',
                autosize: true
            }};

            Plotly.newPlot('dailyChartCenter', traces, layout, {{ responsive: true, displayModeBar: false, scrollZoom: false }});
        }}

        function updateMonthlyChart() {{
            const selectedMonth = monthSelect.value;
            const data = rawMonthlyData[selectedMonth];
            if (!data) return;

            renderSummary('monthlySummary', data.summary);

            const minWidth = Math.max(900, data.datetime.length * 5.625);
            document.getElementById('monthlyChartInner').style.width = minWidth + 'px';

            const yRange = getPowerRangeMonthly(data);

            Plotly.newPlot('monthlyYLeft', [], {{
                margin: {{ t: 40, r: 0, l: 45, b: 90 }},
                height: 460,
                yaxis: {{ title: '電力量 [kWh]', range: yRange, fixedrange: true, zeroline: true, zerolinewidth: 2, zerolinecolor: '#333' }},
                xaxis: {{ visible: false, fixedrange: true }}
            }}, {{ displayModeBar: false }});

            Plotly.newPlot('monthlyYRight', [], {{
                margin: {{ t: 40, r: 45, l: 0, b: 90 }},
                height: 460,
                yaxis: {{ title: 'SOC / 受光強度 [%]', range: [0, 100], side: 'right', fixedrange: true, showgrid: false }},
                xaxis: {{ visible: false, fixedrange: true }}
            }}, {{ displayModeBar: false }});

            const traces = [
                {{
                    x: data.datetime,
                    y: data.sunshine,
                    name: '日照強度 (サニーイエロー)',
                    type: 'scatter',
                    mode: 'lines',
                    fill: 'tozeroy',
                    fillcolor: colors.sunshineFill,
                    line: {{ color: colors.sunshineLine, width: 1 }},
                    yaxis: 'y2',
                    hovertemplate: '%{{x}}<br>日照強度: %{{y}}%<extra></extra>'
                }},
                {{ x: data.datetime, y: data.generation, name: '発電(+)', type: 'bar', marker: {{ color: colors.gen }} }},
                {{ x: data.datetime, y: data.discharging, name: '放電(+)', type: 'bar', marker: {{ color: colors.discharge }} }},
                {{ x: data.datetime, y: data.buy, name: '買電(+)', type: 'bar', marker: {{ color: colors.buy }} }},
                {{ x: data.datetime, y: data.consumption, name: '消費(-)', type: 'bar', marker: {{ color: colors.cons }} }},
                {{ x: data.datetime, y: data.charging, name: '充電(-)', type: 'bar', marker: {{ color: colors.charge }} }},
                {{ x: data.datetime, y: data.sell, name: '売電(-)', type: 'bar', marker: {{ color: colors.sell }} }},
                {{ x: data.datetime, y: data.soc, name: '蓄電SOC[%]', type: 'scatter', mode: 'lines', yaxis: 'y2', line: {{ color: colors.soc, width: 1.2 }} }},
                {{ 
                    x: data.datetime, 
                    y: data.elevation, 
                    name: '受光強度', 
                    type: 'scatter', 
                    mode: 'lines', 
                    yaxis: 'y2', 
                    line: {{ color: colors.elevation, width: 1.2, dash: 'dot' }},
                    hovertemplate: '%{{x}}<br>受光強度: %{{y}}%<extra></extra>'
                }}
            ];

            const layout = {{
                title: selectedMonth + ' 月間電力バランス (30分刻み)',
                margin: {{ t: 40, r: 10, l: 10, b: 90 }},
                height: 460,
                showlegend: false,
                dragmode: false,
                bargap: 0.15,
                bargroupgap: 0,
                xaxis: {{ 
                    title: '日時 (MM/DD HH:MM)', 
                    tickangle: -45,
                    type: 'date',
                    dtick: 6 * 3600 * 1000,
                    tickformat: '%m/%d %H:%M',
                    fixedrange: true
                }},
                yaxis: {{ range: yRange, showticklabels: false, zeroline: true, zerolinewidth: 2, zerolinecolor: '#333', fixedrange: true }},
                yaxis2: {{ range: [0, 100], side: 'right', overlaying: 'y', showticklabels: false, showgrid: false, fixedrange: true }},
                barmode: 'relative'
            }};

            Plotly.newPlot('monthlyChartCenter', traces, layout, {{ responsive: true, displayModeBar: false, scrollZoom: false }});
        }}

        if (dates.length > 0) updateDailyChart();
    </script>
</body>
</html>
"""

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html_content)

print("アメダスデータの日照シェード(サニーイエロー)を適用した index.html を作成しました！")
