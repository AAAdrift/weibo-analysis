from flask import Flask, render_template, request, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import time
import os
from openai import OpenAI
from pathlib import Path
from selenium.webdriver.common.keys import Keys

app = Flask(__name__)

def login(driver):
    driver.get("https://weibo.com/")
    main_window = driver.current_window_handle
    try:
        login_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button.LoginCard_btn_Jp_u1'))
        )
        login_button.click()
        WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))
        for window_handle in driver.window_handles:
            if window_handle != main_window:
                driver.switch_to.window(window_handle)
                break
        time.sleep(10)  # 等待手动登录
        driver.switch_to.window(main_window)
    except Exception as e:
        print("登录失败：", str(e))

def extract_weibo_content(weibo_html):
    soup = BeautifulSoup(weibo_html, 'html.parser')
    result = {
        "content": "",
        "timestamp": "发布时间未知",
        "images": [],
        "retweeted_content": None
    }
    content_div = soup.find("div", class_="detail_wbtext_4CRf9")
    if content_div:
        result["content"] = content_div.get_text(strip=True)
    timestamp_element = soup.find("a", class_="head-info_time_6sFQg")
    if timestamp_element:
        result["timestamp"] = timestamp_element.get_text(strip=True)
    image_elements = soup.select('.picture_pic_eLDxR img')
    result["images"] = [img['src'] for img in image_elements] if image_elements else []
    retweet_container = soup.find("div", class_="retweet Feed_retweet_JqZJb")
    if retweet_container:
        retweet_content_div = retweet_container.find("div", class_="detail_wbtext_4CRf9")
        if retweet_content_div:
            retweet_author = retweet_container.find("span", class_="detail_nick_u-ffy").get_text(strip=True)
            retweet_text = retweet_content_div.get_text(strip=True)
            result["retweeted_content"] = {
                "author": retweet_author,
                "content": retweet_text
            }
    return result

def get_blogs(user_name, driver):
    search_button_script = """
    const searchButton = document.querySelector('.SearchIcon_wrap_3fgul');
    if (searchButton) {
        searchButton.style.visibility = 'visible';
        searchButton.style.display = 'block';
        const clickEvent = new MouseEvent('click', { bubbles: true });
        searchButton.dispatchEvent(clickEvent);
    }
    """
    driver.execute_script(search_button_script)

    search_input = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CLASS_NAME, "woo-input-main"))
    )

    search_input.send_keys(user_name)
    time.sleep(1)
    search_input.send_keys(Keys.RETURN)

    original_window = driver.current_window_handle
    WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))

    for window_handle in driver.window_handles:
        if window_handle != original_window:
            driver.switch_to.window(window_handle)
            break

    user_tab = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, '//div[@class="m-main-nav"]/ul/li/a[@title="用户"]'))
    )
    user_tab.click()

    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.ID, "pl_user_feedList"))
    )

    original_window = driver.current_window_handle
    initial_window_count = len(driver.window_handles)

    user_cards = driver.find_elements(By.CSS_SELECTOR, '.card.card-user-b.s-brt1.card-user-b-padding')
    for card in user_cards:
        try:
            username_element = card.find_element(By.XPATH, './/div[@class="info"]/div/a[@class="name"]')
            if user_name in username_element.text:
                user_link = card.find_element(By.XPATH, './/a')
                user_link.click()
                break
        except Exception as e:
            print("未能找到用户名元素或链接：", str(e))

    WebDriverWait(driver, 10).until(
        lambda driver: len(driver.window_handles) > initial_window_count
    )

    latest_window = driver.window_handles[-1]
    driver.switch_to.window(latest_window)

    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.XPATH, '//div[@class="Main_full_1dfQX"]'))
    )

    weibo_list = extract_all_weibos(driver)
    return weibo_list

def extract_all_weibos(driver):
    weibo_list = []
    extracted_ids = set()
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_step = 200

    while True:
        previous_weibo_count = len(weibo_list)
        all_weibos = driver.find_elements(By.CSS_SELECTOR, 'article.woo-panel-main.Feed_wrap_3v9LH')

        for weibo in all_weibos:
            try:
                weibo_html = weibo.get_attribute('innerHTML')
            except Exception as e:
                print("·此微博已过期")
                continue
            soup = BeautifulSoup(weibo_html, 'html.parser')
            weibo_link = soup.find("a", class_="head-info_time_6sFQg")
            if not weibo_link:
                continue
            weibo_id = weibo_link['href'].split('/')[-1]
            if weibo_id not in extracted_ids:
                flag = True
                try:
                    expand_button = weibo.find_element(By.CSS_SELECTOR, '.expand')
                    driver.execute_script("""
                        arguments[0].scrollIntoView({ 
                            behavior: 'smooth', 
                            block: 'center', 
                            inline: 'nearest' 
                        });
                    """, expand_button)
                    driver.execute_script("arguments[0].click();", expand_button)
                    time.sleep(1)
                except Exception as e:
                    print(f"点击展开按钮失败：{e}")
                    flag = False
                if flag:
                    print("成功点击展开！")
                    weibo_html = weibo.get_attribute('innerHTML')
                
                extracted_ids.add(weibo_id)
                weibo_data = extract_weibo_content(weibo_html)
                if weibo_data:
                    weibo_data["id"] = weibo_id
                    weibo_list.append(weibo_data)
                    print(f"-------新提取到了一条------")
                    print(weibo_data)
                    print("------------------------")
            else:
                print(f"·此微博id：{weibo_id}处理过")

        # 开始小步平滑滚动
        current_scroll_position = driver.execute_script("return window.pageYOffset || document.documentElement.scrollTop;")
        new_scroll_position = current_scroll_position + scroll_step
        driver.execute_script(f"window.scrollTo(0, {new_scroll_position});")
        new_scroll_position = driver.execute_script("return window.pageYOffset || document.documentElement.scrollTop;")
        time.sleep(1)

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_scroll_position == current_scroll_position:
            print("已滚动到底部，检查是否有新内容")
            time.sleep(1)
            if new_height == last_height:
                print("已到达最底部，提取任务完成")
                break
        last_height = new_height

    return weibo_list

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/extract', methods=['POST'])
def extract():
    data = request.json
    target_user_name = data.get('target_user_name', '作家陈岚')
    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(options=options)

    login(driver)
    weibo_list = get_blogs(target_user_name, driver)

    with open('all_weibo.txt', 'w', encoding='utf-8') as f:
        for idx, weibo in enumerate(weibo_list, start=1):
            f.write(f"微博 {idx}\n")
            f.write(f"时间: {weibo['timestamp']}\n")
            f.write(f"文本: {weibo['content']}\n")
            if weibo['retweeted_content']:
                f.write(f"转发微博： {weibo['retweeted_content']}\n")
            f.write("\n")

    client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    file_object = client.files.create(file=Path("all_weibo.txt"), purpose="file-extract")
    file_id = file_object.id

    completion = client.chat.completions.create(
        model="qwen-long",
        messages=[
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            {'role': 'system', 'content': f'fileid://{file_id}'},
            {'role': 'user', 'content': '这是一个微博账号的主页里提取到的微博内容，请总结这个账号的行为特点，做情感分析，结果用普通文本格式而非markdown格式。'}
        ],
        stream=True,
        stream_options={"include_usage": True}
    )

    full_content = ""
    for chunk in completion:
        if chunk.choices and chunk.choices[0].delta.content:
            full_content += chunk.choices[0].delta.content
    
    return jsonify({"analysis": full_content})

if __name__ == '__main__':
    app.run(debug=True)
