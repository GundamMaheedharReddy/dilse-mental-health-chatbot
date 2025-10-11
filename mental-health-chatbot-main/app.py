from flask import Flask, render_template, request, jsonify, session, Response
import json, os, requests, uuid, re
from dotenv import load_dotenv

# --- System prompt for chatbot ---
system_prompt = """
You are Dilse, a friendly, caring, and empathetic mental health chatbot for students.
Always respond in a supportive, concise, and non-judgmental way. Keep language simple and student-focused.
Do NOT address the user by their name except once when you first meet them (use the name only in the first greeting).
Always end with a short follow-up question to keep the conversation going.
"""

# --- Flask app setup ---
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dilse-secret-key')

# --- Load environment variables ---
load_dotenv()
PERPLEXITY_KEY = os.getenv("PERPLEXITY_API_KEY")

# --- Chat history ---
HISTORY_FILE = "chat_history.json"
if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        chat_history = json.load(f)
else:
    chat_history = []

# --- User data ---
USER_FILE = "user.json"
INVALID_NAMES = {
    "no","yes","ok","okay","maybe","nah","nope","i","me","my","mine","student","everyone","none",
    "happy","sad","angry","anxious","excited","stressed","calm","lonely","relaxed","tired","bored","scared","afraid","depressed","upset",
    "yeah","yep","yup","sure","right","okey","okeydokey","kk","k","thanks","thankyou","thank","cool","nice"
}
user_data = {}
if os.path.exists(USER_FILE):
    try:
        with open(USER_FILE, "r", encoding="utf-8") as f:
            user_data = json.load(f) or {}
        saved = (user_data.get("name") or "").strip().lower()
        if saved in INVALID_NAMES:
            user_data = {}
    except Exception:
        user_data = {}

# --- Helper functions ---
def set_user_name(name: str):
    global user_data
    if not name: return False
    name_clean = name.strip()
    if name_clean.lower() in INVALID_NAMES or len(name_clean) < 2: return False
    name_clean = name_clean.capitalize()
    user_data = {"name": name_clean, "greeted": False}
    try:
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Could not save user name:", e)
    return True

def get_user_name():
    if os.path.exists(USER_FILE):
        try:
            d = json.load(open(USER_FILE, "r", encoding="utf-8")) or {}
            return d.get("name")
        except Exception:
            pass
    return user_data.get("name")

def set_user_greeted():
    global user_data
    user_data["greeted"] = True
    try:
        with open(USER_FILE, "w", encoding="utf-8") as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def user_was_greeted():
    if os.path.exists(USER_FILE):
        try:
            d = json.load(open(USER_FILE, "r", encoding="utf-8")) or {}
            return bool(d.get("greeted"))
        except Exception:
            pass
    return bool(user_data.get("greeted"))

def store_name(user_input: str):
    if not user_input: return None
    text = user_input.strip()
    patterns = [
        r"\bmy\s+name\s+is\s+([A-Za-z][A-Za-z'\-]*)\b",
        r"\bcall\s+me\s+([A-Za-z][A-Za-z'\-]*)\b",
        r"\bi\s*(?:'m|am)\s+([A-Za-z][A-Za-z'\-]*)\b"
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = re.sub(r"[^A-Za-z'\-]", "", match.group(1)).strip().capitalize()
            if candidate and candidate.lower() not in INVALID_NAMES:
                return candidate
    tokens = text.split()
    if len(tokens) == 1:
        token = re.sub(r"[^A-Za-z'\-]", "", tokens[0]).strip()
        if token and token.isalpha() and 2 <= len(token) <= 30 and token.lower() not in INVALID_NAMES:
            if re.search(r"[aeiou]", token, flags=re.I) or len(token) <= 3:
                return token.capitalize()
    return None

def choose_followup(user_input: str):
    if not user_input: return "Would you like to tell me more or try a short grounding exercise?"
    u = user_input.lower()
    exams = ["exam","test","grade","marks","result"]
    stress = ["stress","stressed","pressure","deadline"]
    anxious = ["anxious","anxiety","worried"]
    happy = ["happy","excited","celebrate","good"]
    sleep = ["sleep","tired","rest","insomnia"]
    social = ["friend","friends","relationship","peer","classmate","roommate"]
    if any(k in u for k in exams):
        return "Congrats — would you like tips to keep the momentum or plan next study steps?"
    if any(k in u for k in happy):
        return "That’s wonderful — want ideas to celebrate or channels to share this with friends?"
    if any(k in u for k in anxious) or any(k in u for k in stress):
        return "Would you like a short breathing exercise now or a few quick strategies to manage this stress?"
    if any(k in u for k in sleep):
        return "Would you like some quick sleep tips you can try tonight?"
    if any(k in u for k in social):
        return "Do you want help thinking through how to talk to them or what to say?"
    return "Would you like to tell me more, or try a short grounding exercise?"

def ask_perplexity(user_input):
    if not PERPLEXITY_KEY:
        return "(Offline Mode) API key not set."
    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history[-10:]:
        if msg["role"] in ["user","assistant"]:
            messages.append(msg)
    messages.append({"role": "user","content": user_input})
    headers = {"Authorization": f"Bearer {PERPLEXITY_KEY}", "Content-Type": "application/json"}
    payload = {"model":"sonar-pro","messages":messages,"temperature":0.7,"max_tokens":250}
    try:
        r = requests.post("https://api.perplexity.ai/chat/completions", headers=headers, json=payload)
        if r.status_code == 200:
            result = r.json()
            if "choices" in result and len(result["choices"]) > 0:
                return result["choices"][0]["message"]["content"]
            return "(Offline Mode) No choices returned."
        else:
            return f"(Offline Mode) API error {r.status_code}"
    except Exception as e:
        print("Perplexity exception:", e)
        return "(Offline Mode) Could not connect to API."

def format_reply(ai_text, max_sentences: int = 7, followup: str = None, end_conversation: bool = False):
    if not ai_text: return "<p>Sorry, I couldn't generate a reply right now.</p>"
    import re
    text = re.sub(r'(?:\s*\[\d+\])+','', ai_text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = text.replace('*','')
    sentences = re.split(r'(?<=[\.!\?…])\s+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    truncated = sentences[:max_sentences]
    truncated_text = " ".join(truncated).strip()
    if truncated_text and truncated_text[-1] not in ".!?…":
        truncated_text += "."
    if len(sentences) > max_sentences:
        truncated_text += " …"
    has_question = bool(re.search(r'\?\s*$', truncated_text))
    if not has_question and not end_conversation:
        truncated_text += " " + (followup if followup else "Would you like to tell me more?")
    return f"<p>{truncated_text}</p>"

def chatbot_response(user_input):
    user_name = get_user_name()
    if not user_name:
        detected = store_name(user_input)
        if detected:
            set_user_name(detected)
            set_user_greeted()
            return format_reply(f"Nice to meet you, {detected}! How are you feeling today?")
    instruction = "You are Dilse, a friendly, caring, empathetic mental health chatbot. Answer supportively and concisely (limit to 7 sentences). End with a short follow-up question."
    if user_was_greeted():
        instruction += " Do NOT address the user by name in your reply."
    else:
        instruction += " You may use the user's name once to greet them."
    final_prompt = f"{system_prompt}\n{instruction}\nUser: {user_input}"
    ai_text = ask_perplexity(final_prompt)
    followup = choose_followup(user_input)
    html = format_reply(ai_text, max_sentences=9, followup=followup)
    try:
        chat_history.append({"role":"user","content":user_input})
        chat_history.append({"role":"assistant","content":ai_text})
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(chat_history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    if user_name and not user_was_greeted():
        set_user_greeted()
    return html

# --- Flask routes ---
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    user_input = data.get("message","").strip()
    if not user_input:
        return jsonify({"reply": "Please enter a message."})
    response = chatbot_response(user_input)
    return jsonify({"reply": response})

# --- Journal functionality ---
JOURNAL_FILE = 'journal_entries.json'

def get_user_id():
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    return session['user_id']

def load_journal_entries():
    if not os.path.exists(JOURNAL_FILE):
        return {}
    with open(JOURNAL_FILE, 'r', encoding='utf-8') as f:
        try: return json.load(f)
        except Exception: return {}

def save_journal_entries(data):
    with open(JOURNAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/journal')
def journal_page():
    return render_template('journal.html')

@app.route('/api/journal', methods=['GET'])
def api_get_journal():
    user_id = get_user_id()
    data = load_journal_entries()
    entries = data.get(user_id, [])
    return jsonify({'entries': entries})

@app.route('/api/journal', methods=['POST'])
def api_post_journal():
    user_id = get_user_id()
    data = load_journal_entries()
    entry = request.json.get('text', '').strip()
    if entry:
        new_entry = {'text': entry, 'date': request.json.get('date', '')}
        data.setdefault(user_id, []).insert(0, new_entry)
        save_journal_entries(data)
        return jsonify({'success': True, 'entry': new_entry})
    return jsonify({'success': False, 'error': 'Empty entry'}), 400

@app.route('/api/journal/edit', methods=['POST'])
def api_edit_journal():
    user_id = get_user_id()
    data = load_journal_entries()
    payload = request.get_json(silent=True) or {}
    idx = payload.get('idx')
    new_text = payload.get('text', '').strip()
    if idx is None or not new_text:
        return jsonify({'success': False, 'error': 'Invalid data'}), 400
    entries = data.get(user_id, [])
    if 0 <= idx < len(entries):
        entries[idx]['text'] = new_text
        save_journal_entries(data)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Entry not found'}), 404

@app.route('/api/journal/delete', methods=['POST'])
def api_delete_journal():
    user_id = get_user_id()
    data = load_journal_entries()
    payload = request.get_json(silent=True) or {}
    idx = payload.get('idx')
    entries = data.get(user_id, [])
    if idx is not None and 0 <= idx < len(entries):
        entries.pop(idx)
        save_journal_entries(data)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Entry not found'}), 404

@app.route('/api/journal/download', methods=['GET'])
def download_journal():
    user_id = get_user_id()
    data = load_journal_entries()
    entries = data.get(user_id, [])
    lines = []
    for entry in entries:
        date_str = entry.get('date','')
        lines.append(f"Date: {date_str}")
        lines.append(entry.get('text',''))
        lines.append('---')
    content = '\n'.join(lines)
    return Response(
        content,
        mimetype='text/plain',
        headers={'Content-Disposition':'attachment; filename="my_journal.txt"'}
    )

# --- Run Flask ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG","0")=="1"
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
