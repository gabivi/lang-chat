Based on everything in this conversation, here is the full list of requirements for the Companion Chat project:

    ---
    Core Concept

    - Voice conversation app for elderly lonely people
    - Browser-based, single page app
    - Free TTS/STT via Web Speech API (no paid voice service)
    - AI conversation via Claude API (claude-sonnet-4-6)
    - Conversations saved to database

    ---
    User Identification

    - User enters their name on the welcome screen
    - User selects their own gender (female/male) — used for correct Hebrew grammar when addressing them
    - Returning users see their past conversations and can resume or start new
    - User name and gender persisted in DB

    ---
    Language & Interface

    - Interface language chooser on the welcome screen (Hebrew default, English option)
    - All buttons, labels, and prompts display in the chosen language
    - Hebrew UI uses correct gendered forms based on the user's gender (e.g., לחתה → י/לחתה or ילחתה)
    - RTL layout for Hebrew, LTR for English

    ---
    Avatar Setup

    - User chooses companion gender (female/male) on setup screen
    - Language of conversation chosen on setup screen (Hebrew/English)
    - Avatar has a realistic animated SVG face (not an emoji), with blinking both eyes (simultaneously), head movement, mouth animation while speaking
    - Female avatar: longer hair, eyelashes, softer features, light face skin, perky and lively but not too much
    - Male avatar: shorter hair, stubble , light face skin , energetic
    - Hebrew avatars have semi-light skin tone; English avatars have lighter skin tone
    - Avatar names: Sophie (English female), James (English male), רחל (Hebrew female), דוד (Hebrew male)

    ---
    Voice (TTS/STT)

    - Avatar speaks using Web Speech API TTS
    - Voice gender matches avatar gender; if no exact match, pitch is adjusted
    - If no voice exists for the chosen language, avatar automatically switches to English (face, name, and voice all change together)
    - Voice selector hidden from user; a random matching-gender voice is auto-selected
    - TTS voice: rate 1.08, pitch adjusted for cheerful/energetic tone
    - Emojis stripped before TTS (so they are not read aloud)
    - Stop button visible while avatar is speaking
    - Microphone button for STT; speech is captured and sent to conversation

    ---
    Conversation Behavior (AI / System Prompts)

    - 4 system prompts: English female (Sophie), English male (James), Hebrew female (לחר), Hebrew male (דוד)
      -  Avatar introduces itself by name on the first greeting
    - Varied opening sentences, topic suggestions, and goodbyes
    - at opening sentence - explain that it can answer many questions and explain various topics
    - at first conversation for a user, after greetings, explain that this is an AI application
    - After 2–3 exchanges, avatar naturally suggests topics: family, grandchildren, childhood, holidays, music, food, etc.
    - "Skip small talk and suggest topics" button — sends CHANGE_TOPIC command
    - Returning users get a warm welcome-back greeting referencing the previous conversation (RESUME)
    - Short conversations: avatar gives a simple honest goodbye, not a gushing one
    - No arguments, debates, politics, violence, religion disputes, or adult content — avatar politely redirects
    - Max 4 sentences per response, no emojis, simple language
    - if mic is open and nothing recording for 15 seconds, accept input given so far
    - allow getting weather information and forecast - per desired location

    ---
    User Gender in Conversation

    - User's gender passed to the AI so the avatar uses correct pronouns and Hebrew grammar
    - Hebrew: male user addressed with רכז forms, female with הבקנ forms
    - English: he/him or she/her used correctly

    ---
    Persistence

    - SQLite database (companion.db) via SQLAlchemy
    - Users table: id, name, gender
    - Conversations table: id, user_id, language, avatar_gender, avatar_name, title, created_at, updated_at
    - Messages table: id, conversation_id, speaker (user/avatar), text, timestamp
    - User preferences (avatar gender, language, user gender) saved in localStorage across page reloads

    ---
    Admin View

    - Page at /admin showing all conversations
    - Displays: user name, user gender, avatar name, language, start time, last active time, message count
    - Messages shown as chat bubbles with timestamps (text only, no voice)
    - Filter by user name (live search), language, avatar gender
    - Export to CSV (UTF-8 BOM for Hebrew Excel support)
    - admin page protected by password "Gabi1234" , save password in browser
    - converstion content should be kept in DB, and not deleted on deploying a new version	

    ---
    Deployment

    - Backend: FastAPI + Uvicorn
    - Start command for Render: uvicorn main:app --host 0.0.0.0 --port $PORT
    - runtime.txt: 3.12.9
    - ANTHROPIC_API_KEY set as environment variable on Render
    - GitHub repo: https://github.com/gabivi/companion-chat