import pandas as pd
import json
import os

# 1. CSVファイルの読み込み
csv_path = 'パワコン_2026.csv'
if not os.path.exists(csv_path):
    print(f"Error: {csv_path} が見つかりません。")
    exit(1)

# CSVの読み込み（エンコーディングは環境に合わせてutf-8やshift_jisを指定）
try:
    df = pd.read_csv(csv_path, encoding='utf-8')
except:
    df = pd.read_csv(csv_path, encoding='shift_jis')

# 日付と時間の結合
df['日時'] = df['年月日'] + ' ' + df['時刻']
df['日時'] = pd.to_datetime(df['日時'])

# 日付（YYYY-MM-DD）カラムの追加
df['日付'] = df['日時'].dt.strftime('%Y-%m-%d')
df['時刻_str'] = df['日時'].dt.strftime('%H:%M')

# 2. JavaScriptに渡すためのJSONデータ作成
dates = sorted(list(df['日付'].unique()), reverse=True)

daily_data = {}
for date_str in dates:
    sub_df = df[df['日付'] == date_str]
    daily_data[date_str] = {
        'time': sub_df['時刻_str'].tolist(),
        'generation': sub_df['発電電力量[kWh]'].tolist(),
        'consumption': sub_df['消費電力量[kWh]'].tolist(),
        'sell': sub_df['売電電力量[kWh]'].tolist(),
        'buy': sub_df['買電電力量[kWh]'].tolist(),
        'soc': sub_df['蓄電残量(SOC)[%]'].tolist()
    }

json_data = json.dumps(daily_data, ensure_ascii=False)
json_dates = json.dumps(dates, ensure_ascii=False)

# 3. HTMLテンプレートの作成
html_content = f"""<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>太陽光発電モニタリングダッシュボード</title>
    <!-- Plotly.js (グラフ描画ライブラリ) -->
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
            max-width: 1000px;
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
        #chart {{
            width: 100%;
            height: 500px;
        }}
        @media (max-width: 600px) {{
            #chart {{
                height: 400px;
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
            <h1>☀️ 太陽光発電 ダッシュボード</h1>
            <div class="controls">
                <label for="dateSelect"><strong>日付選択:</strong></label>
                <select id="dateSelect" onchange="updateChart()"></select>
            </div>
            <div id="chart"></div>
        </div>
    </div>

    <script>
        const rawData = {json_data};
        const dates = {json_dates};

        // セレクトボックス初期化
        const select = document.getElementById('dateSelect');
        dates.forEach(d => {{
            const opt = document.createElement('option');
            opt.value = d;
            opt.textContent = d;
            select.appendChild(opt);
        }});

        function updateChart() {{
            const selectedDate = select.value;
            const data = rawData[selectedDate];

            if (!data) return;

            // 発電量 (緑の棒グラフ)
            const traceGen = {{
                x: data.time,
                y: data.generation,
                name: '発電[kWh]',
                type: 'bar',
                marker: {{ color: '#2ecc71' }}
            }};

            // 消費量 (オレンジの折れ線)
            const traceCons = {{
                x: data.time,
                y: data.consumption,
                name: '消費[kWh]',
                type: 'scatter',
                mode: 'lines+markers',
                line: {{ color: '#e67e22', width: 2 }}
            }};

            // 売電量 (青の折れ線)
            const traceSell = {{
                x: data.time,
                y: data.sell,
                name: '売電[kWh]',
                type: 'scatter',
                mode: 'lines',
                line: {{ color: '#3498db', dash: 'dot' }}
            }};

            // SOC (右軸：紫色)
            const traceSOC = {{
                x: data.time,
                y: data.soc,
                name: '蓄電SOC[%]',
                type: 'scatter',
                mode: 'lines',
                yaxis: 'y2',
                line: {{ color: '#9b59b6', width: 2 }}
            }};

            const traces = [traceGen, traceCons, traceSell, traceSOC];

            const layout = {{
                title: selectedDate + ' の電力推移',
                margin: {{ t: 40, r: 50, l: 50, b: 40 }},
                legend: {{ orientation: 'h', y: -0.2 }},
                xaxis: {{ title: '時刻' }},
                yaxis: {{
                    title: '電力量 [kWh]',
                    side: 'left'
                }},
                yaxis2: {{
                    title: '蓄電残量 (SOC) [%]',
                    side: 'right',
                    overlaying: 'y',
                    range: [0, 100],
                    showgrid: false
                }},
                barmode: 'group',
                autosize: true
            }};

            const config = {{ responsive: true, displayModeBar: false }};

            Plotly.newPlot('chart', traces, layout, config);
        }}

        // 初期表示
        if (dates.length > 0) {{
            updateChart();
        }}
    </script>
</body>
</html>
"""

# 4. index.html として保存
with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html_content)

print("正常に index.html が生成されました！")
