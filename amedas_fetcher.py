import os
import re
import sys
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import pandas as pd
import requests

# ==========================================
# 1. 設定情報
# ==========================================
PREC_NO = '52'
BLOCK_NO = '0538'

csv_name = os.getenv("AMEDAS_FILENAME", "アメダス_2026.csv")
CSV_PATH = os.path.abspath(f"./{csv_name}")


# ==========================================
# 2. アメダスデータ取得関数 (堅牢化版)
# ==========================================
def fetch_tajimi_amedas_hourly(target_date: datetime) -> pd.DataFrame:
    """指定した日付（JST）の多治見アメダス1時間毎データを取得してDataFrame化"""
    url = (
        f"https://www.data.jma.go.jp/obd/stats/etrn/view/hourly_a1.php?"
        f"prec_no={PREC_NO}&block_no={BLOCK_NO}&"
        f"year={target_date.year}&month={target_date.month}&day={target_date.day}&view="
    )

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        )
    }

    try:
        res = requests.get(url, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')

        # テーブル検出の堅牢化：id="data200" に限定せず、現在値テーブルクラス(data200 / data210 / class='data_table')を幅広く探す
        table = soup.find('table', {'id': 'data200'}) or soup.find(
            'table', {'id': 'data210'}
        )

        if not table:
            # IDで見つからない場合はクラス名で検索
            tables = soup.find_all('table', class_='data200_table') or soup.find_all('table', class_='data_table')
            if tables:
                table = tables[0]

        if not table:
            # それでも見つからない場合は、'時' や '日照時間' を含むテーブルを探す
            for t in soup.find_all('table'):
                if '日照時間' in t.text or '現在値' in t.text:
                    table = t
                    break

        if not table:
            print(
                f"[{target_date.strftime('%Y-%m-%d')}] アメダスデータテーブルが見つかりませんでした。"
            )
            return pd.DataFrame()

        rows = []
        for tr in table.find_all('tr'):
            tds = tr.find_all('td')
            if len(tds) >= 8:  # アメダス1時間データの基本列数
                hour_str = tds[0].text.strip()
                if not hour_str.isdigit():
                    continue
                hour = int(hour_str)

                # 日照時間(h)の列を探す（通常は末尾から2番目または第10列付近）
                # 1時間データ（hourly_a1.php）の場合、列構成:
                # [0:時, 1:現地気圧, 2:海面気圧, 3:降水量, 4:気温, 5:湿度, 6:風速, 7:風向, 8:日照時間, 9:降雪, 10:積雪] など
                # 多治見(アメダス観測所a1)の標準列:
                # 0:時, 1:降水量, 2:気温, 3:風速, 4:風向, 5:日照時間 ... 等のパターンに対応
                
                sunshine_str = ""
                # 列数が多治見アメダスの標準構成の場合
                if len(tds) >= 10:
                    sunshine_str = tds[9].text.strip()
                elif len(tds) >= 6:
                    # アメダス専用機（降水・気温・風向風速・日照）の場合の列インデックス5
                    sunshine_str = tds[5].text.strip()

                # 数値フォーマットチェック ('--' や空文字は未観測・夜間)
                if re.match(r"^\d+(\.\d+)?$", sunshine_str):
                    sunshine_val = float(sunshine_str)
                    sunshine_formatted = f"{sunshine_val:.1f}"
                else:
                    sunshine_formatted = ""

                dt_str = f"{target_date.year}/{target_date.month}/{target_date.day} {hour}:00:00"

                rows.append(
                    {
                        'datetime_str': dt_str,
                        'sunshine_hours': sunshine_formatted,
                        'quality_flag': '8',
                        'homogeneity_flag': '1',
                    }
                )

        if not rows:
            print(f"[{target_date.strftime('%Y-%m-%d')}] 行データのパース結果が0件でした。")

        return pd.DataFrame(rows)

    except Exception as e:
        print(
            f"アメダスデータの取得中にエラーが発生しました ({target_date.strftime('%Y-%m-%d')}): {e}"
        )
        return pd.DataFrame()


# ==========================================
# 3. マスタデータ統合・更新処理
# ==========================================
def update_master_csv():
    """既存のマスターCSVを読み込み、昨日〜本日の最新アメダスデータを結合・更新する"""

    if not os.path.exists(CSV_PATH):
        print(
            f"警告: ローカルファイル '{CSV_PATH}' が存在しません。新規作成用ヘッダーで初期化します。"
        )
        header_lines = [
            'ダウンロードした時刻：'
            + datetime.now().strftime('%Y/%m/%d %H:%M:%S')
            + '\n',
            '\n',
            ',多治見,多治見,多治見\n',
            '年月日時,日照時間(時間),日照時間(時間),日照時間(時間)\n',
            ',,品質情報,均質番号\n',
        ]
        df_master = pd.DataFrame(
            columns=[
                'datetime_str',
                'sunshine_hours',
                'quality_flag',
                'homogeneity_flag',
            ]
        )
    else:
        print(f"既存のマスターCSVを読み込んでいます: {CSV_PATH}")
        with open(CSV_PATH, 'r', encoding='shift_jis') as f:
            header_lines = [f.readline() for _ in range(5)]

        try:
            df_master = pd.read_csv(
                CSV_PATH, encoding='shift_jis', skiprows=5, header=None
            )
        except Exception:
            df_master = pd.read_csv(
                CSV_PATH, encoding='utf-8', skiprows=5, header=None
            )

        df_master = df_master.iloc[:, :4]
        df_master.columns = [
            'datetime_str',
            'sunshine_hours',
            'quality_flag',
            'homogeneity_flag',
        ]
        df_master['sunshine_hours'] = (
            df_master['sunshine_hours'].fillna('').astype(str)
        )

    print(f"既存データの件数: {len(df_master)} 行")

    now_jst = datetime.utcnow() + timedelta(hours=9)
    target_dates = [now_jst - timedelta(days=1), now_jst]

    new_rows = []
    for d in target_dates:
        df_fetched = fetch_tajimi_amedas_hourly(d)
        for _, row in df_fetched.iterrows():
            new_rows.append(row.to_dict())

    if not new_rows:
        print("WEBからの新規データ取得はありませんでした。")
        return

    df_new = pd.DataFrame(new_rows)

    # 結合と重複排除
    combined = pd.concat([df_master, df_new], ignore_index=True)
    combined['datetime_str_clean'] = combined['datetime_str'].str.strip()
    combined.drop_duplicates(
        subset=['datetime_str_clean'], keep='last', inplace=True
    )
    combined.drop(columns=['datetime_str_clean'], inplace=True)

    with open(CSV_PATH, 'w', encoding='shift_jis', newline='') as f:
        for line in header_lines:
            f.write(line)
        combined.to_csv(f, index=False, header=False, lineterminator='\r\n')

    print(
        f"【成功】{csv_name} の統合更新が完了しました。（総データ行数: {len(combined)} 行）"
    )


def main():
    update_master_csv()


if __name__ == '__main__':
    main()
