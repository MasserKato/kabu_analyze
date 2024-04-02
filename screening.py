import requests
import time
# html名を指定
html_list = ['index.html', '00-archives-01.html', '00-archives-02.html', '00-archives-03.html']

def get_html(html):
    # もし既にhtmlが保存されていれば、処理をスキップ
    try:
        with open(f'./saved_page_{html}', 'r', encoding='utf-8') as f:
            html_content = f.read()
        print('Already saved:', html)
    except FileNotFoundError:
    
        # htmlを取得
        response = requests.get('http://www.jpx.co.jp/listing/stocks/new/' + html)
        time.sleep(1)
        response.encoding = response.apparent_encoding
        if response.status_code == 200:
            print('Success:', html)
            with open(f'./saved_page_{html}', 'w', encoding='utf-8') as f:
                f.write(response.text)


for html in html_list:
    get_html(html)

from datetime import datetime
import re
from bs4 import BeautifulSoup

def get_stock_code(html):
    with open(f'./saved_page_{html}', 'r', encoding='utf-8') as f:
        html = f.read()
    soup = BeautifulSoup(html, 'html.parser')
    # stock_codeを取得
    stock_codes = soup.find('div', {'id': 'main-area'}).find('tbody').find_all('span')
    stock_code = [span['id'] for span in stock_codes]
    tr_elements = soup.find('tbody').find_all('tr')
    td_elements = [tr_element.find('td', {'rowspan':'2'}) for tr_element in tr_elements]
    # 日付リストを保存するための空のリストを用意
    dates = []
    
    # 各td要素に対してループ処理
    for td in td_elements:
        if td:
            # カッコ内のテキストを除去
            text = re.sub(r'\（.*?\）', '', td.text)
            # チルダがある場合、最初の日付のみ使用
            if '～' in text:
                date = text.split('～')[0].strip()
            else:
                date = text.strip()
            dates.append(date)   # 上場年月日が現在から３週間以内の銘柄は除外する
    dates = [datetime.strptime(date, '%Y/%m/%d') for date in dates]
    stock_code = [code for code, date in zip(stock_code, dates) if (datetime.now() - date).days > 21]
    # 上場年月日が現在から３年以上前の銘柄も除外する
    stock_code = [code for code, date in zip(stock_code, dates) if (datetime.now() - date).days < 3*365]
    return stock_code

all_stock_code = []
for html in html_list:
    all_stock_code.extend(get_stock_code(html))
print(f'Number of stock codes: {len(all_stock_code)}')
import time
# それぞれの銘柄について、一日あたりの売買高を取得し、１億円に満たない銘柄をall_stock_codeから除外
def check_volume_100M(stock_code):
    response = requests.get(f'https://finance.yahoo.co.jp/quote/{stock_code}.T/')
    response.encoding = response.apparent_encoding
    if response.status_code == 200:
        time.sleep(1)
        print('Success:', stock_code)
        soup = BeautifulSoup(response.text, 'html.parser')
        # class名が,"_3rXWJKZF _11kV6f2G"となっているspanタグについて、その内容を取得
        trading_volume = soup.find_all('span', {'class': '_3rXWJKZF _11kV6f2G'})[5].text.replace(',', '')
        # もしtrading_volumeが数値でない場合、0を返す
        try:
            trading_volume = int(trading_volume)
        except ValueError:
            trading_volume = 0
        print(f"Trading volume of {stock_code}: {trading_volume}")
        return trading_volume >= 10**5

# 一日あたりの売買高が1億円以上の銘柄を記録したテキストファイルが、保存されていない場合は新規作成。既に存在する場合は、入力を要求して、yなら上書き、nなら処理をスキップする。
all_stock_code_filtered = []
try:
    with open('./all_stock_code_filtered.txt', 'r') as f:
        print('all_stock_code_filtered.txt already exists.')
        all_stock_code_filtered = f.read().split('\n')
# ファイルが存在しない場合
except FileNotFoundError:
    for stock_code in all_stock_code:
        if check_volume_100M(stock_code):
            print('Added:', stock_code)
            all_stock_code_filtered.append(stock_code)
    with open('./all_stock_code_filtered.txt', 'w') as f:
        f.write('\n'.join(all_stock_code_filtered))

import yfinance as yf

# それぞれの銘柄について、全期間の株価データを取得。ただし、期間が３年以上になっている場合は、最近の３年間のデータを取得する。
def get_stock_data(stock_code):
    stock = yf.Ticker(f'{stock_code}.T')
    stock_data = stock.history(period='max')
    if len(stock_data) > 3*365:
        stock_data = stock.history(period='3y')
    return stock_data

# 全期間の中で、最初の１ヶ月での高値を取得
def get_high_price(stock_data):
    return stock_data['High'][:30].max()

# 直近１週間の高値を取得
def get_high_price_week(stock_data):
    return stock_data['High'][-5:].max()

# 上場来一ヶ月の高値に対して、直近１週間の高値が何％かを計算
def calculate_high_price_ratio(stock_data):
    high_price = get_high_price(stock_data)
    high_price_week = get_high_price_week(stock_data)
    return high_price_week / high_price

# 上場１ヶ月以内を除外した期間での高値に対して、直近１週間の高値が何％かを計算
def calculate_high_price_ratio_filtered(stock_data):
    high_price = stock_data['High'][30:].max()
    high_price_week = stock_data['High'][-5:].max()
    return high_price_week / high_price

# high_price_ratioが250%以上または30%未満の銘柄を除外
all_stock_code_filtered = []
with open('./all_stock_code_filtered.txt', 'r') as f:
    all_stock_code_filtered = f.read().split('\n')
all_stock_code_filtered = [stock_code for stock_code in all_stock_code_filtered if 0.3 < calculate_high_price_ratio(get_stock_data(stock_code)) < 2]
# high_price_ratio_filteredが50%未満の銘柄を除外
all_stock_code_filtered = [stock_code for stock_code in all_stock_code_filtered if calculate_high_price_ratio_filtered(get_stock_data(stock_code)) > 0.5]

print(f'Number of stock codes after filtered: {len(all_stock_code_filtered)}')
# all_stock_code_filteredを保存
with open('./all_stock_code_filtered2.txt', 'w') as f:
    f.write('\n'.join(all_stock_code_filtered))
