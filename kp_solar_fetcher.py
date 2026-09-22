import os
import glob
import time
import pandas as pd
from openpyxl import load_workbook
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager

load_dotenv()

LOGIN_URL = "https://ctrl.kp-net.com/settingcontrol/login"
USER_ID = os.getenv("KP_USER_ID")
PASSWORD = os.getenv("KP_PASSWORD")

DOWNLOAD_DIR = os.path.abspath("./downloads")
EXCEL_PATH = os.path.abspath("./太陽光発電システム_2026年.xlsx")
SHEET_NAME = "パワコン"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def update_excel_with_csv(csv_path):
    print(f"CSVデータの処理を開始します: {csv_path}")
    
    # 存在チェックログ
    print(f"Excelのパス: {EXCEL_PATH}")
    print(f"Excelファイルは存在するか?: {os.path.exists(EXCEL_PATH)}")

    if not os.path.exists(EXCEL_PATH):
        print(f"エラー: 集計用Excelファイルが見つかりません ({EXCEL_PATH})")
        return

    try:
        df_csv = pd.read_csv(csv_path, encoding="shift_jis")
    except UnicodeDecodeError:
        df_csv = pd.read_csv(csv_path, encoding="utf-8")

    if df_csv.empty:
        print("CSVファイルにデータが含まれていませんでした。")
        return

    wb = load_workbook(EXCEL_PATH)
    if SHEET_NAME not in wb.sheetnames:
        print(f"エラー: Excel内に '{SHEET_NAME}' シートが存在しません。現在のシート一覧: {wb.sheetnames}")
        return
    
    ws = wb[SHEET_NAME]

    # 既存データの (年月日, 時刻) 鍵集合を作成（A列=1, B列=2）
    existing_keys = set()
    for row in ws.iter_rows(min_row=2, max_col=2, values_only=True):
        if row[0] is not None and row[1] is not None:
            existing_keys.add((str(row[0]).strip(), str(row[1]).strip()))

    new_rows_count = 0
    for idx, row in df_csv.iterrows():
        date_val = str(row.iloc[0]).strip()
        time_val = str(row.iloc[1]).strip()
        
        if (date_val, time_val) not in existing_keys:
            row_data = [row.iloc[i] if i < len(row) else "" for i in range(9)]
            ws.append(row_data)
            existing_keys.add((date_val, time_val))
            new_rows_count += 1

    wb.save(EXCEL_PATH)
    print(f"Excel更新成功: 新規データ {new_rows_count} 件を追記して保存しました。")

def main():
    if not USER_ID or not PASSWORD:
        print("エラー: KP_USER_ID または KP_PASSWORD が設定されていません。")
        return

    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--start-maximized')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "directory_upgrade": True
    }
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        print("ログインページへアクセス中...")
        driver.get(LOGIN_URL)
        time.sleep(3)

        print("ID・パスワードを入力中...")
        try:
            id_input = driver.find_element(By.ID, "userId")
        except:
            id_input = driver.find_element(By.NAME, "userId")

        try:
            pass_input = driver.find_element(By.ID, "password")
        except:
            pass_input = driver.find_element(By.NAME, "password")

        id_input.clear()
        id_input.send_keys(USER_ID)
        pass_input.clear()
        pass_input.send_keys(PASSWORD)

        print("ログインボタンをクリック...")
        try:
            login_btn = driver.find_element(By.XPATH, "//button[@type='submit'] | //input[@type='submit']")
            login_btn.click()
        except:
            pass_input.send_keys(Keys.RETURN)

        time.sleep(5)

        print("「各種データのCSV出力」をクリック中...")
        btn = driver.find_element(By.XPATH, "//form[contains(@action, 'variousdataoutputselect')]//button")
        btn.click()
        time.sleep(3)

        print("「計測データのCSV出力」をクリック中...")
        try:
            driver.find_element(By.XPATH, "//*[contains(text(), '計測データ')]").click()
        except:
            driver.find_element(By.XPATH, "//button[contains(., '計測データ')]").click()
        time.sleep(3)

        print("「データ出力」をクリック中...")
        try:
            driver.find_element(By.XPATH, "//*[contains(text(), 'データ出力')]").click()
        except:
            driver.find_element(By.XPATH, "//button[@type='submit']").click()
        
        time.sleep(5)

        # ダウンロードされたCSVの特定とExcel更新
        csv_files = glob.glob(os.path.join(DOWNLOAD_DIR, "*.csv"))
        if csv_files:
            latest_csv = max(csv_files, key=os.path.getctime)
            update_excel_with_csv(latest_csv)
        else:
            print("エラー: CSVファイルがダウンロードされませんでした。")

    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
        print(f"エラー時のURL: {driver.current_url}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
