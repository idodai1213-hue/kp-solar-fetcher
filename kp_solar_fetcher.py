import os
import time
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
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

def main():
    if not USER_ID or not PASSWORD:
        print("エラー: KP_USER_ID または KP_PASSWORD が設定されていません。")
        return

    # クラウド(Linux)上で動作させるためのChrome設定
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')  # 画面を出さずに裏で実行
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--start-maximized')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    # ダウンロード設定
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

        # ダウンロードされたか確認
        files = os.listdir(DOWNLOAD_DIR)
        print(f"ダウンロード完了！ 保存ファイル一覧: {files}")

    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
        print(f"エラー時のURL: {driver.current_url}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
