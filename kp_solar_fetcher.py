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
    ダウンロードしたCSVのデータでExcelファイルの「パワコン」タブを更新
    A～I列（年月日・時刻など）を判定し、A列(年月日)・B列(時刻)の組み合わせで
    すでに存在するデータは重複として除外して追記する。
    """
    print(f"ダウンロードされたCSVを読み込んでいます: {csv_path}")

    # 文字コードの判定（Shift-JIS または UTF-8）
    try:
        df_csv = pd.read_csv(csv_path, encoding="shift_jis")
    except Exception:
        df_csv = pd.read_csv(csv_path, encoding="utf-8")

    # A～I列（最初の9列）のみを取り出し
    df_csv = df_csv.iloc[:, :9]

    # 列名の空白文字除去などの標準化
    df_csv.columns = [str(c).strip() for c in df_csv.columns]

    print("CSVデータ（A〜I列）の先頭サンプル:")
    print(df_csv.head(3))

    sheet_name = "パワコン"

    if os.path.exists(EXCEL_PATH):
        print(f"既存のExcelファイルを読み込んでいます: {EXCEL_PATH}")
        try:
            # 既存の「パワコン」シートを読み込み
            df_excel = pd.read_excel(EXCEL_PATH, sheet_name=sheet_name)
            df_excel = df_excel.iloc[:, :9]  # A〜I列のみ対象

            # 列名を文字列型に変換して統一
            df_excel.columns = [str(c).strip() for c in df_excel.columns]

            # A列(1列目)とB列(2列目)をキーにして重複判定
            col_a = df_excel.columns[0]
            col_b = df_excel.columns[1]

            # 既存の年月日・時刻のペアセットを作成 (文字列化して判定)
            existing_keys = set(
                zip(
                    df_excel[col_a].astype(str).str.strip(),
                    df_excel[col_b].astype(str).str.strip(),
                )
            )

            # CSVデータ側で未存在の行（新規データ）のみを抽出
            csv_col_a = df_csv.columns[0]
            csv_col_b = df_csv.columns[1]

            new_rows_mask = [
                (
                    str(row[csv_col_a]).strip(),
                    str(row[csv_col_b]).strip(),
                )
                not in existing_keys
                for _, row in df_csv.iterrows()
            ]

            df_new = df_csv[new_rows_mask]

            if not df_new.empty:
                print(f"新規追加対象のデータ: {len(df_new)} 件")
                # 既存データの後ろに結合
                df_updated = pd.concat([df_excel, df_new], ignore_index=True)
            else:
                print(
                    "すべてのデータが既存データ（年月日・時刻が一致）と重複しているため、追記をスキップします。"
                )
                df_updated = df_excel

        except ValueError:
            # 「パワコン」シートが存在しない場合は新規作成
            print(
                f"「{sheet_name}」シートが存在しないため、新規作成します。"
            )
            df_updated = df_csv

        # Excelファイルへ書き出し（オープン中の数式や他シートを保持するために openpyxl モード使用）
        with pd.ExcelWriter(
            EXCEL_PATH, engine="openpyxl", mode="a", if_sheet_exists="replace"
        ) as writer:
            df_updated.to_excel(writer, sheet_name=sheet_name, index=False)

    else:
        print(f"新規Excelファイルを作成します: {EXCEL_PATH}")
        with pd.ExcelWriter(EXCEL_PATH, engine="openpyxl") as writer:
            df_csv.to_excel(writer, sheet_name=sheet_name, index=False)

    print("Excelファイルの更新が正常に完了しました！")


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
