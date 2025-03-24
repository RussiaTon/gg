from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
import time
import telegram
import os
import logging
import asyncio
import json
import traceback
import re

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("parser.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("yandex_eda_parser")

# Настройка Telegram бота
TELEGRAM_TOKEN = "7809190658:AAEi_uG41kvEanBFohFJpDE43eMOEpUcBcI"
CHAT_ID = "@salesbuyers"

# Пытаемся загрузить из файла .env, если он есть
try:
    from dotenv import load_dotenv
    load_dotenv()
    env_token = os.getenv('TELEGRAM_TOKEN')
    env_chat_id = os.getenv('TELEGRAM_CHAT_ID')
    
    # Используем значения из .env, если они есть
    if env_token:
        TELEGRAM_TOKEN = env_token
    if env_chat_id:
        CHAT_ID = env_chat_id
except ImportError:
    logger.warning("Модуль dotenv не установлен. Используем значения из кода.")
except Exception as e:
    logger.warning(f"Ошибка при загрузке .env: {e}")

# Проверка валидности токена
if not TELEGRAM_TOKEN:
    logger.error("Необходимо указать токен Telegram бота!")
    use_telegram = False
else:
    use_telegram = True
    try:
        bot = telegram.Bot(token=TELEGRAM_TOKEN)
        logger.info("Бот Telegram инициализирован успешно")
    except Exception as e:
        logger.error(f"Ошибка инициализации бота Telegram: {e}")
        use_telegram = False
        print(f"ОШИБКА: Не удалось инициализировать бота Telegram: {e}")

# Список магазинов для проверки
STORES = [
    "Пятерочка",
    "Перекресток",
    "Магнит",
    "ВкусВилл",
    "Дикси",
    "Лента",
    "Метро"
]

# Настройка Selenium с улучшенными опциями
def setup_driver(headless=False):
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")
    
    # Улучшенные опции для большей стабильности
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")
    
    # Добавляем cookie для обхода капчи
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--allow-running-insecure-content")
    
    driver = webdriver.Chrome(options=chrome_options)
    
    # Скрываем признаки автоматизации
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    driver.maximize_window()
    return driver

# Функция для отправки сообщения в Telegram (асинхронная)
async def async_send_message(text, parse_mode=None):
    if not use_telegram:
        return
    
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")

# Функция-обертка для отправки сообщения
def send_message(text, parse_mode=None):
    if not use_telegram:
        logger.info(f"Сообщение (без отправки в Telegram): {text}")
        print(f"Сообщение (без отправки в Telegram): {text}")
        return
    
    try:
        asyncio.run(async_send_message(text, parse_mode))
        logger.info(f"Сообщение отправлено в Telegram")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        print(f"Ошибка отправки сообщения: {e}")

# Асинхронная функция для отправки фото
async def async_send_photo(photo_url, caption=None, parse_mode=None):
    if not use_telegram:
        return
    
    try:
        await bot.send_photo(chat_id=CHAT_ID, photo=photo_url, caption=caption, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Ошибка отправки фото: {e}")
        # Пытаемся отправить как текст
        await async_send_message(caption, parse_mode)

# Функция-обертка для отправки фото
def send_photo(photo_url, caption=None, parse_mode=None):
    if not use_telegram:
        logger.info(f"Фото (без отправки в Telegram): {photo_url}")
        print(f"Фото (без отправки в Telegram): {photo_url}")
        print(f"Подпись: {caption}")
        return
    
    try:
        asyncio.run(async_send_photo(photo_url, caption, parse_mode))
        logger.info(f"Фото отправлено в Telegram")
    except Exception as e:
        logger.error(f"Ошибка отправки фото: {e}")
        print(f"Ошибка отправки фото: {e}")
        # Пытаемся отправить как текст
        send_message(caption, parse_mode)

# Улучшенная функция проверки капчи
def handle_captcha(driver, max_wait_time=120):
    try:
        # Проверяем наличие капчи с помощью явных ожиданий
        captcha_found = False
        
        # Расширенные селекторы для обнаружения капчи
        captcha_selectors = [
            "//div[contains(@class, 'captcha')]",
            "//iframe[contains(@src, 'captcha')]",
            "//div[contains(@class, 'Captcha')]",
            "//div[contains(text(), 'captcha') or contains(text(), 'Captcha')]",
            "//img[contains(@src, 'captcha')]",
            "//div[contains(@class, 'CheckboxCaptcha')]",
            "//div[contains(@class, 'robot-detector')]"
        ]
        
        # Проверяем каждый селектор
        for selector in captcha_selectors:
            try:
                captcha_elements = driver.find_elements(By.XPATH, selector)
                if captcha_elements:
                    captcha_found = True
                    break
            except:
                continue
        
        if captcha_found:
            logger.info("⚠️ Обнаружена капча! Пожалуйста, пройдите её вручную.")
            print("\n⚠️ ОБНАРУЖЕНА КАПЧА! Пожалуйста, пройдите её вручную в открытом браузере.")
            
            # Отправляем сообщение в Telegram о необходимости пройти капчу
            send_message("⚠️ Обнаружена капча! Пожалуйста, пройдите её вручную.")
            
            # Делаем скриншот капчи
            driver.save_screenshot("captcha.png")
            print("Скриншот капчи сохранен как captcha.png")
            
            # Ждем пока пользователь пройдет капчу
            start_time = time.time()
            while time.time() - start_time < max_wait_time:
                # Проверяем, пропала ли капча
                captcha_still_exists = False
                for selector in captcha_selectors:
                    try:
                        if driver.find_elements(By.XPATH, selector):
                            captcha_still_exists = True
                            break
                    except:
                        pass
                
                if not captcha_still_exists:
                    logger.info("✅ Капча успешно пройдена!")
                    print("✅ Капча успешно пройдена!")
                    return True
                
                # Также проверяем, перешли ли мы уже на нужную страницу
                current_url = driver.current_url
                if "eda.yandex.ru/retail" in current_url:
                    if "/store/" in current_url or "/shop/" in current_url:
                        logger.info("✅ Переход на страницу магазина успешен после капчи!")
                        print("✅ Переход на страницу магазина успешен после капчи!")
                        return True
                
                time.sleep(1)
                
            logger.warning(" Время на прохождение капчи истекло")
            print(" Время на прохождение капчи истекло")
            return False
        
        return True  # Капчи нет, продолжаем работу
    
    except Exception as e:
        logger.error(f"Ошибка при проверке капчи: {e}")
        print(f" Ошибка при проверке капчи: {e}")
        return True  # В случае ошибки продолжаем работу

# Полностью переработанная функция установки местоположения
def set_location(driver, address="Москва"):
    try:
        logger.info(f"Устанавливаем местоположение: {address}")
        print(f"\n🌍 Устанавливаем местоположение: {address}")
        
        # Прямой метод через URL (наиболее надежный способ)
        encoded_address = address.lower().replace(" ", "%20")
        driver.get(f"https://eda.yandex.ru/retail?address={encoded_address}")
        
        # Ждем загрузки страницы
        time.sleep(5)
        
        # Проверяем, установлено ли местоположение, проверив наличие контента
        try:
            # Ждем загрузки элементов страницы
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'PlacesList')]"))
            )
            logger.info(f"✅ Страница с магазинами загружена для адреса: {address}")
            print(f"✅ Страница с магазинами загружена для адреса: {address}")
            return True
        except TimeoutException:
            logger.warning("Не удалось загрузить страницу с магазинами")
            
        # Альтернативный метод: через диалог выбора адреса
        try:
            # Пытаемся найти и кликнуть на кнопку выбора адреса
            address_button_selectors = [
                "//button[contains(@aria-label, 'адрес')]",
                "//button[contains(@class, 'LocationSelector')]",
                "//div[contains(@class, 'LocationSelector')]",
                "//span[contains(text(), 'Укажите адрес')]",
                "//div[contains(@class, 'AddressField')]"
            ]
            
            for selector in address_button_selectors:
                try:
                    elements = driver.find_elements(By.XPATH, selector)
                    if elements:
                        elements[0].click()
                        logger.info(f"Кликнули на кнопку адреса через: {selector}")
                        print(f"Кликнули на кнопку адреса через: {selector}")
                        time.sleep(2)
                        break
                except Exception as e:
                    continue
            
            # Ввод адреса
            input_selectors = [
                "//input[contains(@placeholder, 'Введите адрес')]",
                "//input[contains(@class, 'SearchInput')]",
                "//input[contains(@class, 'AddressInput')]"
            ]
            
            for selector in input_selectors:
                try:
                    # Используем явное ожидание для поиска поля ввода
                    input_field = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, selector))
                    )
                    input_field.clear()
                    input_field.send_keys(address)
                    logger.info(f"Ввели адрес через: {selector}")
                    print(f"Ввели адрес через: {selector}")
                    time.sleep(2)
                    break
                except Exception as e:
                    continue
                    
            # Клик на первую подсказку
            suggest_selectors = [
                "//div[contains(@class, 'SuggestsList')]/div",
                "//ul[contains(@class, 'SuggestsList')]/li",
                "//div[contains(@class, 'suggests-item')]"
            ]
            
            for selector in suggest_selectors:
                try:
                    suggests = WebDriverWait(driver, 5).until(
                        EC.presence_of_all_elements_located((By.XPATH, selector))
                    )
                    if suggests:
                        suggests[0].click()
                        logger.info("Выбрали первую подсказку адреса")
                        print("Выбрали первую подсказку адреса")
                        break
                except Exception as e:
                    continue
                    
            # Подтверждение адреса, если нужно
            confirm_selectors = [
                "//button[contains(text(), 'Подтвердить')]",
                "//button[contains(text(), 'Сохранить')]",
                "//button[contains(@class, 'Button_primary')]"
            ]
            
            for selector in confirm_selectors:
                try:
                    confirm_button = WebDriverWait(driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, selector))
                    )
                    confirm_button.click()
                    logger.info("Подтвердили адрес")
                    print("Подтвердили адрес")
                    break
                except Exception as e:
                    continue
            
            # Ждем загрузки страницы с магазинами
            time.sleep(5)
            logger.info(f"✅ Адрес установлен: {address}")
            print(f"✅ Адрес установлен: {address}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при установке адреса через диалог: {e}")
            print(f"Ошибка при установке адреса через диалог: {e}")
        
        # Проверяем, можем ли мы продолжить без установки адреса
        if "retail" in driver.current_url:
            logger.info("📍 Находимся на странице с магазинами, продолжаем работу")
            print("📍 Находимся на странице с магазинами, продолжаем работу")
            return True
        
        # Пытаемся напрямую перейти на страницу магазинов
        driver.get("https://eda.yandex.ru/retail")
        time.sleep(5)
        
        if "retail" in driver.current_url:
            logger.info("📍 Перешли на страницу с магазинами напрямую, продолжаем работу")
            print("📍 Перешли на страницу с магазинами напрямую, продолжаем работу")
            return True
            
        logger.error(" Не удалось установить местоположение или перейти к магазинам")
        print(" Не удалось установить местоположение или перейти к магазинам")
        return False
        
    except Exception as e:
        logger.error(f"Общая ошибка в функции set_location: {e}")
        print(f" Общая ошибка в функции set_location: {e}")
        return False

# Полностью переработанная функция перехода к магазину
def navigate_to_store(driver, store_name):
    try:
        logger.info(f"Переход к магазину: {store_name}")
        print(f"\n🏪 Переход к магазину: {store_name}")
        
        # Убедимся, что мы на странице с магазинами
        if "retail" not in driver.current_url:
            driver.get("https://eda.yandex.ru/retail")
            time.sleep(5)
        
        # Проверка и обработка капчи
        if not handle_captcha(driver):
            return False
            
        # Прокрутим страницу, чтобы загрузить все магазины
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
        
        # Создадим строку поиска для всех возможных вариаций названия магазина
        store_variations = {
            "Пятерочка": ["Пятёрочка", "Пятерка", "Пятёрка", "Pyaterochka"],
            "Перекресток": ["Перекрёсток", "Perekrestok"],
            "Магнит": ["Magnit"],
            "ВкусВилл": ["Вкусвилл", "VkusVill"],
            "Дикси": ["Dixy"],
            "Лента": ["Lenta"],
            "Метро": ["Metro"]
        }
        
        # Пытаемся найти магазин через поиск (если есть)
        try:
            search_selectors = [
                "//input[contains(@placeholder, 'Поиск')]",
                "//input[contains(@class, 'SearchInput')]"
            ]
            
            for selector in search_selectors:
                try:
                    search_input = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, selector))
                    )
                    search_input.clear()
                    search_input.send_keys(store_name)
                    logger.info(f"Ввели название магазина '{store_name}' в поиск")
                    print(f"🔍 Ввели название магазина '{store_name}' в поиск")
                    time.sleep(3)
                    break
                except:
                    continue
        except:
            logger.warning("Не удалось найти поле поиска")
            print("⚠️ Не удалось найти поле поиска")
        
        # Список вариаций названия магазина
        variations = [store_name]
        if store_name in store_variations:
            variations.extend(store_variations[store_name])
        
        # Пробуем разные селекторы для поиска магазина
        store_found = False
        
        # 1. Поиск по названию магазина в карточке
        for variation in variations:
            selectors = [
                f"//div[contains(text(), '{variation}')]",
                f"//span[contains(text(), '{variation}')]",
                f"//h3[contains(text(), '{variation}')]",
                f"//a[contains(text(), '{variation}')]"
            ]
            
            for selector in selectors:
                try:
                    store_elements = driver.find_elements(By.XPATH, selector)
                    for element in store_elements:
                        # Проверим, что этот элемент видим и кликабелен
                        if element.is_displayed():
                            # Прокручиваем к элементу
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                            time.sleep(1)
                            
                            # Попытаемся найти кликабельную карточку или сам элемент
                            try:
                                # Сначала пробуем родительский элемент (карточку)
                                card = element
                                for _ in range(5):  # Поднимаемся до 5 уровней вверх
                                    try:
                                        card = card.find_element(By.XPATH, "..")  # Родительский элемент
                                        if "card" in card.get_attribute("class") or "Card" in card.get_attribute("class"):
                                            card.click()
                                            store_found = True
                                            logger.info(f"✅ Кликнули на карточку магазина '{variation}'")
                                            print(f"✅ Кликнули на карточку магазина '{variation}'")
                                            break
                                    except:
                                        break
                                
                                # Если карточку не нашли, кликаем на сам элемент
                                if not store_found:
                                    element.click()
                                    store_found = True
                                    logger.info(f"✅ Кликнули на элемент с названием магазина '{variation}'")
                                    print(f"✅ Кликнули на элемент с названием магазина '{variation}'")
                            except Exception as click_error:
                                logger.error(f"Ошибка при клике на магазин: {click_error}")
                                continue
                                
                            break
                    if store_found:
                        break
                except Exception as e:
                    continue
            
            if store_found:
                break
        
        # Если не нашли по тексту, ищем по изображениям и логотипам
        if not store_found:
            try:
                # Анализируем все карточки на странице
                cards = driver.find_elements(By.XPATH, "//div[contains(@class, 'Card') or contains(@class, 'card') or contains(@class, 'Shop') or contains(@class, 'Store')]")
                
                for card in cards:
                    try:
                        card_text = card.text.lower()
                        for variation in variations:
                            if variation.lower() in card_text:
                                # Прокручиваем к карточке
                                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", card)
                                time.sleep(1)
                                
                                try:
                                    card.click()
                                    store_found = True
                                    logger.info(f"✅ Кликнули на карточку магазина '{variation}' по тексту карточки")
                                    print(f"✅ Кликнули на карточку магазина '{variation}' по тексту карточки")
                                    break
                                except:
                                    pass
                    except:
                        continue
                    
                    if store_found:
                        break
            except Exception as e:
                logger.error(f"Ошибка при поиске карточек магазинов: {e}")
        
        # Ждем загрузки страницы магазина
        if store_found:
            # Ждем переход на страницу магазина
            time.sleep(5)
            
            # Проверяем URL или содержимое для подтверждения, что мы на странице магазина
            current_url = driver.current_url
            
            # Проверяем, содержит ли URL имя магазина или "store" или "shop"
            store_in_url = any(variation.lower() in current_url.lower() for variation in variations)
            
            if store_in_url or "/store/" in current_url or "/shop/" in current_url:
                logger.info(f"✅ Успешно перешли на страницу магазина {store_name}")
                print(f"✅ Успешно перешли на страницу магазина {store_name}")
                return True
        
        # Если попали сюда, значит не смогли перейти к магазину
        logger.warning(f" Не удалось перейти в магазин {store_name}")
        print(f" Не удалось перейти в магазин {store_name}")
        
        # Делаем скриншот для отладки
        driver.save_screenshot(f"debug_{store_name}.png")
        logger.info(f"Сделан скриншот debug_{store_name}.png для отладки")
        print(f"Сделан скриншот debug_{store_name}.png для отладки")
        
        return False
        
    except Exception as e:
        logger.error(f"Общая ошибка при переходе к магазину {store_name}: {e}")
        print(f" Общая ошибка при переходе к магазину {store_name}: {e}")
        traceback.print_exc()
        # Делаем скриншот для отладки
        driver.save_screenshot(f"error_{store_name}.png")
        return False

# Улучшенная функция поиска скидок
def check_discounts(driver, min_discount=70, max_price=50):
    discounted_products = []
    
    try:
        logger.info("Начинаем поиск товаров со скидками")
        print("🔍 Начинаем поиск товаров со скидками")
        
        # Прокрутка страницы для загрузки товаров (с динамической проверкой загрузки)
        last_height = driver.execute_script("return document.body.scrollHeight")
        max_scroll_attempts = 10
        scroll_count = 0
        
        while scroll_count < max_scroll_attempts:
            # Прокручиваем страницу вниз
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            # Проверяем, изменилась ли высота страницы
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scroll_count += 1
        
        # Ожидаем загрузки товаров после прокрутки
        time.sleep(3)
        
        # Различные селекторы для поиска карточек товаров
        card_selectors = [
            "//div[contains(@class, 'ProductCard')]",
            "//div[contains(@class, 'sku-card')]",
            "//div[contains(@class, 'product-card')]",
            "//div[contains(@class, 'item-card')]",
            "//div[contains(@class, 'Card_root')]",
            "//div[contains(@class, 'SkuCard')]",
            "//a[contains(@href, '/product/')]"
        ]
        
        # Поиск карточек товаров
        product_cards = []
        for selector in card_selectors:
            try:
                cards = driver.find_elements(By.XPATH, selector)
                if cards:
                    product_cards = cards
                    logger.info(f"Найдено {len(cards)} карточек товаров по селектору: {selector}")
                    print(f"📦 Найдено {len(cards)} карточек товаров")
                    break
            except Exception as e:
                continue
        
        if not product_cards:
            logger.warning(" Не удалось найти карточки товаров")
            print(" Не удалось найти карточки товаров")
            driver.save_screenshot("debug_no_products.png")
            print("Сделан скриншот debug_no_products.png для отладки")
            return []
        
        # Обновленные селекторы для элементов карточки
        selectors_map = {
            "title": [
                ".//div[contains(@class, 'title')]", 
                ".//span[contains(@class, 'title')]",
                ".//h3",
                ".//div[contains(@class, 'name')]",
                ".//div[contains(@class, 'Name')]"
            ],
            "discount": [
                ".//div[contains(@class, 'discount')]",
                ".//span[contains(@class, 'discount')]",
                ".//div[contains(@class, 'Discount')]",
                ".//div[contains(text(), '%')]",
                ".//span[contains(text(), '%')]",
                ".//div[contains(@class, 'Label')]"
            ],
            "price": [
                ".//div[contains(@class, 'price')]",
                ".//span[contains(@class, 'price')]",
                ".//div[contains(@class, 'price')]",
                ".//span[contains(@class, 'price')]",
                ".//div[contains(@class, 'Price')]",
                ".//span[contains(@class, 'Price')]"
            ],
            "old_price": [
                ".//div[contains(@class, 'old-price')]",
                ".//span[contains(@class, 'old-price')]",
                ".//div[contains(@class, 'oldPrice')]",
                ".//span[contains(@class, 'oldPrice')]",
                ".//div[contains(@class, 'crossed-price')]",
                ".//div[contains(@class, 'CrossedPrice')]"
            ],
            "image": [
                ".//img",
                ".//div[contains(@class, 'image')]/img",
                ".//div[contains(@class, 'Image')]/img"
            ]
        }
        
        # Проходим по каждой карточке товара
        for card in product_cards:
            try:
                # Инициализируем данные товара
                product_data = {
                    "title": None,
                    "discount": None,
                    "price": None,
                    "old_price": None,
                    "discount_percent": 0,
                    "image_url": None
                }
                
                # Извлекаем название товара
                for selector in selectors_map["title"]:
                    try:
                        title_element = card.find_element(By.XPATH, selector)
                        if title_element:
                            product_data["title"] = title_element.text.strip()
                            break
                    except:
                        continue
                
                # Если название не найдено, пропускаем
                if not product_data["title"]:
                    continue
                
                # Извлекаем скидку
                discount_text = None
                for selector in selectors_map["discount"]:
                    try:
                        discount_elements = card.find_elements(By.XPATH, selector)
                        for discount_element in discount_elements:
                            discount_text = discount_element.text.strip()
                            # Ищем проценты в тексте
                            if discount_text and "%" in discount_text:
                                # Извлекаем число из текста
                                discount_match = re.search(r'(-?\d+)%', discount_text)
                                if discount_match:
                                    product_data["discount"] = discount_text
                                    product_data["discount_percent"] = abs(int(discount_match.group(1)))
                                    break
                        if product_data["discount"]:
                            break
                    except:
                        continue
                
                # Извлекаем цены
                for selector in selectors_map["price"]:
                    try:
                        price_elements = card.find_elements(By.XPATH, selector)
                        for price_element in price_elements:
                            price_text = price_element.text.strip()
                            # Проверяем, что это не старая цена
                            if price_text and "old" not in price_element.get_attribute("class").lower() and "crossed" not in price_element.get_attribute("class").lower():
                                # Ищем число в тексте
                                price_match = re.search(r'(\d+[\.,]?\d*)', price_text.replace(" ", ""))
                                if price_match:
                                    price_str = price_match.group(1).replace(",", ".")
                                    product_data["price"] = float(price_str)
                                    break
                        if product_data["price"]:
                            break
                    except:
                        continue
                
                # Извлекаем старую цену
                for selector in selectors_map["old_price"]:
                    try:
                        old_price_elements = card.find_elements(By.XPATH, selector)
                        for old_price_element in old_price_elements:
                            old_price_text = old_price_element.text.strip()
                            # Ищем число в тексте
                            old_price_match = re.search(r'(\d+[\.,]?\d*)', old_price_text.replace(" ", ""))
                            if old_price_match:
                                old_price_str = old_price_match.group(1).replace(",", ".")
                                product_data["old_price"] = float(old_price_str)
                                break
                        if product_data["old_price"]:
                            break
                    except:
                        continue
                
                # Если не нашли процент скидки, но есть цена и старая цена, вычисляем
                if not product_data["discount_percent"] and product_data["price"] and product_data["old_price"]:
                    discount_percent = round(100 - (product_data["price"] / product_data["old_price"] * 100))
                    product_data["discount_percent"] = discount_percent
                    product_data["discount"] = f"-{discount_percent}%"
                
                # Извлекаем URL изображения
                for selector in selectors_map["image"]:
                    try:
                        image_element = card.find_element(By.XPATH, selector)
                        if image_element:
                            product_data["image_url"] = image_element.get_attribute("src")
                            break
                    except:
                        continue
                
                # Проверяем, соответствует ли товар критериям поиска
                if (product_data["discount_percent"] and product_data["discount_percent"] >= min_discount and 
                    product_data["price"] and product_data["price"] <= max_price):
                    # Добавляем товар в список
                    discounted_products.append(product_data)
                    
                    logger.info(f"Найден товар со скидкой: {product_data['title']} - {product_data['discount']} - {product_data['price']} руб.")
                    print(f"💰 Найден товар: {product_data['title']} - {product_data['discount']} - {product_data['price']} руб.")
            
            except Exception as e:
                logger.error(f"Ошибка при обработке карточки товара: {e}")
                continue
        
        # Сортируем товары по проценту скидки (по убыванию)
        discounted_products.sort(key=lambda x: x["discount_percent"], reverse=True)
        
        logger.info(f"Всего найдено товаров со скидками: {len(discounted_products)}")
        print(f"✅ Всего найдено товаров со скидками: {len(discounted_products)}")
        
        return discounted_products
        
    except Exception as e:
        logger.error(f"Общая ошибка при поиске скидок: {e}")
        print(f" Общая ошибка при поиске скидок: {e}")
        traceback.print_exc()
        return []

# Функция для форматирования и отправки результатов
def send_results(store_name, products):
    if not products:
        message = f"🏪 <b>{store_name}</b>\n Товары со скидками не найдены."
        send_message(message, parse_mode="HTML")
        return
    
    # Заголовок сообщения
    header = f"🏪 <b>{store_name}</b>\n📊 Найдено товаров со скидками: {len(products)}\n"
    
    # Максимальное количество товаров в одном сообщении
    max_products_per_message = 10
    
    # Формируем и отправляем сообщения
    for i in range(0, len(products), max_products_per_message):
        batch = products[i:i+max_products_per_message]
        
        # Если это первая партия, добавляем заголовок
        message = header if i == 0 else ""
        
        # Добавляем информацию о товарах
        for product in batch:
            product_info = (
                f"🔥 <b>{product['discount']}</b> | {product['title']}\n"
                f"💵 <b>{product['price']} руб.</b>"
            )
            
            if product["old_price"]:
                product_info += f" (было {product['old_price']} руб.)"
            
            product_info += "\n\n"
            message += product_info
        
        # Отправляем сообщение с товарами
        send_message(message, parse_mode="HTML")
        
        # Отправляем изображения первых 5 товаров (только для первой партии)
        if i == 0:
            for product in batch[:5]:
                if product["image_url"]:
                    try:
                        caption = f"🔥 <b>{product['discount']}</b> | {product['title']}\n💵 <b>{product['price']} руб.</b>"
                        if product["old_price"]:
                            caption += f" (было {product['old_price']} руб.)"
                        
                        send_photo(product["image_url"], caption, parse_mode="HTML")
                        time.sleep(1)  # Небольшая задержка между отправками
                    except Exception as e:
                        logger.error(f"Ошибка отправки изображения: {e}")

# Функция сохранения результатов в JSON
def save_results_to_json(results):
    try:
        with open("discounted_products.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info("Результаты сохранены в discounted_products.json")
        print("💾 Результаты сохранены в discounted_products.json")
    except Exception as e:
        logger.error(f"Ошибка сохранения результатов в JSON: {e}")
        print(f" Ошибка сохранения результатов в JSON: {e}")

# Основная функция
def main():
    logger.info("Запуск парсера Яндекс.Еда")
    print("🚀 Запуск парсера Яндекс.Еда для поиска товаров со скидками")
    
    # Отправляем сообщение о начале работы
    send_message("🚀 Начинаем поиск товаров со скидками в Яндекс.Еда")
    
    # Настройка драйвера
    driver = setup_driver(headless=False)
    
    try:
        # Минимальный процент скидки и максимальная цена
        min_discount = 70  # Минимальный процент скидки (%)
        max_price = 50    # Максимальная цена со скидкой (руб.)
        
        logger.info(f"Параметры поиска: скидка от {min_discount}%, цена до {max_price} руб.")
        print(f"⚙️ Параметры поиска: скидка от {min_discount}%, цена до {max_price} руб.")
        
        # Отправляем информацию о параметрах поиска
        send_message(f"⚙️ Ищем товары со скидкой от {min_discount}% и ценой до {max_price} руб.")
        
        # Установка местоположения
        address = "Москва"
        if not set_location(driver, address):
            logger.error("Не удалось установить местоположение. Завершаем работу.")
            send_message("❌ Не удалось установить местоположение. Завершаем работу.")
            driver.quit()
            return
        
        # Словарь для хранения результатов
        all_results = {}
        
        # Обработка каждого магазина
        for store_name in STORES:
            # Переходим к магазину
            if not navigate_to_store(driver, store_name):
                logger.warning(f"Пропускаем магазин {store_name}")
                continue
            
            # Поиск товаров со скидками
            products = check_discounts(driver, min_discount, max_price)
            
            # Сохраняем результаты
            all_results[store_name] = products
            
            # Отправляем результаты в Telegram
            send_results(store_name, products)
            
            # Небольшая задержка между магазинами
            time.sleep(2)
        
        # Сохраняем все результаты в JSON
        save_results_to_json(all_results)
        
        # Отправляем сообщение о завершении работы
        send_message("✅ Поиск товаров со скидками завершен")
        logger.info("Парсер завершил работу")
        print("✅ Парсер завершил работу")
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f" Критическая ошибка: {e}")
        traceback.print_exc()
        send_message(f" Произошла ошибка: {str(e)}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()