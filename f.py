import requests
from bs4 import BeautifulSoup
import time
import re
import pandas as pd
from datetime import datetime
import logging
import requests

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Список магазинов для проверки
SHOPS = [
    {'name': 'Перекрёсток', 'url': 'https://eda.yandex.ru/retail/perekrestok/placeSlug=perekrestok_vypsp'},
    {'name': 'Магнит', 'url': 'https://eda.yandex.ru/retail/magnit/placeSlug=magnit_vypsp'},
    {'name': 'Вкусвилл', 'url': 'https://eda.yandex.ru/retail/vkusvill_express/placeSlug=vkusvill_express_vypsp'},
    # Добавьте другие магазины по необходимости
]

def get_html(url, params=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.text
        else:
            logger.error(f"Error: status code {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Connection error: {e}")
        return None
import requests

def send_to_telegram(products):
    # Замените на ваш токен бота и chat_id
    bot_token = '7809190658:AAEi_uG41kvEanBFohFJpDE43eMOEpUcBcI'
    chat_id = '@salesbuyers'
    
    for product in products:
        discount_text = f" (скидка {product['discount']}%)" if product['discount'] > 0 else ""
        message = f"Найден товар: {product['product_name']}\nЦена: {product['current_price']} руб{discount_text}\nМагазин: {product['shop_name']}\nСсылка: {product['url']}"
        
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        data = {'chat_id': chat_id, 'text': message}
        
        try:
            response = requests.post(url, data=data)
            if response.status_code != 200:
                logger.error(f"Ошибка отправки в Телеграм: {response.text}")
        except Exception as e:
            logger.error(f"Ошибка при отправке в Телеграм: {e}")
        
        time.sleep(1)  # Пауза между отправками сообщений
def extract_discount(old_price, current_price):
    if not old_price or not current_price:
        return 0
    try:
        old_price = float(old_price.replace('₽', '').replace(' ', '').strip())
        current_price = float(current_price.replace('₽', '').replace(' ', '').strip())
        if old_price > current_price:
            return round(((old_price - current_price) / old_price) * 100)
        return 0
    except:
        return 0

def parse_price(price_text):
    if not price_text:
        return None
    # Удаляем все нецифровые символы кроме точки
    clean_price = re.sub(r'[^\d.]', '', price_text)
    try:
        return float(clean_price)
    except:
        return None

def parse_products(html, shop_name, shop_url):
    soup = BeautifulSoup(html, 'html.parser')
    products = []
    
    # Ищем все блоки товаров
    # На основе ваших скриншотов, товары представлены с ценой и названием
    product_blocks = soup.find_all('div', class_=lambda c: c and ('product-card' in c or 'item' in c or 'ProductCard' in c))
    
    if not product_blocks:
        # Если не нашли по классу, ищем элементы с ценой
        price_elements = soup.find_all(text=re.compile(r'\d+\s*₽'))
        for price_element in price_elements:
            parent = price_element.parent
            for _ in range(5):  # Проверяем до 5 уровней вверх по дереву
                if parent and parent.name:
                    # Проверяем, есть ли в родительском блоке название товара
                    name_element = parent.find(text=lambda t: t and len(t.strip()) > 3 and not re.search(r'^\d+\s*₽$', t.strip()))
                    if name_element:
                        current_price = parse_price(price_element.strip())
                        
                        # Ищем старую цену (со скидкой)
                        old_price_element = parent.find(text=re.compile(r'\d+\s*₽'))
                        if old_price_element and old_price_element != price_element:
                            old_price = parse_price(old_price_element.strip())
                        else:
                            old_price = None
                        
                        discount = extract_discount(old_price, current_price) if old_price else 0
                        
                        # Если цена <= 50 рублей или скидка >= 30%
                        if (current_price and current_price <= 50) or discount >= 30:
                            product_url = shop_url
                            # Пытаемся найти ссылку на продукт
                            link = parent.find('a', href=True)
                            if link:
                                product_url = "https://eda.yandex.ru" + link['href'] if link['href'].startswith('/') else link['href']
                            
                            products.append({
                                'shop_name': shop_name,
                                'product_name': name_element.strip(),
                                'current_price': current_price,
                                'old_price': old_price,
                                'discount': discount,
                                'url': product_url
                            })
                            break
                    parent = parent.parent
                else:
                    break
    
    # Если нашли продукты по классу, обрабатываем их
    else:
        for block in product_blocks:
            try:
                # Ищем название продукта
                name_element = block.find(text=lambda t: t and len(t.strip()) > 3 and not re.search(r'^\d+\s*₽$', t.strip()))
                product_name = name_element.strip() if name_element else "Неизвестный продукт"
                
                # Ищем текущую цену
                price_element = block.find(text=re.compile(r'\d+\s*₽'))
                current_price = parse_price(price_element.strip()) if price_element else None
                
                # Ищем старую цену (со скидкой)
                old_price_element = block.find('span', class_=lambda c: c and ('old-price' in c or 'crossed' in c))
                old_price = parse_price(old_price_element.text.strip()) if old_price_element else None
                
                # Если не нашли старую цену, ищем еще раз в других элементах
                if not old_price:
                    old_price_element = block.find(text=re.compile(r'\d+\s*₽'))
                    if old_price_element and old_price_element != price_element:
                        old_price = parse_price(old_price_element.strip())
                
                # Вычисляем скидку
                discount = extract_discount(old_price, current_price) if old_price else 0
                
                # Если цена <= 50 рублей или скидка >= 30%
                if (current_price and current_price <= 100) or discount >= 30:
                    # Ищем ссылку на продукт
                    link = block.find('a', href=True)
                    product_url = "https://eda.yandex.ru" + link['href'] if link and link['href'].startswith('/') else shop_url
                    
                    products.append({
                        'shop_name': shop_name,
                        'product_name': product_name,
                        'current_price': current_price,
                        'old_price': old_price,
                        'discount': discount,
                        'url': product_url
                    })
            except Exception as e:
                logger.error(f"Error parsing product block: {e}")
    
    return products

def save_to_csv(data, filename):
    df = pd.DataFrame(data)
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    logger.info(f"Data saved to {filename}")

def send_to_telegram(products):
    # Здесь будет код для отправки в Телеграм
    # Пока просто выводим в консоль
    for product in products:
        discount_text = f" (скидка {product['discount']}%)" if product['discount'] > 0 else ""
        logger.info(f"Найден товар: {product['product_name']} - {product['current_price']} руб{discount_text} в {product['shop_name']}")
        logger.info(f"Ссылка: {product['url']}")

def main():
    logger.info("Запуск парсера по магазинам...")
    all_products = []
    
    for shop in SHOPS:
        logger.info(f"Проверка магазина: {shop['name']}")
        html = get_html(shop['url'])
        
        if html:
            products = parse_products(html, shop['name'], shop['url'])
            logger.info(f"Найдено {len(products)} товаров со скидкой или дешевле 50₽ в {shop['name']}")
            all_products.extend(products)
            time.sleep(2)  # Пауза между запросами
        else:
            logger.error(f"Не удалось получить HTML для {shop['name']}")
    
    if all_products:
        # Генерируем имя файла с текущей датой и временем
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'cheap_products_{timestamp}.csv'
        save_to_csv(all_products, filename)
        send_to_telegram(all_products)
    else:
        logger.info("Не найдено товаров, соответствующих критериям")

def monitor():
    while True:
        try:
            main()
            logger.info("Ждем 30 минут до следующей проверки...")
            time.sleep(1800)  # 30 минут
        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")
            time.sleep(300)  # Ждем 5 минут при ошибке

if __name__ == "__main__":
    monitor()
