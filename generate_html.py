import pandas as pd
import json
import os

# 1. CSVファイルの読み込み
# --- CSVファイル名の決定（環境変数 CSV_FILENAME があればそれを優先、無ければデフォルト） ---
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

# --- 1時間単位サマリー用の処理（月次グラフ用） ---
df['日時_1h'] = df['日時'].dt.floor('h')

df_1h = df.groupby('日時_1h').agg({
    '発電電力量[kWh]': 'sum',
    '消費電力量[kWh]': 'sum',
    '売電電力量[kWh]': 'sum',
    '買電電力量[kWh]': 'sum',
    '充電電力量[kWh]': 'sum',
    '放電電力量[kWh]': 'sum',
    '蓄電残量(SOC)[%]': 'last'  # SOCは1時間の最後の値を採用
}).reset_index()

df_1h['年月'] = df_1h['日時_1h'].dt.strftime('%Y-%m')
df_1h['日時_str'] = df_1h['日時_1h'].dt.strftime('%m/%d %H:00')

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

# (B) 月次データ (1時間粒度)
months = sorted(list(df_1h['年月'].unique()), reverse=True)
monthly_data = {}
for month_str in months:
    sub_df = df_1h[df_1h['年月'] == month_str]
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
        .chart-scroll-wrapper {{
            width: 100%;
            overflow-x: auto; /* スクロール可能にする構造 */
            -webkit-overflow-scrolling: touch;
        }}
        .chart-inner {{
            min-width: 100%;
        }}
        #dailyChart, #monthlyChart {{
            width: 100%;
            height: 550px;
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        @media (max-width: 600px) {{
            #dailyChart, #monthlyChart {{
                height: 480px;
            }}
            body {{
                padding: 8px;
            }}
            .card {{
                padding: 10px;
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
                <button class="tab-btn" onclick="switchTab('monthly')">月次 (31日間・1時間粒度)</button>
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
                margin: {{ t: 40, r: 50, l: 50, b: 60 }},
                legend: {{ orientation: 'h', y: -0.25, x: 0.5, xanchor: 'center' }},
                xaxis: {{ title: '時刻' }},
                yaxis: {{ title: '電力量 [kWh]', side: 'left', zeroline: true, zerolinewidth: 2, zerolinecolor: '#333' }},
                yaxis2: {{ title: '蓄電残量 (SOC) [%]', side: 'right', overlaying: 'y', range: [0, 100], showgrid: false }},
                barmode: 'relative',
                autosize: true
            }};

            Plotly.newPlot('dailyChart', traces, layout, {{ responsive: true, displayModeBar: false }});
        }}

        // --- 月次グラフ描画 (横スクロール ＆ レンジスライダー対応) ---
        function updateMonthlyChart() {{
            const selectedMonth = monthSelect.value;
            const data = rawMonthlyData[selectedMonth];
            if (!data) return;

            // データ点数に応じた動的横幅（1点あたり約12px幅を確保して見やすく表示）
            const minWidth = Math.max(1000, data.datetime.length * 14);
            document.getElementById('monthlyChartInner').style.width = minWidth + 'px';

            const traces = [
                {{ x: data.datetime, y: data.generation, name: '発電(+)', type: 'bar', marker: {{ color: colors.gen }} }},
                {{ x: data.datetime, y: data.discharging, name: '放電(+)', type: 'bar', marker: {{ color: colors.discharge }} }},
                {{ x: data.datetime, y: data.buy, name: '買電(+)', type: 'bar', marker: {{ color: colors.buy }} }},
                {{ x: data.datetime, y: data.consumption, name: '消費(-)', type: 'bar', marker: {{ color: colors.cons }} }},
                {{ x: data.datetime, y: data.charging, name: '充電(-)', type: 'bar', marker: {{ color: colors.charge }} }},
                {{ x: data.datetime, y: data.sell, name: '売電(-)', type: 'bar', marker: {{ color: colors.sell }} }},
                {{ x: data.datetime, y: data.soc, name: '蓄電SOC[%]', type: 'scatter', mode: 'lines', yaxis: 'y2', line: {{ color: colors.soc, width: 2, shape: 'spline' }} }}
            ];

            const layout = {{
                title: selectedMonth + ' 月間電力バランス (1時間粒度)',
                margin: {{ t: 40, r: 50, l: 50, b: 80 }},
                legend: {{ orientation: 'h', y: -0.3, x: 0.5, xanchor: 'center' }},
                xaxis: {{ 
                    title: '日時 (MM/DD HH:00)', 
                    tickangle: -45,
                    rangeslider: {{ visible: true }} // 下部にミニナビゲーション用スライダーを追加
                }},
                yaxis: {{ title: '電力量 [kWh]', side: 'left', zeroline: true, zerolinewidth: 2, zerolinecolor: '#333' }},
                yaxis2: {{ title: '蓄電残量 (SOC) [%]', side: 'right', overlaying: 'y', range: [0, 100], showgrid: false }},
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

print("月次タブ（1時間粒度・横スクロール）を追加した index.html を生成しました！")
