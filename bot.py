import feedparser
import asyncio
import json
import os
import re
import requests
from datetime import datetime
from telegram import Bot
from telegram.request import HTTPXRequest
from telegram.error import TelegramError, TimedOut

# ===== НАСТРОЙКИ =====
TELEGRAM_TOKEN = "7195445922:AAEhzdYH4GYIfV8sYcNCkmQ"  # ЗАМЕНИТЕ НА НОВЫЙ ТОКЕН!
CHAT_ID = "-1001273424864"

RSS_FEEDS = [
    "http://www.kommersant.ru/RSS/main.xml",
    "https://www.interfax.ru/rss.asp",
    "https://www.finmarket.ru/rss/mainnews.asp",
    "https://tass.ru/rss/v2.xml",
    "http://www.kommersant.ru/RSS/news.xml"	
]

# ВАЖНО: Все ключевые слова ТОЛЬКО в нижнем регистре!
KEYWORDS = [
    # ГК Синара / Банк Синара / СТМ (Транспортные машины)
    "синара", "синара групп", "синара груп", "банк синара", "инвестиционный банк синара",
    "стм", "синара-транспортные машины", "синаратранспортныемашины", "синара транспортные машины", "транспортные машины синара",
    # ЛСР (Группа ЛСР)
    "лср", "лср групп", "группа лср",
    # Медси
    "медси", "группа медси",
    # Охта Проект / Проект 111
    "проект 111", "ооо проект 111", "проект111",
    # Роделен
    "роделен", "группа родедлен",
    # Девар
    "девар", "девар групп", "девар петро",
    # ПР-Лизинг
    "пр-лизинг", "пр лизинг",
    # Уралкуз
    "уралкуз", "уральская кузница",
    # Артген
    "артген", "артген групп",
    # РЖД (включая возможную транслитерацию RZD)
    "ржд", "ржд", "rzd", "российские железные дороги",
    # Азот
    "азот", "гк азот",
    # АйДи
    "айди", "ид",
    # Атомэнергопром
    "атомэнергопром", "атом энергопром"
]

# Создаём регулярное выражение для поиска целых слов
KEYWORDS_PATTERN = re.compile(r'\b(' + '|'.join(re.escape(kw) for kw in KEYWORDS) + r')\b', re.IGNORECASE)

SENT_FILE = "sent_links.json"

# ===== ПРОВЕРКА РАБОТОСПОСОБНОСТИ RSS =====
async def check_rss_health(feed_url):
    """
    Проверяет доступность RSS-ленты
    Возвращает: (статус, код_ответа, количество_новостей, сообщение_об_ошибке)
    """
    try:
        # Отправляем GET-запрос с таймаутом 10 секунд
        response = requests.get(feed_url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # Проверяем статус ответа
        if response.status_code != 200:
            return False, response.status_code, 0, f"HTTP {response.status_code}"
        
        # Парсим RSS
        feed = feedparser.parse(response.content)
        
        # Проверяем наличие ошибок парсинга
        if feed.bozo and hasattr(feed, 'bozo_exception'):
            error_msg = str(feed.bozo_exception)[:100]
            return False, response.status_code, 0, f"Ошибка парсинга: {error_msg}"
        
        # Проверяем, есть ли записи
        entries_count = len(feed.entries)
        
        if entries_count == 0:
            return False, response.status_code, 0, "Нет новостей в ленте"
        
        # Получаем дату последней новости
        last_entry_date = "нет данных"
        if entries_count > 0 and hasattr(feed.entries[0], 'published'):
            last_entry_date = feed.entries[0].published[:16]
        
        return True, response.status_code, entries_count, f"OK (новостей: {entries_count}, последняя: {last_entry_date})"
        
    except requests.exceptions.Timeout:
        return False, 0, 0, "Таймаут подключения (10 сек)"
    except requests.exceptions.ConnectionError:
        return False, 0, 0, "Ошибка соединения"
    except Exception as e:
        return False, 0, 0, f"Ошибка: {str(e)[:100]}"

async def check_all_rss_health():
    """Проверяет все RSS-ленты и выводит красивый отчёт"""
    print(f"\n{'='*60}")
    print(f"🔍 ПРОВЕРКА RSS-ИСТОЧНИКОВ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"{'='*60}")
    
    results = []
    for feed_url in RSS_FEEDS:
        # Извлекаем имя источника из URL
        source_name = feed_url.replace('https://', '').replace('http://', '').split('/')[0]
        
        # Проверяем
        is_ok, status_code, count, message = await check_rss_health(feed_url)
        
        # Выбираем иконку статуса
        if is_ok:
            status_icon = "✅"
            status_text = "РАБОТАЕТ"
        else:
            status_icon = "❌"
            status_text = "НЕ РАБОТАЕТ"
        
        # Форматируем вывод
        print(f"{status_icon} [{status_text}] {source_name}")
        print(f"   📍 URL: {feed_url}")
        print(f"   📊 Код ответа: {status_code if status_code else 'N/A'}")
        print(f"   💬 Сообщение: {message}")
        print(f"   {'-'*50}")
        
        results.append({
            'url': feed_url,
            'source': source_name,
            'status': is_ok,
            'message': message
        })
    
    # Сводка
    working = sum(1 for r in results if r['status'])
    total = len(results)
    print(f"\n📊 СВОДКА: {working}/{total} источников работают")
    
    if working < total:
        print(f"⚠️  НЕРАБОТАЮЩИЕ ИСТОЧНИКИ:")
        for r in results:
            if not r['status']:
                print(f"   - {r['source']}: {r['message']}")
    
    print(f"{'='*60}\n")
    return results

# ===== ОСТАЛЬНЫЕ ФУНКЦИИ =====
def load_sent_links():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()

def save_sent_links(sent_links):
    with open(SENT_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(sent_links), f, ensure_ascii=False, indent=2)

def check_rss_feed(feed_url, sent_links):
    """Проверяет RSS и возвращает новости, где есть ЦЕЛЫЕ ключевые слова"""
    news_items = []
    try:
        feed = feedparser.parse(feed_url)
        
        for entry in feed.entries:
            if entry.link in sent_links:
                continue
            
            # Получаем текст для поиска
            title = entry.get('title', '')
            description = entry.get('description', '')
            text = f"{title} {description}".lower()
            
            # Ищем ЦЕЛЫЕ слова (не части слов)
            match = KEYWORDS_PATTERN.search(text)
            
            if match:
                found_word = match.group(0)
                print(f"✅ Найдено ключевое слово '{found_word}' в: {title[:50]}...")
                
                news_items.append({
                    'title': entry.title,
                    'link': entry.link,
                    'published': entry.get('published', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                    'summary': entry.get('summary', '')[:300],
                    'keyword': found_word
                })
                sent_links.add(entry.link)
                
    except Exception as e:
        print(f"Ошибка при парсинге {feed_url}: {e}")
    
    return news_items

async def send_news_to_telegram(news_list, bot):
    """Отправляет новости в Telegram"""
    for news in news_list:
        message = f"""🔍 <b>Найдено: {news['keyword']}</b>

📊 <b>{news['title']}</b>

📅 {news['published']}

📝 {news['summary']}...

🔗 <a href='{news['link']}'>Читать полностью</a>"""

        try:
            await bot.send_message(
                chat_id=CHAT_ID,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=False
            )
            print(f"[{datetime.now()}] Отправлено: {news['title'][:50]}...")
        except Exception as e:
            print(f"Ошибка отправки: {e}")
        
        await asyncio.sleep(1)

# ===== ОСНОВНАЯ ФУНКЦИЯ С ПРОВЕРКОЙ RSS =====
async def main():
    print(f"🚀 Бот запущен {datetime.now()}")
    print(f"📡 Мониторинг RSS: {len(RSS_FEEDS)} источников")
    print(f"🔍 Ключевых слов: {len(KEYWORDS)}")
    print(f"📝 Ключевые слова: {', '.join(KEYWORDS)}")
    print(f"📨 Отправка в: {CHAT_ID}")
    print("-" * 50)
    
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=10.0
    )
    
    bot = Bot(token=TELEGRAM_TOKEN, request=request)
    sent_links = load_sent_links()
    print(f"📚 Загружено {len(sent_links)} уже отправленных новостей")
    
    # Счётчик итераций для периодической проверки RSS
    iteration = 0
    
    while True:
        iteration += 1
        print(f"\n{'🔄'*30}")
        print(f"🔄 ИТЕРАЦИЯ #{iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'🔄'*30}")
        
        # Проверяем работоспособность RSS-источников (каждую итерацию)
        await check_all_rss_health()
        
        # Ищем новые новости
        print(f"\n🔍 ПОИСК НОВОСТЕЙ ПО КЛЮЧЕВЫМ СЛОВАМ...")
        total_news = 0
        
        for feed_url in RSS_FEEDS:
            news = check_rss_feed(feed_url, sent_links)
            if news:
                total_news += len(news)
                await send_news_to_telegram(news, bot)
                save_sent_links(sent_links)
        
        if total_news == 0:
            print("📭 Новостей по ключевым словам не найдено")
        else:
            print(f"📨 Отправлено новостей: {total_news}")
        
        print(f"\n💤 Следующая проверка через 5 минут...")
        print(f"⏰ Следующий запуск: {(datetime.now().replace(second=0, microsecond=0) + pd.Timedelta(minutes=5)).strftime('%H:%M:%S') if 'pd' in dir() else datetime.now().strftime('%H:%M:%S')}")
        
        await asyncio.sleep(300)  # 5 минут

# Добавляем импорт для красивого вывода времени
from datetime import timedelta

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
