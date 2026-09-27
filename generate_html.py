import pandas as pd
import json
import os
import math

# ---------------------------------------------------------
# 太陽位置およびパネル受光強度計算関数 (多治見市 / 南南東 / 傾斜25度)
# ---------------------------------------------------------
LATITUDE = 35.333   # 多治見市の緯度 (北緯)
LONGITUDE = 137.033 # 多治見市の経度 (東経)

PANEL_TILT_DEG = 25.0       # 屋根の傾斜角 [度]
PANEL_AZIMUTH_DEG = 157.5   # パネルの方位角 [度] (南:180°, 南南東:157.5°)

def calculate_panel_irradiance_score(dt, lat=LATITUDE, lon=LONGITUDE, tilt=PANEL_TILT_DEG, panel_azimuth=PANEL_AZIMUTH_DEG):
    """
    指定日時の太陽位置（高度角・方位角）から、南南東・25度傾斜パネルへの受光強度(0〜100)を算出する。
    100 = パネル面に完全に垂直に光が射し込む（最大効率）
    0   = 夜間またはパネルの裏側に太陽がある状態
    """
    day_of_year = dt.timetuple().tm_yday
    
    # 1. 太陽赤緯 [rad]
    declination_deg = 23.45 * math.sin(math.radians(360 / 365.0 * (284 + day_of_year)))
    declination_rad = math.radians(declination_deg)
    
    # 2. 均時差 [分]
    b = math.radians((360 / 365.0) * (day_of_year - 81))
    eot = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
    
    # 3. 時角 [rad]
    lstm = 135.0  # 日本標準時 (JST)
    time_offset = 4.0 * (lon - lstm) + eot
    time_hours = dt.hour + dt.minute / 60.0 + dt.second / 3600.0
    solar_time_hours = time_hours + time_offset / 60.0
    
    hour_angle_deg = (solar_time_hours - 12.0) * 15.0
    hour_angle_rad = math.radians(hour_angle_deg)
    
    lat_rad = math.radians(lat)
    
    # 4. 太陽高度角 (Elevation)
    sin_elevation = (math.sin(lat_rad) * math.sin(declination_rad) +
                     math.cos(lat_rad) * math.cos(declination_rad) * math.cos(hour_angle_rad))
    sin_elevation = max(-1.0, min(1.0, sin_elevation))
    elevation_rad = math.asin(sin_elevation)
    elevation_deg = math.degrees(elevation_rad)
    
    # 太陽が地平線下にある場合は 0
    if elevation_deg <= 0:
        return 0.0
        
    # 5. 太陽方位角 (Azimuth: 北=0, 東=90, 南=180, 西=270)
    cos_azimuth = (math.sin(declination_rad) * math.cos(lat_rad) - 
                   math.cos(declination_rad) * math.sin(lat_rad) * math.cos(hour_angle_rad)) / math.cos(elevation_rad)
    cos_azimuth = max(-1.0, min(1.0, cos_azimuth))
    
    azimuth_rad = math.acos(cos_azimuth)
    if hour_angle_deg > 0:
        azimuth_rad = 2 * math.pi - azimuth_rad
    solar_azimuth_deg = math.degrees(azimuth_rad)
    
    # 6. 面受光角の計算 (パネル法線と太陽光線のベクトル内積)
    tilt_rad = math.radians(tilt)
    panel_azimuth_rad = math.radians(panel_azimuth)
    
    cos_incidence = (math.sin(elevation_rad) * math.cos(tilt_rad) + 
                     math.cos(elevation_rad) * math.sin(tilt_rad) * math.cos(azimuth_rad - panel_azimuth_rad))
                     
    # 裏から光が入るか地表下なら 0 に丸める
    if cos_incidence < 0:
        cos_incidence = 0.0
        
    # 0〜100 のスケール値に変換
    score = cos_incidence * 100.0
    return round(score, 2)


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


# 2. JSONデータの作成

# (A) 日次データ (30分粒度)
dates = sorted(list(df['日付'].unique()), reverse=True)
daily_data = {}
for date_str in dates:
    sub_df = df[df['日付'] == date_str]
    daily_data[date_str] = {
        'time': sub_df['時刻_str'].tolist(),
        'generation': sub_df['発電電力量[kWh]'].tolist(),
        'buy': sub_df['買電電力量[kWh]'].tolist(),
        'discharging': sub_df['放電電力量[kWh]'].tolist(),
        'consumption': (-sub_df['消費電力量[kWh]']).tolist(),
        'sell': (-sub_df['売電電力量[kWh]']).tolist(),
        'charging': (-sub_df['充電電力量[kWh]']).tolist(),
        'soc': sub_df['蓄電残量(SOC)[%]'].tolist(),
        'elevation': sub_df['仰角'].tolist()
    }

# (B) 月次データ (30分粒度)
months = sorted(list(df['年月'].unique()), reverse=True)
monthly_data = {}
for month_str in months:
    sub_df = df[df['年月'] == month_str]
    monthly_data[month_str] = {
        'datetime': sub_df['日時_str'].tolist(),
        'generation': sub_df['発電電力量[kWh]'].tolist(),
        'buy': sub_df['買電電力量[kWh]'].tolist(),
        'discharging': sub_df['放電電力量[kWh]'].tolist(),
        'consumption': (-sub_df['消費電力量[kWh]']).tolist(),
        'sell': (-sub_df['売電電力量[kWh]'].tolist(),
        'charging': (-sub_df['充電電力量[kWh]']).tolist(),
        'soc': sub_df['蓄電残量(SOC)[%]'].tolist(),
        'elevation': sub_df['仰角'].tolist()
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
    <!-- スマホホーム画面用アイコン設定 -->
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
        /* 外部共通凡例エリア */
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

        /* --- 3カラム（Y軸両端固定）レイアウト構造 --- */
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
            body {{
                padding: 5px;
            }}
            .card {{
                padding: 10px 4px;
            }}
            .yaxis-fixed-left, .yaxis-fixed-right {{
                width: 48px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>☀️ 太陽光発電 収支ダッシュボード</h1>
            
            <!-- タブ切り替えボタン -->
            <div class="tabs">
                <button class="tab-btn active" onclick="switchTab('daily')">日次 (24時間)</button>
                <button class="tab-btn" onclick="switchTab('monthly')">月次 (31日間・30分刻み)</button>
            </div>

            <!-- 常時表示される外部共通凡例 -->
            <div class="custom-legend" id="sharedLegend">
                <div class="legend-item"><div class="legend-color" style="background: #2ecc71;"></div>発電(+)</div>
                <div class="legend-item"><div class="legend-color" style="background: #1e8449;"></div>放電(+)</div>
                <div class="legend-item"><div class="legend-color" style="background: #e74c3c;"></div>買電(+)</div>
                <div class="legend-item"><div class="legend-color" style="background: #e67e22;"></div>消費(-)</div>
                <div class="legend-item"><div class="legend-color" style="background: #3498db;"></div>充電(-)</div>
                <div class="legend-item"><div class="legend-color" style="background: #8e44ad;"></div>売電(-)</div>
                <div class="legend-item"><div class="legend-color" style="background: #2c3e50;"></div>蓄電SOC[%]</div>
                <div class="legend-item"><div class="legend-color" style="background: #f39c12;"></div>受光強度(南南東/25°)</div>
            </div>

            <!-- 日次コンテンツ -->
            <div id="dailyTab" class="tab-content active">
                <div class="controls">
                    <label for="dateSelect"><strong>日付選択:</strong></label>
                    <select id="dateSelect" onchange="updateDailyChart()"></select>
                </div>
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

        // セレクトボックス初期化
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

        // Y軸範囲算出ヘルパー関数
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

        // --- 日次グラフ描画 ---
        function updateDailyChart() {{
            const selectedDate = dateSelect.value;
            const data = rawDailyData[selectedDate];
            if (!data) return;

            const yRange = getPowerRange(data);

            // 1. 左Y軸 (固定)
            Plotly.newPlot('dailyYLeft', [], {{
                margin: {{ t: 40, r: 0, l: 45, b: 80 }},
                height: 460,
                yaxis: {{ title: '電力量 [kWh]', range: yRange, fixedrange: true, zeroline: true, zerolinewidth: 2, zerolinecolor: '#333' }},
                xaxis: {{ visible: false, fixedrange: true }}
            }}, {{ displayModeBar: false }});

            // 2. 右Y軸 (固定)
            Plotly.newPlot('dailyYRight', [], {{
                margin: {{ t: 40, r: 45, l: 0, b: 80 }},
                height: 460,
                yaxis: {{ title: 'SOC / 受光強度 [%]', range: [0, 100], side: 'right', fixedrange: true, showgrid: false }},
                xaxis: {{ visible: false, fixedrange: true }}
            }}, {{ displayModeBar: false }});

            // 3. 中央プロット領域 (グラフ本体)
            const traces = [
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

        // --- 月次グラフ描画 ---
        function updateMonthlyChart() {{
            const selectedMonth = monthSelect.value;
            const data = rawMonthlyData[selectedMonth];
            if (!data) return;

            const minWidth = Math.max(2400, data.datetime.length * 15);
            document.getElementById('monthlyChartInner').style.width = minWidth + 'px';

            const yRange = getPowerRangeMonthly(data);

            // 1. 左Y軸 (固定)
            Plotly.newPlot('monthlyYLeft', [], {{
                margin: {{ t: 40, r: 0, l: 45, b: 90 }},
                height: 460,
                yaxis: {{ title: '電力量 [kWh]', range: yRange, fixedrange: true, zeroline: true, zerolinewidth: 2, zerolinecolor: '#333' }},
                xaxis: {{ visible: false, fixedrange: true }}
            }}, {{ displayModeBar: false }});

            // 2. 右Y軸 (固定)
            Plotly.newPlot('monthlyYRight', [], {{
                margin: {{ t: 40, r: 45, l: 0, b: 90 }},
                height: 460,
                yaxis: {{ title: 'SOC / 受光強度 [%]', range: [0, 100], side: 'right', fixedrange: true, showgrid: false }},
                xaxis: {{ visible: false, fixedrange: true }}
            }}, {{ displayModeBar: false }});

            // 3. 中央プロット領域
            const traces = [
                {{ x: data.datetime, y: data.generation, name: '発電(+)', type: 'bar', marker: {{ color: colors.gen }} }},
                {{ x: data.datetime, y: data.discharging, name: '放電(+)', type: 'bar', marker: {{ color: colors.discharge }} }},
                {{ x: data.datetime, y: data.buy, name: '買電(+)', type: 'bar', marker: {{ color: colors.buy }} }},
                {{ x: data.datetime, y: data.consumption, name: '消費(-)', type: 'bar', marker: {{ color: colors.cons }} }},
                {{ x: data.datetime, y: data.charging, name: '充電(-)', type: 'bar', marker: {{ color: colors.charge }} }},
                {{ x: data.datetime, y: data.sell, name: '売電(-)', type: 'bar', marker: {{ color: colors.sell }} }},
                {{ x: data.datetime, y: data.soc, name: '蓄電SOC[%]', type: 'scatter', mode: 'lines', yaxis: 'y2', line: {{ color: colors.soc, width: 1.5 }} }},
                {{ 
                    x: data.datetime, 
                    y: data.elevation, 
                    name: '受光強度', 
                    type: 'scatter', 
                    mode: 'lines', 
                    yaxis: 'y2', 
                    line: {{ color: colors.elevation, width: 1.5, dash: 'dot' }},
                    hovertemplate: '%{{x}}<br>受光強度: %{{y}}%<extra></extra>'
                }}
            ];

            const layout = {{
                title: selectedMonth + ' 月間電力バランス (30分刻み)',
                margin: {{ t: 40, r: 10, l: 10, b: 90 }},
                height: 460,
                showlegend: false,
                dragmode: false,
                xaxis: {{ 
                    title: '日時 (MM/DD HH:MM)', 
                    tickangle: -45,
                    type: 'date',
                    dtick: 2 * 3600 * 1000,
                    tickformat: '%m/%d %H:%M',
                    fixedrange: true
                }},
                yaxis: {{ range: yRange, showticklabels: false, zeroline: true, zerolinewidth: 2, zerolinecolor: '#333', fixedrange: true }},
                yaxis2: {{ range: [0, 100], side: 'right', overlaying: 'y', showticklabels: false, showgrid: false, fixedrange: true }},
                barmode: 'relative'
            }};

            Plotly.newPlot('monthlyChartCenter', traces, layout, {{ responsive: true, displayModeBar: false, scrollZoom: false }});
        }}

        // 初期表示
        if (dates.length > 0) updateDailyChart();
    </script>
</body>
</html>
"""

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html_content)

print("多治見市・南南東・25度傾斜パネルへの受光強度を反映した index.html を生成しました！")
