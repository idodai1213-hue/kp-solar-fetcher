import os
import sys
import glob
import time
import pandas as pd

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
EXCEL_PATH = os.path.abspath("./data.xlsx")  # ※必要に応じてご自身のファイル名（例: solar_data.xlsx 等）に変更してください


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
    """ダウンロードしたCSVのデータでExcelファイルを更新"""
    print(f"ダウンロードされたCSVを読み込んでいます: {csv_path}")
    
    # 文字コードの判定（Shift-JISまたはUTF-8）
    try:
        df_csv = pd.read_csv(csv_path, encoding="shift_jis")
    except Exception:
        df_csv = pd.read_csv(csv_path, encoding="utf-8")

    print("CSVデータの先頭サンプル:")
    print(df_csv.head(3))

    if os.path.exists(EXCEL_PATH):
        print(f"既存のExcelファイルを更新中: {EXCEL_PATH}")
        # openpyxl等を使ってExcelに書き込み
        with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
            df_csv.to_excel(writer, sheet_name="最新データ", index=False)
        print("Excelファイルの更新が完了しました！")
    else:
        print(f"新規Excelファイルを作成中: {EXCEL_PATH}")
        df_csv.to_excel(EXCEL_PATH, sheet_name="最新データ", index=False)
        print("新規Excelファイルの作成が完了しました！")


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
