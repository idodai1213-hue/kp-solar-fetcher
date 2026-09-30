import pandas as pd
import json
import os
import math

# ---------------------------------------------------------
# 定数・単価設定 (必要に応じて変更してください)
# ---------------------------------------------------------
BUY_PRICE_PER_KWH = 31.0  # 買電単価 [円/kWh]
SELL_PRICE_PER_KWH = 16.0 # 売電単価 [円/kWh]

LATITUDE = 35.333   # 多治見市の緯度 (北緯)
LONGITUDE = 137.033 # 多治見市の経度 (東経)

PANEL_TILT_DEG = 25.0       # 屋根の傾斜角 [度]
PANEL_AZIMUTH_DEG = 142.0   # パネルの方位角 [度] (10:30ピークに補正)

# ---------------------------------------------------------
# 太陽位置およびパネル受光強度計算関数
# ---------------------------------------------------------
def calculate_panel_irradiance_score(dt, lat=LATITUDE, lon=LONGITUDE, tilt=PANEL_TILT_DEG, panel_azimuth=PANEL_AZIMUTH_DEG):
    day_of_year = dt.timetuple().tm_yday
    
    declination_deg = 23.45 * math.sin(math.radians(360 / 365.0 * (284 + day_of_year)))
    declination_rad = math.radians(declination_deg)
    
    b = math.radians((360 / 365.0) * (day_of_year - 81))
    eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    
    lstm = 135.0  # 日本標準時 (JST)
    time_offset = 4.0 * (lon - lstm) + eot
    time_hours = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    solar_time_hours = time_hours + time_offset / 60.0
    
    hour_angle_deg = (solar_time_hours - 12.0) * 15.0
    hour_angle_rad = math.radians(hour_angle_deg)
    
    lat_rad = math.radians(lat)
    
    sin_elevation = (math.sin(lat_rad) * math.sin(declination_rad) +
                     math.cos(lat_rad) * math.cos(declination_rad) * math.cos(hour_angle_rad))
    sin_elevation = max(-1.0, min(1.0, sin_elevation))
    elevation_rad = math.asin(sin_elevation)
    elevation_deg = math.degrees(elevation_rad)
    
    if elevation_deg <= 0:
        raw_score = 0.0
    else:
        cos_azimuth = (math.sin(declination_rad) * math.cos(lat_rad) - 
                       math.cos(declination_rad) * math.sin(lat_rad) * math.cos(hour_angle_rad)) / math.cos(elevation_rad)
        cos_azimuth = max(-1.0, min(1.0, cos_azimuth))
        
        azimuth_rad = math.acos(cos_azimuth)
        if hour_angle_deg > 0:
            azimuth_rad = 2 * math.pi - azimuth_rad
        
        tilt_rad = math.radians(tilt)
        panel_azimuth_rad = math.radians(panel_azimuth)
        
        cos_incidence = (math.sin(elevation_rad) * math.cos(tilt_rad) + 
                         math.cos(elevation_rad) * math.sin(tilt_rad) * math.cos(azimuth_rad - panel_azimuth_rad))
                         
        if cos_incidence < 0:
            cos_incidence = 0.0
            
        raw_score = cos_incidence * 100.0

    adjusted_score = 50.0 + (raw_score * 0.5)
    return round(adjusted_score, 2)


# 1. CSVファイルの読み込み
csv_path = os.environ.get('CSV_FILENAME', 'パワコン_2026.csv')
if not os.path.exists(csv_path):
    print(f"Error: {csv_path} が見つかりません。")
    exit(1)

try:
    df = pd.read_csv(csv_path, encoding='utf-8')
except:
    df = pd.read_csv(csv_path, encoding='shift_jis')

# 日付と時間の結合
df['日時'] = df['年月日'] + ' ' + df['時刻']
df['日時'] = pd.to_datetime(df['日時'])

df['日付'] = df['日時'].dt.strftime('%Y-%m-%d')
df['時刻_str'] = df['日時'].dt.strftime('%H:%M')
df['年月'] = df['日時'].dt.strftime('%Y-%m')
df['日時_str'] = df['日時'].dt.strftime('%Y-%m-%d %H:%M')

# パネル受光強度 (補正済み) の計算
df['仰角'] = df['日時'].apply(calculate_panel_irradiance_score)


# 2. JSONデータの作成および料金・電力量サマリー計算

# (A) 日次データ
dates = sorted(list(df['日付'].unique()), reverse=True)
daily_data = {}
for date_str in dates:
    sub_df = df[df['日付'] == date_str]
    
    gen_sum = sub_df['発電電力量[kWh]'].sum()
    buy_sum = sub_df['買電電力量[kWh]'].sum()
    sell_sum = sub_df['売電電力量[kWh]'].sum()
    cons_sum = sub_df['消費電力量[kWh]'].sum()
    
    # 自給率 = (消費量 - 買電量) / 消費量 * 100
    self_sufficiency = ((cons_sum - buy_sum) / cons_sum * 100) if cons_sum > 0 else 0
    
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
        'summary': {
            'gen': round(gen_sum, 2),
            'buy': round(buy_sum, 2),
            'sell': round(sell_sum, 2),
            'cons': round(cons_sum, 2),
            'self_ratio': round(max(0, min(100, self_sufficiency)), 1),
            'buy_cost': round(buy_sum * BUY_PRICE_PER_KWH),
            'sell_income': round(sell_sum * SELL_PRICE_PER_KWH)
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
        'summary': {
            'gen': round(gen_sum, 1),
            'buy': round(buy_sum, 1),
            'sell': round(sell_sum, 1),
            'cons': round(cons_sum, 1),
            'self_ratio': round(max(0, min(100, self_sufficiency)), 1),
            'buy_cost': round(buy_sum * BUY_PRICE_PER_KWH),
            'sell_income': round(sell_sum * SELL_PRICE_PER_KWH)
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

        /* サマリーテーブル用スタイル */
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 8px;
            margin-bottom: 15px;
            padding: 10px;
            background: #f8fafc;
            border-radius: 8px;
            border: 1px solid #e2e8f0;
        }}
        .summary-card {{
            background: #ffffff;
            padding: 8px 10px;
            border-radius: 6px;
            text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        .summary-card .label {{
            font-size: 0.75rem;
            color: #64748b;
            font-weight: bold;
            margin-bottom: 2px;
        }}
        .summary-card .val {{
            font-size: 1.1rem;
            font-weight: bold;
            color: #1e293b;
        }}
        .summary-card .sub-val {{
            font-size: 0.75rem;
            color: #e74c3c;
            font-weight: bold;
        }}
        .summary-card .sub-val.income {{
            color: #2ecc71;
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
            .summary-grid {{ grid-template-columns: repeat(3, 1fr); gap: 6px; padding: 6px; }}
            .summary-card .val {{ font-size: 0.95rem; }}
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
                
                <!-- 日次サマリーテーブル -->
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

                <!-- 月次サマリーテーブル -->
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
            elevation: '#f39c12'
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

        // サマリー描画関数
        function renderSummary(containerId, summary) {{
            const el = document.getElementById(containerId);
            el.innerHTML = `
                <div class="summary-card">
                    <div class="label">総発電量</div>
                    <div class="val" style="color: #2ecc71;">${{summary.gen.toLocaleString()}} <span style="font-size:0.75rem;">kWh</span></div>
                </div>
                <div class="summary-card">
                    <div class="label">総消費量</div>
                    <div class="val" style="color: #e67e22;">${{summary.cons.toLocaleString()}} <span style="font-size:0.75rem;">kWh</span></div>
                </div>
                <div class="summary-card">
                    <div class="label">買電量 (概算電気代)</div>
                    <div class="val" style="color: #e74c3c;">${{summary.buy.toLocaleString()}} <span style="font-size:0.75rem;">kWh</span></div>
                    <div class="sub-val">¥${{summary.buy_cost.toLocaleString()}}</div>
                </div>
                <div class="summary-card">
                    <div class="label">売電量 (売電収入)</div>
                    <div class="val" style="color: #8e44ad;">${{summary.sell.toLocaleString()}} <span style="font-size:0.75rem;">kWh</span></div>
                    <div class="sub-val income">¥${{summary.sell_income.toLocaleString()}}</div>
                </div>
                <div class="summary-card">
                    <div class="label">電力自給率</div>
                    <div class="val" style="color: #3498db;">${{summary.self_ratio}}%</div>
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

        // 日次グラフ描画
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

print("料金計算と概算サマリーテーブルを追加した index.html を生成しました！")