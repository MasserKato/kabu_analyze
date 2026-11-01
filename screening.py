import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

# html名を指定
html_list = ['index.html', '00-archives-01.html', '00-archives-02.html', '00-archives-03.html']

JPX_BASE = 'https://www.jpx.co.jp/listing/stocks/new/'
YAHOO_QUOTE = 'https://finance.yahoo.co.jp/quote/{code}.T/'
REQUEST_TIMEOUT = 30
# 応答の取得先はこれらのホストだけを許可する
ALLOWED_HOSTS = frozenset({'www.jpx.co.jp', 'finance.yahoo.co.jp'})
HTML_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.html$')
# 保存済み一覧にある東証コード: 4桁の数字、または数字3桁+英字1文字
STOCK_CODE_RE = re.compile(r'^(?:[0-9]{4}|[0-9]{3}[A-Z])$')
_ACTIVE_CONTENT_RE = re.compile(
    r'<\s*(script|iframe|object|embed)\b[^>]*>.*?<\s*/\s*\1\s*>',
    re.IGNORECASE | re.DOTALL,
)
_ACTIVE_VOID_RE = re.compile(
    r'<\s*(script|iframe|object|embed)\b[^>]*/?>',
    re.IGNORECASE,
)


def is_stock_code(code):
    return isinstance(code, str) and STOCK_CODE_RE.fullmatch(code) is not None


def saved_page_path(html_name):
    """保存ファイル名を作業ディレクトリ内に閉じ込める。"""
    if not isinstance(html_name, str) or HTML_NAME_RE.fullmatch(html_name) is None:
        raise ValueError('invalid html name')
    root = Path('.').resolve()
    path = (root / f'saved_page_{html_name}').resolve()
    if path.parent != root:
        raise ValueError('invalid html path')
    return path


def strip_active_content(html_text):
    """保存するHTMLからスクリプト等を除く。表のテキストは残す。"""
    previous = None
    current = html_text
    while previous != current:
        previous = current
        current = _ACTIVE_CONTENT_RE.sub('', current)
    return _ACTIVE_VOID_RE.sub('', current)


def fetch_url(url):
    """HTTPSかつ許可ホストへのリクエストだけを実行する。"""
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError('refusing URL outside the allowlist')
    response = requests.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
    final = urlparse(response.url)
    if final.scheme != 'https' or final.hostname != parsed.hostname:
        raise ValueError('refusing redirect outside the original host')
    return response


def get_html(html):
    # もし既にhtmlが保存されていれば、処理をスキップ
    path = saved_page_path(html)
    try:
        with path.open('r', encoding='utf-8') as f:
            f.read()
        print('Already saved:', html)
    except FileNotFoundError:
        # htmlを取得
        response = fetch_url(JPX_BASE + html)
        time.sleep(1)
        response.encoding = response.apparent_encoding
        if response.status_code == 200:
            print('Success:', html)
            with path.open('w', encoding='utf-8') as f:
                f.write(strip_active_content(response.text))


def get_stock_code(html):
    with saved_page_path(html).open('r', encoding='utf-8') as f:
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
    # リモートHTMLのidをURLへ渡す前に形式を確認する
    stock_code = [code for code in stock_code if is_stock_code(code)]
    return stock_code


# それぞれの銘柄について、一日あたりの売買高を取得し、１億円に満たない銘柄をall_stock_codeから除外
def check_volume_100M(stock_code):
    if not is_stock_code(stock_code):
        print('Skip invalid code:', stock_code)
        return False
    response = fetch_url(YAHOO_QUOTE.format(code=stock_code))
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


def get_stock_data(stock_code):
    if not is_stock_code(stock_code):
        raise ValueError('invalid stock code')
    # それぞれの銘柄について、全期間の株価データを取得。ただし、期間が３年以上になっている場合は、最近の３年間のデータを取得する。
    import yfinance as yf
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


def main():
    for html in html_list:
        get_html(html)

    all_stock_code = []
    for html in html_list:
        all_stock_code.extend(get_stock_code(html))
    print(f'Number of stock codes: {len(all_stock_code)}')

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

    # high_price_ratioが250%以上または30%未満の銘柄を除外
    all_stock_code_filtered = []
    with open('./all_stock_code_filtered.txt', 'r') as f:
        all_stock_code_filtered = f.read().split('\n')
    all_stock_code_filtered = [stock_code for stock_code in all_stock_code_filtered if is_stock_code(stock_code) and 0.3 < calculate_high_price_ratio(get_stock_data(stock_code)) < 2]
    # high_price_ratio_filteredが50%未満の銘柄を除外
    all_stock_code_filtered = [stock_code for stock_code in all_stock_code_filtered if calculate_high_price_ratio_filtered(get_stock_data(stock_code)) > 0.5]

    print(f'Number of stock codes after filtered: {len(all_stock_code_filtered)}')
    # all_stock_code_filteredを保存
    with open('./all_stock_code_filtered2.txt', 'w') as f:
        f.write('\n'.join(all_stock_code_filtered))


if __name__ == '__main__':
    main()
