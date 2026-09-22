import os
import sys
import glob
import pandas as pd
from openpyxl import load_workbook

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# --------------------------------------------------
# 設定値・環境変数
# --------------------------------------------------
KP_USER_ID = os.environ.get("KP_USER_ID")
KP_PASSWORD = os.environ.get("KP_PASSWORD")

LOGIN_URL = "https://ctrl.kp-net.com/settingcontrol/login"
EXCEL_PATH = "solar_data.xlsx"  # 更新対象のExcelファイルパス
SHEET_NAME = "パワコン"         # 追記対象のシート名

# CSVのダウンロード先フォルダ（スクリプトと同じ階層の downloads フォルダ）
DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")


def create_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # ダウンロードフォルダの設定（ヘッドレスモード時の自動保存先指定）
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)

    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    options.add_experimental_option("prefs", prefs)

    return webdriver.Chrome(options=options)


def update_excel_with_csv(csv_path):
    """ダウンロードしたCSVのデータをExcelのパワコンシートに追記更新する"""
    print(f"CSVデータの処理を開始します: {csv_path}")
    
    # 文字コード判別（Shift-JISまたはUTF-8）
    try:
        df_csv = pd.read_csv(csv_path, encoding="shift_jis")
    except UnicodeDecodeError:
        df_csv = pd.read_csv(csv_path, encoding="utf-8")

    # CSVが空でないか確認
    if df_csv.empty:
        print("CSVファイルにデータが含まれていませんでした。")
        return

    # Excelファイルが存在するか確認
    if not os.path.exists(EXCEL_PATH):
        print(f"エラー: 集計用Excelファイルが見つかりません ({EXCEL_PATH})")
        return

    wb = load_workbook(EXCEL_PATH)
    if SHEET_NAME not in wb.sheetnames:
        print(f"エラー: Excel内に '{SHEET_NAME}' シートが存在しません。")
        return
    
    ws = wb[SHEET_NAME]

    # 既存データの (年月日, 時刻) 鍵集合を作成（A列=1, B列=2）
    existing_keys = set()
    for row in ws.iter_rows(min_row=2, max_col=2, values_only=True):
        if row[0] is not None and row[1] is not None:
            existing_keys.add((str(row[0]).strip(), str(row[1]).strip()))

    # CSVから新規データのみ抽出（A列=0番目, B列=1番目と仮定）
    new_rows_count = 0
    for idx, row in df_csv.iterrows():
        date_val = str(row.iloc[0]).strip()
        time_val = str(row.iloc[1]).strip()
        
        # A列(年月日)とB列(時刻)のペアが既存データになければ追記
        if (date_val, time_val) not in existing_keys:
            # A〜I列の最大9要素を書き込み
            row_data = [row.iloc[i] if i < len(row) else "" for i in range(9)]
            ws.append(row_data)
            existing_keys.add((date_val, time_val))
            new_rows_count += 1

    wb.save(EXCEL_PATH)
    print(f"Excel更新完了: 新規データ {new_rows_count} 件を追記しました。")


def get_latest_downloaded_csv(download_dir):
    """ダウンロードフォルダ内から最新のCSVファイルを取得する"""
    csv_files = glob.glob(os.path.join(download_dir, "*.csv"))
    if not csv_files:
        return None
    return max(csv_files, key=os.path.getctime)


def main():
    if not KP_USER_ID or not KP_PASSWORD:
        print("エラー: 環境変数 KP_USER_ID または KP_PASSWORD が設定されていません。")
        sys.exit(1)

    driver = create_driver()
    wait = WebDriverWait(driver, 15)

    try:
        print("ログインページへアクセス中...")
        driver.get(LOGIN_URL)

        # iframeの存在チェック・切り替え
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        if iframes:
            print(f"iframeを検出しました ({len(iframes)}個)。フレーム内に切り替えます...")
            driver.switch_to.frame(iframes[0])

        print("ID・パスワードを入力中...")
        user_id_input = wait.until(
            EC.presence_of_element_located((By.NAME, "userId"))
        )
        wait.until(EC.visibility_of(user_id_input))

        user_id_input.clear()
        user_id_input.send_keys(KP_USER_ID)

        # パスワード入力（※属性名が異なる場合は変更してください）
        password_input = driver.find_element(By.NAME, "password")
        password_input.clear()
        password_input.send_keys(KP_PASSWORD)

        # ログインボタンをクリック
        submit_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit'], input[type='submit']")
        submit_button.click()

        print("ログイン処理を実行しました。遷移を待機中...")
        wait.until(lambda d: d.current_url != LOGIN_URL)
        print("ログインに成功しました。現在のURL:", driver.current_url)

        # --------------------------------------------------
        # CSVダウンロード画面へ遷移 & ダウンロードボタン押下
        # --------------------------------------------------
        print("CSVダウンロードボタンを探しています...")
        
        # 例：CSVダウンロードボタンをクリック（※実際のページのセレクタに合わせて変更してください）
        # download_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".csv-download-button")))
        # download_btn.click()
        
        # ダウンロード完了を数秒待機
        import time
        time.sleep(5)

        # ダウンロードしたCSVファイルの取得
        csv_path = get_latest_downloaded_csv(DOWNLOAD_DIR)
        
        if csv_path and os.path.exists(csv_path):
            # --------------------------------------------------
            # CSVデータを使ってExcelを更新
            # --------------------------------------------------
            update_excel_with_csv(csv_path)
        else:
            print("エラー: ダウンロードされたCSVファイルが見つかりませんでした。")

    except (TimeoutException, NoSuchElementException) as e:
        print(f"\n[エラー] 要素が見つからないか、タイムアウトしました: {e}")
        print("現在のURL:", driver.current_url)
        
        # デバッグ用の情報保存
        driver.save_screenshot("error_screenshot.png")
        with open("error_page.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
            
        print("デバッグ用ファイルを保存しました (error_screenshot.png / error_page.html)")
        sys.exit(1)

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
