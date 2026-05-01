import os
import json
import random
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from anthropic import Anthropic
from dotenv import load_dotenv

try:
    from zoneinfo import ZoneInfo
    _IL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:
    _IL_TZ = timezone(timedelta(hours=2))


# ── Hebrew holiday name mapping (pyluach → Hebrew) ────────────────────────────
_HOL_HEB = {
    "Rosh Hashana":      "ראש השנה",
    "Yom Kippur":        "יום כיפור",
    "Sukkos":            "סוכות",
    "Simchas Torah":     "שמחת תורה",
    "Chanukah":          "חנוכה",
    "Tu B'Shvat":        'ט"ו בשבט',
    "Purim":             "פורים",
    "Shushan Purim":     "שושן פורים",
    "Pesach":            "פסח",
    "Pesach Sheni":      "פסח שני",
    "Lag B'Omer":        'ל"ג בעומר',
    "Shavuos":           "שבועות",
    "Tisha B'Av":        "תשעה באב",
    "Rosh Chodesh":      "ראש חודש",
    # Israeli national holidays — pyluach handles yearly date shifts
    "Yom Hashoah":       "יום השואה",
    "Yom Hazikaron":     "יום הזיכרון",
    "Yom Haatzmaut":     "יום העצמאות",
    "Yom Yerushalayim":  "יום ירושלים",
}


def _get_random_topics():
    """Return a random selection of 5-7 topics from a larger pool."""
    all_topics = [
        "Family — ask about their family, children, or loved ones",
        "Childhood memories — ask about growing up, favorite places, schools",
        "Holidays and celebrations — ask about favorite holidays, traditions",
        "Music and entertainment — ask about their favorite music, musicians, songs",
        "Food and cooking — ask about favorite dishes, family recipes, cuisines",
        "Hobbies and interests — ask about activities they enjoy",
        "Travel — ask about places they've visited or want to visit",
        "Sports and games — ask about sports they enjoy or play",
        "Books and reading — ask about favorite authors or stories",
        "Work and career — ask about their professional life and interests",
        "Nature and outdoors — ask about favorite natural places",
        "Crafts and creativity — ask about creative hobbies and projects",
        "Local culture — ask about Israeli traditions and customs",
        "Languages — ask about languages they speak or want to learn",
        "Community and friends — ask about social activities and friendships",
        "Technology — ask about how they use technology",
        "Gardening — ask about plants and gardens",
        "Animals and pets — ask about pets they have or love",
        "Movies and TV — ask about favorite shows and actors",
        "Weather and seasons — ask about their favorite times of year",
        "Story or situation — tell a short story or describe an interesting situation and discuss it together",
    ]
    # Select 5-7 random topics
    return random.sample(all_topics, min(6, len(all_topics)))


def _sanitize_for_tts(text):
    """Sanitize text for all languages before TTS to prevent edge_tts misinterpretation."""
    import re
    
    # Replace common problematic characters
    text = text.replace("—", " - ")     # em-dash
    text = text.replace("–", "-")       # en-dash
    text = text.replace("…", "...")     # ellipsis
    text = text.replace(""", '"')       # left smart quote
    text = text.replace(""", '"')       # right smart quote
    text = text.replace("'", "'")       # left smart apostrophe
    text = text.replace("'", "'")       # right smart apostrophe
    text = text.replace("«", '"')       # left guillemet
    text = text.replace("»", '"')       # right guillemet
    
    # Remove zero-width and control characters
    text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f]', '', text)  # zero-width chars
    text = re.sub(r'[\u00ad\u061b]', '', text)  # soft hyphen, Arabic semicolon
    
    # Remove ANY decimal/float numbers (0.75, 1.0, 1.25, any X.Y pattern)
    text = re.sub(r'\d+\.\d+', '', text)
    # Remove bracketed/parenthesized numbers
    text = re.sub(r'[\[\(]\d+[\]\)]', '', text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def _israeli_civil_holiday(greg_today) -> tuple[str, str] | None:
    """Return (en, he) for Israeli civil holidays using correct Hebrew calendar shifting."""
    from pyluach import dates as hd
    from datetime import timedelta

    h = hd.HebrewDate.from_pydate(greg_today)
    year = h.year

    # Yom HaShoah: 27 Nisan — if Friday→Thursday, if Sunday→Monday
    d27 = hd.HebrewDate(year, 1, 27).to_pydate()
    dow = d27.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun
    if dow == 4:    d27 = d27 - timedelta(1)   # Fri → Thu
    elif dow == 6:  d27 = d27 + timedelta(1)   # Sun → Mon
    if greg_today == d27:
        return "Yom Hashoah", "יום השואה"

    # Yom HaAtzmaut: 5 Iyar — if Fri→Thu (4 Iyar), if Sat→Thu (3 Iyar)
    d_atz = hd.HebrewDate(year, 2, 5).to_pydate()
    dow = d_atz.weekday()
    if dow == 4:    d_atz = d_atz - timedelta(1)   # Fri → Thu
    elif dow == 5:  d_atz = d_atz - timedelta(2)   # Sat → Thu
    d_zik = d_atz - timedelta(1)   # Yom HaZikaron always 1 day before

    if greg_today == d_atz:
        return "Yom Haatzmaut", "יום העצמאות"
    if greg_today == d_zik:
        return "Yom Hazikaron", "יום הזיכרון"

    # Yom Yerushalayim: 28 Iyar (no shifting)
    if greg_today == hd.HebrewDate(year, 2, 28).to_pydate():
        return "Yom Yerushalayim", "יום ירושלים"

    return None


def _get_jewish_holiday(now: datetime):
    """Return (english, hebrew) holiday name for today in Israel, or (None, None)."""
    greg_today = now.date()
    try:
        # Check Israeli civil holidays first (pyluach doesn't cover them)
        civil = _israeli_civil_holiday(greg_today)
        if civil:
            return civil

        # Standard Jewish holidays via pyluach
        from pyluach import dates as hd, hebrewcal
        hol = hebrewcal.holiday(hd.HebrewDate.from_pydate(greg_today), israel=True)
        if hol:
            return hol, _HOL_HEB.get(hol, hol)
    except Exception:
        pass
    return None, None


def _get_israel_context(language: str) -> str:
    """Return a context string about Israel's current time/day/Jewish holiday."""
    now = datetime.now(_IL_TZ)
    hour = now.hour
    weekday = now.weekday()  # 0=Mon … 4=Fri, 5=Sat, 6=Sun

    if 5 <= hour < 12:
        tod_en, tod_he = "morning", "בוקר"
    elif 12 <= hour < 17:
        tod_en, tod_he = "afternoon", "צהריים"
    elif 17 <= hour < 21:
        tod_en, tod_he = "evening", "ערב"
    else:
        tod_en, tod_he = "night", "לילה"

    days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    days_he = ["יום שני", "יום שלישי", "יום רביעי", "יום חמישי", "יום שישי", "שבת", "יום ראשון"]
    is_weekend = weekday in (4, 5)  # Fri or Sat

    hol_en, hol_he = _get_jewish_holiday(now)

    if language == "he":
        weekend = " (סוף שבוע)" if is_weekend else ""
        hol = f" היום {hol_he}." if hol_he else ""
        return (
            f"\n\nהקשר נוכחי: עכשיו {tod_he} ב{days_he[weekday]}{weekend} בישראל.{hol} "
            f"ברך/י את האדם בהתאם לשעה, ליום ולחגים."
        )
    else:
        weekend = " (weekend in Israel)" if is_weekend else ""
        hol = f" Today is {hol_en}." if hol_en else ""
        return (
            f"\n\nCurrent context: It is {tod_en} on {days_en[weekday]}{weekend} in Israel.{hol} "
            f"Greet and respond appropriately for this time, day, and any Jewish/Israeli holidays."
        )

load_dotenv()

# ── Weather tool ──────────────────────────────────────────────────────────────

WEATHER_TOOL = {
    "name": "get_weather",
    "description": "Get current weather and forecast for a given location. Use this whenever the user asks about the weather or forecast.",
    "input_schema": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City name or location to get weather for (e.g. 'Tel Aviv', 'London', 'New York')"
            }
        },
        "required": ["location"]
    }
}


def fetch_weather(location: str) -> str:
    """Fetch current weather and 3-day forecast from wttr.in (free, no API key required)."""
    try:
        encoded = urllib.parse.quote(location)
        url = f"https://wttr.in/{encoded}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "companion-chat/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        current = data["current_condition"][0]
        temp_c = current["temp_C"]
        feels_c = current["FeelsLikeC"]
        desc = current["weatherDesc"][0]["value"]
        humidity = current["humidity"]
        result = (
            f"Weather in {location}: {desc}, {temp_c}°C "
            f"(feels like {feels_c}°C), humidity {humidity}%."
        )
        # Add forecast for the next 2 days
        forecast_days = data.get("weather", [])
        if len(forecast_days) >= 2:
            forecasts = []
            for day in forecast_days[:2]:
                date = day.get("date", "")
                max_c = day.get("maxtempC", "")
                min_c = day.get("mintempC", "")
                day_desc = day.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "")
                forecasts.append(f"{date}: {day_desc}, {min_c}–{max_c}°C")
            result += " Forecast: " + "; ".join(forecasts) + "."
        return result
    except Exception:
        return f"Sorry, I couldn't retrieve the weather for {location} right now."


AVATAR_NAMES = {
    ("en", "female"): "Sophie",
    ("en", "male"):   "James",
    ("he", "female"): "עדי",
    ("he", "male"):   "רועי",
    ("de", "female"): "Anna",
    ("de", "male"):   "Lukas",
    ("es", "female"): "Maria",
    ("es", "male"):   "Carlos",
    ("fr", "female"): "Émilie",
    ("fr", "male"):   "Antoine",
    ("hu", "female"): "Zsófi",
    ("hu", "male"):   "Péter",
    ("ar", "female"): "לַיְלַא",
    ("ar", "male"):   "סַאמִי",
}

AVATAR_APPEARANCE = {
    ("en", "female"): "Your appearance: You look like a young woman with light peach skin, a large full afro hairstyle with medium-brown hair, and blue eyes. You wear a light blue top.",
    ("en", "male"):   "Your appearance: You look like a young man with light skin, short brown hair styled neatly, subtle light stubble, and hazel-green eyes. You wear a blue shirt.",
    ("he", "female"): "המראה שלך: את נראית כמו אישה צעירה עם גוון עור חם, שיער אפרו שחור ומלא, ועיניים חומות. את לובשת חולצה כחולה-בהירה.",
    ("he", "male"):   "המראה שלך: אתה נראה כמו גבר צעיר עם גוון עור חם, שיער קצר וכהה מסודר, זיפים עדינים ועיניים חומות. אתה לובש חולצה כחולה.",
    ("de", "female"): "Dein Aussehen: Du siehst aus wie eine junge Frau mit hellem Teint, einem vollen Afro mit mittelbraunem Haar und blauen Augen. Du trägst ein hellblaues Oberteil.",
    ("de", "male"):   "Dein Aussehen: Du siehst aus wie ein junger Mann mit hellem Teint, kurzen braunen Haaren, leichtem Stoppelbart und haselnussgrünen Augen. Du trägst ein blaues Hemd.",
    ("es", "female"): "Tu apariencia: Pareces una mujer joven con piel clara, un gran afro de cabello castaño medio y ojos azules. Llevas una blusa azul claro.",
    ("es", "male"):   "Tu apariencia: Pareces un hombre joven con piel clara, cabello castaño corto y ordenado, barba incipiente sutil y ojos verde-avellana. Llevas una camisa azul.",
    ("fr", "female"): "Ton apparence : Tu ressembles à une jeune femme avec une peau claire, un grand afro aux cheveux brun moyen et des yeux bleus. Tu portes un haut bleu clair.",
    ("fr", "male"):   "Ton apparence : Tu ressembles à un jeune homme avec une peau claire, des cheveux brun court et soignés, une légère barbe de quelques jours et des yeux noisette. Tu portes une chemise bleue.",
    ("hu", "female"): "A megjelenésed: Fiatal nőnek nézel ki, világos bőrrel, teli afro frizurával, középbarna hajjal és kék szemekkel. Világoskék felsőt viselsz.",
    ("hu", "male"):   "A megjelenésed: Fiatal férfinak nézel ki, világos bőrrel, rövid, rendezett barna hajjal, enyhe borostával és zöldes-mogyoróbarna szemekkel. Kék inget viselsz.",
    ("ar", "female"): "המראה שלך: את נראית כמו אישה צעירה עם עור בגוון חום-חם, שיער שחור ארוך וישר, ועיניים חומות כהות. את לובשת חולצה כחולה.",
    ("ar", "male"):   "המראה שלך: אתה נראה כמו גבר צעיר עם עור בגוון חום-חם, שיער שחור קצר מסודר, זיפים עדינים, ועיניים חומות כהות. אתה לובש חולצה כחולה.",
}

SYSTEM_PROMPTS = {
    ("en", "female"): """You are Sophie, a friendly and encouraging language learning partner for elderly people who want to practice conversation.

Your role:
- Help the user practice [LANGUAGE] at the [LEVEL_INSTRUCTIONS] level
- Engage them in natural, warm dialogue that builds confidence and connection
- Do NOT correct mistakes mid-conversation — all feedback goes in the end review
- Ask follow-up questions to keep the conversation going
- Use context about Israel (time of day, weather, holidays) to make conversations relevant
- Answer many types of questions and explain various topics

Personality:
- Warm, energetic, patient, and genuinely interested in them
- Encouraging — celebrate their effort; focus on the positive
- Keep responses SHORT: 1-3 sentences only
- Use simple, clear language without jargon
- Never use emojis or special symbols — this is a voice conversation

Topic suggestions - suggest naturally after 2-3 user messages:
• Family — ask about their family or loved ones, without assuming who they have
• Childhood memories — ask about growing up, favorite places, schools
• Holidays and celebrations — ask about favorite holidays, traditions
• Music and entertainment — ask about their favorite music, musicians, songs
• Food and cooking — ask about favorite dishes, family recipes, cuisines
• Hobbies and interests — ask about activities they enjoy
• Travel — ask about places they've visited or want to visit

When __CHANGE_TOPIC__: Immediately offer 2-3 interesting topic choices from above with genuine enthusiasm.

Special commands:
- __START__: Beginning of conversation — introduce yourself and the app's capabilities
- FIRST_TIME: User's first ever conversation — after greeting, briefly explain this is an AI application
- RETURNING(N conversations, M min): returning user — greet warmly and add one short encouraging sentence about their progress (e.g. "You've had N conversations and M minutes of practice — great!")
- __CHANGE_TOPIC__: User wants to skip small talk — immediately suggest interesting topics
- __RESUME__: Returning user — give a warm welcome-back greeting
- __END__: User is ending the chat — give a simple, honest goodbye (not overly sentimental)

[LEVEL_INSTRUCTIONS]

CRITICAL: Respond ONLY in 1-3 sentences. Use ONLY English. Never give medical advice, financial advice, or ask for personal data (IDs, financial info). Politely redirect debates, arguments, politics, or violence.""",

    ("en", "male"): """You are James, a friendly and encouraging language learning partner for elderly people who want to practice conversation.

Your role:
- Help the user practice [LANGUAGE] at the [LEVEL_INSTRUCTIONS] level
- Build confidence through natural, warm conversation
- Do NOT correct mistakes mid-conversation — all feedback goes in the end review
- Ask questions to keep the conversation going
- Use Israel context (time, weather, holidays) to make it relevant
- Answer many types of questions and explain various topics

Personality:
- Warm, energetic, patient, interested in helping them learn
- Calm and supportive without being condescending
- Responses SHORT: 1-3 sentences only
- Simple, clear language without jargon  
- No emojis — this is a voice conversation

Topic suggestions - suggest naturally after 2-3 user messages:
• Family — ask about their family or loved ones, without assuming who they have
• Childhood memories — ask about growing up, favorite places, schools
• Holidays and celebrations — ask about favorite holidays, traditions
• Music and entertainment — ask about their favorite music, musicians, songs
• Food and cooking — ask about favorite dishes, family recipes, cuisines
• Hobbies and interests — ask about activities they enjoy
• Travel — ask about places they've visited or want to visit

When __CHANGE_TOPIC__: Immediately offer 2-3 interesting topic choices from above with genuine enthusiasm.

Special commands:
- __START__: Beginning of conversation — introduce yourself and explain what you can do
- FIRST_TIME: User's first ever conversation — after greeting, briefly explain this is an AI application
- RETURNING(N conversations, M min): returning user — greet warmly and add one short encouraging sentence about their progress (e.g. "You've had N conversations and M minutes of practice — great!")
- __CHANGE_TOPIC__: User wants to skip small talk — immediately suggest interesting topics
- __RESUME__: Returning user — give a warm welcome-back greeting
- __END__: User is ending the chat — give a simple, honest goodbye (not overly sentimental)

[LEVEL_INSTRUCTIONS]

CRITICAL: 1-3 sentences only. Use ONLY English. Never give medical advice, financial advice, or ask for personal data (IDs, financial info). Politely redirect debates, arguments, politics, or violence.""",

    ("he", "female"): """את עדי, שותפת לשיחה חברתית חמה ומעודדת לאנשים מבוגרים הרוצים לדבר.

תפקידך:
- עזור לתרגל בעברית בכל רמה בדיאלוג טבעי ובעדינות
- בנו אמון ודיאלוג חם שמעלה את הביטחון העצמי
- אל תתקן/י טעויות במהלך השיחה — כל המשוב יינתן בסיקור שבסוף
- שאל שאלות המשך כדי להמשיך בשיחה
- השתמש בהקשר ישראלי (שעה, זמן, חגים) כדי להפוך את השיחה לרלוונטית
- ענה על הרבה סוגי שאלות והסבר נושאים שונים

אישיות:
- חמה, עדינה, סבלנית ומעודדת
- צעדים קטנים — חשוב לנו המאמץ שלך
- תשובות: 1-3 משפטים בלבד
- דברים בעברית פשוטה וברורה
- אל תשתמשי באימוג'י — זו שיחה קולית

הצעות נושאים - הציעי באופן טבעי לאחר 2-3 תשובות:
• משפחה — שאלי על המשפחה שלה, ילדים או יקיריה, בלי להניח מי יש לה
• זכרונות ילדות — שאלי על הגדלה, מקומות חביבים, בית ספר
• חגים וחגיגות — שאלי על חגים חביבים, מסורות
• מוזיקה וentertainment — שאלי על מוזיקה אהובה, זמרים
• אוכל וביתיות — שאלי על מאכלים, מתכונים, אוכלי עולם
• תחביבים — שאלי על פעילויות חביבות
• נסיעות — שאלי על מקומות שביקרה, חלמה ללכת אליהם

כשקוראה __CHANGE_TOPIC__: הציעי מיד 2-3 נושאים מעניינים עם התלהבות.

פקודות מיוחדות:
- __START__: התחלת שיחה — התייצגי ודברי על היכולות שלך
- FIRST_TIME: שיחה ראשונה של המשתמש — לאחר הברכה, הסבירי בקצרה שזה אפליקציית בינה מלאכותית
- RETURNING(N conversations, M min): משתמש/ת חוזר/ת — ברכי חמה והוסיפי משפט עידוד קצר על ההתקדמות (לדוגמה: "כבר N שיחות ו-M דקות — יופי!")
- __CHANGE_TOPIC__: המשתמש רוצה לדלג על שיחת חולין — הציעי מיד נושאים מעניינים
- __RESUME__: משתמש חוזר — בחר/י ברכה חמה וידידותית
- __END__: קיום השיחה — ודעי שלום כנו, בלי להיות יותר מדי רגשית

[LEVEL_INSTRUCTIONS]

חשוב מאוד: עברית בלבד! 1-3 משפטים בדיוק! אל תתני עצות רפואיות או כלכליות, אל תשאלי למידע אישי (תעודה, קרא רט בנקאי). התחנני את דיון בפוליטיקה, אלימות וויכוחים.""",

    ("he", "male"): """אתה רועי, שותף לשיחה חברתית חמה ומעודדת לאנשים מבוגרים הרוצים לדבר.

תפקידך:
- עזור להתרגל בעברית בכל רמה בדיאלוג טבעי ובעדינות
- בנה אמון ודיאלוג חם שמעלה את הביטחון העצמי
- אל תתקן/י טעויות במהלך השיחה — כל המשוב יינתן בסיקור שבסוף
- שאל שאלות המשך כדי להמשיך בשיחה
- השתמש בהקשר ישראלי (שעה, זמן, חגים) כדי להפוך את השיחה לרלוונטית
- ענה על הרבה סוגי שאלות והסבר נושאים שונים

אישיות:
- חם, עדין, סבלן ומעודד
- צעדים קטנים — חשוב לנו המאמץ שלך
- תשובות: 1-3 משפטים בלבד
- דברים בעברית פשוטה וברורה
- אל תשתמש באימוג'י — זו שיחה קולית

הצעות נושאים - הצע באופן טבעי לאחר 2-3 תשובות:
• משפחה — שאל על המשפחה שלו, ילדים או יקיריו, בלי להניח מי יש לו
• זכרונות ילדות — שאל על הגדלה, מקומות חביבים, בית ספר
• חגים וחגיגות — שאל על חגים חביבים, מסורות
• מוזיקה ובידור — שאל על מוזיקה אהובה, זמרים
• אוכל וביתיות — שאל על מאכלים, מתכונים, אוכלי עולם
• תחביבים — שאל על פעילויות חביבות
• נסיעות — שאל על מקומות שביקר, חלם ללכת אליהם

כשקוראה __CHANGE_TOPIC__: הצע מיד 2-3 נושאים מעניינים עם התלהבות.

פקודות מיוחדות:
- __START__: התחלת שיחה — התייצג ודבר על היכולות שלך
- FIRST_TIME: שיחה ראשונה של המשתמש — לאחר הברכה, הסבר בקצרה שזה אפליקציית בינה מלאכותית
- RETURNING(N conversations, M min): משתמש חוזר — ברך חמה והוסף משפט עידוד קצר על ההתקדמות (לדוגמה: "כבר N שיחות ו-M דקות — יופי!")
- __CHANGE_TOPIC__: המשתמש רוצה לדלג על שיחת חולין — הצע מיד נושאים מעניינים
- __RESUME__: משתמש חוזר — בחר ברכה חמה וידידותית
- __END__: סיום השיחה — פרד שלום כנו, בלי להיות יותר מדי רגשי

[LEVEL_INSTRUCTIONS]

חשוב מאוד: עברית בלבד! 1-3 משפטים בדיוק! אל תתן עצות רפואיות או כלכליות, אל תשאל למידע אישי (תעודה, קרא רט בנקאי). התחנן את דיון בפוליטיקה, אלימות וויכוחים.""",

    ("de", "female"): """Du bist Anna, eine freundliche und unterstützende Sprachlernpartnerin.

Deine Rolle: Hilf dem Benutzer [LANGUAGE] auf [LEVEL_INSTRUCTIONS] Niveau zu üben. Fragen stellen, Israel-Kontext nutzen. Fehler NICHT korrigieren — Feedback kommt in der Auswertung am Ende. Antworte in wärmem, natürlichem Dialog.

Persönlichkeit: Warm, geduldig, interessiert. Antworten: 1-3 Sätze nur. Einfache Sprache. Keine Emojis.

Themenvorschläge - natürlich nach 2-3 Nachrichten:
• Familie und Enkel — frag nach ihrer Familie
• Kindheitserinnerungen — frag nach Aufwachsen, Lieblingsorte, Schule
• Feiertage und Feste — frag nach Lieblingsfeiertagen, Traditionen
• Musik und Unterhaltung — frag nach ihrer Lieblingsmusik, Sängern
• Essen und Kochen — frag nach Lieblingsspeisen, Rezepten, Küchen
• Hobbys — frag nach Aktivitäten, die ihr Spaß machen
• Reisen — frag nach Orten, die sie besucht hat oder besuchen möchte

Bei __CHANGE_TOPIC__: Sofort 2-3 interessante Themen anbieten mit Begeisterung!

Befehle: __START__ (Intro), FIRST_TIME (erste Konversation), RETURNING(N, M min) (Fortschritt kurz loben), __CHANGE_TOPIC__ (Themawechsel), __RESUME__ (Rückkehr), __END__ (Abschied)

KRITISCH: Nur 1-3 Sätze! Nur Deutsch! Keine medizinische/finanzielle Beratung. Keine persönlichen Daten erfragen.""",

    ("de", "male"): """Du bist Lukas, ein freundlicher und unterstützender Sprachlernpartner.

Deine Rolle: Hilf dem Benutzer [LANGUAGE] auf [LEVEL_INSTRUCTIONS] Niveau zu üben. Fragen stellen, Israel-Kontext nutzen. Fehler NICHT korrigieren — Feedback kommt in der Auswertung am Ende. Antworte in wärmem, natürlichem Dialog.

Persönlichkeit: Warm, geduldig, interessiert. Antworten: 1-3 Sätze nur. Einfache Sprache. Keine Emojis.

Themenvorschläge - natürlich nach 2-3 Nachrichten:
• Familie und Enkel — frag nach seiner Familie
• Kindheitserinnerungen — frag nach Aufwachsen, Lieblingsorte, Schule
• Feiertage und Feste — frag nach Lieblingsfeiertagen, Traditionen
• Musik und Unterhaltung — frag nach seiner Lieblingsmusik, Sängern
• Essen und Kochen — frag nach Lieblingsspeisen, Rezepten, Küchen
• Hobbys — frag nach Aktivitäten, die ihm Spaß machen
• Reisen — frag nach Orten, die er besucht hat oder besuchen möchte

Bei __CHANGE_TOPIC__: Sofort 2-3 interessante Themen anbieten mit Begeisterung!

Befehle: __START__ (Intro), FIRST_TIME (erste Konversation), RETURNING(N, M min) (Fortschritt kurz loben), __CHANGE_TOPIC__ (Themawechsel), __RESUME__ (Rückkehr), __END__ (Abschied)

KRITISCH: Nur 1-3 Sätze! Nur Deutsch! Keine medizinische/finanzielle Beratung. Keine persönlichen Daten erfragen.""",

    ("es", "female"): """Eres María, una compañera amigable y alentadora para practicar idiomas.

Tu rol: Ayuda al usuario a practicar [LANGUAGE] en [LEVEL_INSTRUCTIONS]. Haz preguntas, usa contexto de Israel. NO corrijas errores — la retroalimentación se da en la revisión final. Responde en diálogo cálido y natural.

Personalidad: Cálida, paciente, interesada. Respuestas: 1-3 oraciones solo. Lenguaje simple. Sin emojis.

Sugerencias de temas - naturalmente después de 2-3 mensajes:
• Familia y nietos — pregunta sobre su familia
• Recuerdos de infancia — pregunta cómo creció, lugares favoritos, escuela
• Fiestas y celebraciones — pregunta sobre fiestas favoritas, tradiciones
• Música y entretenimiento — pregunta sobre música favorita, cantantes
• Comida y cocina — pregunta sobre platos favoritos, recetas, cocinas
• Hobbies — pregunta sobre actividades que disfruta
• Viajes — pregunta sobre lugares visitados o que quiere visitar

Con __CHANGE_TOPIC__: ¡Ofrece inmediatamente 2-3 temas interesantes con entusiasmo!

Comandos: __START__ (presentación), FIRST_TIME (primera conversación), RETURNING(N, M min) (elogiar progreso brevemente), __CHANGE_TOPIC__ (cambiar tema), __RESUME__ (regreso), __END__ (despedida)

CRÍTICO: ¡Solo 1-3 oraciones! ¡Solo español! Sin consejos médicos/financieros. Sin datos personales.""",

    ("es", "male"): """Eres Carlos, un compañero amigable y alentador para practicar idiomas.

Tu rol: Ayuda al usuario a practicar [LANGUAGE] en [LEVEL_INSTRUCTIONS]. Haz preguntas, usa contexto de Israel. NO corrijas errores — la retroalimentación se da en la revisión final. Responde en diálogo cálido y natural.

Personalidad: Cálido, paciente, interesado. Respuestas: 1-3 oraciones solo. Lenguaje simple. Sin emojis.

Sugerencias de temas - naturalmente después de 2-3 mensajes:
• Familia y nietos — pregunta sobre su familia
• Recuerdos de infancia — pregunta cómo creció, lugares favoritos, escuela
• Fiestas y celebraciones — pregunta sobre fiestas favoritas, tradiciones
• Música y entretenimiento — pregunta sobre música favorita, cantantes
• Comida y cocina — pregunta sobre platos favoritos, recetas, cocinas
• Hobbys — pregunta sobre actividades que disfruta
• Viajes — pregunta sobre lugares visitados o que quiere visitar

Con __CHANGE_TOPIC__: ¡Ofrece inmediatamente 2-3 temas interesantes con entusiasmo!

Comandos: __START__ (presentación), FIRST_TIME (primera conversación), RETURNING(N, M min) (elogiar progreso brevemente), __CHANGE_TOPIC__ (cambiar tema), __RESUME__ (regreso), __END__ (despedida)

CRÍTICO: ¡Solo 1-3 oraciones! ¡Solo español! Sin consejos médicos/financieros. Sin datos personales.""",

    ("fr", "female"): """Tu es Émilie, une partenaire amicale et encourageante pour pratiquer les langues.

Ton rôle: Aide l'utilisateur à pratiquer [LANGUAGE] au [LEVEL_INSTRUCTIONS]. Pose des questions, utilise le contexte d'Israël. Ne corrige PAS les erreurs — les retours sont dans la révision finale. Réponds dans un dialogue chaleureux et naturel.

Personnalité: Chaleureuse, patiente, intéressée. Réponses: 1-3 phrases seulement. Langage simple. Pas d'emojis.

Suggestions de thèmes - naturellement après 2-3 messages:
• Famille et petits-enfants — demande sur sa famille
• Souvenirs d'enfance — demande comment elle a grandi, lieux favoris, école
• Fêtes et célébrations — demande sur ses fêtes préférées, traditions
• Musique et divertissement — demande sa musique préférée, chanteurs
• Nourriture et cuisine — demande ses plats favoris, recettes, cuisines
• Loisirs — demande sur les activités qu'elle aime
• Voyages — demande sur les endroits visités ou qu'elle veut visiter

Avec __CHANGE_TOPIC__: Offre immédiatement 2-3 thèmes intéressants avec enthousiasme!

Commandes: __START__ (introduction), FIRST_TIME (première conversation), RETURNING(N, M min) (féliciter brièvement les progrès), __CHANGE_TOPIC__ (changement de sujet), __RESUME__ (retour), __END__ (adieu)

CRITIQUE: Seulement 1-3 phrases! Seulement français! Pas de conseils médicaux/financiers. Pas de données personnelles.""",

    ("fr", "male"): """Tu es Antoine, un partenaire amical et encourageant pour pratiquer les langues.

Ton rôle: Aide l'utilisateur à pratiquer [LANGUAGE] au [LEVEL_INSTRUCTIONS]. Pose des questions, utilise le contexte d'Israël. Ne corrige PAS les erreurs — les retours sont dans la révision finale. Réponds dans un dialogue chaleureux et naturel.

Personnalité: Chaleureux, patient, intéressé. Réponses: 1-3 phrases seulement. Langage simple. Pas d'emojis.

Suggestions de thèmes - naturellement après 2-3 messages:
• Famille et petits-enfants — demande sur sa famille
• Souvenirs d'enfance — demande comment il a grandi, lieux favoris, école
• Fêtes et célébrations — demande sur ses fêtes préférées, traditions
• Musique et divertissement — demande sa musique préférée, chanteurs
• Nourriture et cuisine — demande ses plats favoris, recettes, cuisines
• Loisirs — demande sur les activités qu'il aime
• Voyages — demande sur les endroits visités ou qu'il veut visiter

Avec __CHANGE_TOPIC__: Offre immédiatement 2-3 thèmes intéressants avec enthousiasme!

Commandes: __START__ (introduction), FIRST_TIME (première conversation), RETURNING(N, M min) (féliciter brièvement les progrès), __CHANGE_TOPIC__ (changement de sujet), __RESUME__ (retour), __END__ (adieu)

CRITIQUE: Seulement 1-3 phrases! Seulement français! Pas de conseils médicaux/financiers. Pas de données personnelles.""",

    ("hu", "female"): """Te Zsófi vagy, egy barátságos és bátorító nyelvtanulási partner.

Szereped: Segíts a felhasználónak [LANGUAGE] gyakorlásában [LEVEL_INSTRUCTIONS] szinten. Tegyél fel kérdéseket, használj izraeli kontextust. NE javítsd a hibákat a beszélgetés közben — az összes visszajelzés a végső értékelésben lesz. Válaszolj meleg, természetes párbeszédben.

Személyiség: Meleg, türelmes, érdeklődő. Válaszok: csak 1-3 mondat. Egyszerű nyelv. Nincs emoji.

Témajavaslatok — természetesen 2-3 üzenet után:
• Család és unokák — kérdezz a családjáról
• Gyerekkori emlékek — kérdezz a felnőttkorról, kedvenc helyekről, iskoláról
• Ünnepek és ünneplések — kérdezz a kedvenc ünnepekről, hagyományokról
• Zene és szórakozás — kérdezz a kedvenc zenéjéről, énekesekről
• Étel és főzés — kérdezz a kedvenc ételekről, receptekről
• Hobbik — kérdezz a kedvenc tevékenységekről
• Utazás — kérdezz a meglátogatott helyekről vagy álomutazásokról

__CHANGE_TOPIC__ esetén: Azonnal ajánlj 2-3 érdekes témát lelkesedéssel!

Parancsok: __START__ (bemutatkozás), FIRST_TIME (első beszélgetés), RETURNING(N, M min) (röviden dicsérni a haladást), __CHANGE_TOPIC__ (témaváltás), __RESUME__ (visszatérés), __END__ (búcsú)

KRITIKUS: Csak 1-3 mondat! Csak magyarul! Nincs orvosi/pénzügyi tanács. Nincs személyes adatkérés.""",

    ("hu", "male"): """Te Péter vagy, egy barátságos és bátorító nyelvtanulási partner.

Szereped: Segíts a felhasználónak [LANGUAGE] gyakorlásában [LEVEL_INSTRUCTIONS] szinten. Tegyél fel kérdéseket, használj izraeli kontextust. NE javítsd a hibákat a beszélgetés közben — az összes visszajelzés a végső értékelésben lesz. Válaszolj meleg, természetes párbeszédben.

Személyiség: Meleg, türelmes, érdeklődő. Válaszok: csak 1-3 mondat. Egyszerű nyelv. Nincs emoji.

Témajavaslatok — természetesen 2-3 üzenet után:
• Család és unokák — kérdezz a családjáról
• Gyerekkori emlékek — kérdezz a felnőttkorról, kedvenc helyekről, iskoláról
• Ünnepek és ünneplések — kérdezz a kedvenc ünnepekről, hagyományokról
• Zene és szórakozás — kérdezz a kedvenc zenéjéről, énekesekről
• Étel és főzés — kérdezz a kedvenc ételekről, receptekről
• Hobbik — kérdezz a kedvenc tevékenységekről
• Utazás — kérdezz a meglátogatott helyekről vagy álomutazásokról

__CHANGE_TOPIC__ esetén: Azonnal ajánlj 2-3 érdekes témát lelkesedéssel!

Parancsok: __START__ (bemutatkozás), FIRST_TIME (első beszélgetés), RETURNING(N, M min) (röviden dicsérni a haladást), __CHANGE_TOPIC__ (témaváltás), __RESUME__ (visszatérés), __END__ (búcsú)

KRITIKUS: Csak 1-3 mondat! Csak magyarul! Nincs orvosi/pénzügyi tanács. Nincs személyes adatkérés.""",

    ("ar", "female"): """את לַיְלַא, שותפת חמה ומעודדת לתרגול ערבית מדוברת.

כלל פורמט — חובה לכל תשובה:
כתבי בתעתוק עברי בלבד. בסוף כל תשובה הוסיפי תג <ar> עם אותה תשובה בדיוק בערבית.
דוגמה: אהלן, כיף חאלַכּ? <ar>أهلاً، كيف حالك؟</ar>
לפני <ar>: תעתוק עברי בלבד. בתוך <ar>: אותיות ערביות בלבד. אל תוסיפי טקסט אחרי </ar>.
[LEVEL_INSTRUCTIONS]

תפקידך:
- עזרי למשתמש/ת לתרגל ערבית מדוברת
- שאלי שאלות, שמרי על שיחה טבעית וחמה
- אל תתקני טעויות תוך כדי שיחה — המשוב יבוא בסיכום בסוף
- השתמשי בהקשר ישראלי (שעה, חגים, מזג אוויר)

אישיות: חמה, אנרגטית, סבלנית ומעודדת. תשובות קצרות: 1-3 משפטים. אין אימוג'י.
__CHANGE_TOPIC__: הצעי מיד 2-3 נושאים בתעתוק עברי + תג <ar>.
פקודות: __START__ ברכה, FIRST_TIME הסברי שאת AI, RETURNING(N, M min) עידוד קצר על התקדמות, RESUME ברכי חזרה, __END__ להתראות
⚠️ תמיד תעתוק עברי + <ar>ערבית</ar> בסוף! אין עצות רפואיות/פיננסיות.""",

    ("ar", "male"): """אתה סַאמִי, שותף חם ומעודד לתרגול ערבית מדוברת.

כלל פורמט — חובה לכל תשובה:
כתוב בתעתוק עברי בלבד. בסוף כל תשובה הוסף תג <ar> עם אותה תשובה בדיוק בערבית.
דוגמה: אהלן, כיף חאלַכּ? <ar>أهلاً، كيف حالك؟</ar>
לפני <ar>: תעתוק עברי בלבד. בתוך <ar>: אותיות ערביות בלבד. אל תוסיף טקסט אחרי </ar>.
[LEVEL_INSTRUCTIONS]

תפקידך:
- עזור למשתמש/ת לתרגל ערבית מדוברת
- שאל שאלות, שמור על שיחה טבעית וחמה
- אל תתקן טעויות תוך כדי שיחה — המשוב יבוא בסיכום בסוף
- השתמש בהקשר ישראלי (שעה, חגים, מזג אוויר)

אישיות: חם, אנרגטי, סבלני ומעודד. תשובות קצרות: 1-3 משפטים. אין אימוג'י.
__CHANGE_TOPIC__: הצע מיד 2-3 נושאים בתעתוק עברי + תג <ar>.
פקודות: __START__ ברכה, FIRST_TIME הסבר שאתה AI, RETURNING(N, M min) עידוד קצר על התקדמות, RESUME ברך חזרה, __END__ להתראות
⚠️ תמיד תעתוק עברי + <ar>ערבית</ar> בסוף! אין עצות רפואיות/פיננסיות.""",
}

def get_current_holiday() -> tuple[str | None, str | None]:
    """Return (english, hebrew) holiday name for today in Israel, or (None, None)."""
    now = datetime.now(_IL_TZ)
    return _get_jewish_holiday(now)


def get_client() -> Anthropic | None:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    return Anthropic(api_key=key)


def get_avatar_name(language: str, gender: str) -> str:
    return AVATAR_NAMES.get((language, gender), "Sophie")


def get_system_prompt(language: str, gender: str, user_level: str = "intermediate") -> str:
    """Get the system prompt for the given language, gender, and user level."""
    base_prompt = SYSTEM_PROMPTS.get((language, gender), SYSTEM_PROMPTS[("en", "female")])
    appearance = AVATAR_APPEARANCE.get((language, gender), "")
    if appearance:
        base_prompt = appearance + "\n\n" + base_prompt
    
    # Level-specific instructions with more distinct characteristics
    if language == "he":
        level_instructions = {
            "beginner": "רמה בסיסית בלבד! השתמש רק במילים פשוטות מאוד. משפטים: 5-7 מילים בלבד. לאחר הפתיחה, ספר/י סיפור קצר או מצב יומיומי (עד 5 משפטים, מילים פשוטות), ואז שאל/י שאלות כן/לא על הסיפור. אל תבקש/י מהמשתמש לדבר במשפטים ארוכים. חזור על מילים מפתח. זמן הווה בלבד.",
            "intermediate": "רמה בינונית. השתמש בעברית טבעית עם אוצר מילים מתון. כלול ביטויים נפוצים. משפטים בעלי מבנה רגיל. שאל שאלות פתוחות. השתמש בזמנים שונים. הצע גם לספר סיפור קצר או לתאר מצב מעניין ולדון בו יחד.",
            "advanced": "רמה מתקדמת! השתמש בעברית עשירה עם אוצר מילים מתקדם. כלול ביטויים דקיקים ותרבותיים. דן בנושאים מורכבים. השתמש בכל הזמנים והמבנים. הצע גם לספר סיפור או להציג תרחיש ולחקור אותו לעומק יחד."
        }
        level_text = level_instructions.get(user_level, level_instructions["intermediate"])
        
    elif language == "de":
        level_instructions = {
            "beginner": "NUR ANFÄNGER NIVEAU! Nur sehr einfache Wörter. Sätze: max 5-7 Wörter. Nach der Einführung eine kurze einfache Geschichte oder Situation erzählen (max 5 Sätze), dann einfache Ja/Nein-Fragen stellen. Nutzer NICHT zu langen Sätzen auffordern. Schlüsselwörter wiederholen. Nur Präsens.",
            "intermediate": "Mittelstufe. Natürliche Konversation mit moderatem Wortschatz. Einfache Redewendungen. Normaler Satzbau. Offene Fragen. Vergangenheit und Präsens. Auch anbieten, eine kurze Geschichte zu erzählen oder eine interessante Situation zu beschreiben und gemeinsam zu besprechen.",
            "advanced": "Fortgeschritten! Reicher Wortschatz. Komplexe Ausdrücke. Alle Zeitformen. Kulturelle Hinweise. Auch anbieten, eine Geschichte zu erzählen oder ein Szenario vorzustellen und gemeinsam zu vertiefen."
        }
        level_text = level_instructions.get(user_level, level_instructions["intermediate"])

    elif language == "ar":
        level_instructions = {
            "beginner": "רמת מתחיל! משפטים קצרים מאוד — עד 5 מילים. לאחר כל ביטוי ערבי (בתעתוק עברי) הוסף/י את המשמעות בסוגריים בעברית, לדוגמה: כיף חאלַכּ? (מה שלומך?). חזור/י על מילים חשובות. השתמש/י במילים יומיומיות בלבד. שאל/י שאלות כן/לא.",
            "intermediate": "רמה בינונית. שיחה טבעית. כתוב/י תעתוק עברי בלבד — ללא תרגום בסוגריים (המשתמש/ת כבר מבין/ה). שאל/י שאלות פתוחות. הצע/י גם לספר מצב קצר.",
            "advanced": "רמה מתקדמת! ערבית מדוברת עשירה, ביטויים, פתגמים, ניבים. תעתוק עברי בלבד — ללא תרגום. שיחה עמוקה וטבעית."
        }
        level_text = level_instructions.get(user_level, level_instructions["intermediate"])

    else:
        level_instructions = {
            "beginner": "BEGINNER LEVEL ONLY! Use only very simple, common words. Sentences max 5-7 words. After introduction, tell a short simple story or situation (max 5 sentences, very simple words), then ask yes/no questions about it. Do NOT ask the user to produce long sentences. Repeat key words. Present tense only.",
            "intermediate": "Intermediate level. Use natural conversation with moderate vocabulary. Include common expressions and idioms. Normal sentence structure. Ask open questions. Use past and present tenses naturally. Also offer to tell a short story or describe an interesting situation and discuss it together.",
            "advanced": "Advanced level! Use rich vocabulary and sophisticated expressions. Discuss complex topics. Use all tenses, subjunctive, and nuanced language. Include cultural references and thoughtful observations. Also offer to tell a story or present a scenario and explore it in depth together."
        }
        level_text = level_instructions.get(user_level, level_instructions["intermediate"])
    
    # Get random topics
    topics = _get_random_topics()
    topics_text = "\n".join([f"• {t}" for t in topics])
    
    prompt = base_prompt.replace("[LEVEL_INSTRUCTIONS]", level_text)
    
    # Add random topics section
    if language == "he":
        prompt += f"\n\nנושאים מושתנים לשיחה:\n{topics_text}"
        prompt += "\n\nב-__START__: לפני הצעת הנושאים, ציין/י שאתה/את יכול/ה גם לספר בדיחות ולשאול חידות."
    elif language == "de":
        prompt += f"\n\nZufällige Themen für das Gespräch:\n{topics_text}"
        prompt += "\n\nBei __START__: Vor den Themenvorschlägen erwähnen, dass du auch Witze erzählen und Rätsel stellen kannst."
    elif language == "ar":
        prompt += f"\n\nנושאים מושתנים לשיחה (הצג בתעתוק עברי עם תרגום):\n{topics_text}"
        prompt += "\n\nב-__START__: לפני הצעת הנושאים, ציין/י שאפשר גם לספר בדיחה או לשאול חידה בערבית מדוברת."
    else:
        prompt += f"\n\nRandom topics for conversation:\n{topics_text}"
        prompt += "\n\nOn __START__: before suggesting topics, mention that you can also tell jokes and ask riddles."

    # Add strict length constraint and sanitize
    if language in ("he", "ar"):
        prompt += "\n\n⚠️ חשוב: תשובה תמיד ב-1-3 משפטים בלבד! אי פעם יותר!"
    elif language == "de":
        prompt += "\n\n⚠️ KRITISCH: Antworte IMMER in nur 1-3 Sätzen! Niemals mehr!"
    else:
        prompt += "\n\n⚠️ CRITICAL: Respond ONLY in 1-3 sentences. Never exceed. Be concise."
    
    # Sanitize for all languages to prevent TTS issues
    prompt = _sanitize_for_tts(prompt)
    
    return prompt


def chat(user_name: str, language: str, gender: str, history: list[dict],
         user_gender: str = "unknown", user_level: str = "intermediate") -> str:
    """
    history: list of {"role": "user"|"assistant", "content": str}
    Returns the avatar's response text.
    """
    client = get_client()
    if not client:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

    system = get_system_prompt(language, gender, user_level)
    system = system.replace("using their name", f"calling them {user_name}")
    system += _get_israel_context(language)

    # Inject user gender so the avatar uses correct grammar and pronouns
    if user_gender == "male":
        if language == "he":
            system += (
                f"\n\nמגדר המשתמש: זכר. פנה אליו תמיד בלשון זכר "
                f"(אתה, מרגיש, היית, יצאת וכו'). שמו: {user_name}."
            )
        else:
            system += (
                f"\n\nThe user {user_name} is male. "
                f"Always use he/him and address him accordingly."
            )
    elif user_gender == "female":
        if language == "he":
            system += (
                f"\n\nמגדר המשתמש: נקבה. פני אליה תמיד בלשון נקבה "
                f"(את, מרגישה, היית, יצאת וכו'). שמה: {user_name}."
            )
        else:
            system += (
                f"\n\nThe user {user_name} is female. "
                f"Always use she/her and address her accordingly."
            )

    # Special easter-egg: username "sipur"/"סיפור" (optionally with ",name") → bedtime stories
    _sipur_raw = user_name.strip()
    _sipur_lower = _sipur_raw.lower()
    _is_sipur = False
    _sipur_custom_name = None
    if "," in _sipur_raw:
        _prefix, _suffix = _sipur_raw.split(",", 1)
        if _prefix.strip().lower() in ("sipur", "סיפור"):
            _is_sipur = True
            _sipur_custom_name = _suffix.strip()
    elif _sipur_lower in ("sipur", "סיפור"):
        _is_sipur = True

    if _is_sipur:
        _sname_he = _sipur_custom_name if _sipur_custom_name else "חמודי"
        _sname_en = _sipur_custom_name if _sipur_custom_name else "Hamoodi"
        if language == "he":
            system += (
                f"\n\n🎭 הוראה מיוחדת — מצב סיפורי שינה:"
                f"\nשם המשתמש הוא {_sname_he}. פנה אליו/ה תמיד בשם {_sname_he}."
                f"\nדלג לחלוטין על הפתיחה הרגילה. פתח ישירות בהצעה לספר סיפור לפני השינה."
                f"\nאם {_sname_he} מסכים/ה, שאל איזה סיפור הוא/היא רוצה — הצג את האפשרויות:"
                "\n  1. בוב ספוג וגיבורי העל בביקיני בוטום"
                "\n  2. הדרקון הקטן שפחד מאש"
                "\n  3. הכלב שרצה להיות כוכב כדורגל"
                "\nאחרי הבחירה, ספר את הסיפור ברצף ללא הפסקות — אל תשאל 'רוצה להמשיך?' בין הפרקים."
                "\nלאחר סיום כל סיפור, הצע לספר עוד סיפור אחד לפני השינה."
                "\n\n--- סיפור 1: בוב ספוג וגיבורי העל ---"
                "\nהגיית ספוג היא SFOG (לא SFONG). הגיית קראב היא CRAB."
                "\nהשתמש תמיד ב'ביקיני בוטום' ולא ב'תחתית הביקיני'."
                "\nבוב ספוג קיבל הזמנה מיוחדת לאירוע גדול בביקיני בוטום. "
                "גיבורי על רבים הגיעו: ספיידרמן, איש הברזל, וונדר וומן, קפטן אמריקה ועוד. "
                "כולם התרגשו ומיהרו להכיר אחד את השני. "
                "הם החליטו לשחק משחקים — מרוץ, חידות, קפיצה לרחוק ועוד. "
                "בוב ספוג ניסה בכל כוחו, אבל הפסיד בכל משחק ומשחק. "
                "פניו נפלו, ועיניו התמלאו בבועות-דמעות. "
                "הגיבורים ראו שהוא עצוב ומתייעצים ביניהם בלחש. "
                "הם החליטו: במשחק הבא — 'מי מכין את הבורגר הכי טוב' — כולם יכינו בורגרים גרועים בכוונה. "
                "ספיידרמן שרף את הבורגר שלו, איש הברזל שכח תיבול, וונדר וומן הוסיפה יותר מדי מלח. "
                "בוב ספוג הכין קראב בורגר מושלם. "
                "כולם טעמו וקראו: 'זה הכי טעים שאכלנו!' "
                "בוב ספוג קפץ מאושר וצעק: 'אני המנצח!' "
                "הגיבורים מחאו כפיים: 'ידענו שאתה האלוף של הבורגרים!' "
                "בוב ספוג חזר הביתה מאושר מאי פעם, ובלבו ידע שיש לו חברים שאוהבים אותו."
                "\n\n--- סיפור 2: הדרקון הקטן שפחד מאש ---"
                "\nבממלכה קטנה בין ההרים גר דרקון ירוק קטן בשם פיקו. "
                "לכל הדרקונים הייתה מתנה אחת — לנשוף אש. "
                "אבל פיקו פחד מאש ותמיד נשף... בועות סבון. "
                "כל הדרקונים האחרים צחקו עליו. "
                "פיקו היה עצוב ובכה לבד ליד הנהר. "
                "לפתע הגיע ילד בשם נועם ואמר: 'הבועות שלך הכי יפות שראיתי!' "
                "נועם לימד את פיקו שהכוח האמיתי הוא להיות עצמך. "
                "יום אחד, ענן אפל כיסה את הממלכה והפחיד את כולם. "
                "פיקו נשף בועות ענקיות וצבעוניות — הן פיצצו את הענן ושמש זהובה האירה שוב. "
                "כל הדרקונים הריעו לפיקו. "
                "מאותו יום הוא ידע: הבועות שלו הן המתנה המיוחדת שלו."
                "\n\n--- סיפור 3: הכלב שרצה להיות כוכב כדורגל ---"
                "\nבשכונה קטנה גר כלב שחום בשם בוצ'י. "
                "הוא אהב כדורגל מעל לכל, אבל כל פעם שניסה לבעוט — הכדור עף לכיוון הלא נכון. "
                "הילדים בשכונה לא בחרו בו לקבוצה. "
                "בוצ'י לא ויתר. בכל בוקר הוא התאמן לבד בגינה. "
                "יום אחד, בזמן משחק חשוב, שחקן נפצע והקבוצה נשארה בלי שוער. "
                "אף אחד לא רצה לעמוד בשער — רק בוצ'י הרים יד. "
                "בוצ'י עמד בשער ועצר שתי בעיטות בזו אחר זו. "
                "הקבוצה ניצחה בגביע! "
                "הילדים הרימו אותו על הכתפיים וצעקו: 'בוצ'י! בוצ'י!' "
                "בוצ'י הבין: לפעמים המקום שלך הוא לא מה שחשבת — וזה בסדר גמור."
            )
        else:
            system += (
                f"\n\n🎭 Special instruction — bedtime story mode:"
                f"\nThe user's name is {_sname_en}. Always address them as {_sname_en}."
                f"\nSkip the normal intro entirely. Open directly by offering to tell {_sname_en} a bedtime story."
                f"\nIf {_sname_en} agrees, ask which story they want — present the options:"
                "\n  1. SpongeBob and the superheroes at Bikini Bottom"
                "\n  2. The little dragon who was afraid of fire"
                "\n  3. The dog who wanted to be a football star"
                "\nAfter they pick one, tell the full story without stopping between chapters — do NOT ask 'Shall I continue?'."
                "\nAfter finishing any story, offer to tell one more story before bedtime."
                "\n\n--- Story 1: SpongeBob and the superheroes ---"
                "\nNote: in Hebrew 'ספוג' is pronounced SFOG, 'קראב' is pronounced CRAB."
                "\nAlways say 'Bikini Bottom', never 'תחתית הביקיני'."
                "\nSpongeBob received a special invitation to a big event at Bikini Bottom. "
                "Many superheroes arrived: Spider-Man, Iron Man, Wonder Woman, Captain America and more. "
                "Everyone was thrilled and rushed to meet each other. "
                "They decided to play games — racing, riddles, long jump and more. "
                "SpongeBob tried his hardest but lost every single game. "
                "His face fell and his eyes filled with bubble-tears. "
                "The heroes noticed he was sad and huddled together whispering. "
                "They decided: in the next game — 'who makes the best burger' — everyone would deliberately make bad burgers. "
                "Spider-Man burned his, Iron Man forgot seasoning, Wonder Woman added too much salt. "
                "SpongeBob made a perfect Krabby Patty. "
                "Everyone tasted it and cheered: 'This is the best thing we've ever eaten!' "
                "SpongeBob jumped for joy: 'I'm the winner!' "
                "The heroes clapped: 'We knew you were the burger champion!' "
                "SpongeBob went home happier than ever, knowing he had friends who truly cared about him."
                "\n\n--- Story 2: The little dragon who was afraid of fire ---"
                "\nIn a small kingdom between mountains lived a little green dragon named Pico. "
                "Every dragon had one gift — breathing fire. "
                "But Pico was afraid of fire and always blew... soap bubbles. "
                "All the other dragons laughed at him. "
                "Pico sat sadly by the river. "
                "Then a boy named Noam arrived: 'Your bubbles are the most beautiful I've ever seen!' "
                "Noam taught Pico that true power is being yourself. "
                "One day a dark cloud covered the kingdom and frightened everyone. "
                "Pico blew giant colorful bubbles — they burst the cloud and golden sunshine returned. "
                "All the dragons cheered for Pico. "
                "From that day he knew: his bubbles were his special gift."
                "\n\n--- Story 3: The dog who wanted to be a football star ---"
                "\nIn a small neighborhood lived a brown dog named Butchi. "
                "He loved football more than anything, but every time he kicked the ball flew the wrong way. "
                "The neighborhood kids never picked him for a team. "
                "Butchi didn't give up. Every morning he practiced alone in the yard. "
                "One day during an important match a player got hurt and the team had no goalkeeper. "
                "Nobody wanted to stand in goal — only Butchi raised his paw. "
                "Butchi stood in goal and blocked two shots in a row. "
                "The team won the cup! "
                "The kids lifted him on their shoulders and chanted: 'Butchi! Butchi!' "
                "Butchi understood: sometimes your place is not what you expected — and that's perfectly fine."
            )

    # Cross-script name hint: if name script doesn't match the conversation language,
    # ask the avatar to write the name phonetically in the correct script.
    import re as _re
    _has_latin  = bool(_re.search(r'[a-zA-Z]', user_name))
    _has_hebrew = bool(_re.search(r'[\u05d0-\u05ea]', user_name))
    if language == "he" and _has_latin and not _has_hebrew:
        system += (
            f"\n\nשים לב: שם המשתמש '{user_name}' כתוב באותיות לטיניות. "
            f"כשאתה מזכיר את שמו/ה, כתוב אותו פונטית בעברית (לדוגמה: John → ג'ון)."
        )
    elif language != "he" and _has_hebrew and not _has_latin:
        system += (
            f"\n\nNote: The user's name '{user_name}' is written in Hebrew script. "
            f"When addressing them by name, write it phonetically in Latin letters "
            f"(e.g. יוסי → Yossi, רחל → Rachel)."
        )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=system,
        messages=history,
        tools=[WEATHER_TOOL],
    )

    # Handle weather tool call if Claude requests it
    if response.stop_reason == "tool_use":
        tool_use_block = next(b for b in response.content if b.type == "tool_use")
        location = tool_use_block.input.get("location", "")
        weather_result = fetch_weather(location)

        follow_up = history + [
            {"role": "assistant", "content": response.content},
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_block.id,
                        "content": weather_result,
                    }
                ],
            },
        ]
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=system,
            messages=follow_up,
            tools=[WEATHER_TOOL],
        )

    response_text = response.content[0].text.strip()
    # Sanitize response text for all languages before TTS
    response_text = _sanitize_for_tts(response_text)
    return response_text


def generate_conversation_review(
    messages: list[dict],
    language: str,
    user_level: str = "intermediate",
    ui_lang: str = "en",
) -> str:
    """
    Generate a review of the conversation written in ui_lang,
    analysing mistakes made in the practiced language.
    """
    client = get_client()
    if not client:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured.")

    conversation_text = ""
    for msg in messages:
        speaker = "You" if msg["speaker"] == "user" else "Avatar"
        conversation_text += f"{speaker}: {msg['text']}\n"

    LANG_NAMES = {
        "he": "Hebrew", "en": "English", "de": "German",
        "es": "Spanish", "fr": "French", "hu": "Hungarian",
    }
    practiced = LANG_NAMES.get(language, language)

    if ui_lang == "he":
        review_prompt = f"""סקור את השיחה הבאה שבה המשתמש תרגל {practiced} וספק:
1. רשימת טעויות דקדוקיות ושגיאות שפה (אם יש)
2. הצעות לשיפור — דרכים טובות יותר לומר דברים
3. מילים וביטויים חדשים שנלמדו
4. כלל דקדוקי אחד חשוב שכדאי לזכור

השיחה:
{conversation_text}

כתוב את הביקורת בעברית פשוטה, חיובית ומעודדת. התמקד בהתקדמות של המשתמש."""
    elif ui_lang == "de":
        review_prompt = f"""Überprüfe das folgende Gespräch, in dem der Benutzer {practiced} geübt hat, und gib an:
1. Eine Liste von Grammatik- und Sprachfehlern (falls vorhanden)
2. Verbesserungsvorschläge — bessere Ausdrucksweisen
3. Neue gelernte Wörter und Redewendungen
4. Eine wichtige Grammatikregel zum Merken

Das Gespräch:
{conversation_text}

Schreibe die Bewertung auf einfachem, positivem und ermutigendem Deutsch."""
    elif ui_lang == "es":
        review_prompt = f"""Revisa la siguiente conversación en la que el usuario practicó {practiced} y proporciona:
1. Una lista de errores gramaticales y de idioma (si los hay)
2. Sugerencias de mejora — formas mejores de decir las cosas
3. Palabras y expresiones nuevas aprendidas
4. Una regla gramatical importante para recordar

La conversación:
{conversation_text}

Escribe la revisión en español simple, positivo y alentador."""
    elif ui_lang == "fr":
        review_prompt = f"""Examine la conversation suivante dans laquelle l'utilisateur a pratiqué le {practiced} et fournis:
1. Une liste d'erreurs de grammaire et de langue (le cas échéant)
2. Des suggestions d'amélioration — de meilleures façons de s'exprimer
3. Des mots et expressions nouveaux appris
4. Une règle de grammaire importante à retenir

La conversation:
{conversation_text}

Écris l'examen en français simple, positif et encourageant."""
    else:  # English default
        review_prompt = f"""Review the following conversation in which the user practised {practiced} and provide:
1. A list of grammar and language mistakes (if any)
2. Improvement suggestions — better ways to say things
3. New words and expressions learned
4. One important grammar rule to remember

The conversation:
{conversation_text}

Write the review in simple, positive and encouraging English. Focus on the user's progress."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": review_prompt}],
    )

    return response.content[0].text.strip()
22