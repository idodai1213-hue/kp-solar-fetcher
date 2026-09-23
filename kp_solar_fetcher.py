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

DOWNLOAD_DIR = os.path.abspath("./downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# 管理対象のマスターCSVファイル
# 環境変数 CSV_FILENAME を取得（未設定の場合は fallback として "パワコン_2026.csv" を使用）
csv_name = os.getenv("CSV_FILENAME", "パワコン_2026.csv")
CSV_PATH = os.path.abspath(f"./{csv_name}")


def create_driver():
    """GitHub Actions (Headless) およびローカル両対応のChrome Driverを作成"""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument(
        '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )

    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    driver.execute_cdp_cmd(
        "Page.setDownloadBehavior",
        {"behavior": "allow", "downloadPath": DOWNLOAD_DIR},
    )

    return driver


def get_latest_downloaded_csv(download_dir):
    """指定ディレクトリ内で最新のダウンロードCSVファイルを取得"""
    csv_files = glob.glob(os.path.join(download_dir, "*.csv"))
    if not csv_files:
        return None
    return max(csv_files, key=os.path.getmtime)


def update_master_csv_with_new_csv(downloaded_csv_path):
    """
    ダウンロードしたCSVデータを読み込み、既存の「パワコン_2026.csv」に新規行のみを追記更新する。
    1行目はヘッダーとし、2行目以降のA列(年月日)・B列(時刻)のペアで重複を判定。
    """
    print(f"ダウンロードされたCSVを処理中: {downloaded_csv_path}")

    # 文字コード判別 (Shift-JIS または UTF-8)
    try:
        df_new = pd.read_csv(downloaded_csv_path, encoding="shift_jis")
    except Exception:
        df_new = pd.read_csv(downloaded_csv_path, encoding="utf-8")

    # A～I列（最初の9列）のみを対象
    df_new = df_new.iloc[:, :9]
    df_new.columns = [str(c).strip() for c in df_new.columns]

    # 1. 既存のマスターCSV(パワコン_2026.csv)の存在チェックと既存キーのロード
    existing_keys = set()

    if os.path.exists(CSV_PATH):
        print(f"既存のマスターCSVを読み込んでいます: {CSV_PATH}")
        try:
            try:
                df_master = pd.read_csv(CSV_PATH, encoding="shift_jis")
            except Exception:
                df_master = pd.read_csv(CSV_PATH, encoding="utf-8")

            df_master = df_master.iloc[:, :9]
            df_master.columns = [str(c).strip() for c in df_master.columns]

            col_a = df_master.columns[0]
            col_b = df_master.columns[1]

            # 2行目以降のデータから (年月日, 時刻) のセットを作成
            for _, row in df_master.iterrows():
                val_a = str(row[col_a]).split(" ")[0].replace("-", "/").strip()
                val_b = str(row[col_b]).strip()
                if len(val_b) == 4 and val_b[1] == ":":
                    val_b = "0" + val_b
                existing_keys.add((val_a, val_b))

            print(f"既存データの件数: {len(df_master)} 行")
        except Exception as e:
            print(f"既存CSVの読み込み中に警告が発生しました (新規作成します): {e}")

    # 2. 新規データ側の重複チェックと抽出
    new_col_a = df_new.columns[0]
    new_col_b = df_new.columns[1]

    new_rows = []
    for _, row in df_new.iterrows():
        val_a = str(row[new_col_a]).split(" ")[0].replace("-", "/").strip()
        val_b = str(row[new_col_b]).strip()
        if len(val_b) == 4 and val_b[1] == ":":
            val_b = "0" + val_b

        # 既存に存在しないペアのみを抽出
        if (val_a, val_b) not in existing_keys:
            # 日付フォーマットの正規化を反映
            row_dict = row.to_dict()
            row_dict[new_col_a] = val_a
            row_dict[new_col_b] = val_b
            new_rows.append(row_dict)
            existing_keys.add((val_a, val_b))

    # 3. マスターCSVへの追記・保存処理
    if new_rows:
        df_to_add = pd.DataFrame(new_rows)
        file_exists = os.path.exists(CSV_PATH) and os.path.getsize(CSV_PATH) > 0

        # ファイルが存在する場合はヘッダーなしで追記(mode='a')、存在しない場合はヘッダー付き新規作成
        df_to_add.to_csv(
            CSV_PATH,
            mode="a" if file_exists else "w",
            header=not file_exists,
            index=False,
            encoding="utf-8-sig",  # Excel等で開いても文字化けしないBOM付きUTF-8
        )
        print(f"【成功】新規データ {len(df_to_add)} 件を「パワコン_2026.csv」に追記しました！")
    else:
        print("すべてのデータが既存データ（年月日・時刻が一致）と重複しているため、追記をスキップしました。")


def main():
    if not USER_ID or not PASSWORD:
        print("エラー: KP_USER_ID または KP_PASSWORD が設定されていません。")
        sys.exit(1)

    driver = create_driver()

    try:
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
                id_input = driver.find_element(
                    By.XPATH, "//input[@type='text' or @type='email']"
                )

        try:
            pass_input = driver.find_element(By.ID, "password")
        except Exception:
            try:
                pass_input = driver.find_element(By.NAME, "password")
            except Exception:
                pass_input = driver.find_element(
                    By.XPATH, "//input[@type='password']"
                )

        id_input.clear()
        id_input.send_keys(USER_ID)
        pass_input.clear()
        pass_input.send_keys(PASSWORD)

        print("ログインボタンをクリック...")
        try:
            login_btn = driver.find_element(
                By.XPATH, "//button[@type='submit'] | //input[@type='submit']"
            )
            login_btn.click()
        except Exception:
            pass_input.send_keys(Keys.RETURN)

        time.sleep(5)

        print("「各種データのCSV出力」をクリック中...")
        try:
            btn = driver.find_element(
                By.XPATH,
                "//form[contains(@action, 'variousdataoutputselect')]//button",
            )
            btn.click()
        except Exception as e1:
            print(f"フォーム属性検索失敗のためフォールバック実行: {e1}")
            btn = driver.find_element(By.XPATH, "//h5[contains(., '各種データ')]")
            btn.click()

        time.sleep(3)

        print("「計測データのCSV出力」をクリック中...")
        try:
            driver.find_element(
                By.XPATH, "//*[contains(text(), '計測データ')]"
            ).click()
        except Exception:
            driver.find_element(
                By.XPATH, "//button[contains(., '計測データ')]"
            ).click()
        time.sleep(3)

        print("「データ出力」をクリック中...")
        try:
            driver.find_element(
                By.XPATH, "//*[contains(text(), 'データ出力')]"
            ).click()
        except Exception:
            driver.find_element(By.XPATH, "//button[@type='submit']").click()

        print("ファイルダウンロードを待機中...")
        time.sleep(5)

        downloaded_csv = get_latest_downloaded_csv(DOWNLOAD_DIR)

        if downloaded_csv and os.path.exists(downloaded_csv):
            print(f"【成功】CSVファイル取得完了: {downloaded_csv}")
            update_master_csv_with_new_csv(downloaded_csv)
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
