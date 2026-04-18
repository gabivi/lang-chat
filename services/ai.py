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
    "Rosh Hashana":   "ראש השנה",
    "Yom Kippur":     "יום כיפור",
    "Sukkos":         "סוכות",
    "Simchas Torah":  "שמחת תורה",
    "Chanukah":       "חנוכה",
    "Tu B'Shvat":     'ט"ו בשבט',
    "Purim":          "פורים",
    "Shushan Purim":  "שושן פורים",
    "Pesach":         "פסח",
    "Pesach Sheni":   "פסח שני",
    "Lag B'Omer":     'ל"ג בעומר',
    "Shavuos":        "שבועות",
    "Tisha B'Av":     "תשעה באב",
    "Rosh Chodesh":   "ראש חודש",
}

# Israeli civil holidays (Gregorian month, day) → (English, Hebrew)
_CIVIL_HOLIDAYS = {
    (4, 16): ("Yom HaShoah", "יום השואה"),
    (4, 22): ("Yom HaZikaron", "יום הזיכרון"),
    (4, 23): ("Yom HaAtzmaut", "יום העצמאות"),
}


def _get_random_topics():
    """Return a random selection of 5-7 topics from a larger pool."""
    all_topics = [
        "Family and grandchildren — ask about their family",
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
        "Weather and seasons — ask about their favorite times of year"
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
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def _get_jewish_holiday(now: datetime):
    """Return (english, hebrew) holiday name for today in Israel, or (None, None)."""
    # Check civil Israeli holidays first
    civil = _CIVIL_HOLIDAYS.get((now.month, now.day))
    if civil:
        return civil
    # Use pyluach for dynamic Hebrew calendar holidays
    try:
        from pyluach import dates as hd, hebrewcal
        today = hd.HebrewDate.today()
        hol = hebrewcal.holiday(today, israel=True)
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
• Family and grandchildren — ask about their family
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
• Family and grandchildren — ask about their family
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
- __CHANGE_TOPIC__: User wants to skip small talk — immediately suggest interesting topics
- __RESUME__: Returning user — give a warm welcome-back greeting
- __END__: User is ending the chat — give a simple, honest goodbye (not overly sentimental)

[LEVEL_INSTRUCTIONS]

CRITICAL: 1-3 sentences only. Use ONLY English. Never give medical advice, financial advice, or ask for personal data (IDs, financial info). Politely redirect debates, arguments, politics, or violence.""",

    ("he", "female"): """את עדי, שותפת לשיחה חברתית חמה ומעודדת לאנשים מבוגרים הרוצים לדבר.

תפקידך:
- עזור להתרגל בעברית בכל רמה בדיאלוג טבעי ובעדינות
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
• משפחה ונכדים — שאלי על המשפחה שלה
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
• משפחה ונכדים — שאל על המשפחה שלו
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

Befehle: __START__ (Intro), FIRST_TIME (erste Konversation), __CHANGE_TOPIC__ (Themawechsel), __RESUME__ (Rückkehr), __END__ (Abschied)

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

Befehle: __START__ (Intro), FIRST_TIME (erste Konversation), __CHANGE_TOPIC__ (Themawechsel), __RESUME__ (Rückkehr), __END__ (Abschied)

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

Comandos: __START__ (presentación), FIRST_TIME (primera conversación), __CHANGE_TOPIC__ (cambiar tema), __RESUME__ (regreso), __END__ (despedida)

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

Comandos: __START__ (presentación), FIRST_TIME (primera conversación), __CHANGE_TOPIC__ (cambiar tema), __RESUME__ (regreso), __END__ (despedida)

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

Commandes: __START__ (introduction), FIRST_TIME (première conversation), __CHANGE_TOPIC__ (changement de sujet), __RESUME__ (retour), __END__ (adieu)

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

Commandes: __START__ (introduction), FIRST_TIME (première conversation), __CHANGE_TOPIC__ (changement de sujet), __RESUME__ (retour), __END__ (adieu)

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

Parancsok: __START__ (bemutatkozás), FIRST_TIME (első beszélgetés), __CHANGE_TOPIC__ (témaváltás), __RESUME__ (visszatérés), __END__ (búcsú)

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

Parancsok: __START__ (bemutatkozás), FIRST_TIME (első beszélgetés), __CHANGE_TOPIC__ (témaváltás), __RESUME__ (visszatérés), __END__ (búcsú)

KRITIKUS: Csak 1-3 mondat! Csak magyarul! Nincs orvosi/pénzügyi tanács. Nincs személyes adatkérés.""",
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
    
    # Level-specific instructions with more distinct characteristics
    if language == "he":
        level_instructions = {
            "beginner": "רמה בסיסית בלבד! השתמש רק במילים פשוטות מאוד. משפטים קצרים מאוד: 5-7 מילים בלבד. חזור על מילים. שאל שאלות פשוטות (כן/לא). אל תשתמש במילים מתקדמות.",
            "intermediate": "רמה בינונית. השתמש בעברית טבעית עם אוצר מילים מתון. כלול ביטויים נפוצים. משפטים בעלי מבנה רגיל. שאל שאלות פתוחות. השתמש בזמנים שונים.",
            "advanced": "רמה מתקדמת! השתמש בעברית עשירה עם אוצר מילים מתקדם. כלול ביטויים דקיקים ותרבותיים. דן בנושאים מורכבים. השתמש בכל הזמנים והמבנים."
        }
        level_text = level_instructions.get(user_level, level_instructions["intermediate"])
        
    elif language == "de":
        level_instructions = {
            "beginner": "NUR ANFÄNGER NIVEAU! Nutze nur sehr einfache Wörter. Kurze Sätze: nur 5-7 Wörter. Wiederhole Schlüsselwörter. Stelle einfache Ja/Nein-Fragen. Kein komplexes Vokabular. Nur Präsens.",
            "intermediate": "Mittelstufe. Nutze natürliche Konversation mit moderatem Wortschatz. Einfache Redewendungen. Normaler Satzbau. Offene Fragen. Vergangenheit und Präsens.",
            "advanced": "Fortgeschritten! Reicher Wortschatz. Komplexe Ausdrücke. Komplexe Themen. Alle Zeitformen. Kulturelle Hinweise. Subtile Nuancen."
        }
        level_text = level_instructions.get(user_level, level_instructions["intermediate"])
        
    else:
        level_instructions = {
            "beginner": "BEGINNER LEVEL ONLY! Use only very simple, common words. Keep sentences SHORT (5-7 words max). Repeat key words. Ask very simple yes/no questions. NO complex vocabulary. Use present tense only.",
            "intermediate": "Intermediate level. Use natural conversation with moderate vocabulary. Include common expressions and idioms. Normal sentence structure. Ask open questions. Use past and present tenses naturally.",
            "advanced": "Advanced level! Use rich vocabulary and sophisticated expressions. Discuss complex topics. Use all tenses, subjunctive, and nuanced language. Include cultural references and thoughtful observations."
        }
        level_text = level_instructions.get(user_level, level_instructions["intermediate"])
    
    # Get random topics
    topics = _get_random_topics()
    topics_text = "\n".join([f"• {t}" for t in topics])
    
    prompt = base_prompt.replace("[LEVEL_INSTRUCTIONS]", level_text)
    
    # Add random topics section
    if language == "he":
        prompt += f"\n\nנושאים מושתנים לשיחה:\n{topics_text}"
    elif language == "de":
        prompt += f"\n\nZufällige Themen für das Gespräch:\n{topics_text}"
    else:
        prompt += f"\n\nRandom topics for conversation:\n{topics_text}"
    
    # Add strict length constraint and sanitize
    if language == "he":
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