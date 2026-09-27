import pandas as pd
import json
import os

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
        'soc': sub_df['蓄電残量(SOC)[%]'].tolist()
    }

# (B) 月次データ (30分粒度に変更)
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
        'sell': (-sub_df['売電電力量[kWh]']).tolist(),
        'charging': (-sub_df['充電電力量[kWh]']).tolist(),
        'soc': sub_df['蓄電残量(SOC)[%]'].tolist()
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>太陽光発電 収支モニタリング</title>
    <!-- スマホホーム画面用アイコン設定 (ライトモード対応) -->
    <link rel="apple-touch-icon" href="solar_dashboard_icon_light.png">
    <link rel="icon" type="image/png" href="solar_dashboard_icon_light.png">
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 15px;
            background-color: #f4f7f9;
            color: #333;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        .card {{
            background: #fff;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            margin-bottom: 20px;
        }}
        h1 {{
            font-size: 1.5rem;
            margin-top: 0;
            color: #2c3e50;
            text-align: center;
        }}
        .tabs {{
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-bottom: 20px;
        }}
        .tab-btn {{
            padding: 10px 24px;
            font-size: 1rem;
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
            margin-bottom: 15px;
        }}
        select {{
            padding: 8px 16px;
            font-size: 1rem;
            border-radius: 8px;
            border: 1px solid #ccc;
            background-color: #fff;
        }}
        /* 外部共通凡例エリア（スクロールしても常に表示） */
        .custom-legend {{
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 12px;
            margin-bottom: 15px;
            padding: 10px;
            background: #f8fafc;
            border-radius: 8px;
            font-size: 0.85rem;
            font-weight: bold;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .legend-color {{
            width: 14px;
            height: 14px;
            border-radius: 3px;
        }}
        .chart-scroll-wrapper {{
            width: 100%;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }}
        .chart-inner {{
            min-width: 100%;
        }}
        #dailyChart, #monthlyChart {{
            width: 100%;
            height: 520px;
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        @media (max-width: 600px) {{
            #dailyChart, #monthlyChart {{
                height: 450px;
            }}
            body {{
                padding: 8px;
            }}
            .card {{
                padding: 10px;
            }}
            .custom-legend {{
                font-size: 0.75rem;
                gap: 8px;
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
            </div>

            <!-- 日次コンテンツ -->
            <div id="dailyTab" class="tab-content active">
                <div class="controls">
                    <label for="dateSelect"><strong>日付選択:</strong></label>
                    <select id="dateSelect" onchange="updateDailyChart()"></select>
                </div>
                <div id="dailyChart"></div>
            </div>

            <!-- 月次コンテンツ -->
            <div id="monthlyTab" class="tab-content">
                <div class="controls">
                    <label for="monthSelect"><strong>年月選択:</strong></label>
                    <select id="monthSelect" onchange="updateMonthlyChart()"></select>
                </div>
                <div class="chart-scroll-wrapper">
                    <div id="monthlyChartInner" class="chart-inner">
                        <div id="monthlyChart"></div>
                    </div>
                </div>
            </div>

        </div>
    </div>

    <script>
        const rawDailyData = {json_daily_data};
        const dates = {json_dates};
        const rawMonthlyData = {json_monthly_data};
        const months = {json_months};

        // カラー定義（統一）
        const colors = {{
            gen: '#2ecc71',      // 発電: 明るい緑
            discharge: '#1e8449',// 放電: 深緑
            buy: '#e74c3c',      // 買電: 赤
            cons: '#e67e22',     // 消費: オレンジ
            charge: '#3498db',   // 充電: 青
            sell: '#8e44ad',     // 売電: 紫
            soc: '#2c3e50'       // SOC: 紺
        }};

        // --- セレクトボックス初期化 ---
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

        // --- タブ切り替えロジック ---
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

        // --- 日次グラフ描画 ---
        function updateDailyChart() {{
            const selectedDate = dateSelect.value;
            const data = rawDailyData[selectedDate];
            if (!data) return;

            const traces = [
                {{ x: data.time, y: data.generation, name: '発電(+)', type: 'bar', marker: {{ color: colors.gen }} }},
                {{ x: data.time, y: data.discharging, name: '放電(+)', type: 'bar', marker: {{ color: colors.discharge }} }},
                {{ x: data.time, y: data.buy, name: '買電(+)', type: 'bar', marker: {{ color: colors.buy }} }},
                {{ x: data.time, y: data.consumption, name: '消費(-)', type: 'bar', marker: {{ color: colors.cons }} }},
                {{ x: data.time, y: data.charging, name: '充電(-)', type: 'bar', marker: {{ color: colors.charge }} }},
                {{ x: data.time, y: data.sell, name: '売電(-)', type: 'bar', marker: {{ color: colors.sell }} }},
                {{ x: data.time, y: data.soc, name: '蓄電SOC[%]', type: 'scatter', mode: 'lines+markers', yaxis: 'y2', line: {{ color: colors.soc, width: 2 }}, marker: {{ size: 4 }} }}
            ];

            const layout = {{
                title: selectedDate + ' の電力バランス (30分粒度)',
                margin: {{ t: 40, r: 50, l: 50, b: 40 }},
                showlegend: false, // 外部共通凡例を使うため内蔵レジェンドは非表示
                xaxis: {{ title: '時刻', fixedrange: true }}, // ズーム無効化
                yaxis: {{ title: '電力量 [kWh]', side: 'left', zeroline: true, zerolinewidth: 2, zerolinecolor: '#333', fixedrange: true }},
                yaxis2: {{ title: '蓄電残量 (SOC) [%]', side: 'right', overlaying: 'y', range: [0, 100], showgrid: false, fixedrange: true }},
                barmode: 'relative',
                autosize: true
            }};

            Plotly.newPlot('dailyChart', traces, layout, {{ responsive: true, displayModeBar: false }});
        }}

        // --- 月次グラフ描画 (30分刻み・横スクロール対応) ---
        function updateMonthlyChart() {{
            const selectedMonth = monthSelect.value;
            const data = rawMonthlyData[selectedMonth];
            if (!data) return;

            // 30分粒度（1日48コマ×31日＝最大約1488点）に合わせた動的横幅（1点あたり約10px）
            const minWidth = Math.max(1200, data.datetime.length * 10);
            document.getElementById('monthlyChartInner').style.width = minWidth + 'px';

            const traces = [
                {{ x: data.datetime, y: data.generation, name: '発電(+)', type: 'bar', marker: {{ color: colors.gen }} }},
                {{ x: data.datetime, y: data.discharging, name: '放電(+)', type: 'bar', marker: {{ color: colors.discharge }} }},
                {{ x: data.datetime, y: data.buy, name: '買電(+)', type: 'bar', marker: {{ color: colors.buy }} }},
                {{ x: data.datetime, y: data.consumption, name: '消費(-)', type: 'bar', marker: {{ color: colors.cons }} }},
                {{ x: data.datetime, y: data.datetime ? data.charging : [], name: '充電(-)', type: 'bar', marker: {{ color: colors.charge }} }},
                {{ x: data.datetime, y: data.sell, name: '売電(-)', type: 'bar', marker: {{ color: colors.sell }} }},
                {{ x: data.datetime, y: data.soc, name: '蓄電SOC[%]', type: 'scatter', mode: 'lines', yaxis: 'y2', line: {{ color: colors.soc, width: 1.5 }} }}
            ];

            const layout = {{
                title: selectedMonth + ' 月間電力バランス (30分刻み)',
                margin: {{ t: 40, r: 50, l: 50, b: 80 }},
                showlegend: false, // 外部共通凡例を使うため非表示
                xaxis: {{ 
                    title: '日時 (MM/DD HH:MM)', 
                    tickangle: -45,
                    fixedrange: true, // ズーム無効化
                    rangeslider: {{ visible: true }} // 下部ミニナビゲーションスライダー
                }},
                yaxis: {{ title: '電力量 [kWh]', side: 'left', zeroline: true, zerolinewidth: 2, zerolinecolor: '#333', fixedrange: true }},
                yaxis2: {{ title: '蓄電残量 (SOC) [%]', side: 'right', overlaying: 'y', range: [0, 100], showgrid: false, fixedrange: true }},
                barmode: 'relative'
            }};

            Plotly.newPlot('monthlyChart', traces, layout, {{ responsive: true, displayModeBar: false }});
        }}

        // 初期表示
        if (dates.length > 0) updateDailyChart();
    </script>
</body>
</html>
"""

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html_content)

print("UI改善（ズーム無効化・30分刻み月次・外部固定凡例・アイコン設定）を適用した index.html を生成しました！")
