import os
import sys
import glob
import time
import pandas as pd
import openpyxl
import datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

# ==========================================
# 1. 設定情報
# ==========================================
LOGIN_URL = "https://ctrl.kp-net.com/settingcontrol/login"
USER_ID = os.getenv("KP_USER_ID")
PASSWORD = os.getenv("KP_PASSWORD")

# CSVの保存先フォルダ（スクリプトと同じ場所のdownloadsフォルダ）
DOWNLOAD_DIR = os.path.abspath("./downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# 更新対象のExcelファイル（プロジェクト直下に配置されている前提）
EXCEL_PATH = os.path.abspath("./太陽光発電システム_2026年.xlsx")


def create_driver():
    """GitHub Actions (Headless) およびローカル両対応のChrome Driverを作成"""
    options = webdriver.ChromeOptions()
    
    # GitHub Actions等のCI環境向けのオプション設定
    options.add_argument('--headless=new')  # 新しいヘッドレスモード
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # CSV自動ダウンロードの設定（Headless環境でもダウンロードを許可）
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    options.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    # Headlessモードでダウンロードを許可するためのDevToolsコマンド呼び出し
    driver.execute_cdp_cmd(
        "Page.setDownloadBehavior",
        {"behavior": "allow", "downloadPath": DOWNLOAD_DIR}
    )

    return driver


def get_latest_downloaded_csv(download_dir):
    """指定ディレクトリ内で最新のCSVファイルを取得"""
    csv_files = glob.glob(os.path.join(download_dir, "*.csv"))
    if not csv_files:
        return None
    latest_file = max(csv_files, key=os.path.getmtime)
    return latest_file


def update_excel_with_csv(csv_path):
    """
    ダウンロードしたCSVのデータでExcelファイルの「パワコン」タブを更新。
    破損を防ぐため keep_vba は使用せず、既存のグラフや構造を維持しながら最小限のセル追記を行う。
    """
    print(f"ダウンロードされたCSVを読み込んでいます: {csv_path}")

    # 文字コードの判定（Shift-JIS または UTF-8）
    try:
        df_csv = pd.read_csv(csv_path, encoding="shift_jis")
    except Exception:
        df_csv = pd.read_csv(csv_path, encoding="utf-8")

    # A～I列（最初の9列）のみを取り出し
    df_csv = df_csv.iloc[:, :9]
    df_csv.columns = [str(c).strip() for c in df_csv.columns]

    print("CSVデータ（A〜I列）の先頭サンプル:")
    print(df_csv.head(3))

    sheet_name = "パワコン"

    if not os.path.exists(EXCEL_PATH):
        print(f"エラー: 更新対象のExcelファイルが見つかりません: {EXCEL_PATH}")
        sys.exit(1)

    print(f"既存のExcelファイルをオープン中: {EXCEL_PATH}")
    
    # 【重要】keep_vba=True は .xlsx でファイルを破損させるため削除
    # data_only=False で数式やシート構造を保持
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=False)

    if sheet_name not in wb.sheetnames:
        print(f"エラー: 「{sheet_name}」シートがExcel内に存在しません。")
        sys.exit(1)

    ws = wb[sheet_name]

    # --------------------------------------------------
    # 1. 既存のA列(年月日)・B列(時刻)のペアを収集
    # --------------------------------------------------
    existing_keys = set()
    for row in ws.iter_rows(min_row=2, max_col=2, values_only=True):
        val_a, val_b = row[0], row[1]
        if val_a is not None and val_b is not None:
            # 日付のフォーマット統一 ('YYYY/MM/DD')
            if isinstance(val_a, (datetime.datetime, datetime.date)):
                str_a = val_a.strftime("%Y/%m/%d")
            else:
                str_a = str(val_a).split(" ")[0].replace("-", "/").strip()

            # 時刻のフォーマット統一 ('HH:MM')
            if isinstance(val_b, datetime.time):
                str_b = val_b.strftime("%H:%M")
            else:
                str_b = str(val_b).strip()
                if len(str_b) == 4 and str_b[1] == ":":
                    str_b = "0" + str_b

            existing_keys.add((str_a, str_b))

    # --------------------------------------------------
    # 2. CSV側から新規行を抽出
    # --------------------------------------------------
    csv_col_a = df_csv.columns[0]
    csv_col_b = df_csv.columns[1]

    new_rows = []
    for _, row in df_csv.iterrows():
        val_a_raw = str(row[csv_col_a]).strip()
        val_b_raw = str(row[csv_col_b]).strip()

        str_a = val_a_raw.split(" ")[0].replace("-", "/").strip()
        str_b = val_b_raw
        if len(str_b) == 4 and str_b[1] == ":":
            str_b = "0" + str_b

        if (str_a, str_b) not in existing_keys:
            row_data = []
            for idx, val in enumerate(row):
                if idx == 0:
                    row_data.append(str_a)
                else:
                    try:
                        if pd.isna(val):
                            row_data.append("")
                        elif isinstance(val, (int, float)):
                            row_data.append(val)
                        else:
                            val_str = str(val).strip()
                            row_data.append(float(val_str) if "." in val_str else int(val_str))
                    except ValueError:
                        row_data.append(str(val).strip())

            new_rows.append(row_data)
            existing_keys.add((str_a, str_b))

    # --------------------------------------------------
    # 3. ワークシートの末尾に書き込み
    # --------------------------------------------------
    if new_rows:
        start_row = ws.max_row + 1
        print(f"新規データ {len(new_rows)} 件を {start_row} 行目から追記します...")

        for r_idx, row_data in enumerate(new_rows, start=start_row):
            for c_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=r_idx, column=c_idx, value=val)
                if c_idx == 1:
                    cell.number_format = '@'

        print("追記処理が完了しました。")
    else:
        print("すべてのデータが既存データ（年月日・時刻が一致）と重複しているため、追記をスキップしました。")

    # --------------------------------------------------
    # 4. 保存処理
    # --------------------------------------------------
    wb.save(EXCEL_PATH)
    wb.close()
    print("Excelファイルの保存が正常に完了しました！")


def main():
    if not USER_ID or not PASSWORD:
        print("エラー: 環境変数 KP_USER_ID または KP_PASSWORD が設定されていません。")
        sys.exit(1)

    driver = create_driver()

    try:
        # ==========================================
        # 3. ログイン処理
        # ==========================================
        print("ログインページへアクセス中...")
        driver.get(LOGIN_URL)
        time.sleep(3)

        print("ID・パスワードを入力中...")
        try:
            id_input = driver.find_element(By.ID, "userId")
        except Exception:
            try:
                id_input = driver.find_element(By.NAME, "userId")
            except Exception:
                id_input = driver.find_element(By.XPATH, "//input[@type='text' or @type='email']")

        try:
            pass_input = driver.find_element(By.ID, "password")
        except Exception:
            try:
                pass_input = driver.find_element(By.NAME, "password")
            except Exception:
                pass_input = driver.find_element(By.XPATH, "//input[@type='password']")

        id_input.clear()
        id_input.send_keys(USER_ID)
        pass_input.clear()
        pass_input.send_keys(PASSWORD)

        print("ログインボタンをクリック...")
        try:
            login_btn = driver.find_element(By.XPATH, "//button[@type='submit'] | //input[@type='submit']")
            login_btn.click()
        except Exception:
            pass_input.send_keys(Keys.RETURN)

        time.sleep(5)

        # ==========================================
        # 4. 「各種データのCSV出力」ボタンのクリック
        # ==========================================
        print("「各種データのCSV出力」をクリック中...")
        try:
            btn = driver.find_element(By.XPATH, "//form[contains(@action, 'variousdataoutputselect')]//button")
            btn.click()
        except Exception as e1:
            print(f"フォーム属性による検索に失敗したためフォールバック指定を試みます: {e1}")
            btn = driver.find_element(By.XPATH, "//h5[contains(., '各種データ')]")
            btn.click()

        time.sleep(3)

        # ==========================================
        # 5. 次画面での選択・出力処理
        # ==========================================
        print("「計測データのCSV出力」をクリック中...")
        try:
            driver.find_element(By.XPATH, "//*[contains(text(), '計測データ')]").click()
        except Exception:
            driver.find_element(By.XPATH, "//button[contains(., '計測データ')]").click()
        time.sleep(3)

        print("「データ出力」をクリック中...")
        try:
            driver.find_element(By.XPATH, "//*[contains(text(), 'データ出力')]").click()
        except Exception:
            driver.find_element(By.XPATH, "//button[@type='submit']").click()

        print("ファイルダウンロードを待機中...")
        time.sleep(5)

        # ==========================================
        # 6. CSV取得とExcelファイルの更新
        # ==========================================
        downloaded_csv = get_latest_downloaded_csv(DOWNLOAD_DIR)

        if downloaded_csv and os.path.exists(downloaded_csv):
            print(f"【成功】CSVファイルが正常に取得されました: {downloaded_csv}")
            update_excel_with_csv(downloaded_csv)
        else:
            print("エラー: ダウンロードされたCSVファイルが見つかりませんでした。")
            sys.exit(1)

    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
        print(f"エラー時のURL: {driver.current_url}")
        sys.exit(1)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
